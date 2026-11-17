"""OCR 定位: 帧缓存/双闸门计时/过宽块拆分/区域化/统计打印。

E01(batch-03, 2026-11-14) 自单文件 ocr_engine.py 机械拆包: 本文件各段为原文件对应
行段的**逐行原文**(唯 __file__ 锚点因包层级 +1 机械重锚定, 见 ast_hash_compare.py
allowlist)。行为等价口径: 帧集回归 0 退化 + 闸门全绿 + import 面零改动。
原行段映射: evidence/batch-03/tiles_manifest.json。
"""
from __future__ import annotations

import hashlib
import time

import numpy as np

from .._constants import SPLIT_CACHE_MAX
from .._geometry import Point
from .._stat import _stat_add
from ocr_ui import get_engine, get_engine_mixed, get_engine_region, ocr_image

class _OcrMixin:
    # ---- OCR 定位 ----
    @staticmethod
    def _frame_hash(img) -> "bytes | None":
        """静态帧指纹: 画面像素完全一致则指纹一致。1280x720 实测 ~3ms, 远低于一次全屏 OCR。"""
        try:
            return hashlib.blake2b(img.tobytes(), digest_size=16).digest()
        except Exception:
            return None

    def locate_fine(self, kws, region_rel, upscale=2, min_score=0.4,
                    img=None, exact=False, exclude=None) -> "Point | None":
        """滤色精识: 对 region_rel 小区域「裁剪 → 放大 → 白字滤色 → OCR」定位关键字。

        背景(2026-10-06, 用户方案): 小花仙按钮为统一白字彩底, 部分好友花园的紫/蓝底会把
        常规 OCR 置信度压到阈值以下造成整词 MISS(当日日志: 好友花园「社交」110 次尝试
        0 命中, 10 页采粉全部放弃)。滤色 = 提取高亮低饱和像素(白字)转黑字白底, 彩底噪声
        全部归零, 与按钮「色调统一」的美术规格正好互补。
        开销约束(用户要求不加重性能/内存): 只在调用方常规定位未命中后对小裁片运行,
        一次小图推理毫秒级, 不做全图二次扫描; 中间数组为瞬态小裁片; 命中路径零额外开销。
        返回坐标已映射回全图绝对像素; 未命中返回 None。"""
        import cv2
        img = img if img is not None else self.screenshot()
        if img is None:
            return None
        H, W = img.shape[:2]
        x1 = max(0, int(region_rel[0] * W)); y1 = max(0, int(region_rel[1] * H))
        x2 = min(W, int(region_rel[2] * W)); y2 = min(H, int(region_rel[3] * H))
        if x2 <= x1 or y2 <= y1:
            return None
        crop = img[y1:y2, x1:x2]
        crop = cv2.resize(crop, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        white = cv2.inRange(hsv, (0, 0, 170), (180, 70, 255))  # 高亮 + 低饱和 → 白字
        binimg = np.full(crop.shape[:2], 255, np.uint8)
        binimg[white > 0] = 0                                  # 黑字白底(OCR 友好)
        kws = kws if isinstance(kws, list) else [kws]
        exclude = exclude or []
        best = None
        for b in ocr_image(cv2.cvtColor(binimg, cv2.COLOR_GRAY2BGR)):
            if b.get("score", 1) < min_score:
                continue
            t = b.get("text", "").strip()
            if not any(((t == kw) if exact else (kw in t)) for kw in kws):
                continue
            if any(e in t for e in exclude):
                continue
            bx = b["box"]
            cx = int((bx[0] + bx[2]) / 2 / upscale) + x1
            cy = int((bx[1] + bx[3]) / 2 / upscale) + y1
            if best is None or b["score"] > best[0]:
                best = (b["score"], Point(cx, cy, W, H))
        if best:
            print(f"[精识] {kws} 滤色放大命中 score={best[0]:.2f} "
                  f"@({best[1].x},{best[1].y}) region={region_rel}")
            return best[1]
        return None

    def _ocr_frame(self, img, need_split: bool = True) -> tuple[list, list]:
        """对一帧做全图 OCR(+ 可选过宽块 2x 拆分), 同一静态帧(指纹一致)直接复用上次结果。

        性能(2026-10-03, 长期目标 §11.3-2「同一静态帧内的重复 OCR 必须复用」): wait_text 每个轮询周期、
        相邻步骤(if_text 判断后紧跟 click_text)都会对**画面未变**的帧反复全屏 OCR, 每次实测烧 ~13 核 × 400ms。
        这里对帧内容做 blake2b 指纹: 指纹一致 → 复用; 画面一变指纹失效 → 自动重新识别,
        语义与逐次 OCR 完全一致(等待变化的循环不会被陈旧结果卡住 —— 变了指纹必然变)。
        返回 (全图文字块, 过宽块拆出的精确子块)。

        O1(2026-10-21): **拆分改为按需**。`judge_scene` 只读 blocks[0]、从不使用子块, 却让整帧所有
        过宽块都做 2× 重识别 —— social 单轮实测拆分 1093s(占模块 41%), 其中场景判断这一支纯浪费。
        现在: `need_split=False` 时只做全图 OCR; 帧缓存先存 blocks、子块置 None(未算);
        同一帧后续若需要坐标精度(点击)再补算一次并写回缓存 —— 同帧仍只拆一次, 语义零变化。
        """
        sig = self._frame_hash(img)
        if sig is not None:
            with self._frame_lock:
                if sig == self._frame_sig:
                    self._ocr_stat["hit_n"] += 1
                    blocks_c, subs_c = self._frame_cache
                else:
                    blocks_c = subs_c = None
            if blocks_c is not None:
                if need_split and subs_c is None:
                    # 命中缓存但子块未算(O1 惰性): 补算一次; 若期间帧已变则不写回, 防止串帧
                    subs_c = self._split_wide(img, blocks_c)
                    with self._frame_lock:
                        if sig == self._frame_sig:
                            self._frame_cache = (blocks_c, subs_c)
                return blocks_c, (subs_c or [])
        blocks = self._timed_ocr(img, "full")
        sub_blocks = self._split_wide(img, blocks) if need_split else None
        if sig is not None:
            with self._frame_lock:
                self._frame_cache = (blocks, sub_blocks)
                self._frame_sig = sig
        return blocks, (sub_blocks or [])

    def _timed_ocr(self, img, kind: str, region_ok: bool = True, sub: str | None = None):
        """批C-②: 带 OCR 计时统计的 ocr_image 封装。kind: full(全图)/region(区域裁片)/split(2x拆分)。
        计时为纯观测, 不改行为; 缓存命中不经过本函数(由各缓存点自行计 hit_n)。
        O0(2026-10-21): 同时按 self._ocr_src(当前步骤/内部模块) 计数, 用于回答“谁花的这笔时间”。
        P1(2026-11-10, OCR-0/OCR-1 双闸门分级灰度):
          - 选引擎(默认两键全关 = engine=None, 与旧版逐字节等价):
            kind=="region" 且 det_region_limit=true       -> get_engine_region()(32/min 裁片实例);
            kind=="split" 且 det_region_limit_split=true  -> get_engine_region() —— 仅 _split_wide
            传入; _refine_wide_block 调用点 region_ok=False, 永不进入本分支(本批不给它开闸, 只观测)。
            full/direct 及其余一律默认实例(全图严禁动 limit: 960/max 实测好友列表丢块)。
          - region_ok=False: 该调用点明确声明不参与裁片闸门(当前仅 _refine_wide_block)。
          - sub 非空("split_wide"/"refine")时, 把本次调用另记一套子类 n/t 计数(纯观测,
            不改既有 full/region/split 口径; split 口径仍包含这两类调用)。
        OCR4(batch-09, 2026-11-15, 混合路由灰度 `mixed_route.enabled` **默认 false = 本段零行为**;
        裁定二两步走: region 分支=GPU 复用 OCR3 + split/refine 分支=P2C 字高归一化 s48):
          - kind=="region" 且灰度开: engine=ocr_ui.get_engine()(batch-08 档位实例 ——
            ocr_execution_provider=cpu 时与默认实例同参同输出; cuda/dml 时为 P2E GPU 引擎,
            5014 裁片 text+box 0 diff)。det_region_limit 的 32/min 通道原样保留, 但灰度开时
            region 腿按裁定二走 GPU(两个灰度同开时以混合路由优先; 两者默认全关, 生产默认零行为)。
          - split/refine 腿(kind=="split" 或 sub=="refine"): P2C 字高归一化管线 —— 见
            _mixed_route_sr(估计/倍率/重缩放语义与实验 harness prototypes/P2C/p2c.py run()
            逐字对齐, min_conf=0.5/fmin=0.5, 参数冻结 mixed_route.target_split/target_refine=48;
            s64 会复现参数坑: 负样本帧 fr_08a73155d528 稳定读出「白色菊小1仙」→ L4 FAIL)。
            块坐标 ÷zoom 映射回输入坐标系, 调用方既有 /2(/scale) 映射不变 —— 总链路与实验
            「÷(c.scale*factor)」同构。三类回退(skip-det/低置信/触顶)落回默认引擎原图,
            与实验 fallback_* 一致 —— 这些裁片与基线逐块一致。
            计时口径: split_t 等含估计/缩放开销(生产口径); 实验 15.67×/15.88× 为引擎调用口径
            (不含估计/缩放), 两口径并存在 batch-09 EVIDENCE, 报告必须带口径标签。
            硬约束随行: region 腿绝不走 P2C/P2A(负清单 N6); 字高估计器「仍不可全信」冻结判断
            保持(DECISION §3/§4.2), 仅本腿使用 charh(负清单 N20 不另立用途)。"""
        t0 = time.perf_counter()
        eng = None
        run_img = img   # OCR4: 混合路由 split/refine 腿可重缩放; 其余恒等(旧路径零行为)
        zoom = 1.0      # OCR4: 输入坐标系 -> 送检图坐标系倍率; 默认恒等
        mr_active = False
        if self.config.get("mixed_route.enabled", False):
            if kind == "region":
                # 裁定二第一步: region 分支复用 batch-08 GPU 实例(get_engine() 档位实例)。
                # get_engine_region() 32/min 通道(:131-134 原两闸门)原样保留, 灰度关时照旧生效。
                eng = get_engine()
                mr_active = True
            elif kind == "split" or sub == "refine":
                mr_active = True
                prep = self._mixed_route_sr(img, kind, sub)
                if prep is not None:
                    eng, run_img, zoom = prep
                # prep=None = P2C 三类回退(实验 fallback_skipdet/lowconf/cap): 落回默认引擎
                # 原图路径(下方 blocks = ocr_image(run_img=img, engine=None)), 这些裁片与
                # 基线逐块一致 —— 且不经 det_region_limit_split 32/min 闸门(保回退=基线语义)。
        if not mr_active and region_ok:
            if kind == "region" and self.config.get("det_region_limit", False):
                eng = get_engine_region()
            elif kind == "split" and self.config.get("det_region_limit_split", False):
                eng = get_engine_region()
        blocks = ocr_image(run_img, engine=eng)
        if zoom != 1.0:
            # OCR4: 送检图(重缩放 zoom 倍)坐标 -> 输入坐标系; 调用方再按生产放大倍率 /2、/scale。
            for nb in blocks:
                nb["center"] = [int(nb["center"][0] / zoom), int(nb["center"][1] / zoom)]
                nb["box"] = [int(nb["box"][0] / zoom), int(nb["box"][1] / zoom),
                             int(nb["box"][2] / zoom), int(nb["box"][3] / zoom)]
        dt = time.perf_counter() - t0
        self._ocr_stat[kind + "_n"] += 1
        self._ocr_stat[kind + "_t"] += dt
        if sub:
            self._ocr_stat[sub + "_n"] += 1
            self._ocr_stat[sub + "_t"] += dt
        d = self._ocr_stat["by_src"].setdefault(kind, {})
        d[self._ocr_src] = d.get(self._ocr_src, 0) + 1
        return blocks

    def _mixed_route_sr(self, img, kind: str, sub: str | None):
        """OCR4(batch-09): 混合路由 split/refine 腿的 P2C 准备(字高估计/倍率/重缩放)。
        返回 (engine, 送检图, factor) 供 _timed_ocr 送检并在返回后按 ÷factor 映射回输入
        坐标系; 返回 None = 本裁片按实验语义回退默认引擎原图(三类 fallback, 见下)。

        语义与实验 harness `prototypes/P2C/p2c.py run()` **逐字对齐**(min_conf=0.5,
        fmin=0.5; 混合路由 s48 冻结参数):
          - 跳 det 判据与库内 rapid_ocr_api.py 逐字一致(实验 p2c.py:151-152 同款, 对当前输入):
            h<=30 或 w/h>8.0 → 回退;
          - charh.estimate 不可用(h=None)或置信度<0.5 → 回退(实验 fallback_lowconf);
          - factor = target / est_h; factor >= 736/短边(默认实例短边倍率) → 触顶回退
            (实验 fallback_cap: 默认倍率同档或更激进时一律走默认路径, 保证「不劣于默认」);
          - factor < 0.5 → 抬到 0.5 下限(实验 adaptive_floor);
          - |factor-1|<=1e-3 不重缩放但仍用 P2C 自适应实例(实验同行为);
          - 缩放插值 = cv2.INTER_CUBIC(与实验及调用方 _split_wide 2x 同款)。
        target: sub=="refine" → `mixed_route.target_refine`(冻结 48); 其余(kind=="split")
        → `mixed_route.target_split`(冻结 48)。参数坑(验收线随行): 误用 s64 时负样本帧
        fr_08a73155d528 的拆分裁片稳定读出「白色菊小1仙」(真值「白色菊小仙」) → L4 FAIL,
        s48 恢复 PASS(MIXED_ROUTE.md §2) —— 两键默认 48 冻结入库, 改值仅限离线复现实验。
        估计器: `ocr_engine/charh.py`(P2C 估计器, batch-09 随批引入, 原型逐字拷贝)。
        冻结判断保持: 字高估计器仍不可全信(DECISION §3/§4.2) —— 仅本混合路由腿使用,
        不另立 estimate_char_h 用途(负清单 N20); region 腿绝不走 P2C/P2A(负清单 N6)。
        引擎: ocr_ui.get_engine_mixed()(det 8192/max, 其余参数与默认实例逐字一致,
        = 实验 Engines.adaptive 同配方; CPU 构建 —— P2C 实验全部在正式 venv CPU 口径,
        GPU 收益只落 region 腿, 本实例不随 ocr_execution_provider)。"""
        if sub == "refine":
            target = self.config.get("mixed_route.target_refine", 48)
            est_kind = "refine"
        else:
            target = self.config.get("mixed_route.target_split", 48)
            est_kind = "split"
        try:
            target = int(target)
        except (TypeError, ValueError):
            target = 48
        if target <= 0:
            return None
        h, w = img.shape[:2]
        short = min(h, w)
        default_factor = 736.0 / max(1, short)
        if (h <= 30) or (w / float(max(1, h)) > 8.0):
            return None    # 实验 fallback_skipdet: 小裁片/超宽裁片 det 判据逐字同库内
        from .. import charh
        est = charh.estimate(img, est_kind)
        if est.get("h") is None or est.get("conf", 0.0) < 0.5:
            return None    # 实验 fallback_lowconf
        factor = target / max(1e-6, est["h"])
        if factor >= default_factor - 1e-9:
            return None    # 实验 fallback_cap: 与默认倍率相同或更大 → 默认引擎原图跑
        if factor < 0.5:
            factor = 0.5   # 实验 adaptive_floor
        import cv2
        if abs(factor - 1.0) > 1e-3:
            img2 = cv2.resize(img, None, fx=factor, fy=factor,
                              interpolation=cv2.INTER_CUBIC)
        else:
            img2 = img
        return get_engine_mixed(), img2, factor

    def ocr_direct(self, img, src: str = "direct"):
        """流程外的直调 OCR(供 pollin 的页码/诊断等): 计入 direct 统计并按 src 归属。
        与 _timed_ocr 的区别仅在于 kind=direct —— 不会混进“全图/区域”口径, 避免低估问题被掩盖。"""
        prev = self._ocr_src
        self._ocr_src = src
        try:
            return self._timed_ocr(img, "direct")
        finally:
            self._ocr_src = prev

    def _split_wide(self, img, blocks):
        """过宽块(宽>90) 2x 重识别拆分(批C 自 _ocr_frame 原样抽出, 全图/区域化两路径共用)。
        返回精确子块列表; 拆分缓存键含裁片内 origin(批A 修订), 语义与原实现逐字节一致。"""
        sub_blocks: list = []  # 过宽块 2x 重识别拆出的精确子块, 点击定位时优先(点击点落到目标文字自身中心)
        for b in blocks:
            x1, y1, x2, y2 = b["box"]
            w = x2 - x1
            if w > 90:  # 过宽, 疑似合并(如「菜单/奇妙花宝」挤在一起): 放大重识别尝试拆出更精确的子按钮
                crop = img[max(0, y1 - 10):y2 + 10, max(0, x1 - 10):x2 + 10]
                if crop.size:
                    import cv2
                    # 按裁片像素指纹缓存拆分结果: 内容没变直接复用(等价幂等), 变了(跑马灯/滚动)
                    # 自动重拆 —— 行为与逐帧拆分完全一致。命中重插=简单 LRU 续期。
                    # 2026-11-17(P2 性能): 上限 400→1000。C47 实测单轮拆分 1470 次/1737s,
                    # 缓存命中仅 312 次; 扩大热工作集可把跨屏重复的静态碎片转为命中(内存可忽略)。
                    origin = (max(0, x1 - 10), max(0, y1 - 10))
                    # ⚠ 键必须含**裁片位置**（主 agent 修订, 里程碑 83）：缓存值存的是**全帧绝对坐标**
                    # (/2 + origin)，若同一像素内容出现在不同位置（重复 UI 元素 / 移动中的横幅，
                    # 且 10px 边距也恰好一致），纯像素键会把上一位置的**陈旧坐标**当结果复用 →
                    # 定位错误（正是本项目反复警惕的"陈旧坐标"类风险）。加入 origin 后只有
                    # 「同一位置 + 同内容」才复用：静态 UI 碎片照旧全命中（速收益不变），
                    # 移动/重复内容自动重拆（安全优先）。
                    key = (origin[0], origin[1],
                           hashlib.blake2b(np.ascontiguousarray(crop).tobytes(),
                                           digest_size=16).digest())
                    with self._split_lock:
                        cached = self._split_cache.get(key)
                        if cached is not None:
                            self._split_cache.pop(key)
                            self._split_cache[key] = cached
                    if cached is not None:
                        self._ocr_stat["split_cache_hit"] += 1   # O0: 缓存命中(无 OCR)
                        sub_blocks.extend(dict(nb) for nb in cached)
                        continue
                    big = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                    newly: list = []
                    # P1(2026-11-10): sub="split_wide" 子类耗时观测; kind=="split" 命中
                    # det_region_limit_split 闸门时用裁片专用实例(32/min), 默认关 = engine=None。
                    for nb in self._timed_ocr(big, "split", sub="split_wide"):
                        ox = int(nb["center"][0] / 2) + max(0, x1 - 10)
                        oy = int(nb["center"][1] / 2) + max(0, y1 - 10)
                        nb2 = dict(nb)
                        nb2["center"] = [ox, oy]
                        nb2["box"] = [int(nb["box"][0] / 2) + max(0, x1 - 10),
                                      int(nb["box"][1] / 2) + max(0, y1 - 10),
                                      int(nb["box"][2] / 2) + max(0, x1 - 10),
                                      int(nb["box"][3] / 2) + max(0, x1 - 10)]
                        newly.append(nb2)
                    with self._split_lock:
                        if len(self._split_cache) >= SPLIT_CACHE_MAX:
                            self._split_cache.pop(next(iter(self._split_cache)))
                        self._split_cache[key] = newly
                    sub_blocks.extend(dict(nb) for nb in newly)
        return sub_blocks

    def _ocr_frame_region(self, img, region_rel, need_split: bool = True):
        """批C-①: 区域化 OCR —— region 面积<=全图 40% 时只 OCR 裁片, 坐标映射回全图。
        返回 (blocks, sub_blocks)(全图坐标系) 或 None(调用方回退全图路径)。
        - pad 按 region 宽/高各 5% 外扩(用户 2026-10-11 裁定: 纯比例适配任意分辨率, 不用固定像素),
          保证贴边文字块完整进入裁片, 消除 det 边界截断;
        - 裁片 OCR 走独立 LRU(键=裁片像素指纹, 值=裁片相对坐标块), 不占用全图单槽帧缓存;
          拆分复用 _split_wide(其缓存键含裁片内 origin, 语义一致);
        - 语义: 调用方拿到块后照常执行原有区域过滤, 过滤语义与全图路径一致; 区域内未命中时
          由调用方回退一次全图 —— 区域化只省命中路径耗时, 不制造新 MISS。
        O2(2026-10-21): `need_split=False` 时跳过拆分子块(判断类调用); 缓存值用 None 表示“未算”,
          同一裁片后续需要坐标精度时再补算并写回 —— 与 _ocr_frame 的惰性策略一致。
        """
        w, h = self.screen_w, self.screen_h
        if not w or not h or img is None or len(region_rel) != 4:
            return None
        rx1, ry1 = int(region_rel[0] * w), int(region_rel[1] * h)
        rx2, ry2 = int(region_rel[2] * w), int(region_rel[3] * h)
        rw, rh = rx2 - rx1, ry2 - ry1
        if rw <= 0 or rh <= 0 or rw * rh > 0.4 * w * h:
            return None
        pad_x, pad_y = max(1, int(rw * 0.05)), max(1, int(rh * 0.05))
        cx1, cy1 = max(0, rx1 - pad_x), max(0, ry1 - pad_y)
        cx2, cy2 = min(w, rx2 + pad_x), min(h, ry2 + pad_y)
        crop = img[cy1:cy2, cx1:cx2]
        if crop.size == 0:
            return None
        sig = self._frame_hash(crop)
        cached = None
        if sig is not None:
            with self._region_lock:
                cached = self._region_cache.get(sig)
                if cached is not None:
                    self._region_cache.pop(sig)
                    self._region_cache[sig] = cached
        if cached is not None:
            self._ocr_stat["hit_n"] += 1
            # ⚠ 命中副本与存储副本必须分离: 下面要按当次 origin 重映射(键重绑定),
            # 若直接改缓存内字典, 第二次命中会叠加两次偏移(坐标错位) —— 测试 T2 实证。
            blocks = [dict(b) for b in cached[0]]
            subs_cached = cached[1]      # None = 未拆分(O2 惰性)
        else:
            blocks = self._timed_ocr(crop, "region")
            subs_cached = None
        if need_split and subs_cached is None:
            subs_cached = self._split_wide(crop, blocks)
            if sig is not None:
                with self._region_lock:
                    if sig in self._region_cache:
                        self._region_cache.pop(sig)
                    elif len(self._region_cache) >= 200:
                        self._region_cache.pop(next(iter(self._region_cache)))
                    # 存**原始副本**(未经映射); 每次返回另出映射副本(见下), 缓存内容永不带偏移
                    self._region_cache[sig] = ([dict(b) for b in blocks],
                                               [dict(b) for b in subs_cached])
            sub_blocks = [dict(b) for b in subs_cached]
        else:
            sub_blocks = [dict(b) for b in subs_cached] if subs_cached else []
            if cached is None and sig is not None:
                with self._region_lock:
                    if len(self._region_cache) >= 200:
                        self._region_cache.pop(next(iter(self._region_cache)))
                    self._region_cache[sig] = ([dict(b) for b in blocks], None)
        # 裁片相对坐标 -> 全图绝对坐标(映射用当次 origin, 缓存命中也重映射)
        for b in blocks + sub_blocks:
            b["center"] = [b["center"][0] + cx1, b["center"][1] + cy1]
            b["box"] = [b["box"][0] + cx1, b["box"][1] + cy1,
                        b["box"][2] + cx1, b["box"][3] + cy1]
        return blocks, sub_blocks

    def _ocr_candidates(self, img, region_rel, need_refine: bool = True):
        """批C-①: 判定入口共用的块获取。region 面积<=40% 且 region_ocr 开启时走区域化。
        返回 (blocks, sub_blocks, used_region); 区域路径零命中时由调用方回退全图。
        O2(2026-10-21): need_refine=False 时不做过宽块拆分(判断类只需布尔/计数)。"""
        if region_rel and len(region_rel) == 4 and self.config.get("region_ocr", True):
            r = self._ocr_frame_region(img, region_rel, need_split=need_refine)
            if r is not None:
                return r[0], r[1], True
        b, sb = self._ocr_frame(img, need_split=need_refine)
        return b, sb, False

    def ocr_blocks(self, img=None, region_rel=None) -> list[dict]:
        """读取一帧的全部 OCR 文本块(全图坐标, dict: text/score/center/box)。

        供种植等需要「整页字段解析」的模块使用: 只读, 不拆分过宽块(拆分只为点击精度)。
        region_rel 给定且 region_ocr 开启、面积<=40% 时走区域裁片(复用 _region_cache),
        否则全图; 结果按 center 再过滤到 region, 与既有区域语义一致。
        不改任何判定语义, 不写 last_rel / _last_match_block。
        """
        img = img if img is not None else self.screenshot()
        if img is None:
            return []
        blocks = None
        if region_rel and len(region_rel) == 4 and self.config.get("region_ocr", True):
            r = self._ocr_frame_region(img, region_rel, need_split=False)
            if r is not None:
                blocks = r[0]
        if blocks is None:
            blocks, _ = self._ocr_frame(img, need_split=False)
        if region_rel and len(region_rel) == 4:
            w, h = self.screen_w or 1, self.screen_h or 1
            x1, y1, x2, y2 = region_rel
            blocks = [b for b in blocks
                      if x1 * w <= b["center"][0] <= x2 * w
                      and y1 * h <= b["center"][1] <= y2 * h]
        return blocks

    def _print_ocr_stat(self, mid):
        """批C-②: 模块级 OCR 计时汇总(纯观测), 并累计进整轮统计。
        O0(2026-10-21): 追加「来源 / 拆分缓存 / 仅子块命中 / 直调」三行, 用于把 44min 之类的耗时
        精确归因到步骤类型, 并为 O1/O2 提供前后对照基线。"""
        st = self._ocr_stat
        _stat_add(self._ocr_stat_total, st)
        print(f"[OCR统计] 模块 {mid}: 全图 {st['full_n']} 次 {st['full_t']:.2f}s · "
              f"区域 {st['region_n']} 次 {st['region_t']:.2f}s · 拆分 {st['split_n']} 次 {st['split_t']:.2f}s · "
              f"缓存命中 {st['hit_n']} 次"
              # P1(2026-11-10): 末尾追加 split 子类观测(拆宽=_split_wide / 精识=_refine_wide_block),
              # 既有字段顺序与名字不变; .get 兼容缺键的旧统计结构。
              f" · 拆宽 {st.get('split_wide_n', 0)} 次 {st.get('split_wide_t', 0.0):.2f}s"
              f" · 精识 {st.get('refine_n', 0)} 次 {st.get('refine_t', 0.0):.2f}s"
              # Q04(batch-05, 2026-11-14): 末尾追加截图观测(纯新增, 既有字段不动) ——
              # OCR 慢 vs 截图慢分账(输入管道是主要慢因之一); .get 兼容缺键旧结构。
              f" · 截图 {st.get('shot_n', 0)} 次 {st.get('shot_t', 0.0):.2f}s")
        by = st.get("by_src") or {}

        def _fmt(kind, limit=8):
            d = by.get(kind) or {}
            if not d:
                return "-"
            items = sorted(d.items(), key=lambda kv: -kv[1])[:limit]
            return " · ".join(f"{k} {v}" for k, v in items)

        print(f"[OCR来源] 全图: {_fmt('full')}  |  区域: {_fmt('region')}  |  拆分: {_fmt('split')}")
        print(f"[OCR健康] 拆分缓存命中 {st['split_cache_hit']} 次 · 仅子块命中 {st['split_only_hit']} 次 · "
              f"场景判断 {st['scene_calls']} 次(折叠 {st.get('scene_quiet_n', 0)}) · "
              f"直调 {st['direct_n']} 次 {st['direct_t']:.2f}s "
              f"({_fmt('direct', 4)}) · 静默未命中 {st.get('miss_silent_n', 0)} 次(弹窗/启动守卫确认无)")
        cn = st.get("friend_coarse_n", 0)
        if cn:
            ch = st.get("friend_coarse_hit", 0)
            fn = st.get("friend_fine_n", 0)
            fh = st.get("friend_fine_hit", 0)
            total_ok = ch + fh
            total = cn
            print(f"[粗OCR] 社交面板「好友」: 粗识 {ch}/{cn} ({ch / cn:.0%}) · "
                  f"精识兜底 {fh}/{fn} ({(fh / fn if fn else 0):.0%}) · "
                  f"综合 {total_ok}/{total} ({(total_ok / total if total else 0):.0%})"
                  f"  ← 粗识成功率偏低时优先改进粗 OCR(用户 2026-10-24: 日志保留, 只统计)")
        # V01-a(batch-11): 低对比模板观测汇总 —— **仅 tm_low_n 非零时打印**(常态零输出,
        # [OCR统计] 既有行文案/键序零漂移; 方案 [OCR统计] 键面白名单: V01-a 允许新增观测键,
        # batch-05 口径)。分数物理意义见 _template._note_tm_lowcontrast(07 笔记 V01 实测塌缩)。
        tm_n = st.get("tm_low_n", 0)
        if tm_n:
            per = " | ".join(
                f"{k} {v.get('hit', 0)}/{v.get('n', 0)}@均分{((v.get('sum', 0.0) or 0.0) / v['n']):.3f}"
                for k, v in sorted((st.get("tm_low_by_tpl") or {}).items()) if v.get("n"))
            print(f"[模板观测] 模块 {mid}: 低灰度std模板匹配 {tm_n} 次"
                  f"(命中 {st.get('tm_low_hit_n', 0)}) 均分 "
                  f"{((st.get('tm_low_score_sum', 0.0) or 0.0) / tm_n):.4f}"
                  + (f" · {per}" if per else "")
                  + " (纯观测不改判定; 低对比帧上的分数作标定依据前须在正常帧复核)")
