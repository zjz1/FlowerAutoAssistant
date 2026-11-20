"""编排执行: run_flow/run_module/run_daily/完成动作/界面采集。

E01(batch-03, 2026-11-14) 自单文件 ocr_engine.py 机械拆包: 本文件各段为原文件对应
行段的**逐行原文**(唯 __file__ 锚点因包层级 +1 机械重锚定, 见 ast_hash_compare.py
allowlist)。行为等价口径: 帧集回归 0 退化 + 闸门全绿 + import 面零改动。
原行段映射: evidence/batch-03/tiles_manifest.json。
"""
from __future__ import annotations

import json
import sys
import time

import metrics_recorder

from .._constants import FLOW_DIR
from .._exceptions import FlowFailed, StopRequested, clear_stop
from .._failures import get_failures, report_failure
from .._geometry import Point
from .._stat import _new_ocr_stat, _ts
from ocr_ui import ocr_image

class _OrchestrateMixin:
    def run_flow(self, flow: dict):
        """执行整个流程。flow 含 steps 列表。返回值: 接口回调事件列表。
        流程顶层可声明 scene(如 "scene": "家园主界面"), 之后点击默认记入该场景。
        """
        clear_stop()
        name = flow.get("name", "未命名流程")
        self._module = name          # 失败登记时标注来源模块
        self._buy_count = 0          # G1 v2: 单跑流程时同样按轮重置购买计数
        if flow.get("scene"):
            self._scene = flow["scene"]
        # 度量基座(2026-11-13 批): 轮开始落盘(内存采样+OCR统计起点快照)。run_flow 单跑不重置
        # _ocr_stat(进程累计), 结束时由记录器对起点快照求增量得出本轮口径。
        _metrics_rec = metrics_recorder.metrics_round_start(
            "flow", name, screen=(self.screen_w, self.screen_h), ocr_stat=self._ocr_stat)
        _metrics_interrupted = False   # 度量基座: 异常退出标记(except 已处理的异常不进 finally 的 exc_info)
        print(f"\n[{_ts()}] ===== 流程: {name} (scene={self._scene}) =====")
        try:
            # 2026-11-20: 与模块路径统一走 run_steps —— 支持嵌套 list 与 BranchAborted 的
            # 「required 首步失败只中止当前层」语义, 不再逐条 run_step 绕过。
            self.run_steps(flow.get("steps", []))
        except StopRequested:
            print(f"[{_ts()}] ===== 流程已由停止请求中断: {name} =====")
            _metrics_interrupted = True
            return
        except FlowFailed as e:
            # 单跑该流程(非编排)时同样如实中止, 不把 fail_flow 当成未捕获异常抛到调用方
            print(f"[{_ts()}] ===== 流程中止(主动判失败): {name} -> {e} =====")
            _metrics_interrupted = True
            return
        finally:
            # 度量基座: 轮结束落盘(三条退出路径统一走 finally; interrupted 如实标记:
            # StopRequested/FlowFailed 由标记位, 未捕获异常经 finally 期 exc_info 兜底)。
            metrics_recorder.metrics_round_end(
                _metrics_rec, ocr_stat=self._ocr_stat,
                interrupted=_metrics_interrupted or sys.exc_info()[0] is not None)
        print(f"[{_ts()}] ===== 流程完成: {name} =====")

    def run_module(self, module: dict, registry: dict) -> str:
        """执行单个模块(module), 返回结果: 'ok' | 'skip' | 'fail'。
        module: {"id","flow","flow_data","required","on_fail"}
        registry: {文件名: 已加载的 flow dict}, 避免重复读盘。
        """
        mid = module.get("id", "?")
        self._module = str(mid)      # 失败登记时标注来源模块
        self._buy_count = 0          # G1 v2: 单轮购买次数随模块重置(硬上限按模块计)
        # V03(ii)(batch-11): 编排层短路 —— 本轮归位已失败(ensure_home 如实放弃)时, 后续模块
        # 开头仅做**一次** at_home_main 轻验: 画面已自行恢复 → 清位照常执行; 仍卡在同一画面
        # → 该模块短路记 fail(report_failure 照发, 不掩盖失败), 不再每模块重复烧 4 轮归位
        # (2026-11-07 日志 1180 行起: 同一卡死画面连累 energy/claim/daily 各跑 4 轮空转)。
        # 不改引擎判定语义(方案红线); 状态位按轮重置(run_daily 入口)。
        if self._home_recover_failed:
            from pollin import at_home_main   # 函数内延迟导入(循环依赖, 同 _step_ensure_home)
            img0 = self.screenshot()
            if img0 is not None and at_home_main(self, img0):
                self._home_recover_failed = False   # 已自行恢复: 清位, 本模块照常执行
                print(f"[{_ts()}] [模块:{mid}] 轻验: 已回到主线(自行恢复), 清除归位失败位, 照常执行")
            else:
                print(f"[{_ts()}] [模块:{mid}] 本轮归位已失败且模块开头轻验仍不在主线, "
                      f"短路跳过(如实记失败, 不再空转 4 轮归位)")
                report_failure(mid, "归位失败短路: 本轮归位已失败, 模块开头轻验仍不在家园主界面, 本模块跳过")
                return "fail"
        # 批C-②: 模块级 OCR 统计清零(模块结束打印并累计进整轮 _ocr_stat_total)
        self._ocr_stat = _new_ocr_stat()
        # F03(batch-11): 模块生命周期清场 —— _last_dump/_count_probes 原先只在 claim_scroll/
        # count_probe 内写入/重置, 模块结束从不清空: 上一模块的旧行/旧读数跨模块残留
        # (FLOWS.md:623-625 官方登记的「第①步 claim_scroll 被页签守卫拦截时第②步 if_collected
        # 读上一轮旧行」脏读窗口)。入口清场 = 全新赋值(不用 .clear() 复用旧对象, 同型
        # 「入口重置」已出过翻倍 bug 先例 —— 原 run_daily 的 dict(self._ocr_stat) 10→20):
        # 清场后行缺失 → if_collected 走 else 跳过, 「如实不假装」, 判定方向更安全。
        self._last_dump = {}
        self._count_probes = {}
        _, fail_seq0 = get_failures(0)   # 进入模块前的失败序号, 用于识别流程内软失败(A1)
        fname = module.get("flow")
        flow = module.get("flow_data") or registry.get(fname)
        if flow is None:
            print(f"[{_ts()}] [模块:{mid}] 未找到流程文件 {fname}, 标记失败")
            report_failure(mid, f"模块流程文件缺失: {fname}")
            return "fail"
        on_fail = module.get("on_fail", "stop_round")
        required = module.get("required", False)
        print(f"\n>>> 模块执行: {mid} [{fname}] {'[必选]' if required else '[可选]'}".strip())
        try:
            if isinstance(flow, dict):
                self.run_steps(flow.get("steps", []))
            soft_items, fail_seq1 = get_failures(fail_seq0)
            if fail_seq1 > fail_seq0:
                # 流程内部已 report_failure 登记软失败(等待超时/放弃/跑满轮数等)但未抛异常:
                # 如实收成 'fail', 交编排 on_fail 处置, 避免汇总 fail 与 [失败] 登记自相矛盾(A1)
                self._print_ocr_stat(mid)
                print(f"[{_ts()}] <<< 模块失败(软失败 {len(soft_items)} 项): {mid} (on_fail={on_fail})")
                return "fail"
            self._print_ocr_stat(mid)
            print(f"[{_ts()}] <<< 模块完成: {mid}")
            return "ok"
        except FlowFailed as e:
            # 流程用 fail_flow 步骤主动判失败: 如实收成 'fail'(不是"模块异常"), 交编排 on_fail 处置
            self._print_ocr_stat(mid)
            print(f"[{_ts()}] <<< 模块失败: {mid} -> {e} (on_fail={on_fail})")
            report_failure(mid, str(e))
            return "fail"
        except Exception as e:
            self._print_ocr_stat(mid)
            print(f"[{_ts()}] <<< 模块异常: {mid} -> {e} (on_fail={on_fail})")
            report_failure(mid, f"模块异常: {e}")
            return "fail"

    def run_daily(self, plan: dict) -> dict:
        """按编排 plan 调度各模块。plan: {"name","modules":[{"id","flow",...}]}。
        返回统计: {"ok":[],"skip":[],"fail":[]}。容错规则由每个 module.on_fail 决定:
          skip        -> 失败继续下一个
          stop_round  -> 失败终止本轮后续模块
        收到停止请求时(StopRequested)立即中断本轮全部模块, 返回已执行统计。
        """
        clear_stop()
        # 批C-②: 整轮 OCR 统计清零。⚠ 主 agent 修订(里程碑 88): 原为 dict(self._ocr_stat) ——
        # run_module 只在**入口**清零 _ocr_stat(出口不清), 故同一进程连跑第 2 轮时, 此处会把上一轮
        # **末模块**的残留当成本轮初值, 整轮汇总被翻倍(实测: 伪造 10 次/轮 → 第 2 轮 20 次)。
        # 改为按 key 显式全零, 整轮统计才逐轮独立。
        self._ocr_stat_total = _new_ocr_stat()
        # V03(ii)(batch-11): 「归位已失败」状态位按轮重置 —— 作用域=本轮编排(见 run_module
        # 入口短路轻验与 note_home_recover_failed 公有口)。
        self._home_recover_failed = False
        name = plan.get("name", "每日编排")
        # 度量基座(2026-11-13 批): 轮开始落盘(内存采样+画面尺寸+OCR统计起点快照, 后者为全零
        # —— 整轮计数器刚清零)。纯观测: metrics_recorder 零 print 不改 stdout 行为, 失败静默。
        _metrics_rec = metrics_recorder.metrics_round_start(
            "daily", name, screen=(self.screen_w, self.screen_h), ocr_stat=self._ocr_stat_total)
        # 预加载所有引用到的流程
        registry = {}
        for m in plan.get("modules", []):
            fname = m.get("flow")
            if fname and fname not in registry:
                fp = FLOW_DIR / fname
                if fp.exists():
                    with open(str(fp), encoding="utf-8") as f:
                        registry[fname] = json.load(f)
        result = {"ok": [], "skip": [], "fail": []}
        self.current_module = None   # 当前运行模块(WebUI /api/status 读取, 用于锁定运行中模块的设置)
        _metrics_interrupted = False   # 度量基座: 停止请求中断标记(度量落盘用, 见 finally)
        print(f"\n[{_ts()}] ########## 编排: {name} ##########")
        try:
            for m in plan.get("modules", []):
                self._check_stop()
                mid = m.get("id")
                self.current_module = mid
                print(f"[{_ts()}] >>> 进入模块: {mid}")
                res = self.run_module(m, registry)
                self.current_module = None
                result[res if res in result else "fail"].append(mid)
                if res == "fail" and m.get("on_fail", "stop_round") == "stop_round":
                    print(f"[编排] 模块 {m.get('id')} 失败且 on_fail=stop_round, 终止本轮")
                    break
        except StopRequested:
            print(f"[{_ts()}] ########## 编排已由停止请求中断 ({len(result['ok'])} ok) ##########")
            _metrics_interrupted = True
            return result
        finally:
            self.current_module = None
            t = self._ocr_stat_total
            print(f"[{_ts()}] [OCR统计] 整轮: 全图 {t['full_n']} 次 {t['full_t']:.2f}s · "
                  f"区域 {t['region_n']} 次 {t['region_t']:.2f}s · 拆分 {t['split_n']} 次 {t['split_t']:.2f}s · "
                  f"缓存命中 {t['hit_n']} 次 · 直调 {t['direct_n']} 次 {t['direct_t']:.2f}s"
                  # P1(2026-11-10): 末尾追加 split 子类观测(拆宽/精识), 既有字段顺序与名字不变。
                  f" · 拆宽 {t.get('split_wide_n', 0)} 次 {t.get('split_wide_t', 0.0):.2f}s"
                  f" · 精识 {t.get('refine_n', 0)} 次 {t.get('refine_t', 0.0):.2f}s")
            by = t.get("by_src") or {}

            def _tot(kind, limit=8):
                d = by.get(kind) or {}
                items = sorted(d.items(), key=lambda kv: -kv[1])[:limit]
                return " · ".join(f"{k} {v}" for k, v in items) or "-"

            print(f"[{_ts()}] [OCR来源] 整轮 全图: {_tot('full')} | 拆分: {_tot('split')}")
            print(f"[{_ts()}] [OCR健康] 整轮 拆分缓存命中 {t['split_cache_hit']} 次 · "
                  f"仅子块命中 {t['split_only_hit']} 次 · 场景判断 {t['scene_calls']} 次"
                  f"(折叠 {t.get('scene_quiet_n', 0)}) · "
                  f"静默未命中 {t.get('miss_silent_n', 0)} 次(弹窗/启动守卫确认无)")
            if t.get("friend_coarse_n"):
                cn, ch = t["friend_coarse_n"], t.get("friend_coarse_hit", 0)
                fn, fh = t.get("friend_fine_n", 0), t.get("friend_fine_hit", 0)
                print(f"[{_ts()}] [粗OCR] 整轮 社交面板「好友」: 粗识 {ch}/{cn} ({ch / cn:.0%}) · "
                      f"精识兜底 {fh}/{fn} ({(fh / fn if fn else 0):.0%})")
            # 度量基座(2026-11-13 批): 轮结束落盘(与上方 [OCR统计] 整轮打印同一数据源 t,
            # OCR9「≥3 轮 [OCR统计]/[粗OCR] 落盘」与整轮编排开销补测的取数通道;
            # interrupted 如实标记: 停止请求由标记位, 未捕获异常经 finally 期 exc_info 兜底)。
            metrics_recorder.metrics_round_end(
                _metrics_rec, ocr_stat=t, result=result,
                interrupted=_metrics_interrupted or sys.exc_info()[0] is not None)
        print(f"[{_ts()}] ########## 编排结束: ok={len(result['ok'])} skip={len(result['skip'])} fail={len(result['fail'])} ##########")
        # 完成动作收尾(2026-11-10, 完成后关闭客户端): 全部模块跑完才触发(含某模块
        # stop_round 提前终止后的正常收尾); StopRequested 中断路径已在上面提前 return,
        # 不触发 —— 用户主动按停止时人在机器前, 不应再替其关客户端。
        # 动作解析: 编排级 plan["finish_action"](WebUI _run_daily_sel 显式传入)优先,
        # 其次全局配置 finish_action(/api/set_config 持久化), 都缺省 "none" = 零行为变化。
        action = str(plan.get("finish_action") or self.config.get("finish_action") or "none")
        self._finish_action(action)
        return result

    # ---- 完成动作: 编排跑完后的可选收尾(2026-11-10, 完成后关闭客户端; 默认 none=无动作) ----
    def _finish_action(self, action: str) -> None:
        """按动作名执行编排收尾。只认两值:
          none         -> 直接返回(零行为, 与旧版逐字节一致)
          close_client -> 关闭模拟器里的游戏客户端: 优先 MaaFw 停应用接口
                          (self._ctrl.post_stop_app —— maa.controller.AdbController
                          既有能力, ADB 控制器 intent=包名), 引擎无该能力(未连接/
                          控制器缺方法)时降级 adb shell am force-stop <包名>。
        约束: 任何失败只如实打日志, 不重试不降级不抛出(收尾动作绝不影响本轮统计返回);
        包名 target_package 缺键/空白时记 WARN 跳过(不做任何动作)。
        """
        # 动作名归一: 只认 "close_client"; none/空直接返回, 未知值记日志后按 none 处理
        # (WebUI 入口已拒收非法值, 这里是引擎侧兜底)。
        if action != "close_client":
            if action not in ("none", ""):
                print(f"[{_ts()}] [finish] 未知完成动作 {action!r}, 按 none 处理(不动作)")
            return
        # 动作前日志(动作前后各一条 [finish] 日志)
        print(f"[{_ts()}] [finish] 完成动作=close_client: 准备关闭客户端")
        # 包名来源: 配置键 target_package(可在模拟器 `adb shell dumpsys window` 查前台
        # 包名填入, 见 config.example.json 注释)。缺键/空白=记 WARN 跳过, 不做任何动作。
        pkg = str(self.config.get("target_package", "") or "").strip()
        if not pkg:
            print(f"[{_ts()}] [finish] WARN: 未配置 target_package，跳过关闭")
            return
        # 优先级 1: MaaFw 停应用接口 —— connect() 后持有的 AdbController 自带
        # post_stop_app(intent)(ADB 控制器下 intent 即包名), 命中即用, 不走 adb。
        ctrl = getattr(self, "_ctrl", None)
        if ctrl is not None and hasattr(ctrl, "post_stop_app"):
            try:
                print(f"[{_ts()}] [finish] 经 MaaFw post_stop_app 关闭: {pkg}")
                # Q04(batch-05): 原文只 .wait() 不查成败, 经 _post 统一 wait+succeeded 核验
                # (失败打 [失败] 行; 收尾「只如实打日志、不重试不降级不抛出」契约不变)。
                self._post(ctrl, "stop_app", pkg, desc=f"关闭客户端 {pkg}")
                print(f"[{_ts()}] [finish] MaaFw post_stop_app 已下发完成: {pkg}")
                return
            except Exception as e:
                # 调用失败如实记录后直接返回: 不重试、不降级 adb(降级只留给「接口不存在」)、不抛出
                print(f"[{_ts()}] [finish] MaaFw post_stop_app 失败: {e} (不重试)")
                return
        # 优先级 2(降级): 引擎无 MaaFw 停应用能力(未连接 _ctrl=None 或控制器缺方法) → adb 直停。
        print(f"[{_ts()}] [finish] 引擎无 MaaFw 停应用能力(_ctrl={type(ctrl).__name__ if ctrl is not None else None}), 降级 adb force-stop")
        try:
            import subprocess  # 局部导入(与 connect() 同风格); 桩测可整体 monkeypatch subprocess.run
            r = subprocess.run(
                [self.adb_path, "-s", self.address, "shell", "am", "force-stop", pkg],
                capture_output=True, timeout=15)  # 硬超时: 收尾动作绝不挂住编排线程
            if r.returncode == 0:
                print(f"[{_ts()}] [finish] adb force-stop {pkg} 完成")
            else:
                err = (getattr(r, "stderr", b"") or b"").decode("utf-8", "replace").strip()
                print(f"[{_ts()}] [finish] adb force-stop {pkg} 失败: rc={r.returncode} {err[:200]} (不重试)")
        except Exception as e:
            # 超时/adb 不存在等一切异常: 如实记录, 不重试不抛出
            print(f"[{_ts()}] [finish] adb force-stop {pkg} 异常: {e} (不重试)")

    # ---- 界面采集 ----
    def collect_ui(self, min_score=0.5, scene: str | None = None) -> dict:
        """采集当前界面所有文字块, 写入 click_log 知识库(按场景分组)。
        scene 缺省用 self._scene(流程步骤声明的当前界面)。
        返回: {文字: 记录} 字典。
        """
        img = self.screenshot()
        blocks = ocr_image(img)
        sc = scene or self._scene or "未分类"
        new_entries = {}
        for b in blocks:
            if b.get("score", 1.0) < min_score:
                continue
            text = b["text"].strip()
            if not text or len(text) < 2:
                continue
            cx, cy = b["center"]
            pt = Point(cx, cy, self.screen_w, self.screen_h)
            entry = {
                "name": text,
                "text": [text],
                "rel": [round(pt.rel[0], 4), round(pt.rel[1], 4)],
                "method": "ocr",
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "category": self.auto_category(text),
            }
            # 同场景同名按钮只保留最新(跨场景互不覆盖)
            self.click_log_scenes.setdefault(sc, {})[text] = entry
            self.click_log[text] = entry  # 同步扁平索引
            new_entries[text] = entry
        self._save_click_log()
        print(f"[采集] [{sc}] 当前界面: {len(new_entries)} 个按钮已写入知识库")
        for name, e in sorted(new_entries.items()):
            print(f"  {name:<16} 相对{e['rel']}")
        return new_entries
