"""公共导航注册表 + 场景判断。

E01(batch-03, 2026-11-14) 自单文件 ocr_engine.py 机械拆包: 本文件各段为原文件对应
行段的**逐行原文**(唯 __file__ 锚点因包层级 +1 机械重锚定, 见 ast_hash_compare.py
allowlist)。行为等价口径: 帧集回归 0 退化 + 闸门全绿 + import 面零改动。
原行段映射: evidence/batch-03/tiles_manifest.json。
"""
from __future__ import annotations

import json

from .._constants import NAV_ENTRIES_PATH, NAV_SCENES_PATH

class _RegistryMixin:
    # ---- 公共导航注册表 (flows/common/entries.json) ----
    def _load_navigation(self) -> dict:
        """加载公共「进入目标界面」注册表。返回 {"targets": {目标名: {scene, mark_text, mark_fallback_rel, max_rounds, nav}}}。"""
        try:
            if NAV_ENTRIES_PATH.exists():
                with open(NAV_ENTRIES_PATH, encoding="utf-8") as fp:
                    data = json.load(fp)
                    return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"[导航注册表加载失败] {e}")
        return {}

    def _load_scenes(self) -> dict:
        """加载公共「场景判断」注册表。返回 {"scenes": {场景名: {description, markers, any_of, min_total}}}。"""
        try:
            if NAV_SCENES_PATH.exists():
                with open(NAV_SCENES_PATH, encoding="utf-8") as fp:
                    data = json.load(fp)
                    return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"[场景注册表加载失败] {e}")
        return {}

    # ---- 场景判断 (继 OCR 判断 / template 判断后的第三种判定, 2026-10-05 用户定立) ----
    # 判定条件完全声明在 flows/common/scenes.json 每个场景的 rule 条件树里(JSON 声明式,
    # 改条件/加场景不动引擎代码, 条件树可整体复制迁移到其它场景甚至其它项目):
    #   {"op":"hit",   "kw":"X",              "region_rel"?}  单关键字命中(子串包含)
    #   {"op":"any",   "kws":[...],           "region_rel"?}  至少其一命中
    #   {"op":"all",   "kws":[...],           "region_rel"?}  全部命中
    #   {"op":"count", "kws":[...],"min":N,"max":M,"region_rel"?}  命中数落在 [min,max]
    #   {"op":"absent","kws":[...],           "region_rel"?}  关键字均不出现(排除法)
    #   {"op":"and","conds":[...]} / {"op":"or","conds":[...]} / {"op":"not","cond":{...}}
    # region_rel=[x1,y1,x2,y2](0~1, 相对截图宽高)限定该叶子条件的判定区域。
    # 兼容旧版简写 schema(markers/any_of/min_total): 无 rule 时自动编译为等价条件树。
    @staticmethod
    def _rule_kws(cond) -> set:
        """收集条件树引用的全部关键字(仅用于日志展示命中集)。"""
        op = cond.get("op")
        if op in ("and", "or"):
            out: set = set()
            for c in cond.get("conds", []):
                out |= _RegistryMixin._rule_kws(c)
            return out
        if op == "not":
            return _RegistryMixin._rule_kws(cond.get("cond") or {})
        kws = set(cond.get("kws") or [])
        if cond.get("kw"):
            kws.add(cond["kw"])
        return kws

    @staticmethod
    def _compile_legacy_scene(entry: dict) -> dict:
        """旧版简写(markers/any_of/min_total) → 等价条件树, 保证旧条目继续可用。"""
        markers = list(entry.get("markers") or [])
        any_of = list(entry.get("any_of") or markers)
        min_total = entry.get("min_total", 1)
        conds = [{"op": "any", "kws": any_of}]
        if min_total > 1 and markers:
            conds.append({"op": "count", "kws": markers, "min": min_total})
        return conds[0] if len(conds) == 1 else {"op": "and", "conds": conds}

    def _scene_blocks(self, img, min_score: float, region_rel=None) -> list:
        """场景判定的 OCR 块(默认一次全图识别, 引擎帧缓存复用)。

        O0(2026-10-21): 把发起处临时标为 scene —— 这样 `[OCR统计]` 能直接量出「场景判断触发了
        多少次全图 OCR / 多少次拆分」。拆分结果(子块)在本函数里**从未被读取**, 该计数也是
        O1「场景判断不做拆分」的基线。
        O1(2026-10-21): 传 need_split=False —— 场景判定只需要 blocks, 拆分纯属浪费。
        E1(2026-10-27, zcode-20261028-2): 场景级 `region_rel`(scenes.json 场景条目可选字段)——
        该场景全部判据锚点所在的固定条带(面积须 <=40% 才生效, 否则按 None 走全图)。区域化后
        **区域 MISS 即最终判定**(场景判据的轮询负判定占调用大头 —— 若未命中回退全图,
        每次轮询 MISS 变成"裁片+全图"两次识别反而更慢; 与 find_text 的"未命中回退"语义**有意不同**,
        正确性前提=region 覆盖该场景全部锚点, 由 scenes.json 注明的实机证据与 C 类实机验证保证;
        `region_ocr: false` 总开关可一键回退全图)。块坐标仍映射回全图, rule 树叶节点自身的
        region_rel 过滤语义不变。
        """
        prev = self._ocr_src
        self._ocr_src = "scene"
        try:
            if region_rel and len(region_rel) == 4 and self.config.get("region_ocr", True):
                r = self._ocr_frame_region(img, region_rel, need_split=False)
                if r is not None:
                    return [b for b in r[0] if b.get("score", 1) >= min_score]
            return [b for b in self._ocr_frame(img, need_split=False)[0]
                    if b.get("score", 1) >= min_score]
        finally:
            self._ocr_src = prev

    @staticmethod
    def _kw_hits(blocks: list, kws, region=None) -> set:
        """返回 kws 中命中的子集(子串包含)。region=(x1,y1,x2,y2) 绝对像素, 限定块中心。"""
        if region is not None:
            x1, y1, x2, y2 = region
            blocks = [b for b in blocks
                      if x1 <= b.get("center", [0, 0])[0] <= x2
                      and y1 <= b.get("center", [0, 0])[1] <= y2]
        texts = [b.get("text", "") for b in blocks]
        return {kw for kw in kws if any(kw in t for t in texts)}

    def _eval_rule(self, cond, blocks) -> bool:
        """递归求值条件树。叶子节点带 region_rel 时按截图宽高换算为绝对像素区域。"""
        op = cond.get("op")
        if op in ("and", "or"):
            conds = cond.get("conds", [])
            if op == "and":
                return all(self._eval_rule(c, blocks) for c in conds)
            return any(self._eval_rule(c, blocks) for c in conds)
        if op == "not":
            return not self._eval_rule(cond.get("cond") or {}, blocks)
        region = None
        rr = cond.get("region_rel")
        if rr and self.screen_w and self.screen_h:
            region = (rr[0] * self.screen_w, rr[1] * self.screen_h,
                      rr[2] * self.screen_w, rr[3] * self.screen_h)
        kws = list(cond.get("kws") or [])
        if cond.get("kw"):
            kws.append(cond["kw"])
        hits = self._kw_hits(blocks, kws, region)
        if op in ("hit", "any"):
            return bool(hits)
        if op == "all":
            return len(hits) >= len(kws) if kws else False
        if op == "count":
            n = len(hits)
            return n >= cond.get("min", 0) and (cond.get("max") is None or n <= cond["max"])
        if op == "absent":
            return not hits
        print(f"[场景判断] 未知条件 op='{op}', 按 MISS")
        return False

    def judge_scene(self, name: str, img=None, min_score: float = 0.4,
                    quiet: bool = False) -> bool:
        """按 flows/common/scenes.json 注册表判定当前画面是否为指定场景(第三种判定)。
        判定条件 = 注册表里该场景的 rule 条件树(JSON 声明式, 改条件不动代码, ops 见类头注释);
        旧版简写(markers/any_of/min_total)自动编译为等价条件树。未注册场景按 MISS(不抛错)。

        quiet=True(2026-10-24 P2-5): 不打印逐次判定行, 只累加 `scene_quiet_n`。
        仅用于**轮询/重试循环内的常态负判定**(如等进园时每秒探一次「好友列表」),
        由调用方的汇总行保留信息; 一次性判定(如 ensure_home)仍应 quiet=False。
        """
        entry = self._scenes.get("scenes", {}).get(name)
        if not entry:
            print(f"[场景判断] 场景『{name}』未在 scenes.json 注册, 按 MISS")
            return False
        img = img if img is not None else self.screenshot()
        if img is None:
            return False
        rule = entry.get("rule") or self._compile_legacy_scene(entry)
        self._ocr_stat["scene_calls"] += 1   # O0: 场景判定调用次数(含帧缓存命中)
        # E1(2026-10-27): 场景条目可选 region_rel —— 该场景锚点集中的固定条带, 区域化省全图
        blocks = self._scene_blocks(img, min_score, entry.get("region_rel"))
        hits = self._kw_hits(blocks, self._rule_kws(rule))
        ok = self._eval_rule(rule, blocks)
        if quiet:
            self._ocr_stat["scene_quiet_n"] = self._ocr_stat.get("scene_quiet_n", 0) + 1
        else:
            print(f"[场景判断] {name}: 命中{len(hits)}处{sorted(hits)} -> {'HIT' if ok else 'MISS'}")
        return ok
