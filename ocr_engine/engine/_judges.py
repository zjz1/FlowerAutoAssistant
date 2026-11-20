"""颜色/锚点/解析/计数判定原子。

E01(batch-03, 2026-11-14) 自单文件 ocr_engine.py 机械拆包: 本文件各段为原文件对应
行段的**逐行原文**(唯 __file__ 锚点因包层级 +1 机械重锚定, 见 ast_hash_compare.py
allowlist)。行为等价口径: 帧集回归 0 退化 + 闸门全绿 + import 面零改动。
原行段映射: evidence/batch-03/tiles_manifest.json。
"""
from __future__ import annotations

import math
import re
import time

import numpy as np

from .._geometry import Point
from .._failures import report_failure

class _JudgeMixin:
    def locate_color(self, color_cfg: dict, img=None) -> "Point | None":
        """颜色特征定位: HSV 过滤 + 连通区域分析, 返回中心 Point。
        color_cfg: {"hsv_lower": [h,s,v], "hsv_upper": [h,s,v],
                    "area_min": int, "area_max": int, "region": [x1,y1,x2,y2]}
        """
        import cv2
        import numpy as np
        img = img if img is not None else self.screenshot()
        if img is None:
            return None
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        lower = np.array(color_cfg["hsv_lower"])
        upper = np.array(color_cfg["hsv_upper"])
        mask = cv2.inRange(hsv, lower, upper)
        # 可选: 限定搜索区域
        region = color_cfg.get("region")
        if region:
            x1, y1, x2, y2 = region
            sub_mask = np.zeros_like(mask)
            sub_mask[y1:y2, x1:x2] = mask[y1:y2, x1:x2]
            mask = sub_mask
        num_labels, _, stats, centroids = cv2.connectedComponentsWithStats(mask)
        area_min = color_cfg.get("area_min", 50)
        area_max = color_cfg.get("area_max", 999999)
        candidates = []
        for i in range(1, num_labels):
            area = stats[i, cv2.CC_STAT_AREA]
            if area_min < area < area_max:
                cx, cy = centroids[i]
                candidates.append((cx, cy, area))
        if not candidates:
            return None
        # 取面积最大的
        candidates.sort(key=lambda c: c[2], reverse=True)
        cx, cy = int(candidates[0][0]), int(candidates[0][1])
        return Point(cx, cy, self.screen_w, self.screen_h)

    def count_color(self, color_cfg: dict, img=None) -> int:
        """统计指定 HSV 颜色连通域的个数。

        用于「画面里某种色块出现多少次」的计数(如已领取的绿色勾号)。
        color_cfg: {"hsv_lower": [h,s,v], "hsv_upper": [h,s,v],
                    "area_min": int, "area_max": int, "region": [x1,y1,x2,y2]}
        与 locate_color 同一套 HSV 过滤 + 连通域分析, 但返回**命中个数**而非最大块中心;
        仅保留面积在 (area_min, area_max) 区间内的连通域, 默认排除过小/过大的噪点。
        """
        import cv2
        import numpy as np
        img = img if img is not None else self.screenshot()
        if img is None:
            return 0
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        lower = np.array(color_cfg["hsv_lower"])
        upper = np.array(color_cfg["hsv_upper"])
        mask = cv2.inRange(hsv, lower, upper)
        region = color_cfg.get("region")
        if region:
            x1, y1, x2, y2 = region
            sub_mask = np.zeros_like(mask)
            sub_mask[y1:y2, x1:x2] = mask[y1:y2, x1:x2]
            mask = sub_mask
        num_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        area_min = color_cfg.get("area_min", 20)
        area_max = color_cfg.get("area_max", 999999)
        n = 0
        for i in range(1, num_labels):
            area = stats[i, cv2.CC_STAT_AREA]
            if area_min < area < area_max:
                n += 1
        return n

    def locate_anchor_offset(self, anchor_cfg: dict, img=None, min_score=0.4) -> "Point | None":
        """锚点 + 像素偏移定位: 适用于「固定尺寸界面」(如小花仙登录界面不随设备分辨率缩放),
        整体画面相对坐标(0~1)会失效, 但「界面内元素相对锚点的像素偏移」恒定不变。

        anchor_cfg: {"anchors": [
            {"text_contains": "****", "offset": [dx, dy]},   # 按子串找锚点块(如账号 abc****de)
            {"text": ["登录"], "offset": [dx, dy]},           # 按关键字找锚点块
        ]}
        依次尝试各锚点, 首个命中即返回 锚点中心+offset 的 Point; 全部失败返回 None。
        """
        img = img if img is not None else self.screenshot()
        if img is None:
            return None
        for a in anchor_cfg.get("anchors", []):
            dx, dy = a.get("offset", [0, 0])
            pat = a.get("text_contains")
            if pat:
                # O2: 锚点查询只用合并块文本 -> 不拆分
                hit = next((b for b in self._ocr_frame(img, need_split=False)[0]
                            if pat in b.get("text", "")), None)
                if hit is None:
                    print(f"[锚点偏移] 未找到含 '{pat}' 的文本块")
                    continue
                cx, cy = hit["center"]
            else:
                pt = self.locate(a.get("text", []), img=img, min_score=min_score)
                if pt is None:
                    continue
                cx, cy = pt.x, pt.y
            tx = max(0, min(self.screen_w - 1, int(cx + dx)))
            ty = max(0, min(self.screen_h - 1, int(cy + dy)))
            return Point(tx, ty, self.screen_w, self.screen_h)
        return None

    def click_account_tail(self, tail: str, region_rel=None, min_score=0.4) -> bool:
        """在账号选择界面点击「账号文本尾部数字」匹配的账号条目并返回坐标缓存。

        账号条目文本形如 `abc****de`(中部脱敏的账号文本)。登录界面固定尺寸, 用 OCR 识别各账号块,
        locale 匹配文本尾部数字==tail 的块(可能合并块需取尾部), 点击其中心。
        region_rel=[x1,y1,x2,y2] 限定时只在账号列表区域匹配, 避免误点其它数字文本。
        """
        img = self.screenshot()
        if img is None:
            return False
        blocks = [b for b in self._ocr_frame(img, need_split=False)[0] if b.get("score", 1) >= min_score]
        # 区域限定
        if region_rel:
            w, h = self.screen_w, self.screen_h
            rx1, ry1 = int(region_rel[0] * w), int(region_rel[1] * h)
            rx2, ry2 = int(region_rel[2] * w), int(region_rel[3] * h)
            blocks = [b for b in blocks if rx1 <= b["center"][0] <= rx2 and ry1 <= b["center"][1] <= ry2]
        tail = str(tail).strip()
        best = None
        for b in blocks:
            txt = b.get("text", "").strip()
            # 匹配账号格式: 尾部数字 == tail (可含 **** 脱敏)
            m = re.search(r"(\d+)\s*$", txt)
            if not m or m.group(1) != tail:
                continue
            if "****" in txt:  # 确认是脱敏账号块
                best = b
                break
        if best is None:
            print(f"[账号尾部] 未找到尾部={tail} 的账号条目")
            report_failure(self._module, f"切换账号: 账号列表中未找到尾部={tail} 的账号条目"
                                        f"(账号列表可能未展开或已改版)")
            return False
        cx, cy = best["center"]
        pt = Point(cx, cy, self.screen_w, self.screen_h)
        print(f"[账号尾部] {best['text']} 尾部={tail} -> {cx},{cy}")
        self.click_abs(cx, cy)
        # 知识库键名不含真实账号文本: 按账号列表中的行序编号(每行坐标不同, 仍需分别缓存)
        rows = sorted([b for b in blocks if "****" in b.get("text", "")],
                      key=lambda b: b["center"][1])
        idx = next((i for i, b in enumerate(rows) if b is best), 0) + 1
        self._log_click(f"账号条目#{idx}", [], pt, "account_tail")
        for kw in (best["text"], f"账号尾{tail}"):
            self.last_rel[kw] = pt.rel
        return True

    def locate_anchor_color(self, anchor_kw, color_cfg: dict, dx_range=(150, 400), dy_tol=60,
                            img=None, min_score=0.4, quiet: bool = False) -> "Point | None":
        """锚点 + 颜色复合定位: 先 OCR 找锚点文字(如「提示」), 在锚点右侧/某偏移区域按颜色找目标按钮。
        用于弹窗关闭按钮等「有文字作锚点 + 按钮自身无文字」的场景, 比固定绝对坐标更健壮。
        color_cfg 的 region 若未提供, 则由锚点动态计算。
        quiet=True: 不打印（P1-2 批2 的“点后复检”用, 避免每次关闭都刷常态 MISS）。
        """
        img = img if img is not None else self.screenshot()
        if img is None:
            return None
        anchor = self.locate([anchor_kw], img=img, min_score=min_score,
                             log_miss=not quiet)
        if anchor is None:
            if not quiet:
                print(f"[锚点定位] 未找到锚点文字 '{anchor_kw}'")
            return None
        import cv2
        import numpy as np
        ax, ay = anchor.x, anchor.y
        # 若颜色配置未给定 region, 用锚点动态生成右侧搜索区
        cfg = dict(color_cfg)
        if not cfg.get("region"):
            x1, x2 = ax + dx_range[0], ax + dx_range[1]
            y1, y2 = ay - dy_tol, ay + dy_tol
            cfg["region"] = [max(0, x1), max(0, y1), x2, y2]
        return self.locate_color(cfg, img=img)

    def parse_fraction_at(self, region_rel, img=None, tol=60) -> "tuple[int,int] | None":
        """OCR 整图, 找形如 'a/b' 的数字块, 取中心离 region_rel*屏 最近且距离<=tol 的, 返回 (a,b)。
        未找到返回 None。
        """
        img = img if img is not None else self.screenshot()
        if img is None:
            return None
        w, h = self.screen_w, self.screen_h
        tx, ty = int(region_rel[0] * w), int(region_rel[1] * h)

        def _scan(blks):
            b_best, b_d = None, float("inf")
            for b in blks:
                m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", b.get("text", "").strip())
                if not m:
                    continue
                cx, cy = b["center"]
                d = (cx - tx) ** 2 + (cy - ty) ** 2
                if d < b_d:
                    b_d, b_best = d, (int(m[1]), int(m[2]))
            return b_best, b_d

        # 批C-①: 点+tol 查询换算小方框区域化(半径 tol*1.25: 覆盖中心在 tol 内的计数文字全像素;
        # a/b 计数器位置稳定, 裁片约 1~2% 全图面积)。区域内未找到 → 回退一次全图。
        if self.config.get("region_ocr", True) and w and h:
            r = int(tol * 1.25)
            box = (max(0, tx - r) / w, max(0, ty - r) / h, min(w, tx + r) / w, min(h, ty + r) / h)
            rr = self._ocr_frame_region(img, box, need_split=False)
            if rr is not None:
                best, best_d = _scan(rr[0])
                if best is not None and best_d ** 0.5 <= tol:
                    return best
        best, best_d = _scan(self._ocr_frame(img, need_split=False)[0])
        if best is not None and best_d ** 0.5 <= tol:
            return best
        return None

    def parse_count_at(self, region_rel, img=None, tol=120, min_score: float = 0.0) -> "int | None":
        """OCR 整图, 找形如 '关键字:N' 或纯数字('N') 的数字块, 取中心离 region_rel*屏 最近且距离<=tol 的, 返回 N。
        用于解析『剩余抽奖次数:3』这类带关键字的单值数字。未找到返回 None。
        min_score: 可选识别分数下限(if_greater 步骤的 min_score 在此生效)。
        """
        img = img if img is not None else self.screenshot()
        if img is None:
            return None
        w, h = self.screen_w, self.screen_h
        tx, ty = int(region_rel[0] * w), int(region_rel[1] * h)

        def _scan(blks):
            b_best, b_d = None, float("inf")
            for b in blks:
                if float(b.get("score", 1.0)) < min_score:
                    continue
                m = re.search(r"[:：]?\s*(\d+)\s*$", b.get("text", "").strip())
                if not m:
                    continue
                cx, cy = b["center"]
                d = (cx - tx) ** 2 + (cy - ty) ** 2
                if d < b_d:
                    b_d, b_best = d, int(m[1])
            return b_best, b_d

        # 批C-①: 同 parse_fraction_at(半径 tol*1.25 小方框区域化, 未命中回退全图)
        if self.config.get("region_ocr", True) and w and h:
            r = int(tol * 1.25)
            box = (max(0, tx - r) / w, max(0, ty - r) / h, min(w, tx + r) / w, min(h, ty + r) / h)
            rr = self._ocr_frame_region(img, box, need_split=False)
            if rr is not None:
                best, best_d = _scan(rr[0])
                if best is not None and best_d ** 0.5 <= tol:
                    return best
        best, best_d = _scan(self._ocr_frame(img, need_split=False)[0])
        if best is not None and best_d ** 0.5 <= tol:
            return best
        return None

    def eval_count(self, step, img=None) -> bool:
        """判断指定相对位置处 '关键字:N' 的数字 N 是否满足 condition (变量 N)。如 N>0。"""
        reg = step.get("region_rel")
        if not reg:
            print("[if_greater] 缺少 region_rel")
            return False
        n = self.parse_count_at(reg, img=img, min_score=float(step.get("min_score", 0.0)))
        if n is None:
            print(f"[if_greater] 区域{reg} 未识别到 '关键字:N' 数字")
            return False
        cond = step.get("condition", "N>0")
        if not re.fullmatch(r"[N0-9+\-*/<>!= ().,]+", cond):
            print(f"[if_greater] 非法条件 '{cond}'")
            return False
        try:
            ok = bool(eval(cond, {"__builtins__": {}}, {"N": n}))
        except Exception as e:
            print(f"[if_greater] 条件求值异常 '{cond}': {e}")
            return False
        print(f"[if_greater] 区域{reg} N={n} 条件'{cond}' -> {'TRUE' if ok else 'FALSE'}")
        return ok

    def count_text(self, kws, region_rel=None, img=None) -> int:
        """统计文本关键字在(限定时)区域内出现的总次数。跨 OCR 块去重: 挡块文本本身可能含多个关键字时按出现次数计。"""
        img = img if img is not None else self.screenshot()
        if img is None:
            return 0
        w, h = self.screen_w, self.screen_h
        blocks, _sub, used_region = self._ocr_candidates(img, region_rel, need_refine=False)
        hits = 0
        for _attempt in range(2):
            hits = 0
            for b in blocks:
                x1, y1, x2, y2 = b["box"]
                if region_rel:
                    rx1, ry1, rx2, ry2 = region_rel
                    if not (rx1 * w <= x1 and x2 <= rx2 * w and ry1 * h <= y1 and y2 <= ry2 * h):
                        continue
                text = b.get("text", "")
                for kw in (kws if isinstance(kws, list) else [kws]):
                    hits += text.count(kw)
            if hits or not used_region:
                break
            # 批C-①: 区域化零命中 → 回退一次全图重试(语义同 find_text); O2: 只数块 -> 不拆分
            blocks = self._ocr_frame(img, need_split=False)[0]
            used_region = False
        print(f"[count_text] {kws} 区域{region_rel or '全屏'} 命中 {hits} 次")
        return hits

    def eval_fraction(self, step, img=None) -> bool:
        """判断某个相对位置处 'a/b' 数字是否满足 condition。
        condition 使用变量 a(分子)/b(分母) 的表达式, 如 'a<b'、'a>=20'。返回 True/False。
        """
        reg = step.get("region_rel")
        if not reg:
            print("[if_fraction] 缺少 region_rel")
            return False
        res = self.parse_fraction_at(reg, img=img)
        if res is None:
            print(f"[if_fraction] 区域{reg} 未识别到 'a/b' 数字块")
            return False
        a, b = res
        cond = step.get("condition", "a<b")
        # 配置可信, 但仅放行数字/变量/运算符, 避免任意代码
        if not re.fullmatch(r"[ab0-9+\-*/<>!= ().,]+", cond):
            print(f"[if_fraction] 非法条件 '{cond}'")
            return False
        try:
            ok = bool(eval(cond, {"__builtins__": {}}, {"a": a, "b": b}))
        except Exception as e:
            print(f"[if_fraction] 条件求值异常 '{cond}': {e}")
            return False
        print(f"[if_fraction] 区域{reg} a={a}/b={b} 条件'{cond}' -> {'TRUE' if ok else 'FALSE'}")
        return ok

    def store_fraction(self, step: dict, img=None) -> bool:
        """读取指定相对位置处 'a/b' 数字的分子(a), 存入 config 并持久化。
        用于记录『已浇水次数』等带冷却/每日上限的行为, 便于流程判断当天是否已满。
        键名规则: config[step.key]=a, config[step.key+"_date"]=YYYYMMDD。
        读取不到 a/b 时返回 False (不写入)。
        """
        reg = step.get("region_rel")
        key = step.get("key")
        if not reg or not key:
            print("[store_fraction] 缺少 region_rel/key")
            return False
        res = self.parse_fraction_at(reg, img=img)
        if res is None:
            print(f"[store_fraction] 区域{reg} 未识别到 'a/b', 不写入")
            return False
        a, _b = res
        self.update_config(**{key: a, key + "_date": time.strftime("%Y%m%d")})
        print(f"[store_fraction] 区域{reg} a/b={a}/{_b} -> 已存 {key}={a}")
        return True

    def eval_config(self, step: dict) -> bool:
        """判断 config 中键值是否满足条件, 用于流程内做配置开关。返回 True/False。
        step: {key, value, op} op ∈ {==,!=,>=,<=,>,<}, 默认 ==。
        value 支持 ${key} 占位符解析与 bool/int/str 自动转换。
        """
        key = step.get("key")
        if not key:
            print("[if_config] 缺少 key")
            return False
        # G1 v2(2026-11-03): 支持步骤声明 default —— 配置缺键时按声明的缺省值判定。
        # 仅在本步显式给出 default 时生效, 既有流程(未写 default)行为完全不变。
        raw = self.config.get(key, step.get("default"))
        want_raw = self.resolve(str(step.get("value", "")))
        if want_raw in ("True", "true"):
            want = True
        elif want_raw in ("False", "false"):
            want = False
        else:
            try:
                want = int(want_raw)
            except (TypeError, ValueError):
                want = want_raw
        op = step.get("op", "==")
        try:
            ok = {
                "==": lambda: raw == want,
                "!=": lambda: raw != want,
                ">=": lambda: raw >= want,
                "<=": lambda: raw <= want,
                ">": lambda: raw > want,
                "<": lambda: raw < want,
            }[op]()
        except Exception as e:
            print(f"[if_config] 比较失败 {key}={raw} {op} {want}: {e}")
            return False
        print(f"[if_config] config[{key}]={raw} {op} {want} -> {'TRUE' if ok else 'FALSE'}")
        return ok

    def _calc_int(self, formula, a, b) -> int:
        """受信配置内安全求值整数公式。可用变量 a=分子, b=分母, 函数 ceil()/floor(), 四则运算。
        非法字符/求值异常抛 ValueError / 返回 0。
        """
        if not re.fullmatch(r"[a-zA-Z0-9+\-*/<>!= ().,]+", formula):
            raise ValueError(f"非法公式 '{formula}'")
        ns = {"a": a, "b": b, "ceil": math.ceil, "floor": math.floor}
        try:
            return int(eval(formula, {"__builtins__": {}}, ns))
        except Exception as e:
            raise ValueError(f"公式求值异常 '{formula}': {e}")

    def run_loop_fraction(self, step, indent=0):
        """按『分数区域算出的循环次数』重复执行 do 子流程。
        iterations: [{region_rel, formula}] 各自从相对位置读取 a/b 并按公式算一个整数值;
        combine: 取 min(默认) 或 max 合并; 结果再夹到 max_loop; 为 0 则不循环。
        典型用法: n=ceil((b-a)/57) 与 m=floor(a/20), combine=min → 每次消耗 20 体力直到结束或所需满足。
        """
        pad = "  " * indent
        img = self.screenshot()
        vals = []
        for spec in step.get("iterations", []):
            res = self.parse_fraction_at(spec["region_rel"], img=img)
            if res is None:
                print(f"{pad}[loop_fraction] 区域{spec['region_rel']} 未识别到 a/b, 循环次数=0")
                return
            v = self._calc_int(spec["formula"], res[0], res[1])
            print(f"{pad}[loop_fraction] 区域{spec['region_rel']} a={res[0]} b={res[1]} 公式'{spec['formula']}' -> {v}")
            vals.append(v)
        combine = step.get("combine", "min")
        m = min(vals) if combine != "max" else max(vals)
        if m < 0:
            m = 0
        m = min(m, step.get("max_loop", 100))
        print(f"{pad}[loop_fraction] 合并({combine})={vals} -> 循环 {m} 次")
        # 一次性步骤(如读完顶栏后点「光偶像」进入新界面), 在循环前执行一次
        if step.get("once"):
            print(f"{pad}[loop_fraction] 执行入场步骤 once")
            self.run_steps(step["once"], indent=indent + 1)
        for i in range(m):
            print(f"{pad} --- 逻辑 {i + 1}/{m} ---")
            self.run_steps(step.get("do", []), indent=indent + 1)
