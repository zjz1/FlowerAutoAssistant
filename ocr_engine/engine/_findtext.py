"""find_text 三级策略链/合并块纠偏/故障存证/locate。

E01(batch-03, 2026-11-14) 自单文件 ocr_engine.py 机械拆包: 本文件各段为原文件对应
行段的**逐行原文**(唯 __file__ 锚点因包层级 +1 机械重锚定, 见 ast_hash_compare.py
allowlist)。行为等价口径: 帧集回归 0 退化 + 闸门全绿 + import 面零改动。
原行段映射: evidence/batch-03/tiles_manifest.json。
"""
from __future__ import annotations

import hashlib
import re
import time

import numpy as np

from pathlib import Path

from .._geometry import Point
from ocr_ui import ocr_find

class _FindTextMixin:
    def _refine_wide_block(self, img, block):
        """O3(2026-10-21): **只对命中的合并块**做一次定向精识(替代全帧预拆)。

        为什么不直接复用 _split_wide 的固定参数:
          - 横向留 10px 会把隔壁按钮的字重新纳入裁片 -> det 又合并成一块(越拆越合);
          - 纵向需要更宽余量, 防上下切掉笔画/标点。
        故: pad_x=3(紧), pad_y=max(6, 0.35×块高)(松), 放大倍率按块高自适应(小字 3×, 常规 2×)。
        返回映射回全帧坐标的子块列表; 缓存与 _split_wide 共用 `_split_cache`(键含 pad/scale, 不会串用)。
        """
        x1, y1, x2, y2 = block["box"]
        bh = max(1, y2 - y1)
        pad_y = max(6, int(bh * 0.35))
        pad_x = 3
        ox, oy = max(0, x1 - pad_x), max(0, y1 - pad_y)
        ex, ey = min(self.screen_w, x2 + pad_x), min(self.screen_h, y2 + pad_y)
        crop = img[oy:ey, ox:ex]
        if crop.size == 0:
            return []
        scale = 3.0 if bh < 16 else 2.0
        key = (ox, oy, pad_x, pad_y, int(round(scale * 10)),
               hashlib.blake2b(np.ascontiguousarray(crop).tobytes(), digest_size=16).digest())
        with self._split_lock:
            cached = self._split_cache.get(key)
            if cached is not None:
                self._split_cache.pop(key)
                self._split_cache[key] = cached
        if cached is not None:
            self._ocr_stat["split_cache_hit"] += 1
            return [dict(nb) for nb in cached]
        import cv2
        big = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        subs: list = []
        # P1(2026-11-10): region_ok=False 硬排除 —— det_region_limit_split 闸门**绝不覆盖**命中精识
        # 路径(它直接决定点哪儿, 本批不开闸); sub="refine" 仅子类耗时观测。两键任意开关, 本行恒默认实例。
        for nb in self._timed_ocr(big, "split", region_ok=False, sub="refine"):
            nb2 = dict(nb)
            nb2["center"] = [int(nb["center"][0] / scale) + ox,
                             int(nb["center"][1] / scale) + oy]
            nb2["box"] = [int(nb["box"][0] / scale) + ox,
                          int(nb["box"][1] / scale) + oy,
                          int(nb["box"][2] / scale) + ox,
                          int(nb["box"][3] / scale) + oy]
            subs.append(nb2)
        with self._split_lock:
            if len(self._split_cache) >= 400:
                self._split_cache.pop(next(iter(self._split_cache)))
            self._split_cache[key] = subs
        return [dict(nb) for nb in subs]

    def _is_merged_hit(self, block, keywords) -> bool:
        """O3: 该命中块是否是**合并块**(文本比关键字更长, 且宽度>90)。
        注意必须在 `_narrow_merged` 之前判断 —— 窄化后 box 已缩到关键字本身, 宽度失去意义。
        归一化只用于“是否需要精识”的判断, 不参与坐标计算。"""
        if (block["box"][2] - block["box"][0]) <= 90:
            return False
        text = re.sub(r"\s+", "", block.get("text", "") or "")
        if not text:
            return False
        kws = keywords if isinstance(keywords, list) else [keywords]
        for kw in kws:
            nk = re.sub(r"\s+", "", str(kw))
            if nk and nk in text and len(text) > len(nk):
                return True
        return False

    def find_text(self, keywords, img=None, top_k=3, exact=False, region_rel=None, exclude=None,
                  need_refine: bool = True, log_miss: bool = True):
        """在截图(或给定图)中按关键字找文字块。返回 OCR 块列表 (含坐标)。
        exact=True 要求块文本与关键字完全相等, 避免『家园』误命中『勇气国花园』等。
        region_rel=[x1,y1,x2,y2] (0~1) 时只保留中心落在该区域内的块 (用于区域限定文本判断)。
        exclude=['已领取'] 时剔除「文字里含这些排除词」的块: 关键字默认是**子串匹配**,
        所以「领取」会命中「已领取」——按钮已领取时点它当然什么都不会发生, 必须排除。

        O3(2026-10-21) 三级策略(取代“先对全帧所有过宽块做 2× 拆分”):
          ① 精确等值命中 -> 直接用, 零额外开销;
          ② 模糊命中在**合并块**内(文本比关键字长且宽>90) -> 只对该块做一次定向精识
             (`_refine_wide_block`: 横向紧/纵向松/自适应倍率), 再在“子块+合并块”中重匹配;
          ③ 仍未命中且需要精度 -> 兜底全量拆分一次(保持旧召回, 防“只在子块可读”的极端情况);
        判断类调用(need_refine=False)完全不拆分(O2)。合并块始终保留, `_narrow_merged` 仍兜底。
        """
        img = img if img is not None else self.screenshot()
        if img is None:
            return []
        # O3: 先不拆分; 后面只对命中的合并块按需精识
        blocks, sub_blocks, used_region = self._ocr_candidates(img, region_rel, need_refine=False)
        hits = []
        refined_ids: set = set()
        did_full_split = False
        rx1 = ry1 = rx2 = ry2 = 0
        if region_rel:
            w, h = self.screen_w, self.screen_h
            rx1, ry1 = int(region_rel[0] * w), int(region_rel[1] * h)
            rx2, ry2 = int(region_rel[2] * w), int(region_rel[3] * h)

        def _in_region(lst):
            if not region_rel:
                return list(lst)
            return [b for b in lst
                    if rx1 <= b["center"][0] <= rx2 and ry1 <= b["center"][1] <= ry2]

        for _attempt in range(2):
            # 精确子块优先(点击点优先落到目标文字自身中心), 原合并块兜底保证整体命中
            hits = ocr_find(_in_region(sub_blocks + blocks), keywords, exact=exact)
            # O0: 安全指标 —— 本次命中是否**完全依赖拆分子块**?
            if hits and sub_blocks:
                if not ocr_find(_in_region(blocks), keywords, exact=exact):
                    self._ocr_stat["split_only_hit"] += 1
            # O3-②: 命中的合并块定向精识(只处理这一块, 不碰全帧其它过宽块)
            if need_refine and hits:
                merged = [b for b in hits
                          if id(b) not in refined_ids and self._is_merged_hit(b, keywords)]
                if merged:
                    new_subs = []
                    for b in merged:
                        refined_ids.add(id(b))
                        new_subs.extend(self._refine_wide_block(img, b))
                    if new_subs:
                        sub_blocks = sub_blocks + new_subs
                        hits = ocr_find(_in_region(sub_blocks + blocks), keywords, exact=exact)
            # O3-③: 仍未命中 -> 兜底全量拆分一次(与旧行为一致的召回)。
            # 仅在**全图**块上做: 区域化未命中时先回退全图再拆, 避免对裁片块做无用拆分。
            if need_refine and not hits and not did_full_split and not used_region:
                did_full_split = True
                more = self._split_wide(img, blocks)
                if more:
                    sub_blocks = sub_blocks + more
                    hits = ocr_find(_in_region(sub_blocks + blocks), keywords, exact=exact)
            if not exact:
                kws = keywords if isinstance(keywords, list) else [keywords]
                hits = [self._narrow_merged(b, kws) for b in hits]
            if exclude:
                ex = exclude if isinstance(exclude, list) else [exclude]
                keep = [b for b in hits if not any(e in b["text"] for e in ex)]
                if hits and not keep:
                    # 命中块全被排除词剔除: 典型情况是「领取」其实读到的是「已领取」(按钮已领),
                    # 必须如实报出来 —— 否则日志会显示"识别到领取却没领到", 让人以为是点击不准。
                    print(f"[排除] {keywords} 命中{len(hits)}块但均含排除词{ex}, 不点击: "
                          + " | ".join(f"{b['text'][:10]}@({b['center'][0]},{b['center'][1]})" for b in hits[:5]))
                hits = keep
            if hits or not used_region:
                break
            # 批C-①: 区域化未命中 → 回退一次全图重试(防小图 det 上下文差异制造新 MISS;
            # 结果照常入全图单槽缓存)。区域化只省命中路径耗时, 不制造新 MISS。
            # O3: 回退的全图也不预拆 —— 若命中合并块, 下一轮会定向精识。
            blocks, sub_blocks = self._ocr_frame(img, need_split=False)
            used_region = False
        if hits:
            self._miss_sig = None  # 命中即复位「同画面未命中折叠」(2026-10-03, 见 _log_ocr_miss)
        if not hits:
            # E1(2026-10-22): log_miss=False 供弹窗/启动状态等“常态负判定”使用 ——
            #   不再逐次打印 `[OCR未命中]`; 但保留末帧证据 + 汇总计数,
            #   便于其他调用方(如 reward_dialog)输出一行摘要与“疑似低分”提示。
            if log_miss:
                self._log_ocr_miss(keywords, exact, region_rel, blocks)
            else:
                self._ocr_stat["miss_silent_n"] += 1
                self._last_miss_blocks = list(blocks or [])
                self._last_miss_keywords = keywords if isinstance(keywords, list) else [keywords]
        return hits

    def _log_ocr_miss(self, keywords, exact, region_rel, blocks, max_blocks=10):
        """诊断输出: 文本未命中时打印本次 OCR 实际读到的文字块摘要。

        用于区分三种失败: ① 该文字根本没被检出(画面未就绪/低对比/艺术字);
        ② 检出了但文字不符或被合并(如把「家族」「家族活动」并成一块);
        ③ 检出了但落在限定区域之外 —— 即区域坐标写错(此前只打全屏前 10 块, 无法区分 ③)。
        区域限定时分别打印「区域内实读」与「区域外含同字块(疑似区域坐标不对)」。
        只打印前 max_blocks 块, 控制日志体积。

        ⚠ 同画面重复未命中折叠(2026-10-03, 协作区 zcode-20261003-2): 卡死画面会让每种探测
          每轮都完整打印「实读到前10块」(2026-10-03 日志: 93×删除好友 / 51×社交 / 36×确定,
          日志膨胀难检索)。签名=帧指纹+exact+区域(同帧块内容本就相同, 不再按关键字区分),
          同签名只完整打印首条, 其后每 10 次折叠为一行计数; 画面一变(指纹变)或命中即复位。
        """
        kws = keywords if isinstance(keywords, list) else [keywords]

        # ---- 同画面重复未命中折叠 ----
        # 仅在帧指纹可用时折叠(哈希失败则逐条打印, 宁多勿漏); 并发下计数最多偏差 1, 纯日志层可接受
        if self._frame_sig is not None:
            sig = (self._frame_sig, bool(exact),
                   tuple(region_rel) if region_rel else None)
            if sig == self._miss_sig:
                self._miss_count += 1
                if self._miss_count % 10 == 0:  # 每 10 次提一条, 避免完全静默
                    print(f"[OCR未命中] 同画面重复 x{self._miss_count} (已折叠): {kws}")
                return
            self._miss_sig = sig
            self._miss_count = 1

        def brief(bs):
            return " | ".join(
                f"{b['text'][:10]}@{b['score']:.2f}({b['center'][0]},{b['center'][1]})"
                for b in bs[:max_blocks])

        if not region_rel:
            more = f" 共{len(blocks)}块" + (f"(只列前{max_blocks}块)" if len(blocks) > max_blocks else "")
            print(f"[OCR未命中] {kws} exact={exact} 区域=None{more}"
                  + (f" 实读到: {brief(blocks)}" if blocks else " 未读到任何文字块"))
            return
        w, h = self.screen_w, self.screen_h
        rx1, ry1 = int(region_rel[0] * w), int(region_rel[1] * h)
        rx2, ry2 = int(region_rel[2] * w), int(region_rel[3] * h)
        inside = [b for b in blocks
                  if rx1 <= b["center"][0] <= rx2 and ry1 <= b["center"][1] <= ry2]
        inside_ids = {id(b) for b in inside}
        chars = {c for kw in kws for c in kw if not c.isspace()}
        outside_same = [b for b in blocks
                        if id(b) not in inside_ids and any(c in b["text"] for c in chars)]
        lines = [f"[OCR未命中] {kws} exact={exact} 区域={region_rel}"
                 f" 全屏{len(blocks)}块 / 区域内{len(inside)}块"
                 f" (区域绝对像素 x{rx1}-{rx2} y{ry1}-{ry2})",
                 "  区域内实读: " + (brief(inside) if inside else "无")]
        if outside_same:
            lines.append("  ⚠ 区域外含同字块(疑似区域坐标不对): " + brief(outside_same))
        print("\n".join(lines))

    # 故障存证 tag → 文件名 ASCII slug(里程碑 94): 中文 tag 在 Windows 下经 cv2.imwrite 落盘会**乱码**
    # (现网实测 fail_绛夊緟瓒呮椂___…png), 故文件名一律 ASCII; 中文原文保留在日志与 index.jsonl 的 tag 字段。
    _DUMP_TAG_MAP = (("未命中", "miss"), ("等待超时", "wait_timeout"), ("消失超时", "vanish_timeout"))

    @classmethod
    def _dump_tag_slug(cls, tag: str) -> str:
        for zh, en in cls._DUMP_TAG_MAP:
            if tag.startswith(zh):
                return en
        s = re.sub(r"_+", "_", "".join(
            ch if (ch.isascii() and (ch.isalnum() or ch in "_-")) else "_" for ch in str(tag))).strip("_")
        return (s or "misc")[:32]

    def dump_full_frame(self, tag: str, img=None) -> None:
        """故障现场存证: 全量 OCR(不截断) + 当前帧截图落盘 (2026-10-14 用户要求)。

        常规未命中日志(_log_ocr_miss)只列前 10 块, 卡死/报错时无法判断画面到底有什么
        (弹窗遮挡? 动画中间帧? 艺术字被读错?) —— 故在**离散错误点**(等待超时/点击未命中)
        额外做一次**全量** OCR 并保存当帧, 供离线复核与模板/区域校准。

        ⚠ 里程碑 94(用户方案) 存证策略重构 —— "缓存"语义 + 零内存 + 信息不死:
        - **零运行内存**: 截图**当场同步写盘**, 进程内不缓存 numpy/bytes/图片数据(只留一条元数据);
          代价是该点阻塞若干毫秒~百毫秒(全量 OCR 是大头), 属用户明示接受的取舍。
        - **缓存目录**: `data/fail_cache/<会话戳>/`(会话戳=引擎实例创建时刻 ⇒ 一次服务运行一个目录,
          跨服务重启**保留不清**, 便于崩溃后仍能看现场)。
        - **纯 ASCII 文件名**: `fail_<日期>_<时刻>_<序号>_<slug>.jpg` —— 修 O2(Windows 中文名乱码)。
        - **JPEG(q85)** 而非 PNG: 单张 ≈200KB(原 PNG 1.3~1.6MB) —— 缓解 O3。
        - **不设自动淘汰**: 无任何大小/张数守卫(避免每次落盘都统计的开销); 清理**只由用户触发**
          (启动超阈值提醒弹窗 / 「清除日志」按钮), 详见 webui.py::clean_fail_cache。
        - **元数据墓碑(信息不死)**: 每次落盘追加一条到 `data/fail_cache/index.jsonl`, 含
          时间/会话/tag(中文原文)/文件名/字节数/**全量 OCR 文本**/帧指纹 —— 日后像素被清理时
          该条目标 `evicted:true` 而**记录永久保留** ⇒ 不会"静默丢失信息"。
        - 预算 `fail_dump_budget` 与 (tag,帧指纹) 去重维持不变; 异常一律吞掉, 不影响流程。
        """
        try:
            if self._dump_left <= 0:
                return
            if img is None:
                img = self.last_frame if self.last_frame is not None else self.screenshot()
            if img is None:
                print(f"[故障存证] {tag}: 取帧失败, 跳过")
                return
            sig = self._frame_hash(img)
            key = (tag, sig)
            if sig is not None and key == self._dump_sig:
                return
            self._dump_sig = key
            self._dump_left -= 1
            # O2: 存证只打印/落盘文字块 -> 不拆分
            blocks, _sub = self._ocr_frame(img, need_split=False)
            print(f"[故障存证] {tag}: 全量 OCR {len(blocks)} 块 (本轮预算余 {self._dump_left})")
            for b in blocks:
                c = b.get("center") or (0, 0)
                print(f"    · {str(b.get('text',''))[:24]} @{float(b.get('score',1.0)):.2f} ({c[0]},{c[1]})")
            import cv2
            import json
            base = Path(__file__).resolve().parent.parent.parent / "data" / "fail_cache"
            out = base / self._session_stamp
            out.mkdir(parents=True, exist_ok=True)
            self._dump_seq += 1
            slug = self._dump_tag_slug(tag)
            fn = f"fail_{time.strftime('%Y%m%d_%H%M%S')}_{self._dump_seq:03d}_{slug}.jpg"
            fp = out / fn
            ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok:
                print(f"[故障存证] {tag}: JPEG 编码失败, 跳过")
                return
            buf.tofile(str(fp))   # 用 tofile 而非 imwrite: 绕开 OpenCV 对非 ASCII 路径的处理差异
            nbytes = fp.stat().st_size
            rel = f"{self._session_stamp}/{fn}"
            print(f"[故障存证] {tag}: 画面已保存 -> data/fail_cache/{rel} ({nbytes/1024:.0f} KB, {len(blocks)} 块)")
            # 元数据墓碑: 记录永久留档, 供日后"像素已清理但记录仍在"的追溯
            try:
                entry = {
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "session": self._session_stamp,
                    "tag": str(tag), "slug": slug, "file": rel, "bytes": nbytes,
                    "sig": (sig.hex()[:16] if sig is not None else None),
                    "ocr": [f"{str(b.get('text',''))[:40]}@{float(b.get('score',1.0)):.2f}"
                            f"({(b.get('center') or (0,0))[0]},{(b.get('center') or (0,0))[1]})"
                            for b in blocks],
                    "evicted": False,
                }
                with open(base / "index.jsonl", "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception as e2:
                print(f"[故障存证] {tag}: 索引写入失败(不影响流程): {e2}")
        except Exception as e:
            print(f"[故障存证] {tag}: 存证异常(不影响流程): {e}")

    @staticmethod
    def _narrow_merged(b: dict, kws: list[str]) -> dict:
        """合并块纠偏: OCR 常把相邻按钮并成一块(实测「快捷操作种植箱」[1275..1480]),
        此时子串命中返回的是**合并块中心**, 落点正好在两按钮之间的空隙上, 点击无效
        (实测偏差 50px: 真实中心 1327 vs 返回 1377)。
        按字符占比把关键字在块内的位置还原出来, 重算中心与框。
        仅当块文本比关键字更长(确为合并块)时生效; 文本与关键字等长(精确命中)原样返回。
        """
        text = b["text"].strip()
        for k in kws:
            if k in text and len(text) > len(k):
                idx = text.find(k)
                x1, y1, x2, y2 = b["box"]
                n, w = len(text), x2 - x1
                sx, ex = x1 + w * idx / n, x1 + w * (idx + len(k)) / n
                nb = dict(b)
                nb["box"] = [int(sx), y1, int(ex), y2]
                nb["center"] = [int((sx + ex) / 2), int((y1 + y2) / 2)]
                return nb
        return b

    def locate(self, keywords, img=None, min_score=0.5, exact=False, region_rel=None, exclude=None,
               need_refine: bool = True, log_miss: bool = True):
        """返回第一个命中块的中心绝对坐标 Point; 未命中返回 None。
        命中后更新 last_rel 缓存, 并把**实际命中的原始文字**记到 self._last_match_text,
        便于日志区分「命中就是关键字本身」与「命中的是含关键字的更长文字(如已领取)」。
        E1: `log_miss=False` 透传给 find_text —— 供「确认没有弹窗/不在更新页」这类高频负判定静默。
        """
        blocks = self.find_text(keywords, img=img, exact=exact, region_rel=region_rel, exclude=exclude,
                                need_refine=need_refine, log_miss=log_miss)
        for b in blocks:
            if b.get("score", 1.0) < min_score:
                continue
            cx, cy = b["center"]
            pt = Point(cx, cy, self.screen_w, self.screen_h)
            for kw in (keywords if isinstance(keywords, list) else [keywords]):
                self.last_rel[kw] = pt.rel
            self._last_match_text = b["text"].strip()
            self._last_match_block = b  # 命中块(含 score/text/center), 供相邻定位复用的严谨校验(批B)
            return pt
        self._last_match_text = None
        self._last_match_block = None
        return None
