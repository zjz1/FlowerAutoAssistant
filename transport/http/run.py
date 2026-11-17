# -*- coding: utf-8 -*-
"""HTTP 路由 mixin：run。"""
from __future__ import annotations

from .common import *  # noqa: F401,F403
class RunRoutes:
    def _run_daily_sel(self):
        data = self._read_json()
        selected = data.get("selected", [])
        mode = data.get("mode", "use")
        # 完成动作(2026-11-10, 完成后关闭客户端): 解析 data.finish_action, 仅接受
        # none/close_client 二值 —— 其余值一律 400 拒收, 绝不静默落进编排(防拼错键名
        # 造成意外关闭客户端)。缺省 "none" = 零行为变化(引擎收尾不做任何动作)。
        finish_action = str(data.get("finish_action", "none") or "none")
        if finish_action not in ("none", "close_client"):
            return self._send_json(
                {"error": f"finish_action 仅接受 none/close_client, 收到: {finish_action!r}"}, 400)
        _set_mode(mode)
        import json as _json
        p = BASE / "flows" / "daily.json"
        if not p.exists():
            return self._send_json({"error": "daily.json 缺失"}, 500)
        try:
            plan = _json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            return self._send_json({"error": f"daily.json 解析失败: {e}"}, 500)
        all_modules = plan.get("modules", [])
        # on_fail 处置(2026-10-06 用户方案A): 勾选模块统一 skip「跳过继续」, 但
        # **保留 daily.json 里声明为 stop_round 的模块**(当前即 startup) —— 启动失败
        # 即真异常(#1 修复后签到窗盖底栏的误报已根治), 按用户 10-03 决策「宁可当天
        # 不跑, 也不能用错误账号/未登录状态跑完」应整轮停止, 不再被统一 skip 废掉。
        # 此前无条件改写使该保护在勾选路径从未生效(16:35 实弹: startup 软失败靠
        # skip 才没中止整轮, 当日属侥幸)。startup 真失败时后续模块只会各自空转,
        # 白跑 ~10-20 分钟且日志全红 —— 整轮停止正是为这种时刻设计的。
        chosen = []
        for m in all_modules:
            if m.get("id") not in selected:
                continue
            m = dict(m)
            if m.get("on_fail") != "stop_round":
                m["on_fail"] = "skip"
            chosen.append(m)
        if not chosen:
            return self._send_json({"error": "未勾选任何任务"}, 400)
        plan["modules"] = chosen
        plan["description"] = "Web UI 使用界面按勾选模块调度"
        # 完成动作随编排传给引擎: 引擎 run_daily 全部模块跑完后按该值决定是否关闭客户端
        # (none=无动作; close_client=关客户端。引擎侧同样只认这两值, 其余按 none 处理)。
        plan["finish_action"] = finish_action
        name = plan.get("name", "每日编排")
        try:
            run_service.start_daily(plan, name, len(chosen))
        except run_service.RunConflict:
            return self._send_json({"error": "已有流程在运行, 请先停止"}, 409)
        return self._send_json({"ok": True, "started": name, "count": len(chosen)})

    def _run(self):
        data = self._read_json()
        key = data.get("flow", "")
        mode = data.get("mode", "use")
        flows = load_flows()
        target = select_flow(flows, key)
        if target is None:
            return self._send_json({"error": f"未找到流程: {key}"}, 400)
        name = target.get("name")
        try:
            _set_mode(mode)
            run_service.start_flow(target, name)
        except run_service.RunConflict:
            return self._send_json({"error": "已有流程在运行, 请先停止"}, 409)
        return self._send_json({"ok": True, "started": name})

    def _stop(self):
        request_stop()
        log_append("[stop] 已请求停止当前所有流程 (WebUI 服务保持运行)")
        return self._send_json({"ok": True, "message": "已请求停止当前流程"})

    def _shutdown(self):
        log_append("[webui] 收到关闭服务请求, 正在退出...")
        self._send_json({"ok": True, "message": "服务已关闭"})
        shutdown_server()
        return
