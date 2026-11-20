# -*- coding: utf-8 -*-
"""HTTP 路由 mixin：router。"""
from __future__ import annotations

from .common import *  # noqa: F401,F403
class RouterMixin:
    def _route(self):
        p = self.path.split("?", 1)[0]
        if p == "/" and self.command == "GET":
            return self._serve_page()
        if p == "/tpltool" and self.command == "GET":
            return self._serve_tpl_page()
        # API 全部带 /api 前缀
        if not p.startswith("/api/"):
            self._send_json({"error": "notfound"}, 404)
            return
        api = p[len("/api/"):]

        if api == "status" and self.command == "GET":
            return self._send_json(_status())
        # Stage 4: 服务存活/就绪探针（客户端探测端口归属的唯一握手点）
        if api == "health" and self.command == "GET":
            return self._health()
        if api == "ready" and self.command == "GET":
            return self._ready()
        if api == "plant_presets" and self.command == "GET":
            return self._plant_presets()
        if api == "flows" and self.command == "GET":
            flows = []
            for f in load_flows():
                fname = f.get("_file")
                flows.append({
                    "name": f.get("name"),
                    "file": fname,
                    "description": f.get("description", ""),
                    "modules": f.get("modules", []),
                })
            return self._send_json({"flows": flows})
        if api == "kb" and self.command == "GET":
            return self._send_json(self._kb())
        # W1(2026-10-27, zcode-20261028-6): 删除 GET /api/config —— 前端零消费方
        # (webui.html/tpltool.html 全文 0 引用, codex-20261025-4 已核实并留主 agent 裁量);
        # 现行设置回显统一走 /api/daily(modules[].settings + 识别设置字段), 保存统一走 /api/set_config。
        if api == "daily" and self.command == "GET":
            return self._daily()
        if api == "run_daily" and self.command == "POST":
            return self._run_daily_sel()
        if api == "set_config" and self.command == "POST":
            data = self._read_json()
            eng = get_engine()
            pre = bool(eng.config.get("enable_switch", False))
            # F06+W03(batch-04): 全部键由 _CONFIG_KEYS 元数据表驱动(白名单/校验/日志/回显/
            # ⚙meta 五处同源, 表见模块级定义与历史事故注释)。键序与改前 if-chain 逐键一致;
            # enum 键白名单外 400 中断(已应用键保持已应用, 改前 finish_action 原语义);
            # 三种特殊校验器逐字节保持: ocr_threads 钳制(max(0,min(8)), 解析失败回 2) /
            # fail_cache_prompt_mb 下限 1.0(解析失败跳过不落盘) / finish_action 400 拒收不落配置。
            for key, spec in _CONFIG_KEYS.items():
                if key not in data:
                    continue
                err = _apply_config_key(eng, key, spec, data[key])
                if err is not None:
                    return self._send_json({"error": err}, 400)
            now = bool(eng.config.get("enable_switch", False))
            for line in _config_log_lines(eng, now):
                log_append(line)
            return self._send_json(_config_echo(eng, now, pre))

        if api == "connect" and self.command == "POST":
            return self._connect()
        if api == "set_mode" and self.command == "POST":
            data = self._read_json()
            _set_mode(data.get("mode", "use"))
            return self._send_ok()
        if api == "screen" and self.command == "GET":
            return self._screen()
        if api == "ocr" and self.command == "GET":
            return self._ocr()
        if api == "failures" and self.command == "GET":
            return self._failures()
        if api == "failures_clear" and self.command == "POST":
            clear_failures()
            return self._send_ok()
        if api == "click" and self.command == "POST":
            return self._click()
        if api == "run" and self.command == "POST":
            return self._run()
        if api == "stop" and self.command == "POST":
            return self._stop()
        if api == "log" and self.command == "GET":
            return self._log()
        if api == "log_download" and self.command == "GET":
            return self._log_download()
        if api == "stream" and self.command == "GET":   # SSE 推送(2026-11-10 新增, 既有端点零改动)
            return self._stream()
        if api == "log_clear" and self.command == "POST":
            return self._log_clear()
        # ---- 故障存证截图: 缓存信息 / 清理 / 浏览目录 (里程碑 94) ----
        if api == "fail_cache_info" and self.command == "GET":
            # D7(方案批 D 表 D7): set 不可 JSON 序列化 -> 复制一份再转有序列表。
            # ⚠ 2026-11-18: 不能原地改 stat() 的缓存 dict —— 否则 files 变 list,
            # 紧随的 /api/status 里 set<=set 子集比对会抛 TypeError(自测实测 500)。
            st = dict(_fail_cache_stat())
            st["files"] = sorted(st["files"])
            thr = float(get_engine().config.get("fail_cache_prompt_mb", 100) or 100)
            return self._send_json({**st, "mb": st["bytes"] / 1048576, "threshold_mb": thr,
                                    "exceed": st["bytes"] / 1048576 >= thr})
        if api == "fail_cache_clean" and self.command == "POST":
            data = self._read_json() if int(self.headers.get("Content-Length") or 0) else {}
            return self._send_json({"ok": True,
                                    **_fail_cache_clean(str(data.get("mode") or "all"), data.get("days"))})
        if api == "fail_cache_open" and self.command == "POST":
            import os
            try:
                _FAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                os.startfile(str(_FAIL_CACHE_DIR))
                log_append(f"[截图缓存] 已打开缓存目录: {_FAIL_CACHE_DIR}\n")
                return self._send_json({"ok": True, "dir": str(_FAIL_CACHE_DIR)})
            except Exception as e:
                return self._send_json({"ok": False, "error": str(e)}, 500)
        if api == "shutdown" and self.command == "POST":
            return self._shutdown()

        # ---- 模板标注工具 API (人机协同标注, 只回传坐标, 不直接存模板) ----
        if api == "tplt_init" and self.command == "GET":
            return self._tplt_init()
        if api == "tplt_load" and self.command == "POST":
            return self._tplt_load()
        if api == "tplt_submit" and self.command == "POST":
            return self._tplt_submit()
        if api == "tplt_contour" and self.command == "POST":
            return self._tplt_contour()

        self._send_json({"error": "no such api"}, 404)
