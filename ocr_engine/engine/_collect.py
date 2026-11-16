"""采集/领取专属原子: dump_text/claim_scroll/if_collected/click_row_button。

E01(batch-03, 2026-11-14) 自单文件 ocr_engine.py 机械拆包: 本文件各段为原文件对应
行段的**逐行原文**(唯 __file__ 锚点因包层级 +1 机械重锚定, 见 ast_hash_compare.py
allowlist)。行为等价口径: 帧集回归 0 退化 + 闸门全绿 + import 面零改动。
原行段映射: evidence/batch-03/tiles_manifest.json。
"""
from __future__ import annotations

import json
import re
import time

from pathlib import Path

from .._exceptions import BranchAborted
from .._failures import report_failure

class _CollectMixin:
    # ---- 采集: dump_text (2026-10-12 每日任务/手账采集, 用户确认方案; 实机原型见协作区 v7/v8) ----
    def _group_task_rows(self, blocks):
        """行分组: 每个含 (a/b) 进度的块, 向上 Δy∈[0.01,0.09](屏高比) 找最近描述块配对。
        返回 [(desc_core, 'a/b', center_abs), ...] 按屏幕 y 排序; desc 去装饰前缀
        (·+*★?？!！~空白——实测这些符号 OCR 乱跳, 不可进指纹)。
        无进度的块不参与配对。2026-10-12 每日任务采集实机原型(协作区 v7/v8 两轮验证)。"""
        if not self.screen_w or not self.screen_h or not blocks:
            return []
        prog_re = re.compile(r"(\d+)\s*/\s*(\d+)")
        desc_re = re.compile(r"[\u4e00-\u9fff]")
        strip_re = re.compile(r"[·+*★?？!！~\s]")
        items = []
        for b in blocks:
            c = b.get("center")
            if not c and b.get("box"):
                box = b["box"]
                c = [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]
            if not c:
                continue
            items.append((b.get("text", ""), c[0] / self.screen_w, c[1] / self.screen_h, b, c))
        rows = []
        for text, rx, ry, b, c in items:
            m = prog_re.search(text)
            if not m:
                continue
            best = None
            for t2, rx2, ry2, b2, c2 in items:
                if b2 is b or not desc_re.search(t2) or prog_re.search(t2):
                    continue
                dy = ry - ry2
                if 0.01 <= dy <= 0.09 and 0.45 <= rx2 <= 0.85:
                    if best is None or dy < best[0]:
                        best = (dy, t2)
            core = strip_re.sub("", best[1]) if best else "?"
            rows.append((core, f"{int(m.group(1))}/{int(m.group(2))}", (c[0], c[1])))
        rows.sort(key=lambda r: r[2][1])
        return rows

    @staticmethod
    def _merge_rows(acc: list, rows: list) -> None:
        """把本屏行分组并入「本次采集」的累计列表 (按 (desc, progress) 去重, 先见先留, 保持上→下顺序)。

        v2.1(2026-10-17): 修复 _last_dump 曾**每轮覆盖**的丢行缺陷 —— 每日任务点赞门槛
        (if_collected 查「献上点赞」) 因内存只剩**末屏**行而查不到中段行, 点赞被误跳过
        (2026-10-16 日志实锤: 第 4 轮屏幕采到「为精美搭配献上点赞吧=0/2」, 8 轮扫到底后
        if_collected 判「命中行=None」走 else)。
        作用域(须与文档一致): acc 与 _last_dump[label] 均为**单次采集调用**的跨屏累计,
        调用开始时重置(防同进程重复调用残留旧行, 如循环跑第二次时把已完成任务误判为未完成);
        _write_collect 留档仍按**每屏**原样写入, 不受本合并影响。
        已知限制(观察项 O1, 暂不处理): OCR 对同一任务文字的轻微变体(尾标点/近形字)会使
        (desc, progress) 不完全相等而各留一条 -> 同一任务可能重复入列; 查询按先见序取第一条,
        对现有点赞门槛无影响; 若后续有按行计数用途再定模糊归并方案(见本批 REPORT 观察列表)。
        """
        seen = {(d, p) for d, p, _c in acc}
        for d, p, c in rows:
            if (d, p) not in seen:
                seen.add((d, p))
                acc.append((d, p, c))

    def _dump_text(self, step: dict) -> None:
        """dump_text 采集步骤: 区域 OCR → (可选)行分组 → [采集] 日志 + data/collect/<save>.jsonl。
        可选 scroll 滚动采集: 内部手势滑动(规则6边界: 手势参数非点击坐标, 2026-10-06 用户
        裁定沿用; 700ms 慢滑——400ms 实测被游戏/输入链吞掉致假冻结), 以「行分组指纹」连续
        两屏一致判列表到底(内容锚定, 免疫滚动位移/装饰噪声/动画闪烁)。
        页签守卫在 tab_region_rel 小区域独立检测——页签通常在采集区域外, 守卫不可复用采集区
        文本(2026-10-12 实机踩坑)。只读采集: 本步骤不点击任何业务按钮。参数:
          region_rel=[x1,y1,x2,y2] 采集区; label 日志标签; save jsonl 文件名(可省);
          row_pair=true 启用行分组; tab_region_rel+tab_variants 页签守卫;
          scroll={swipe:[x1,y1,x2,y2], duration_ms=700, settle=1.8, max_rounds=18}。"""
        region_rel = step.get("region_rel")
        label = step.get("label", "dump")
        save = step.get("save")
        use_pair = bool(step.get("row_pair"))
        tab_region = step.get("tab_region_rel")
        tab_vars = step.get("tab_variants") or []
        scroll = step.get("scroll") or {}
        max_rounds = max(1, int(scroll.get("max_rounds", 1)))
        settle = float(scroll.get("settle", 1.8))
        swipe = scroll.get("swipe")
        dur = int(scroll.get("duration_ms", 700))
        acc_rows: list = []                     # v2.1: 本次调用的跨屏累计行(供 _last_dump/if_collected)
        self._last_dump[label] = acc_rows       # 重置: 本 label 以本次采集为准(防跨次调用残留)
        prev_fp = None
        for round_no in range(1, max_rounds + 1):
            self._check_stop()
            img = self.screenshot()
            if img is None:
                print(f"[采集] {label}: 第{round_no}轮截图失败, 如实停止")
                return
            if tab_region and tab_vars:
                # O2: 页签守卫只需布尔 -> 不拆分
                tb, _sub, _used = self._ocr_candidates(img, tab_region, need_refine=False)
                if not any(v in b.get("text", "") for b in tb for v in tab_vars):
                    print(f"[采集] {label}: 第{round_no}轮页签守卫 MISS(变体={tab_vars}), 如实停止")
                    return
            # O2: 行分组只用 blocks(不看子块) -> 不拆分
            blocks, _sub, _used = self._ocr_candidates(img, region_rel, need_refine=False)
            rows = self._group_task_rows(blocks) if use_pair else []
            self._merge_rows(acc_rows, rows)    # v2.1: 跨屏累计(供 if_collected; 修复曾只留末屏)
            fp = frozenset((d, p) for d, p, _c in rows) if use_pair else None
            print(f"[采集] {label} 第{round_no}轮: 块{len(blocks)} 行{len(rows)}"
                  + (f" (累计 {len(acc_rows)})" if use_pair else "")
                  + (" " + "; ".join(f"{d}={p}" for d, p, _c in rows) if rows else ""))
            if save:
                self._write_collect(save, label, round_no, rows, blocks)
            if not swipe:
                return                       # 单发模式: 一轮即止
            if prev_fp is not None and fp == prev_fp:
                print(f"[采集] {label}: 连续两屏行分组指纹一致 -> 列表到底(共 {round_no} 轮)")
                return
            prev_fp = fp
            self.swipe_rel(*swipe, duration_ms=dur)
            time.sleep(settle)
        print(f"[采集] {label}: 达到 max_rounds={max_rounds} 上限仍未稳定, 如实登记")

    def _write_collect(self, save, label, round_no, rows, blocks):
        """采集留档: 追加 data/collect/<save>.jsonl(ts/label/round/rows/blocks 全量)。
        dump_text 与 claim_scroll 共用(2026-10-12 v2 抽取)。"""
        try:
            out_dir = Path(__file__).resolve().parent.parent.parent / "data" / "collect"
            out_dir.mkdir(parents=True, exist_ok=True)
            rec = {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "label": label, "round": round_no,
                "screen": [self.screen_w, self.screen_h],
                "rows": [{"desc": d, "progress": p,
                          "rel": [round(c[0] / self.screen_w, 4),
                                  round(c[1] / self.screen_h, 4)]}
                         for d, p, c in rows],
                "blocks": [{"text": b.get("text", ""),
                            "score": round(float(b.get("score", 1.0)), 3),
                            "rel": [round(b["center"][0] / self.screen_w, 4),
                                    round(b["center"][1] / self.screen_h, 4)]}
                           for b in blocks if b.get("center")],
            }
            with open(out_dir / f"{save}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError as e:
            print(f"[采集] {label}: jsonl 写入失败(不影响流程): {e}")

    def _claim_scroll(self, step: dict) -> None:
        """领取循环(2026-10-12 v2, 每日任务四步闭环①④): 每屏点尽「领取」-> 关奖励弹窗 -> 上滑;
        行分组指纹连续两屏一致判到底。可选 save/row_pair 顺带按屏留档(同屏采集+领取一趟完成,
        同时写 _last_dump(跨屏累计, 见 _merge_rows) 供 if_collected)。只点 claim_keywords(默认「领取」)与弹窗关闭词,
        不点其它任何按钮。参数: region_rel; claim_keywords; close_keywords; tab_region_rel+
        tab_variants 页签守卫; max_claim_per_screen(默认8, 防单屏死循环); save/label/row_pair;
        stop_claim_after_first(D14a: 领取成功一次后不再找「领取」, 只滚动采行);
        scroll={swipe,duration_ms,settle,max_rounds}。

        D13: 奖励弹窗统一交给 _reward_dialog 判定/关闭/上报(未见成功界面 required 时登记软失败)。
        D14a: 用户 2026-10-19 领域知识 —— 点任一已完成任务的「领取」后**所有已完成任务一并领取**,
        故首次领取成功后本屏/后续屏都不必再找「领取」(只保留滚动采行, 供 if_collected/留档)。"""
        region_rel = step.get("region_rel")
        label = step.get("label", "claim")
        save = step.get("save")
        use_pair = bool(step.get("row_pair"))
        claim_kws = step.get("claim_keywords", ["领取"])
        close_kws = step.get("close_keywords", ["点击任意处关闭", "恭喜获得"])
        tab_region = step.get("tab_region_rel")
        tab_vars = step.get("tab_variants") or []
        scroll = step.get("scroll") or {}
        max_rounds = max(1, int(scroll.get("max_rounds", 12)))
        settle = float(scroll.get("settle", 1.5))
        swipe = scroll.get("swipe")
        dur = int(scroll.get("duration_ms", 700))
        max_per_screen = int(step.get("max_claim_per_screen", 8))
        stop_after_first = bool(step.get("stop_claim_after_first"))   # D14(a)
        claimed_ok = 0                          # 真正见到「领取成功」界面的次数(不是点击次数)
        acc_rows: list = []                     # v2.1: 本次调用的跨屏累计行(供 _last_dump/if_collected)
        self._last_dump[label] = acc_rows       # 重置: 本 label 以本次采集为准(防跨次调用残留)
        prev_fp = None
        for round_no in range(1, max_rounds + 1):
            self._check_stop()
            img = self.screenshot()
            if img is None:
                print(f"[领取] {label}: 第{round_no}轮截图失败, 如实停止")
                return
            if tab_region and tab_vars:
                # O2: 页签守卫只需布尔 -> 不拆分
                tb, _s, _u = self._ocr_candidates(img, tab_region, need_refine=False)
                if not any(v in b.get("text", "") for b in tb for v in tab_vars):
                    print(f"[领取] {label}: 第{round_no}轮页签守卫 MISS(变体={tab_vars}), 如实停止")
                    return
            # 1) 本屏点尽「领取」(每次点击后重截图; 奖励弹窗即时关闭)
            claimed = 0
            skipped_scan = False
            if stop_after_first and claimed_ok > 0:
                skipped_scan = True
                print(f"[领取] {label} 第{round_no}轮: 已领取成功(全部已完成任务一并领取)"
                      f" -> 跳过「{'/'.join(claim_kws)}」定位, 只采行")
            else:
                for _ in range(max_per_screen):
                    self._check_stop()
                    img = self.screenshot()
                    blocks, _s, _u = self._ocr_candidates(img, region_rel)
                    claims = [b for b in blocks if any(k in b.get("text", "") for k in claim_kws)]
                    if not claims:
                        break
                    c = max(claims, key=lambda b: float(b.get("score", 1.0)))
                    cc = c.get("center")
                    if not cc and c.get("box"):
                        cc = [(c["box"][0] + c["box"][2]) / 2, (c["box"][1] + c["box"][3]) / 2]
                    if not cc:
                        break
                    print(f"[领取] {label} 第{round_no}轮 点「{c.get('text', '')}」"
                          f"@rel({cc[0] / self.screen_w:.3f},{cc[1] / self.screen_h:.3f})")
                    self.click_abs(int(cc[0]), int(cc[1]))
                    time.sleep(1.5)
                    # 2) 奖励弹窗(D13 统一原语; 全图 OCR——弹窗可覆盖采集区域外)
                    # A1(2026-10-22): wait 0.5 → 2.0 —— 10-22 日志 L2265-2269 点击后同帧仍读到
                    #   「领取」, 0.5s 窗口内未见弹窗就登记失败(假失败); 服务端回包+弹窗动画通常需 1~2s。
                    ok = self.reward_dialog({
                        "wait": 2.0, "tries": 2, "required": True,
                        "keywords": close_kws, "name": f"{label} 奖励弹窗",
                    })
                    claimed += 1
                    if ok:
                        claimed_ok += 1
                        if stop_after_first:
                            print(f"[领取] {label} 第{round_no}轮: 领取成功 -> 本屏不再找"
                                  f"「{'/'.join(claim_kws)}」(D14a: 已完成任务一并领取)")
                            break
            if claimed == 0 and not skipped_scan:
                print(f"[领取] {label} 第{round_no}轮: 本屏无「{'/'.join(claim_kws)}」")
            # 3) 留档 + 内存(供 if_collected)
            img3 = self.screenshot()
            if img3 is None:
                return
            # O2: 行分组只用 blocks -> 不拆分
            blocks3, _s, _u = self._ocr_candidates(img3, region_rel, need_refine=False)
            rows = self._group_task_rows(blocks3) if use_pair else []
            self._merge_rows(acc_rows, rows)    # v2.1: 跨屏累计(修复曾只留末屏行)
            if save:
                self._write_collect(save, label, round_no, rows, blocks3)
            fp = frozenset((d, p) for d, p, _c in rows) if use_pair else None
            print(f"[领取] {label} 第{round_no}轮小结: 领取 {claimed} 个, 行 {len(rows)}"
                  + (f" (累计 {len(acc_rows)})" if use_pair else ""))
            # 4) 到底判定 / 滑动
            if not swipe:
                return
            if prev_fp is not None and fp == prev_fp:
                print(f"[领取] {label}: 连续两屏一致 -> 到底(共 {round_no} 轮)")
                return
            prev_fp = fp
            self.swipe_rel(*swipe, duration_ms=dur)
            time.sleep(settle)
        print(f"[领取] {label}: 达到 max_rounds={max_rounds} 上限, 如实登记")

    def _if_collected(self, step: dict, indent: int) -> None:
        """条件分支(2026-10-12 v2): 查询最近一次采集(label)的**跨屏累计**行分组结果, 按 desc 关键字找行,
        对进度 (a/b) 求条件; 命中且条件为真走 then, 否则(含行缺失/无进度)走 else。
        参数: label; keywords(子串列表); cond(默认 "a<b", 支持 a<b/a<=b/a==b/a>b/a>=b/a!=b); then/else。
        用途: 每日任务点赞门槛——「献上点赞」行 a<b 才执行社区点赞; 行缺失=当日无此任务要求 -> else。"""
        label = step.get("label", "")
        kws = step.get("keywords") or []
        cond = (step.get("cond") or "a<b").replace(" ", "")
        rows = self._last_dump.get(label) or []
        hit = None
        for d, p, _c in rows:
            if any(k in d for k in kws):
                hit = p
                break
        ok = False
        if hit and "/" in hit:
            try:
                a, b = (int(x) for x in hit.split("/")[:2])
                ok = bool({"a<b": a < b, "a<=b": a <= b, "a==b": a == b,
                           "a>b": a > b, "a>=b": a >= b, "a!=b": a != b}.get(cond, a < b))
            except (ValueError, TypeError):
                ok = False
        print(f"{'  ' * indent}[if_collected] {label} 关键词{kws} 命中行={hit} 条件'{cond}' "
              f"-> {'TRUE' if ok else 'FALSE'}" + ("" if hit else " (未找到该行, 走 else)"))
        branch = step.get("then") if ok else step.get("else")
        if branch:
            self.run_steps(branch, indent=indent + 1)

    def click_row_button(self, step: dict, indent: int) -> None:
        """行级按钮点击(2026-10-25 浏览热卖): 在**当前帧**重新定位目标任务行并点击行内按钮,
        不写死任何坐标, 不复用历史采集坐标。

        为什么不复用 claim_scroll 采集的行坐标(2026-10-25 E2E 实锤):
        采集跨屏滚动后, _last_dump 里各行的坐标是「该行首次被看见那屏」的位置;
        claim_scroll 结束时列表已滚动到底, 当前画面同 y 位置是**另一行任务**
        (实测: 采集时「查看最新热卖套装」@y435, 点击时 y435 处已是别的任务行)。
        按陈旧 y 开行带会锚错行 —— 窄行带防误点的设计反而成了「锚错行的精确执行」。

        因此本原子每轮: 截图 → 全图 OCR → 行分组(_group_task_rows) → 按 keywords 子串找
        目标行 → 用**本帧**该行进度块中心 y 开窄行带 → 带内实时识别 text 按钮词(如「前往」)
        并点击该按钮自身的本次命中坐标(规则6合规范式①)。行不在当前画面则滑动翻页找:
        claim_scroll 结束时列表在底部故先向上翻, 连续两屏行集合不变(到边)则反向,
        最多 max_rounds 轮; 找到行但带内无按钮时**不点击**并存证, 交调用方处置。

        行带几何: 进度块与按钮同 y(五日留档 Δy≤0.003), 相邻行距 Δy≈0.189,
        半高默认 0.028(≈行距 1/7)不会跨行; find_text 区域过滤保证回退全图重试的
        结果仍须落回行带内, 窄带 MISS 不会点到其它行的同名按钮。
        """
        pad = "  " * indent
        row_kws = step.get("keywords") or []
        row_kws = row_kws if isinstance(row_kws, list) else [row_kws]
        kws = step.get("text") or ["前往"]
        kws = kws if isinstance(kws, list) else [kws]
        half_h = float(step.get("row_half_h", 0.028))
        x1_rel, x2_rel = (float(v) for v in step.get("row_x_range", (0.60, 1.0)))
        max_rounds = max(1, int(step.get("max_rounds", 8)))
        settle = float(step.get("settle", 1.5))
        swipe = step.get("swipe") or [0.68, 0.60, 0.68, 0.35]
        sx1, sy1, sx2, sy2 = (float(v) for v in swipe[:4])
        if not self.screen_h:
            self.screenshot()
        direction = -1   # claim_scroll 结束时列表在底部: 先向上翻找目标行
        prev_sig = None
        for round_no in range(1, max_rounds + 1):
            self._check_stop()
            img = self.screenshot()
            if img is None:
                print(f"{pad}[click_row_button] 第{round_no}轮截图失败, 如实放弃")
                return
            blocks, _subs = self._ocr_frame(img, need_split=False)
            rows = self._group_task_rows(blocks)
            hit = None
            for d, p, c in rows:
                if any(k in d for k in row_kws):
                    hit = (d, p, c)
                    break
            if hit:
                d, p, c = hit
                ry = c[1] / self.screen_h if self.screen_h else 0.0
                band = [x1_rel, max(0.0, ry - half_h), x2_rel, min(1.0, ry + half_h)]
                print(f"{pad}[click_row_button] 第{round_no}轮 行'{d}'={p} y={ry:.4f} "
                      f"行带={[round(v, 3) for v in band]}")
                pt = self.locate(kws, img=img, min_score=0.4, region_rel=band,
                                 exclude=step.get("exclude"))
                if pt is not None:
                    print(f"{pad}[click_row_button] {kws} -> ({pt.x},{pt.y}) 本帧行内命中, 点击")
                    self.click_abs(pt.x, pt.y)
                    time.sleep(step.get("delay", 1.0))
                    return
                print(f"{pad}[click_row_button] 行带内未命中{kws}, 不点击")
                self.dump_full_frame(f"行按钮未命中:{kws[0]}")
                if step.get("required"):
                    report_failure(self._module, f"click_row_button 行'{d}'带内未命中{kws}(required)")
                    raise BranchAborted(f"click_row_button 行内无按钮 {kws}")
                return
            sig = frozenset((d, p) for d, p, _c in rows)
            if sig == prev_sig and sig:
                direction = -direction
                print(f"{pad}[click_row_button] 第{round_no}轮 行集合未变化(到边), 反向翻页")
            else:
                print(f"{pad}[click_row_button] 第{round_no}轮 当前画面无{row_kws}行, "
                      f"{'向下' if direction > 0 else '向上'}翻页")
            prev_sig = sig
            if direction > 0:   # 向下翻: 手指从下往上滑(同 claim_scroll swipe)
                self.swipe_rel(sx1, sy1, sx2, sy2, duration_ms=700)
            else:               # 向上翻: 手指从上往下滑(反向)
                self.swipe_rel(sx1, sy2, sx2, sy1, duration_ms=700)
            time.sleep(settle)
        print(f"{pad}[click_row_button] {max_rounds} 轮未找到含{row_kws}的行, 如实放弃")
        self.dump_full_frame(f"行未命中:{row_kws[0] if row_kws else '?'}")
        if step.get("required"):
            report_failure(self._module, f"click_row_button {max_rounds}轮未找到行{row_kws}(required)")
            raise BranchAborted(f"click_row_button 未找到行 {row_kws}")
