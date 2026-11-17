# -*- coding: utf-8 -*-
"""通用导航原语：任意家园（自己/好友）归位。

2026-11-17 P1-5：buy_seed / fairyland 各自复制过一份相同的 `_ensure_garden`
（右下角有「离开」即在家园，否则户外点「家园」）。本模块收敛该原语；
plant 的「必须自己家园」三态语义不同（自家/好友家单帧同形，需点「离开」后判下一屏），
仍保留在 flow_plant.json 阶段0，不混用。
"""
from __future__ import annotations
from core.ports import UiPort

import time

# 自己家园 / 好友家园 / 户外 的右下角操作带（只作判据，点击仍取实时命中）
GARDEN_ACTION_REGION = [0.78, 0.85, 1.0, 1.0]


def ensure_any_garden(eng: UiPort, timeout: float = 8.0) -> bool:
    """自己或好友家园均可：右下角有「离开」即在家园；否则点「家园」并等待到位。"""
    if eng.locate(["离开"], region_rel=GARDEN_ACTION_REGION,
                  need_refine=False, log_miss=False):
        return True
    if eng.click_text(["家园"], region_rel=GARDEN_ACTION_REGION,
                      min_score=0.4, no_fallback=True):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if eng.locate(["离开"], region_rel=GARDEN_ACTION_REGION,
                          need_refine=False, log_miss=False):
                return True
            time.sleep(1.0)
    return False
