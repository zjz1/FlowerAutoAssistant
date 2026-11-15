"""Point 坐标类型。

E01(batch-03, 2026-11-14) 自单文件 ocr_engine.py 机械拆包: 本文件各段为原文件对应
行段的**逐行原文**(唯 __file__ 锚点因包层级 +1 机械重锚定, 见 ast_hash_compare.py
allowlist)。行为等价口径: 帧集回归 0 退化 + 闸门全绿 + import 面零改动。
原行段映射: evidence/batch-03/tiles_manifest.json。
"""
from __future__ import annotations

from dataclasses import dataclass, field  # field: 基线原样保留(未用, 不删疑似死代码)
# ---------- 坐标 ----------
@dataclass
class Point:
    """绝对坐标 (px) 与相对坐标 (0~1 归一化)。"""
    x: int
    y: int
    w: int  # 屏幕宽
    h: int  # 屏幕高

    @property
    def rel(self) -> tuple[float, float]:
        return (self.x / self.w if self.w else 0.0,
                self.y / self.h if self.h else 0.0)

    @staticmethod
    def from_rel(rx: float, ry: float, w: int, h: int) -> "Point":
        return Point(int(rx * w), int(ry * h), w, h)
