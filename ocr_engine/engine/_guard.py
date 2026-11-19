"""click_text 三通道回退 + 相邻定位复用。

E01(batch-03, 2026-11-14) 自单文件 ocr_engine.py 机械拆包: 本文件各段为原文件对应
行段的**逐行原文**(唯 __file__ 锚点因包层级 +1 机械重锚定, 见 ast_hash_compare.py
allowlist)。行为等价口径: 帧集回归 0 退化 + 闸门全绿 + import 面零改动。
原行段映射: evidence/batch-03/tiles_manifest.json。
"""
from __future__ import annotations

import time

from .._constants import BIAS_HARD_PX, BIAS_MAX_PX
from .._geometry import Point

class _GuardMixin:
    def click_text(self, keywords, img=None, fallback_rel=None, min_score=0.5, exact=False,
                   region_rel=None, exclude=None, no_fallback=False,
                   verify: bool = False) -> bool:
        """OCR 定位关键字并点击。命中返回 True。

        1.0 #10: `verify=True`（步骤里写 `"verify": true`）时，点击前抓一帧、点击返回后
        再抓一帧做 `verify_action` 分类；仅当判定为 `no_change`（点了界面没动）才返回 False，
        `failed`（截不到图）不否决点击本身。默认关闭 —— 既有流程零行为变化、零额外截图。
        回退链: OCR → 颜色特征(若知识库有 color 配置) → 进程缓存 → 知识库坐标 → 失败
        exact=True 时用精确匹配(要求块文本完全等于关键字)。
        no_fallback=True 时**禁止缓存回退**: OCR/锚点/颜色全部未命中就直接如实返回 False,
        不采信任何历史坐标盲点。用于「点错后果严重」的高危按钮(如「切换账号」一旦盲点到
        「登录」就会用错误账号跑完当天全部任务), 宁可失败交调用方处置。
        全局开关 `use_cache_pos`(data/config.json, **默认 false**) 关闭时, **自动学习到的缓存**整条停用:
        「均值复核」(拿历史均值 veto 本次 OCR 命中)不执行, 回退链也不再查 `mean_rel`/进程缓存 `last_rel`/
        知识库 `rel`。但**步骤里显式手写的 `fallback_rel` 仍生效** —— 那是人工设计的兜底(flows 中数十处),
        与"自动学到的历史坐标"性质不同, 全局开关不得静默禁用它。
        no_fallback(步骤级)比全局开关更严格: 连显式 `fallback_rel` 一并禁用, 只认本次实时识别结果。
        配套开关 `log_click_pos`(**默认 false**) 关闭时 `_log_click` 不再把坐标写入知识库(见 docstring)。
        region_rel 给定时只在限定区域内找文字, 并**跳过均值复核**: 同一个按钮在界面上出现多次时
        (如花灵派对面板里多处「领取」)单一均值必然对不上, 区域限定本身已是可信来源,
        不能再让缓存 veto 掉一个真实的 OCR 命中(缓存回退不得作为命中判据)。
        其余情况方案②复核: OCR 命中点与该按钮(按当前场景)历史均值偏差 > BIAS_MAX_PX 时判为可疑,
        触发局部放大重识别(_refine_hit)校准; 无更优子块时, 偏差未超 BIAS_HARD_PX 则沿用原命中并记录日志,
        超过 BIAS_HARD_PX 则判为误命中并**弃用**(不点击/不写知识库), 交由回退链(均值/缓存)处理。
        """
        kw0 = keywords[0] if isinstance(keywords, list) else keywords
        # 1.0 #10: 点后校验的"点击前帧"（仅 verify=True 时才多截一帧）
        before = (img if img is not None else self.screenshot()) if verify else None
        # 全局开关「使用缓存位置」(use_cache_pos) 默认关闭: 关闭后不采信**自动学习到的**历史坐标
        # ——既不做「均值复核」(拿历史均值去 veto 本次 OCR 命中), 也不走缓存回退(不查 mean_rel/last_rel/
        # 知识库 rel)。步骤里显式手写的 fallback_rel 属人工兜底, 不受此开关影响(见 docstring)。
        use_cache = bool(self.config.get("use_cache_pos", False))
        # 批B 相邻定位复用: 上一步(if_text/wait_text)刚命中的同一点位, 若本次 click_text 的查询
        # 参数兼容(关键字子集/区域子集/阈值不更松/exact 兼容/未传 img/不在均值复核路径)且该点位
        # 自身满足本次判据, 则直接复用 —— 免去二次截图 + 全图 OCR。不兼容返回 None 走原路径。
        guard_pt = self._take_guard_point(keywords, img, min_score, exact,
                                          region_rel, exclude, use_cache)
        if guard_pt is not None:
            self._last_locate_source = "ocr"
            mt = getattr(self, "_last_match_text", None)
            tag = f" 命中块文字'{mt}'" if mt and mt != kw0 else ""
            print(f"[OCR命中] {keywords} -> {guard_pt.x},{guard_pt.y}{tag} (复用上一步守卫定位, 免重扫)")
            self.click_abs(guard_pt.x, guard_pt.y)
            self._log_click(kw0, keywords, guard_pt, "ocr", category=self._step_category)
            return self._finish_click(verify, before, keywords, guard_pt)
        pt = self.locate(keywords, img=img, min_score=min_score, exact=exact,
                         region_rel=region_rel, exclude=exclude)
        dropped_by_review = False   # 是否被复核判为误命中而弃用(用于日志如实描述, 不能与"未OCR到"混淆)
        if pt is not None and region_rel is not None:
            print(f"[复核] {kw0} 区域限定{list(region_rel)}, 跳过均值复核")
        elif pt is not None and not use_cache:
            # 同一条全局事实不要在每次 OCR 命中时重复刷屏(提示只打一次)
            if not getattr(self, "_cachepos_notice_done", False):
                self._cachepos_notice_done = True
                print("[复核] 使用缓存位置已关闭(use_cache_pos=false), 不做均值复核、不用历史坐标回退(本提示只打一次)")
        if pt is not None and region_rel is None and use_cache:
            entry = self._entry_for(kw0)
            mean = entry.get("mean_rel") if entry else None
            dev = self._bias_px(pt, mean, self.screen_w, self.screen_h)
            if dev is not None and dev > BIAS_MAX_PX:
                print(f"[复核] {kw0} OCR命中({pt.x},{pt.y}) 与场景均值{tuple(round(v,3) for v in mean)} "
                      f"偏差{dev:.0f}px > {BIAS_MAX_PX}px, 二次精细处理…")
                rp = self._refine_hit(kw0, pt, img if img is not None else self.screenshot())
                dev2 = self._bias_px(rp, mean, self.screen_w, self.screen_h) if rp is not None else None
                if dev2 is not None and dev2 < dev:
                    print(f"[复核] 局部重识别得更稳子块({rp.x},{rp.y}) 偏差{dev2:.0f}px, 校准确认")
                    pt = rp
                elif dev > BIAS_HARD_PX:
                    print(f"[复核] 偏差{dev:.0f}px 超硬阈值 {BIAS_HARD_PX}px 且无更优子块, 判为误命中, 弃用该 OCR 命中")
                    pt = None                     # 不可信 -> 不点击/不写库, 交回退链
                    dropped_by_review = True
                else:
                    print(f"[复核] 局部重识别无更优子块, 沿用 OCR 命中")
        if pt is not None:
            self._last_locate_source = "ocr"
            mt = getattr(self, "_last_match_text", None)
            # 如实打印实际命中的原始文字: 关键字是子串匹配, 「领取」命中的可能是「已领取」,
            # 不报出来就会被误读成"识别到了领取按钮"。
            tag = f" 命中块文字'{mt}'" if mt and mt != kw0 else ""
            print(f"[OCR命中] {keywords} -> {pt.x},{pt.y}{tag}")
            self.click_abs(pt.x, pt.y)
            self._log_click(kw0, keywords, pt, "ocr", category=self._step_category)
            return self._finish_click(verify, before, keywords, pt)
        # 锚点偏移定位 (固定尺寸界面, 如登录界面无文字图形按钮)
        kws = keywords if isinstance(keywords, list) else [keywords]
        for kw in kws:
            entry = self.click_log.get(kw)
            if entry and "anchor" in entry:
                pt_a = self.locate_anchor_offset(entry["anchor"], img=img)
                if pt_a is not None:
                    self._last_locate_source = "anchor"
                    print(f"[锚点偏移命中] {kw} -> {pt_a.x},{pt_a.y}")
                    self.click_abs(pt_a.x, pt_a.y)
                    self._log_click(kw, [kw], pt_a, "anchor", category=self._step_category)
                    return self._finish_click(verify, before, keywords, pt_a)
        # 颜色特征检测 (针对无文字的图形按钮)
        for kw in kws:
            entry = self.click_log.get(kw)
            if entry and entry.get("method") == "color" and "color" in entry:
                pt_c = self.locate_color(entry["color"], img=img)
                if pt_c is not None:
                    self._last_locate_source = "color"
                    print(f"[颜色命中] {kw} -> {pt_c.x},{pt_c.y}")
                    self.click_abs(pt_c.x, pt_c.y)
                    self._log_click(kw, [kw], pt_c, "color", category=self._step_category)
                    return self._finish_click(verify, before, keywords, pt_c)
        if no_fallback:
            # 高危按钮: 本次实时识别(OCR/锚点/颜色)全部未命中时, 连步骤里显式写的回退坐标也不盲点
            # (2026-10-03: 「切换账号」OCR 永远认不到折角图标, 一路回退到历史坐标 (989,283),
            #  该点此时已是「登录」-> 误登录, 公告/进入游戏/收尾守卫全部空转)。
            self._last_locate_source = "none"
            print(f"[未命中] {keywords} (no_fallback=True: 禁用一切缓存/回退坐标, 交调用方处置)")
            self.dump_full_frame(f"未命中:{kw0}")
            return False
        # OCR+锚点+颜色均未命中: 尝试回退缓存 (方案②: 均值点补齐优先于进程缓存/最新坐标; 再无知识库坐标)
        if fallback_rel is None:
            if not use_cache:
                # 全局开关「使用缓存位置」(use_cache_pos) 默认关闭: 不查自动学习到的历史坐标
                # (mean_rel 均值 / last_rel 进程缓存 / click_log 知识库坐标), 认不到就如实失败。
                # 注意: 只挡"自动缓存"; 上面 no_fallback 分支已放行步骤里显式手写的 fallback_rel。
                self._last_locate_source = "none"
                print(f"[未命中] {keywords} (use_cache_pos=false: 不用自动缓存的历史坐标, 交调用方处置)")
                self.dump_full_frame(f"未命中:{kw0}")
                return False
            for kw in kws:
                e = self._entry_for(kw)
                if e and e.get("mean_rel"):
                    fallback_rel = tuple(e["mean_rel"])
                    break
            if fallback_rel is None:
                for kw in kws:
                    if kw in self.last_rel:
                        fallback_rel = self.last_rel[kw]
                        break
            if fallback_rel is None:
                for kw in kws:
                    e = self.click_log.get(kw) or {}
                    if e.get("method") == "fallback":
                        # 回退坐标不是位置证据, 不得再当作缓存复用 —— 否则一次"没识别到就盲点"会把错坐标
                        # 反复续传(毒坐标自我强化)。本条防御与 _log_click 的"fallback 不落库"配套。
                        print(f"[回退] 跳过 [{kw}] 的历史缓存回退条目(method=fallback, 非位置证据)")
                        continue
                    rel = e.get("rel")
                    if rel:
                        fallback_rel = tuple(rel)
                        break
        if fallback_rel is not None:
            self._last_locate_source = "fallback"
            reason = "复核弃用后回退" if dropped_by_review else "未OCR到"
            print(f"[回退缓存] {keywords} {reason}, 用缓存 {fallback_rel}")
            pt_fb = Point.from_rel(fallback_rel[0], fallback_rel[1], self.screen_w, self.screen_h)
            self.click_rel(*fallback_rel)
            self._log_click(kw0, keywords, pt_fb, "fallback", category=self._step_category)
            return self._finish_click(verify, before, keywords, pt_fb)
        self._last_locate_source = "none"
        print(f"[未命中] {keywords}")
        return False

    def _finish_click(self, verify: bool, before, keywords, pt) -> bool:
        """1.0 #10: 可选点后校验。仅 no_change（界面没动）否决战果；failed 不否决。"""
        if not verify:
            return True
        out = self.verify_action(before, wait=0.8)
        diff = out.get("diff")
        extra = f" blocker={out.get('blocker')}" if out.get("blocker") else ""
        print(f"[验证] {keywords} @({pt.x},{pt.y}) -> {out['result']}"
              f"(diff={'-' if diff is None else round(diff, 4)}){extra}")
        return out["result"] != "no_change"

    # ---- 相邻定位复用 (性能批 zcode-20261007-16 批B) ----
    @staticmethod
    def _region_within(c, g) -> bool:
        """相对区域 c 是否被 g 包含(None=全图)。坐标均为 [x1,y1,x2,y2] (0~1), 归一化同帧可比。"""
        if g is None:
            return True          # 守卫全图 -> 任何区域都在其内
        if c is None:
            return False         # 本次全图 ⊄ 守卫子区域
        return c[0] >= g[0] and c[1] >= g[1] and c[2] <= g[2] and c[3] <= g[3]

    def _remember_guard(self, kws, pt, exact, region_rel, min_score,
                        exclude=None) -> None:
        """记录一次定位守卫(if_text/wait_text)的**真实 OCR 命中**, 供**紧邻的下一步**
        click_text 复用同一命中点位。仅在真实命中处调用(缓存回退不在此列)。

        关键: 记下命中块 b 的 score/text 与守卫查询参数 —— click_text 复用时必须逐条校验
        (见 _take_guard_point): 复用点必须自身满足 click 的全部判据, 且 click 判据是守卫判据的
        "子集"(关键字/区域/阈值/exclude), 以保证收窄后 click 的首个命中仍是同一个块。
        """
        if not self.config.get("guard_reuse", True):
            return
        b = getattr(self, "_last_match_block", None) or {}
        kws = list(kws) if isinstance(kws, list) else [kws]
        self._guard_hit = {
            "seq": self._step_seq + 1,               # 仅紧邻的下一次 run_step 可复用
            "kws": frozenset(kws),
            "exact": bool(exact),
            "region": tuple(region_rel) if region_rel else None,
            "min_score": min_score,
            "exclude": frozenset(exclude or ()),
            "pt": pt,
            "text": (b.get("text") or "").strip(),
            "score": b.get("score", 1.0),
        }

    def _take_guard_point(self, keywords, img, min_score, exact, region_rel,
                          exclude, use_cache):
        """若存在**紧邻、兼容**的定位守卫, 复用其命中点位并返回 Point; 否则返回 None。

        安全规则(须全部满足; 任一不满足即返回 None, 走原 locate 路径):
          1) 仅紧邻下一步: 守卫的 seq == 当前步骤 seq(中间隔了任何步骤即失效);
          2) 未显式传 img: 复用点与守卫取自同一帧截图;
          3) 守卫 exact=False(if_text/wait_text 恒为子串匹配) 且 本次关键字 ⊆ 守卫关键字;
          4) 本次区域 ⊆ 守卫区域;  本次 min_score >= 守卫 min_score;  守卫 exclude ⊆ 本次 exclude;
          5) 不在 use_cache 的均值复核路径(region 为空且 use_cache 时, 正常路径会拿均值复核,
             复用会改变该行为, 故不复用);
          6) 复用点自身满足本次全部判据: score 达标 / 命中文字满足关键字语义 / 不含本次 exclude /
             落在本次区域内。
        全局开关 guard_reuse(data/config.json, 默认 true) 置 false 时, _remember_guard 不再记录,
        本方法恒返回 None —— 一键关闭该优化(无需改代码)。
        """
        if not self.config.get("guard_reuse", True):
            return None
        g = self._guard_hit
        if g is None or g["seq"] != self._step_seq or img is not None:
            return None
        if use_cache and region_rel is None:
            return None
        kws = list(keywords) if isinstance(keywords, list) else [keywords]
        if not (frozenset(kws) <= g["kws"]) or g["exact"]:
            return None
        if not self._region_within(region_rel, g["region"]):
            return None
        if min_score < g["min_score"]:
            return None
        ex = set(exclude or ())
        if not (g["exclude"] <= ex):
            return None
        pt, text, score = g["pt"], g["text"], g["score"]
        if score < min_score:
            return None
        if ex and any(e in text for e in ex):
            return None
        if region_rel is not None:
            w, h = self.screen_w, self.screen_h
            rx1, ry1 = int(region_rel[0] * w), int(region_rel[1] * h)
            rx2, ry2 = int(region_rel[2] * w), int(region_rel[3] * h)
            if not (rx1 <= pt.x <= rx2 and ry1 <= pt.y <= ry2):
                return None
        if not any((text == k) if exact else (k in text) for k in kws):
            return None
        # 通过全部校验: 一次性消费, 并补齐与正常命中一致的副作用(last_rel / _last_match_text)
        self._guard_hit = None
        for k in kws:
            self.last_rel[k] = pt.rel
        self._last_match_text = text or None
        return pt
