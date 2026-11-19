"""run_step 分派 handler(E06+F01, batch-03): 42 个具名 handler, 与 run_step「保 elif 外壳」
分派一一对应。每个 handler 体 = 原 run_step 对应 `elif s_type == <类型名>` 分支体**逐行原文**
(整体反缩进 4, 注释随迁), 由 gen_commit_b.py 机械生成并做 AST 分支体全等对拍。
注: 本文件注释中的 s_type 比较字样均为 42 白名单成员本身(逐 handler 注释), 不引入新类型
(tools/check_project.py 兜底正则扫包对拍=42, 见 evidence/batch-03)。
签名为统一形 `(self, step, kws, pad, indent)` —— kws/pad/indent 是 run_step 前导段既有局部量,
未用参数为机械统一签名所致(零行为影响)。
"""
from __future__ import annotations

import re
import time

from .._exceptions import BranchAborted, FlowFailed
from .._failures import report_failure


class _StepHandlersMixin:
    # E06: 原 run_step `if s_type == "wait_text"` 分支体原文(快照行 3574-3576)
    def _step_wait_text(self, step, kws, pad, indent):
        self.wait_text(kws, timeout=step.get("timeout", 30), interval=step.get("interval", 1.0),
                       need_refine=step.get("need_refine", True),
                       min_score=step.get("min_score", 0.5))

    # E06: 原 run_step `elif s_type == "dump_frame"` 分支体原文(快照行 3582-3582)
    def _step_dump_frame(self, step, kws, pad, indent):
        self.dump_full_frame(str(step.get("tag") or "手动存证"))

    # E06: 原 run_step `elif s_type == "wait_text_gone"` 分支体原文(快照行 3587-3592)
    def _step_wait_text_gone(self, step, kws, pad, indent):
        ok_gone = self.wait_text_gone(kws, timeout=step.get("timeout", 30),
                                      interval=step.get("interval", 1.0),
                                      require_seen=bool(step.get("require_seen", False)))
        if step.get("required") and not ok_gone:
            report_failure(self._module, f"wait_text_gone {kws} 未确认离开(required)")
            raise BranchAborted(f"wait_text_gone {kws} 未确认离开")

    # E06: 原 run_step `elif s_type == "wait_update_done"` 分支体原文(快照行 3596-3599)
    def _step_wait_update_done(self, step, kws, pad, indent):
        ok = self.wait_update_done(step)
        if not ok and step.get("abort_on_fail"):
            raise FlowFailed(step.get("abort_reason")
                             or "资源更新未完成/异常, 按 abort_on_fail 中止本模块")

    # E06: 原 run_step `elif s_type == "click_text"` 分支体原文(快照行 3603-3621)
    def _step_click_text(self, step, kws, pad, indent):
        ok = self.click_text(kws, fallback_rel=step.get("fallback_rel"),
                             min_score=step.get("min_score", 0.5),
                             exact=step.get("exact", False),
                             region_rel=step.get("region_rel"),
                             exclude=step.get("exclude"),
                             no_fallback=step.get("no_fallback", False),
                             verify=step.get("verify", False))
        print(f"{pad}[click_text] {kws} -> {'ok' if ok else 'fail'}")
        if not ok and step.get("abort_on_fail"):
            # 高危步骤(如「切换账号」): 没点到就如实中止本模块, 不让流程带着错前提继续往下跑
            raise FlowFailed(step.get("abort_reason")
                             or f"click_text {kws} 未命中, 按 abort_on_fail 中止本模块")
        if ok and step.get("mark"):
            # P0-3: 缓存回退只是「照旧点一下」的兜底, 不构成「已进入目标界面」的证据,
            # 否则进入链永远"成功", 识别层整体失效也无人察觉。
            if self._last_locate_source == "fallback":
                print(f"{pad}[mark] {kws} 本次为缓存回退, 不计入命中(无法证明已在目标界面)")
            else:
                self._rr_hit = True  # 命中目标步骤, 记为本轮 retry_loop 成功
        time.sleep(step.get("delay", 0.5))

    # E06: 原 run_step `elif s_type == "click_template"` 分支体原文(快照行 3626-3646)
    def _step_click_template(self, step, kws, pad, indent):
        pt = self.click_template(
            step.get("template"),
            threshold=step.get("threshold", 0.8),
            region_rel=step.get("region_rel"),
            scale_range=step.get("scale_range", (0.7, 1.0)),
            fallback_rel=step.get("fallback_rel"),
            no_fallback=step.get("no_fallback", False),
            metric=step.get("metric", "sqdiff"),
            offset_rel=step.get("offset_rel"),
        )
        ok = pt is not None
        print(f"{pad}[click_template] {step.get('template')} -> {'ok' if ok else 'fail'}")
        if not ok and step.get("abort_on_fail"):
            raise FlowFailed(step.get("abort_reason")
                             or f"click_template {step.get('template')} 未命中, 按 abort_on_fail 中止本模块")
        if ok and step.get("mark"):
            if self._last_locate_source == "fallback":
                print(f"{pad}[mark] 模板 {step.get('template')} 本次为回退坐标, 不计入命中")
            else:
                self._rr_hit = True
        time.sleep(step.get("delay", 0.5))

    # E06: 原 run_step `elif s_type == "click_account_tail"` 分支体原文(快照行 3650-3661)
    def _step_click_account_tail(self, step, kws, pad, indent):
        tail = self.resolve(step.get("tail"))
        if tail in (None, ""):
            tail = self.resolve(self.config.get("target_tail", ""))
        ok = self.click_account_tail(str(tail), region_rel=step.get("region_rel"),
                                     min_score=step.get("min_score", 0.4))
        print(f"{pad}[click_account_tail] tail={tail} -> {'ok' if ok else 'fail'}")
        if not ok and step.get("abort_on_fail"):
            # 点不到目标账号就不许继续去点「登录」——否则会沿用当前(非目标)账号登录,
            # 之后整轮任务都跑在错误账号上。宁可当天不跑(用户 2026-10-03 决策)。
            raise FlowFailed(step.get("abort_reason")
                             or f"切换账号: 未找到尾部={tail} 的账号条目, 按 abort_on_fail 中止本模块")
        time.sleep(step.get("delay", 0.5))

    # E06: 原 run_step `elif s_type == "sleep"` 分支体原文(快照行 3663-3663)
    def _step_sleep(self, step, kws, pad, indent):
        time.sleep(step.get("seconds", 1.0))

    # E06: 原 run_step `elif s_type == "click_rel"` 分支体原文(快照行 3665-3667)
    def _step_click_rel(self, step, kws, pad, indent):
        rx, ry = step["rel"]
        self.click_rel(rx, ry)
        time.sleep(step.get("delay", 0.5))

    # E06: 原 run_step `elif s_type == "close_dialog"` 分支体原文(快照行 3669-3675)
    def _step_close_dialog(self, step, kws, pad, indent):
        self.close_dialog(
            anchor_kw=step.get("anchor", "提示"),
            dx_range=step.get("dx_range", (150, 400)),
            dy_tol=step.get("dy_tol", 60),
            only_types=step.get("only_types"),
        )
        time.sleep(step.get("delay", 1.0))

    # E06: 原 run_step `elif s_type == "dump_text"` 分支体原文(快照行 3678-3678)
    def _step_dump_text(self, step, kws, pad, indent):
        self._dump_text(step)

    # E06: 原 run_step `elif s_type == "claim_scroll"` 分支体原文(快照行 3681-3681)
    def _step_claim_scroll(self, step, kws, pad, indent):
        self._claim_scroll(step)

    # E06: 原 run_step `elif s_type == "reward_dialog"` 分支体原文(快照行 3684-3684)
    def _step_reward_dialog(self, step, kws, pad, indent):
        self.reward_dialog(step)

    # E06: 原 run_step `elif s_type == "if_collected"` 分支体原文(快照行 3687-3687)
    def _step_if_collected(self, step, kws, pad, indent):
        self._if_collected(step, indent)

    # E06: 原 run_step `elif s_type == "if_text"` 分支体原文(快照行 3691-3706)
    def _step_if_text(self, step, kws, pad, indent):
        region_rel = step.get("region_rel")
        min_score = step.get("min_score", 0.5)
        # B2/B3/B4(2026-10-22): 纯分支判定可传 need_refine=false 跳过拆块。
        #   拆块只为「紧邻下一步 click_text 复用命中点」服务(见 _remember_guard/_take_guard_point,
        #   守卫 seq 只允许紧邻一步); 若 then/else 首步与顶层后继都不点同词, 拆块纯浪费。
        pt = self.locate(kws, min_score=min_score, region_rel=region_rel,
                         need_refine=bool(step.get("need_refine", True)),
                         log_miss=bool(step.get("log_miss", True)))
        hit = pt is not None
        if hit:
            # 批B: 命中后登记守卫, 供紧邻下一步 click_text 复用该点位(免二次截图+全图 OCR)。
            self._remember_guard(kws, pt, False, region_rel, min_score)
        branch = step.get("then") if hit else step.get("else")
        print(f"{pad}[if_text] {kws} {'区域'+str(region_rel)+' ' if region_rel else ''}-> {'HIT' if hit else 'MISS'}")
        if branch:
            self.run_steps(branch, indent=indent + 1)

    # E06: 原 run_step `elif s_type == "if_scene"` 分支体原文(快照行 3710-3713)
    def _step_if_scene(self, step, kws, pad, indent):
        hit = self.judge_scene(step.get("scene", ""), min_score=step.get("min_score", 0.4))
        branch = step.get("then") if hit else step.get("else")
        if branch:
            self.run_steps(branch, indent=indent + 1)

    # E06: 原 run_step `elif s_type == "wait_scene"` 分支体原文(快照行 3725-3749)
    def _step_wait_scene(self, step, kws, pad, indent):
        scene = step.get("scene", "")
        scenes = scene if isinstance(scene, list) else [scene]
        timeout = step.get("timeout", 10)
        interval = step.get("interval", 1.0)
        okflag = False
        okname = None
        waited, probes = 0.0, 0
        while waited < timeout:
            self._check_stop()
            img = self.screenshot()
            probes += 1
            for nm in scenes:
                if self.judge_scene(nm, img=img, min_score=step.get("min_score", 0.4)):
                    okflag, okname = True, nm
                    break
            if okflag:
                break
            time.sleep(interval)
            waited += interval
        if okflag:
            if len(scenes) > 1:
                print(f"[等待成功] 场景『{okname}』(多场景任一命中, 第{probes}次探测)")
        else:
            print(f"[等待超时] 场景『{scene}』(纯等待{timeout}s, 探测{probes}次)")
            report_failure(self._module, f"等待场景『{scene}』超时 纯等待{timeout}s/{probes}次探测")

    # E06: 原 run_step `elif s_type == "if_account_tail"` 分支体原文(快照行 3755-3777)
    def _step_if_account_tail(self, step, kws, pad, indent):
        tail = str(self.resolve(step.get("tail", ""))).strip()
        img = self.screenshot()
        # O2: 只判尾部数字 -> 不拆分
        blocks = [b for b in (self._ocr_frame(img, need_split=False)[0] if img is not None else [])
                  if b.get("score", 1) >= step.get("min_score", 0.4)]
        if step.get("region_rel"):
            w, h = self.screen_w, self.screen_h
            rx1, ry1 = int(step["region_rel"][0] * w), int(step["region_rel"][1] * h)
            rx2, ry2 = int(step["region_rel"][2] * w), int(step["region_rel"][3] * h)
            blocks = [b for b in blocks
                      if rx1 <= b["center"][0] <= rx2 and ry1 <= b["center"][1] <= ry2]
        cur = None
        for b in blocks:
            txt = b.get("text", "").strip()
            m = re.search(r"(\d+)\s*$", txt)
            if m and "****" in txt:
                cur = m.group(1)
                break
        hit = bool(tail) and cur == tail
        print(f"{pad}[if_account_tail] 当前账号尾部={cur} 目标={tail} -> {'HIT' if hit else 'MISS'}")
        branch = step.get("then") if hit else step.get("else")
        if branch:
            self.run_steps(branch, indent=indent + 1)

    # E06: 原 run_step `elif s_type == "if_fraction"` 分支体原文(快照行 3780-3783)
    def _step_if_fraction(self, step, kws, pad, indent):
        hit = self.eval_fraction(step)
        branch = step.get("then") if hit else step.get("else")
        if branch:
            self.run_steps(branch, indent=indent + 1)

    # E06: 原 run_step `elif s_type == "store_fraction"` 分支体原文(快照行 3786-3786)
    def _step_store_fraction(self, step, kws, pad, indent):
        self.store_fraction(step)

    # E06: 原 run_step `elif s_type == "if_greater"` 分支体原文(快照行 3789-3792)
    def _step_if_greater(self, step, kws, pad, indent):
        hit = self.eval_count(step)
        branch = step.get("then") if hit else step.get("else")
        if branch:
            self.run_steps(branch, indent=indent + 1)

    # E06: 原 run_step `elif s_type == "count_text"` 分支体原文(快照行 3795-3800)
    def _step_count_text(self, step, kws, pad, indent):
        n = self.count_text(step.get("text"), region_rel=step.get("region_rel"))
        ok = n >= step.get("threshold", 1)
        branch = step.get("then") if ok else step.get("else")
        print(f"{pad}[count_text] {step.get('text')} 计数={n} threshold={step.get('threshold',1)} -> {'TRUE' if ok else 'FALSE'}")
        if branch:
            self.run_steps(branch, indent=indent + 1)

    # E06: 原 run_step `elif s_type == "if_color_count"` 分支体原文(快照行 3806-3827)
    def _step_if_color_count(self, step, kws, pad, indent):
        reg = step.get("region_rel")
        if reg:
            if not self.screen_w or not self.screen_h:
                self.screenshot()
            w, h = self.screen_w, self.screen_h
            reg = [int(reg[0] * w), int(reg[1] * h), int(reg[2] * w), int(reg[3] * h)]
        n = self.count_color({
            "hsv_lower": step.get("hsv_lower"),
            "hsv_upper": step.get("hsv_upper"),
            "area_min": step.get("area_min", 20),
            "area_max": step.get("area_max", 999999),
            "region": reg,
        })
        op = step.get("op", "<")
        target = step.get("threshold", 3)
        ok = {"<": lambda: n < target, "<=": lambda: n <= target,
              ">": lambda: n > target, ">=": lambda: n >= target,
              "==": lambda: n == target, "!=": lambda: n != target}[op]()
        branch = step.get("then") if ok else step.get("else")
        print(f"{pad}[if_color_count] {step.get('name','')} 色块数={n} {op} {target} -> {'TRUE' if ok else 'FALSE'}")
        if branch:
            self.run_steps(branch, indent=indent + 1)

    # E06: 原 run_step `elif s_type == "if_config"` 分支体原文(快照行 3830-3833)
    def _step_if_config(self, step, kws, pad, indent):
        hit = self.eval_config(step)
        branch = step.get("then") if hit else step.get("else")
        if branch:
            self.run_steps(branch, indent=indent + 1)

    # E06: 原 run_step `elif s_type == "if_time"` 分支体原文(快照行 3838-3846)
    def _step_if_time(self, step, kws, pad, indent):
        import datetime
        w = step.get("window", [10, 21])
        start, end = int(w[0]), int(w[1])
        hour = datetime.datetime.now().hour
        hit = (start <= hour <= end) if start <= end else (hour >= start or hour <= end)
        branch = step.get("then") if hit else step.get("else")
        print(f"{pad}[if_time] 当前 {hour} 时, 窗口 {start}-{end} -> {'TRUE' if hit else 'FALSE'}")
        if branch:
            self.run_steps(branch, indent=indent + 1)

    # E06: 原 run_step `elif s_type == "if_weekday"` 分支体原文(快照行 3850-3857)
    def _step_if_weekday(self, step, kws, pad, indent):
        import datetime
        days = {int(d) % 7 for d in step.get("days", [5, 6, 0])}
        today = datetime.datetime.now().weekday()
        hit = today in days
        branch = step.get("then") if hit else step.get("else")
        print(f"{pad}[if_weekday] weekday={today}(0=周一), 开放日{sorted(days)} -> {'TRUE' if hit else 'FALSE'}")
        if branch:
            self.run_steps(branch, indent=indent + 1)

    # E06: 原 run_step `elif s_type == "loop_text"` 分支体原文(快照行 3861-3891)
    def _step_loop_text(self, step, kws, pad, indent):
        kws = step.get("text", step.get("keywords"))
        body = step.get("do", [])
        guard = step.get("max_loop", 20)
        n = 0
        last_pt = None
        stalled = False
        while n < guard:
            pt = self.locate(kws, min_score=step.get("min_score", 0.4),
                             region_rel=step.get("region_rel"),
                             exclude=step.get("exclude"))
            if pt is None:
                break
            # 无进展守卫: 这一轮定位到的还是上一轮那个点, 说明点击对它根本没有作用
            # (按钮是「已领取」或未达标的灰按钮), 再点多少次结果都一样 —— 立刻停,
            # 不要空转满 max_loop 次骗自己"在领取"。
            if last_pt is not None and abs(pt.x - last_pt.x) <= 4 and abs(pt.y - last_pt.y) <= 4:
                stalled = True
                break
            n += 1
            last_pt = pt
            print(f"{pad}[loop_text] {kws} 存在({pt.x},{pt.y}), 执行第 {n} 次领取/操作")
            self.run_steps(body, indent=indent + 1)
        if stalled:
            print(f"{pad}[loop_text] {kws} 连续两轮落在同一坐标({last_pt.x},{last_pt.y})且画面无变化, "
                  f"判定该按钮当前不可领(已领取/未达标), 提前退出")
        elif n >= guard:
            # 到上限退出时按钮可能仍然存在, 不能说成"不存在/完成"(否则把放弃谎报成成功)
            print(f"{pad}[loop_text] {kws} 已达上限 {guard} 次仍在, 放弃本轮循环(未确认真已领完)")
            report_failure(self._module, f"loop_text {kws} 达上限 {guard} 次仍在, 放弃本轮(未确认真领完)")
        else:
            print(f"{pad}[loop_text] {kws} 不存在, 领取/操作完成, 退出")

    # E06: 原 run_step `elif s_type == "loop_fraction"` 分支体原文(快照行 3894-3894)
    def _step_loop_fraction(self, step, kws, pad, indent):
        self.run_loop_fraction(step, indent)

    # E06: 原 run_step `elif s_type == "loop_times"` 分支体原文(快照行 3897-3901)
    def _step_loop_times(self, step, kws, pad, indent):
        times = step.get("times", 1)
        body = step.get("do", [])
        for i in range(times):
            print(f"{pad}[loop_times] 第 {i+1}/{times} 次")
            self.run_steps(body, indent=indent + 1)

    # E06: 原 run_step `elif s_type == "retry_loop"` 分支体原文(快照行 3909-3934)
    def _step_retry_loop(self, step, kws, pad, indent):
        rounds = step.get("max_rounds", 3)
        body = step.get("do", [])
        fail_do = step.get("fail_do")
        hit = False
        for i in range(rounds):
            print(f"{pad}[retry_loop] 第 {i+1}/{rounds} 轮")
            self._rr_hit = False
            self.run_steps(body, indent=indent + 1)
            if self._rr_hit:
                print(f"{pad}[retry_loop] 第 {i+1} 轮命中目标, 退出")
                hit = True
                break
            # 末轮措辞如实(2026-10-03, 协作区 zcode-20261003-3): 最后一轮后并无下一轮重试,
            # 旧文案「脱困重试」言过其实; 脱困动作本身保留执行(后续步骤可能依赖末轮清场)。
            if i + 1 < rounds:
                print(f"{pad}[retry_loop] 第 {i+1} 轮未命中, 脱困重试")
            else:
                print(f"{pad}[retry_loop] 第 {i+1} 轮未命中(已达最大轮数)")
            if fail_do:
                self.run_steps(fail_do, indent=indent + 1)
            else:
                # V02(batch-11): 默认脱困收窄为锚点档(须 OCR 读到面板标题才动作) —— 原全注册表
                # close_dialog 与里程碑 93 修复前的 escape_overlay 同型(pollin.py:560-568 事故史:
                # corner_pink_small 误命中花园横幅 → 误开「在线礼包」面板 → ensure_home 未识别
                # 分支 12 次空转 ≈4.5min); GATE_TYPES 主界面门控只覆盖 户外/家园/好友列表 三场景
                # 且仅 only_types=None 时生效(_closebtn.close_dialog), 家族活动/委托子页/社区页等
                # 非门控场景下全表链仍可能选中共享小✕。已收窄先例: escape_overlay(pollin.py:585)/
                # ensure_home 锚点档(pollin.py:742)/buy_item 兜底(_buy.py:66)。
                # 失败方向从「可能乱点」变「只按标题自证关闭」; 锚点档在无面板画面零动作。
                # (前置排查: 全部 retry_loop/navigate 调用点确认无依赖全表关闭者 —— 6 处 retry_loop
                #  显式传 fail_do 不受影响, 4 处无 fail_do + 5 处 navigate 明细见 evidence/batch-11。)
                self.close_dialog(only_types=["anchor_color"])
                time.sleep(step.get("delay", 1.0))
        if not hit and step.get("report_fail", True):
            # 跑满轮数仍无任何带 mark 的真实命中 = 该功能的进入/触发失败(如实上报, 供失败弹窗)
            report_failure(self._module, f"retry_loop 跑满 {rounds} 轮仍未命中目标步骤")

    # E06: 原 run_step `elif s_type == "navigate"` 分支体原文(快照行 3939-3939)
    def _step_navigate(self, step, kws, pad, indent):
        self.run_navigate(step, indent)

    # E06: 原 run_step `elif s_type == "friend_pollin"` 分支体原文(快照行 3944-3949)
    def _step_friend_pollin(self, step, kws, pad, indent):
        from pollin import run_friend_pollin
        res = run_friend_pollin(self)
        print(f"{pad}[friend_pollin] 结果 {res}")
        if isinstance(res, dict) and any(v is None for v in res.values()):
            report_failure(self._module, f"好友采粉: 有类别未跑通(打开好友列表失败) 结果={res}")
        time.sleep(step.get("delay", 1.0))

    # E06: 原 run_step `elif s_type == "ensure_menu"` 分支体原文(快照行 3953-3955)
    def _step_ensure_menu(self, step, kws, pad, indent):
        ok = self.ensure_menu_expanded(step)
        print(f"{pad}[ensure_menu] 顶部菜单 -> {'ok' if ok else '未确认展开(已告警)'}")
        time.sleep(step.get("delay", 0.5))

    # E06: 原 run_step `elif s_type == "ensure_home"` 分支体原文(快照行 3960-3965)
    def _step_ensure_home(self, step, kws, pad, indent):
        from pollin import ensure_home
        ok = ensure_home(self)
        print(f"{pad}[ensure_home] 归位到自己家园 -> {'ok' if ok else 'fail'}")
        if not ok:
            report_failure(self._module, "ensure_home 未确认回到自己家园主界面(已如实报出, 不假装成功)")
        time.sleep(step.get("delay", 0.5))

    # E06: 原 run_step `elif s_type == "community_like"` 分支体原文(快照行 3970-3973)
    def _step_community_like(self, step, kws, pad, indent):
        from community_like import run_community_like
        res = run_community_like(self)
        print(f"{pad}[community_like] 结果 {res}")
        time.sleep(step.get("delay", 1.0))

    # E06: 原 run_step `elif s_type == "click_row_button"` 分支体原文(快照行 3977-3977)
    def _step_click_row_button(self, step, kws, pad, indent):
        self.click_row_button(step, indent)

    # E06: 原 run_step `elif s_type == "slide"` 分支体原文(快照行 3984-3988)
    def _step_slide(self, step, kws, pad, indent):
        sx, sy = (float(v) for v in step.get("start_rel", (0, 0)))
        ex, ey = (float(v) for v in step.get("end_rel", (0, 0)))
        dur = int(step.get("duration_ms", 600))
        self.swipe_rel(sx, sy, ex, ey, duration_ms=dur)
        time.sleep(step.get("delay", 1.5))

    # E06: 原 run_step `elif s_type == "count_probe"` 分支体原文(快照行 3993-3996)
    def _step_count_probe(self, step, kws, pad, indent):
        n = self.parse_count_at(step.get("region_rel"), tol=int(step.get("tol", 60)))
        self._count_probes[str(step.get("as", "count"))] = n
        print(f"{pad}[count_probe] {step.get('as', 'count')} = {n} (region {step.get('region_rel')})")
        time.sleep(step.get("delay", 0.5))

    # E06: 原 run_step `elif s_type == "if_count"` 分支体原文(快照行 4006-4024)
    def _step_if_count(self, step, kws, pad, indent):
        cur = self.parse_count_at(step.get("region_rel"), tol=int(step.get("tol", 60)))
        before = self._count_probes.get(str(step.get("before", "count")))
        cond = str(step.get("cond", "minus1"))
        if cur is None or before is None:
            ok = bool(step.get("on_unread", False))
            print(f"{pad}[if_count] 读数失败 cur={cur} before={before} -> {'TRUE(on_unread)' if ok else 'FALSE'}")
        elif cond == "minus1":
            sb, sc = str(before), str(cur)
            ok = (cur == before - 1) or (len(sc) < len(sb) and sb.startswith(sc))
        elif cond == "changed":
            ok = (cur != before)
        elif cond == "same":
            ok = (cur == before)
        else:
            ok = False
        print(f"{pad}[if_count] {step.get('before')}={before} -> cur={cur} cond='{cond}' -> {'TRUE' if ok else 'FALSE'}")
        branch = step.get("then") if ok else step.get("else")
        if branch:
            self.run_steps(branch, indent=indent + 1)

    # E06: 原 run_step `elif s_type == "buy_item"` 分支体原文(快照行 4028-4028)
    def _step_buy_item(self, step, kws, pad, indent):
        self.buy_item(step, indent)

    # E06: 原 run_step `elif s_type == "touch_drag"` 分支体原文(快照行 4036-4058)
    def _step_touch_drag(self, step, kws, pad, indent):
        sx, sy = (float(v) for v in step.get("start_rel", (0, 0)))
        ex, ey = (float(v) for v in step.get("end_rel", (0, 0)))
        press_pause = float(step.get("press_pause", 0.35))
        steps_n = max(2, int(step.get("steps", 8)))
        step_pause = float(step.get("step_pause", 0.15))
        end_pause = float(step.get("end_pause", 0.35))
        if not self.screen_w or not self.screen_h:
            self.screenshot()
        x1, y1 = int(sx * self.screen_w), int(sy * self.screen_h)
        x2, y2 = int(ex * self.screen_w), int(ey * self.screen_h)
        ctrl = self._ctrl
        # Q04(batch-05): 三段 post 原文只 .wait() 不查成败, 经 _post 统一 wait+succeeded 核验
        # (失败打 [失败] 行, 纯观测; 分段推进控制流与旧版一致 —— 判定行为零变化)。
        self._post(ctrl, "touch_down", x1, y1, desc=f"touch_drag 起点({x1},{y1})")
        time.sleep(press_pause)
        for i in range(1, steps_n + 1):
            xi = x1 + (x2 - x1) * i // steps_n
            yi = y1 + (y2 - y1) * i // steps_n
            self._post(ctrl, "touch_move", xi, yi, desc=f"touch_drag 分段{i}")
            time.sleep(step_pause)
        time.sleep(end_pause)
        self._post(ctrl, "touch_up", desc="touch_drag 抬起")
        print(f"{pad}[touch_drag] ({x1},{y1})->({x2},{y2}) 分段{steps_n}段 "
              f"(press {press_pause}s / step {step_pause}s / end {end_pause}s)")
        time.sleep(step.get("delay", 2.5))

    # E06: 原 run_step `elif s_type == "fail_flow"` 分支体原文(快照行 4064-4066)
    def _step_fail_flow(self, step, kws, pad, indent):
        reason = step.get("reason") or "流程主动中止(未说明原因)"
        print(f"{pad}[fail_flow] {reason} -> 中止本模块")
        raise FlowFailed(str(reason))
