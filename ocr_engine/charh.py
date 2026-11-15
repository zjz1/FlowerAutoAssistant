# -*- coding: utf-8 -*-
"""P2C · 自适应字高估计器（轻量, 纯 cv2/numpy, 确定性）。

[随批引入注记 · OCR4/batch-09, 2026-11-15] 本文件自 `_lab/ocr/prototypes/P2C/charh.py`
(222 行) 随 OCR4 混合路由批**逐字引入**基线树(清单 P3 · OCR6「仅随 OCR4 批引入」),
除本段注记外内容与原型逐字节一致; 唯一消费方 = `ocr_engine/engine/_ocr.py` 的混合路由
split/refine 腿(灰度键 mixed_route.enabled, 默认 false)。冻结判断保持(DECISION.md
§3/§4.2): **字高估计器仍不可全信** —— 本估计器仅服务混合路由 split/refine 腿的缩放
决策与三类回退, 不另立 estimate_char_h 用途(负清单 N20), region 腿继续弃用 P2C/P2A
(负清单 N6)。

背景（为什么不用 P1 的 labcore.estimate_char_h）:
  P1 h* 的字高估计器对**原始灰度**做 Otsu 反相。游戏 UI 的面板底色/半透明遮罩
  占多数像素时, Otsu 把整块面板判成前景 → 行投影处处超阈值 → 返回整幅裁片高。
  实测退化率 region 83.4% / split 30.8% / refine 18.7%（P1 §8）, 缩放被夹到
  0.25 → 字被缩没 → h16~h48 全灭。所以 P1 证伪的是"坏估计器", 不是 H2 本身。

本估计器:
  1) 墨迹图 = 逐通道 |ch - medianBlur(ch, k)| 取最大 —— 去掉低频面板/遮罩,
     对底色与文字颜色极性都不敏感;
  2) 行带 = 行投影连续段（不合并/轻合并两版）, 过滤墨迹量过低的孤立细线;
  3) 对齐连通域组 = 垂直中心与高度相近、横向展开 ≥min_span 的连通域簇,
     取最大簇高（对美术图/图标更稳, 见 P2C.md §2 的逐裁片对比）;
  4) 按裁片类型取估计:
       split / refine（裁片来自源块框, 行带即文本行）: band_max
       region（任意 UI 区域, 可能含美术）: min(band_max, group_max)
  5) 置信度: 无墨迹/无行带/估计越界 → 低置信, 调用方回退默认引擎。

接口:
    estimate(img, kind) -> dict(h=float|None, method, conf, n_bands, n_comps,
                                band_max, group_max, reason)

本文件只依赖 cv2/numpy; 不 import 正式版任何模块。
"""
from __future__ import annotations

import cv2
import numpy as np


# ---------------------------------------------------------------------------
def _odd(v: int, lo: int = 3) -> int:
    v = max(lo, int(v))
    return v if v % 2 == 1 else v - 1


def ink_map(img: np.ndarray, kmax: int = 0) -> np.ndarray:
    """逐通道 |ch - medianBlur(ch,k)| 取最大 → 高频墨迹图（uint8）。"""
    h, w = img.shape[:2]
    k = kmax if kmax > 0 else 15
    k = _odd(min(k, (min(h, w) // 2) * 2 - 1))
    hp = []
    nch = img.shape[2] if img.ndim == 3 else 1
    for c in range(nch):
        ch = img[:, :, c] if img.ndim == 3 else img
        hp.append(cv2.absdiff(ch, cv2.medianBlur(ch, k)))
    return np.maximum.reduce(hp) if len(hp) > 1 else hp[0]


def _runs(mask: np.ndarray, thr: float) -> list[tuple[int, int]]:
    out, c, st = [], 0, 0
    for i, v in enumerate(mask):
        if v > thr:
            if c == 0:
                st = i
            c += 1
        elif c:
            out.append((st, st + c))
            c = 0
    if c:
        out.append((st, st + c))
    return out


def _median(v):
    if not v:
        return 0.0
    s = sorted(v)
    n = len(s)
    return float(s[n // 2]) if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


# ---------------------------------------------------------------------------
def _bands(ink: np.ndarray, row_frac: float = 0.02, min_h: int = 4,
           merge_frac: float = 0.0) -> list[tuple[int, int]]:
    h, w = ink.shape
    proj = ink.sum(axis=1)
    row_thr = max(2, int(row_frac * w))
    bands = [b for b in _runs(proj, row_thr) if b[1] - b[0] >= min_h]
    if bands and merge_frac > 0:
        mh = _median([b[1] - b[0] for b in bands]) or 1.0
        merged = [list(bands[0])]
        for a, b in bands[1:]:
            if a - merged[-1][1] < merge_frac * mh:
                merged[-1][1] = b
            else:
                merged.append([a, b])
        bands = [tuple(b) for b in merged]
    return bands


def _band_max(ink: np.ndarray, bands: list, max_h_frac: float = 0.85,
              mass_frac: float = 0.005) -> float | None:
    h = ink.shape[0]
    tot = max(1, int(ink.sum()))
    cand = []
    for y0, y1 in bands:
        bh = y1 - y0
        if bh > max_h_frac * h:
            continue
        if int(ink[y0:y1].sum()) < mass_frac * tot:
            continue                        # 孤立细线/噪声
        cand.append(bh)
    return float(max(cand)) if cand else None


def _comps(ink: np.ndarray, max_h_frac: float = 0.6) -> list[dict]:
    h, w = ink.shape
    n, lab, stats, _cent = cv2.connectedComponentsWithStats(ink, 8)
    out = []
    for i in range(1, n):
        x, y, cw, ch, area = (int(v) for v in stats[i])
        if area < 6 or ch < 4:
            continue
        if ch > max_h_frac * h:
            continue
        if cw > 5 * ch or cw < 2:
            continue
        if area / float(max(1, cw * ch)) < 0.10:
            continue
        out.append(dict(x=x, y=y, w=cw, h=ch, a=area, cx=x + cw / 2.0,
                        cy=y + ch / 2.0))
    return out


def _align_groups(comps: list[dict], y_tol: float = 0.5, h_tol: float = 0.3,
                  min_n: int = 2, min_span: int = 12) -> list[dict]:
    """垂直对齐的连通域簇（文本行候选）。返回 [{h, n, span, y0, y1}]。"""
    if not comps:
        return []
    groups = []
    for c in sorted(comps, key=lambda c: (c["cy"], c["h"])):
        placed = False
        for g in groups:
            mh = _median([x["h"] for x in g]) or 1
            mcy = _median([x["cy"] for x in g])
            if abs(c["cy"] - mcy) <= y_tol * mh and abs(c["h"] - mh) <= h_tol * mh:
                g.append(c)
                placed = True
                break
        if not placed:
            groups.append([c])
    out = []
    for g in groups:
        if len(g) < min_n:
            continue
        span = max(x["x"] + x["w"] for x in g) - min(x["x"] for x in g)
        if span < min_span:
            continue
        mh = _median([x["h"] for x in g])
        hs2 = [x["h"] for x in g if x["h"] >= 0.55 * mh]   # 去掉标点/噪声碎片
        out.append(dict(h=_median(hs2), n=len(g), span=int(span)))
    return out


# ---------------------------------------------------------------------------
def estimate(img: np.ndarray, kind: str = "split", dev_abs: int = 10,
             dev_rel: float = 0.22) -> dict:
    """估计裁片内字高（**裁片像素**, 不是原图像素）。

    返回 dict:
      h: 估计字高（裁片像素）, None=不可用
      method: 'band' | 'band+group' | 'none'
      conf: 0~1
      band_max / group_max: 两个分量估计（便于复核与报告）
      reason: 'ok' | 'no_ink' | 'no_band' | 'implausible'
    """
    h, w = img.shape[:2]
    out = dict(h=None, method="none", conf=0.0, band_max=None, group_max=None,
               n_bands=0, n_comps=0, n_groups=0, reason="")
    if w < 4 or h < 4:
        out["reason"] = "tiny"
        return out
    dev = ink_map(img)
    mx = int(dev.max())
    if mx <= dev_abs:
        out["reason"] = "no_ink"
        return out
    thr = max(dev_abs, int(dev_rel * mx))
    ink = (dev > thr).astype(np.uint8)
    ink = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    bmax = _band_max(ink, _bands(ink, merge_frac=0.0))
    comps = _comps(ink)
    gmax = None
    groups = _align_groups(comps)
    if groups:
        gmax = float(max(g["h"] for g in groups))
    out.update(band_max=bmax, group_max=gmax, n_comps=len(comps),
               n_groups=len(groups), n_bands=len(_bands(ink)))

    if kind in ("split", "refine"):
        est, method = bmax, "band"
    else:
        cands = [v for v in (bmax, gmax) if v]
        if not cands:
            est, method = None, "none"
        elif len(cands) == 1:
            est, method = cands[0], "band" if bmax else "band+group"
        else:
            est, method = min(cands), "band+group"

    if est is None or est < 3.0 or est > 0.9 * h:
        out["reason"] = "implausible" if est is not None else "no_band"
        out["h"] = None
        return out

    conf = 1.0
    if out["n_comps"] < 3:
        conf *= 0.6
    if bmax is None or gmax is None:
        conf *= 0.7
    if est > 0.6 * h:
        conf *= 0.5
    if bmax is not None and gmax is not None:
        ratio = max(bmax, gmax) / max(1.0, min(bmax, gmax))
        if ratio > 3.0:
            conf *= 0.6            # 两个分量互相矛盾
    out.update(h=float(est), method=method, conf=round(float(conf), 3),
               reason="ok")
    return out
