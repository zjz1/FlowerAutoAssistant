"""流程执行: 等待原语/run_steps/run_step/run_navigate。

E01(batch-03, 2026-11-14) 自单文件 ocr_engine.py 机械拆包: 本文件各段为原文件对应
行段的**逐行原文**(唯 __file__ 锚点因包层级 +1 机械重锚定, 见 ast_hash_compare.py
allowlist)。行为等价口径: 帧集回归 0 退化 + 闸门全绿 + import 面零改动。
原行段映射: evidence/batch-03/tiles_manifest.json。
"""
from __future__ import annotations

import re
import time

from .._exceptions import BranchAborted, FlowFailed, StopRequested, stop_requested
from .._failures import report_failure

class _FlowExecMixin:
    # ---- 流程执行 ----
    @staticmethod
    def _check_stop():
        """在需要中断的位置调用: 若已请求停止则抛 StopRequested 中断流程。"""
        if stop_requested():
            raise StopRequested("收到停止请求, 中断流程")

    def wait_text(self, keywords, timeout=30, interval=1.0, need_refine: bool = True,
                  min_score: float = 0.5):
        """轮询等待某文字出现, 返回 Point; 超时返回 None。

        超时语义(2026-10-07 用户决策「等待时间不计 OCR」): timeout 只累计**纯等待**
        (每轮探测后的 sleep), 截图/OCR 耗时不计入 —— 识别再慢也不压缩探测次数。
        背景: 10-07 22:49 实测登录页轮播动画打死帧缓存, 单轮全图 OCR 5.6s,
        旧墙钟语义下 startup 10s 窗口被 OCR 吃掉 83%(仅 2 次探测), 冷加载误报即此。
        wait_text / wait_text_gone / wait_scene 三处循环骨架同步此语义。
        O2(2026-10-22): `need_refine=False` 供启动页状态守卫等纯判断调用跳过拆块。
        2026-10-23: `min_score` 步骤参数接通(此前 JSON 里写 min_score 会被静默忽略, 同 click_text 旧坑)。
        """
        kws = keywords if isinstance(keywords, list) else [keywords]
        waited, probes = 0.0, 0
        while waited < timeout:
            self._check_stop()
            img = self.screenshot()
            probes += 1
            pt = self.locate(kws, img=img, min_score=min_score, need_refine=need_refine)
            if pt is not None:
                # 批B: 登记守卫, 供紧邻下一步 click_text 复用该命中点位(免二次截图+全图 OCR)。
                self._remember_guard(kws, pt, False, None, 0.5)
                print(f"[等待成功] {kws} @ {pt.x},{pt.y} (第{probes}次探测)")
                return pt
            time.sleep(interval)
            waited += interval
        print(f"[等待超时] {kws} (纯等待{timeout}s, 探测{probes}次)")
        self.dump_full_frame(f"等待超时:{kws}")
        report_failure(self._module, f"等待文本 {kws} 超时 纯等待{timeout}s/{probes}次探测")
        return None

    def wait_text_gone(self, keywords, timeout=30, interval=1.0, require_seen=False):
        """轮询等待某文字消失, 返回 True; 超时返回 False。超时语义同 wait_text(纯等待时钟)。

        E2(2026-10-27): `require_seen=True` 时, **首次探测即未见** = 该文字从未出现过 ——
        意味着"已经离开原界面"的前提不成立(前置动作很可能没生效), 返回 False 并如实打印,
        **不再**打出误导性的"[消失成功]"(2026-10-26 双日志实锤: 行未命中后 wait_text_gone
        首探即"消失成功", 把链的空转伪装成了正常完成)。缺省 False 保持旧行为。"""
        kws = keywords if isinstance(keywords, list) else [keywords]
        waited, probes = 0.0, 0
        while waited < timeout:
            self._check_stop()
            img = self.screenshot()
            probes += 1
            if self.locate(kws, img=img, min_score=0.3, need_refine=False) is None:
                if require_seen and probes == 1:
                    print(f"[消失跳过] {kws} (require_seen: 首探即未见=文字从未出现, "
                          f"前置动作可能未生效, 不假装离开成功)")
                    return False
                print(f"[消失成功] {kws} (第{probes}次探测)")
                return True
            time.sleep(interval)
            waited += interval
        print(f"[消失超时] {kws} (纯等待{timeout}s, 探测{probes}次)")
        self.dump_full_frame(f"消失超时:{kws}")
        report_failure(self._module, f"等待文本 {kws} 消失超时 纯等待{timeout}s/{probes}次探测")
        return False

    def wait_update_done(self, step: dict) -> bool:
        """步骤 wait_update_done: 等待游戏资源更新完成并自动进入登录页。

        实机依据(2026-10-23 用户授权探测, 未做额外点击):
          - 更新提示: 弹窗「有需要更新的内容，共57个，109.4MB」+「确定」; 提示在屏时先点确定。
          - 下载期: 底部「开始更新资源..(N/57)」+ 一位小数百分比(20.7%) + 「736KB/S (22.3MB/109.4MB)」。
          - 下载完成后**自动进入登录页**(「登录」「登录其他账号」「186****61」), 无完成弹窗、无重启。
          - ⚠ 进度带不能取 0.78~0.93(108px@720p): RapidOCR 检不出; 0.70~0.98(202px) 可稳定读出。

        参数: timeout(墙钟秒, 默认 600) / interval(默认 4)
              progress_region_rel / prompt_region_rel / done_region_rel
              prompt_keywords / confirm_keywords / confirm_tries
              progress_keywords / done_keywords / update_done_keywords / error_keywords
              max_error_retries / stall_warn / name
        返回 True=已到登录页 / False=超时、提示点不掉或更新异常(均如实 report_failure)。
        注意: 本步骤 timeout 是**墙钟**(含 OCR/点击), 与 wait_text 的纯等待时钟不同 ——
              更新时间不可预估, 且进度/点击本身要算进预算。
        """
        timeout = max(1.0, float(step.get("timeout", 600)))
        interval = max(0.5, float(step.get("interval", 4.0)))
        progress_region = step.get("progress_region_rel") or [0.0, 0.70, 1.0, 0.98]
        prompt_region = step.get("prompt_region_rel") or [0.25, 0.24, 0.75, 0.82]
        done_region = step.get("done_region_rel") or [0.20, 0.30, 0.90, 0.75]
        prompt_kws = step.get("prompt_keywords") or ["有需要更新的内容"]
        confirm_kws = step.get("confirm_keywords") or ["确定"]
        active_kws = step.get("progress_keywords") or ["开始更新资源", "正在检测资源更新"]
        done_kws = step.get("done_keywords") or ["登录", "点击进入游戏", "进入游戏"]
        done_more_kws = step.get("update_done_keywords") or ["更新完成", "重启游戏", "重新启动", "更新完毕"]
        error_kws = step.get("error_keywords") or ["更新失败", "网络异常", "下载失败"]
        confirm_tries = max(0, int(step.get("confirm_tries", 3)))
        max_error_retries = max(0, int(step.get("max_error_retries", 2)))
        stall_warn = max(0.0, float(step.get("stall_warn", 120)))
        label = step.get("name") or "资源更新"
        mod = getattr(self, "current_module", None) or ""
        pct_re = re.compile(r"(\d{1,3}(?:\.\d)?)\s*%")
        mask_re = re.compile(r"\d{3}\*{4}\d{2}")

        def _text(blocks) -> str:
            return " ".join(b.get("text", "") for b in blocks)

        deadline = time.time() + timeout
        confirm_used = confirm_miss = 0
        error_retries = 0
        last_pct = None
        max_pct = -1.0
        last_change = time.time()
        unknown_n = 0
        last_unknown = ""
        probes = 0

        while time.time() < deadline:
            self._check_stop()
            img = self.screenshot()
            if img is None:
                time.sleep(min(interval, 1.0))
                continue
            probes += 1

            # 1) 更新提示仍在屏 -> 点「确定」(最多 confirm_tries 次; 点不掉如实失败)
            pb = self._ocr_candidates(img, prompt_region, need_refine=False)[0]
            if any(k in _text(pb) for k in prompt_kws):
                if confirm_used >= confirm_tries:
                    print(f"[更新] {label}: 更新提示仍在屏, 「确定」已点 {confirm_used} 次仍未生效")
                    self.dump_full_frame(f"更新提示无法关闭:{label}")
                    report_failure(mod, f"{label}: 更新提示无法关闭(确定点击 {confirm_used} 次未生效)")
                    return False
                pt = self.locate(confirm_kws, img=img, min_score=0.5,
                                 region_rel=prompt_region, need_refine=False)
                if pt is None:
                    confirm_miss += 1
                    print(f"[更新] {label}: 更新提示在屏但未定位到「确定」({confirm_miss}/3)")
                    if confirm_miss >= 3:
                        self.dump_full_frame(f"更新提示无确定:{label}")
                        report_failure(mod, f"{label}: 更新提示在屏但 OCR 定位不到「确定」")
                        return False
                    time.sleep(interval)
                    continue
                confirm_miss = 0
                confirm_used += 1
                print(f"[更新] {label}: 更新提示在屏 -> 第{confirm_used}次点击「确定」@({pt.x},{pt.y})")
                self.click_abs(pt.x, pt.y)
                time.sleep(1.5)
                continue

            # 2) 下载进度带(区域够高, 见 docstring 的 108px 教训)
            rb = self._ocr_candidates(img, progress_region, need_refine=False)[0]
            rtext = _text(rb)
            m = pct_re.search(rtext)
            pct = float(m.group(1)) if m else None
            if pct is not None or any(k in rtext for k in active_kws):
                unknown_n = 0
                last_unknown = ""
                if pct is not None:
                    max_pct = max(max_pct, pct)
                    if last_pct is None:
                        print(f"[更新] {label}: 下载中 {pct:g}%")
                        last_change = time.time()
                    elif pct != last_pct:
                        # 2026-10-24(P3-6): 回跳只记「读数变化」, 不伪装成正常进度推进。
                        # 实机出现过 82.6% -> 8%(疑似识别误差/单文件进度与总进度混读),
                        # 完成判据用的是登录页, 与进度读数无关。
                        if pct < last_pct:
                            print(f"[更新] {label}: 进度读数回跳 {last_pct:g}% -> {pct:g}%"
                                  f"(识别误差/多进度源, 仅记录, 不改变完成判据)")
                        else:
                            print(f"[更新] {label}: 进度 {last_pct:g}% -> {pct:g}%")
                        last_change = time.time()
                    last_pct = pct
                    if stall_warn and time.time() - last_change >= stall_warn:
                        print(f"[更新] {label}: 进度停滞({pct:g}%, "
                              f"已 {int(time.time() - last_change)}s 无变化), 继续等待")
                        last_change = time.time()
                elif last_pct is None:
                    print(f"[更新] {label}: 更新进行中")
                    last_change = time.time()
                time.sleep(interval)
                continue

            # 3) 登录页(正向完成判据)
            db = self._ocr_candidates(img, done_region, need_refine=False)[0]
            dtext = _text(db)
            if any(k in dtext for k in done_kws) or mask_re.search(dtext):
                print(f"[更新] {label}: 已进入登录界面 (探测{probes}次, 最高进度"
                      f"{f'{max_pct:g}%' if max_pct >= 0 else '未读到'})")
                return True

            # 4) 底部无进度且未到登录页 -> 每 2 次探测做一次全屏 OCR 判过渡/异常
            unknown_n += 1
            if unknown_n >= 2:
                fb = self._ocr_frame(img, need_split=False)[0]
                ftext = _text(fb)
                if ftext != last_unknown:
                    print(f"[更新] {label}: 过渡画面 -> 全屏 OCR: "
                          + " | ".join(b.get("text", "") for b in fb[:10]))
                    last_unknown = ftext
                if any(k in ftext for k in error_kws):
                    if error_retries < max_error_retries:
                        # exact: 「重试」是子串高发词(如「请重试」是说明文字, 不是按钮), 只认等文本块
                        pt = self.locate(["重试"], img=img, min_score=0.4, exact=True,
                                         need_refine=False)
                        if pt is not None:
                            error_retries += 1
                            print(f"[更新] {label}: 更新异常 -> 第{error_retries}次点击「重试」"
                                  f"@({pt.x},{pt.y})")
                            self.click_abs(pt.x, pt.y)
                            time.sleep(2.0)
                            unknown_n = 0
                            continue
                    print(f"[更新] {label}: 更新异常且无法重试, 如实上报")
                    self.dump_full_frame(f"更新异常:{label}")
                    report_failure(mod, f"{label}: 更新异常(重试 {error_retries} 次仍失败)")
                    return False
                if any(k in ftext for k in done_more_kws):
                    pt = self.locate(confirm_kws, img=img, min_score=0.4, need_refine=False)
                    if pt is not None:
                        print(f"[更新] {label}: 出现更新完成提示 -> 点击「确定」@({pt.x},{pt.y})")
                        self.click_abs(pt.x, pt.y)
                        time.sleep(2.0)
                        unknown_n = 0
                        continue
                if any(k in ftext for k in done_kws) or mask_re.search(ftext):
                    print(f"[更新] {label}: 已进入登录界面 (全屏复核)")
                    return True
                unknown_n = 0

            time.sleep(interval)

        last = f"{max_pct:g}%" if max_pct >= 0 else "未读到"
        print(f"[更新] {label}: 等待超时 {timeout:g}s (最后进度 {last}, 探测{probes}次)")
        self.dump_full_frame(f"更新超时:{label}")
        report_failure(mod, f"{label}: 资源更新等待超时 {timeout:g}s(最后进度 {last})")
        return False

    def detect_scene(self, timeouts: dict) -> str:
        """判断当前所处界面。timeouts: {场景标识文字: 超时秒}。
        依次 OCR 检查每个标识文字是否存在, 返回命中的场景 key; 全未命中返回 'unknown'。
        """
        img = self.screenshot()
        hits = []
        for label, kws in timeouts.items():
            kws_list = kws if isinstance(kws, list) else [kws]
            for kw in kws_list:
                if self.locate([kw], img=img, min_score=0.4) is not None:
                    hits.append(label)
                    break
        return hits[0] if hits else "unknown"

    def run_steps(self, steps: list, indent=1):
        """顺序执行一组 steps, 支持 list 形式的嵌套(用于 loop 子块)。返回达到的最大步骤索引。

        E2(2026-10-27): 步骤抛出 BranchAborted(required 步骤失败)时, 中止**当前这一层列表**
        的剩余步骤并打印一行短路日志; 上一层的后续步骤照常执行 —— 使「任务链首步失败即放弃整链,
        不空跑链内收尾步骤」成为流程可声明的能力(required 缺省 False, 既有流程零行为变化)。
        """
        for step in steps:
            if isinstance(step, list):
                # 嵌套块列表
                try:
                    self.run_steps(step, indent=indent + 1)
                except BranchAborted:
                    print("  " * indent + "[分支短路] 子列表被 required 步骤中止, 继续当前列表后续步骤")
                continue
            try:
                self.run_step(step, indent=indent)
            except BranchAborted as e:
                print("  " * indent + f"[分支短路] required 步骤失败({e or '未附原因'}), "
                      f"中止当前列表剩余 {len(steps) - steps.index(step) - 1} 步, 继续上层后续步骤")
                break
        return 0

    def run_step(self, step: dict, indent=1):
        """执行单个步骤。step 为流程 JSON 中的一个节点; 分派外壳逐 type 转 handler(E06)。

        支持全部 46 种步骤类型(= 模块级 STEP_TYPES 白名单, tools/check_project.py 闸门消费;
        本 docstring 原先只列 11 种的漂移随批对齐 —— F09 文档维度仅改本 docstring):
        buy_item / buy_seed / claim_scroll / click_account_tail / click_rel / click_row_button /
        click_template / click_text / close_dialog / community_like / count_probe / count_text /
        dump_frame / dump_text / ensure_home / ensure_menu / fail_flow / fairyland_claim /
        friend_pollin / if_account_tail / if_collected / if_color_count / if_config / if_count /
        if_fraction / if_greater / if_scene / if_text / if_time / if_weekday / loop_fraction /
        loop_text / loop_times / navigate / plant_flower / plant_harvest / retry_loop /
        reward_dialog / sleep / slide / store_fraction / touch_drag / wait_scene / wait_text /
        wait_text_gone / wait_update_done

        handler 签名统一为 `self._step_<type>(step, kws, pad, indent)`(kws/pad/indent 为
        run_step 前导段既有局部量); 分支体逐行原文搬移至 _steps.py, AST 分支体全等对拍。
        """
        self._check_stop()
        pad = "  " * indent
        s_type = step.get("type")
        if not s_type:
            # 纯文档节点(如 {"_note": "..."}): 不是可执行步骤。
            # 此前会一路落到末尾的 [未知步骤] None, 每遇到一个就在日志里刷一行噪音。
            return
        # 批B: 每个可执行步骤递增序号 —— 相邻定位守卫只在"紧邻的下一步"可复用(见 _take_guard_point)。
        # 放在文档节点之后: 注释节点无副作用, 不消耗序号, 不至于平白让紧邻守卫过期。
        self._step_seq += 1
        # O0(2026-10-21): 标记本步骤为 OCR 发起处(纯观测)。不做 save/restore —— 每个步骤都会重置,
        # 残留值只会影响「步骤结束后、非步骤内」的调用(pollin 内部函数在 friend_pollin 步骤内, 正确归属)。
        self._ocr_src = s_type
        kws = step.get("text", step.get("keywords"))
        # 步骤可声明当前界面场景(如 "scene": "家园主界面"), 之后的点击默认记入该场景
        if step.get("scene"):
            self._scene = step["scene"]
        if step.get("category") and (
                s_type in ("click_text", "click_rel", "click_account_tail")):
            self._step_category = step["category"]
        if s_type == "wait_text":
            self._step_wait_text(step, kws, pad, indent)
        elif s_type == "dump_frame":
            self._step_dump_frame(step, kws, pad, indent)
        elif s_type == "wait_text_gone":
            self._step_wait_text_gone(step, kws, pad, indent)
        elif s_type == "wait_update_done":
            self._step_wait_update_done(step, kws, pad, indent)
        elif s_type == "click_text":
            self._step_click_text(step, kws, pad, indent)
        elif s_type == "click_template":
            self._step_click_template(step, kws, pad, indent)
        elif s_type == "click_account_tail":
            self._step_click_account_tail(step, kws, pad, indent)
        elif s_type == "sleep":
            self._step_sleep(step, kws, pad, indent)
        elif s_type == "click_rel":
            self._step_click_rel(step, kws, pad, indent)
        elif s_type == "close_dialog":
            self._step_close_dialog(step, kws, pad, indent)
        elif s_type == "dump_text":
            self._step_dump_text(step, kws, pad, indent)
        elif s_type == "claim_scroll":
            self._step_claim_scroll(step, kws, pad, indent)
        elif s_type == "reward_dialog":
            self._step_reward_dialog(step, kws, pad, indent)
        elif s_type == "if_collected":
            self._step_if_collected(step, kws, pad, indent)
        elif s_type == "if_text":
            self._step_if_text(step, kws, pad, indent)
        elif s_type == "if_scene":
            self._step_if_scene(step, kws, pad, indent)
        elif s_type == "wait_scene":
            self._step_wait_scene(step, kws, pad, indent)
        elif s_type == "if_account_tail":
            self._step_if_account_tail(step, kws, pad, indent)
        elif s_type == "if_fraction":
            self._step_if_fraction(step, kws, pad, indent)
        elif s_type == "store_fraction":
            self._step_store_fraction(step, kws, pad, indent)
        elif s_type == "if_greater":
            self._step_if_greater(step, kws, pad, indent)
        elif s_type == "count_text":
            self._step_count_text(step, kws, pad, indent)
        elif s_type == "if_color_count":
            self._step_if_color_count(step, kws, pad, indent)
        elif s_type == "if_config":
            self._step_if_config(step, kws, pad, indent)
        elif s_type == "if_time":
            self._step_if_time(step, kws, pad, indent)
        elif s_type == "if_weekday":
            self._step_if_weekday(step, kws, pad, indent)
        elif s_type == "loop_text":
            self._step_loop_text(step, kws, pad, indent)
        elif s_type == "loop_fraction":
            self._step_loop_fraction(step, kws, pad, indent)
        elif s_type == "loop_times":
            self._step_loop_times(step, kws, pad, indent)
        elif s_type == "retry_loop":
            self._step_retry_loop(step, kws, pad, indent)
        elif s_type == "navigate":
            self._step_navigate(step, kws, pad, indent)
        elif s_type == "friend_pollin":
            self._step_friend_pollin(step, kws, pad, indent)
        elif s_type == "plant_flower":
            self._step_plant_flower(step, kws, pad, indent)
        elif s_type == "plant_harvest":
            self._step_plant_harvest(step, kws, pad, indent)
        elif s_type == "fairyland_claim":
            self._step_fairyland_claim(step, kws, pad, indent)
        elif s_type == "buy_seed":
            self._step_buy_seed(step, kws, pad, indent)
        elif s_type == "ensure_menu":
            self._step_ensure_menu(step, kws, pad, indent)
        elif s_type == "ensure_home":
            self._step_ensure_home(step, kws, pad, indent)
        elif s_type == "community_like":
            self._step_community_like(step, kws, pad, indent)
        elif s_type == "click_row_button":
            self._step_click_row_button(step, kws, pad, indent)
        elif s_type == "slide":
            self._step_slide(step, kws, pad, indent)
        elif s_type == "count_probe":
            self._step_count_probe(step, kws, pad, indent)
        elif s_type == "if_count":
            self._step_if_count(step, kws, pad, indent)
        elif s_type == "buy_item":
            self._step_buy_item(step, kws, pad, indent)
        elif s_type == "touch_drag":
            self._step_touch_drag(step, kws, pad, indent)
        elif s_type == "fail_flow":
            self._step_fail_flow(step, kws, pad, indent)
        else:
            print(f"[未知步骤] {s_type}")

    def run_navigate(self, step: dict, indent=1):
        """按公共导航注册表进入目标界面(target)。返回 True=命中进入, False=轮数耗尽放弃。
        step: {"type":"navigate","target":"家族活动","max_rounds"?,"delay"?}
        每轮 do = [顶层 mark_text 探测点击] + entry["nav"]导航链; 期间任一带 mark 的
        click_text 真实命中会置 self._rr_hit=True -> 本轮成功, 并把 self._scene 切到目标场景。
        未命中则 close_dialog(only_types=["anchor_color"]) 脱困(锚点档, V02 batch-11 收窄 ——
        原 close_dialog() 全注册表与 retry_loop 同型隐患, 见 _steps._step_retry_loop 注),
        进入下一轮; 跑满轮数仍未命中则放弃(不抛错)。
        """
        pad = "  " * indent
        target = step.get("target")
        entry = self._navigation.get("targets", {}).get(target)
        if not entry:
            print(f"{pad}[navigate] 未在注册表找到目标『{target}』, 跳过")
            report_failure(self._module, f"navigate 目标《{target}》未在公共注册表 entries.json 中定义")
            return False
        mark_text = entry.get("mark_text", [])
        mfb = entry.get("mark_fallback_rel")
        scene = entry.get("scene")
        nav = entry.get("nav", [])
        rounds = step.get("max_rounds", entry.get("max_rounds", 3))
        # 每轮 do: 顶层先探测目标文字; 命中则点击(mark)即成功, 否则走上 fail.else? 见下
        # 注意: target 本身可能出现在任意深度(顶层/菜单后/家园后)。nav 已含内层 mark 点击,
        # 顶层这里统一补一个"当前画面即可见目标"的探测分支。
        do = [{
            "type": "if_text", "text": mark_text, "min_score": 0.4,
            "then": [{
                "type": "click_text", "text": mark_text, "mark": True,
                "delay": 1.5, "fallback_rel": mfb
            }]
        }]
        do.extend(nav)
        for i in range(rounds):
            print(f"{pad}[navigate] 《{target}》 第 {i+1}/{rounds} 轮")
            self._rr_hit = False
            self.run_steps(do, indent=indent + 1)
            if self._rr_hit:
                if scene:
                    self._scene = scene
                print(f"{pad}[navigate] 《{target}》 第 {i+1} 轮命中进入, scene={self._scene}")
                return True
            # 末轮措辞如实(同 retry_loop, 2026-10-03): 脱困动作保留, 仅措辞区分有无下一轮。
            if i + 1 < rounds:
                print(f"{pad}[navigate] 《{target}》 第 {i+1} 轮未命中, 脱困重试")
            else:
                print(f"{pad}[navigate] 《{target}》 第 {i+1} 轮未命中(已达最大轮数)")
            # V02(batch-11): 脱困收窄为锚点档(与 retry_loop 同批同型, 见 _steps._step_retry_loop 注)
            # —— 原全注册表 close_dialog 在非门控场景可能误点共享小✕(corner_pink_small 事故史
            # pollin.py:560-568, 误开在线礼包 12 次空转 ≈4.5min); 锚点档须读到面板标题才动作,
            # 无面板画面零动作, 失败方向如实(不再「乱点脱困」)。
            self.close_dialog(only_types=["anchor_color"])
            time.sleep(step.get("delay", 1.0))
        print(f"{pad}[navigate] 《{target}》 {rounds} 轮未命中, 放弃")
        report_failure(self._module, f"navigate 进入《{target}》{rounds} 轮未命中, 放弃")
        return False
