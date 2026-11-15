"""
FlowerAutoAssistant - OCR 数据驱动引擎核心（替代 MAA 模板匹配路线）

核心循环: 截图 -> OCR识别文字 -> 按关键字定位按钮 -> 计算相对坐标(归一化) -> 点击

与 MAA 模板匹配的区别:
- 不依赖模板图片, 每次运行通过 OCR 直接识别文字/按钮位置
- 使用「相对坐标」: 记录 (x/宽, y/高) 归一化坐标, 屏幕尺寸变化时相对位置不变
- 数据驱动: 流程由 JSON 描述(flow), 无需改代码即可适配新流程
- 回退缓存: 记录「最后已知相对坐标」, 当 OCR 瞬时失败时可用缓存补点击, 提高鲁棒性

用法:
    python ocr_engine.py --list            # 列出可用流程
    python ocr_engine.py --flow 每日      # 运行指定流程(按关键字匹配)

拆包说明(E01, batch-03, 2026-11-14):
    本模块自单文件 ocr_engine.py(4712 行)机械拆分为 ocr_engine/ 包(Mixin 纵切 + facade):
    import ocr_engine 一律解析到 ocr_engine/ 包(常规包优先于同目录同名 .py 文件);
    全部旧符号由 ocr_engine/__init__.py 再导出, import 面零改动 —— 消费方
    main.py:25 / pollin.py:23-24 / community_like.py:59 / webui.py:26 / tools/collect_frames.py:41。
    根 ocr_engine.py 保留为 `python ocr_engine.py ...` CLI 直执行入口(shim)。
"""
from __future__ import annotations

from ._constants import (ADB_ADDRESS, ADB_PATH, BIAS_HARD_PX, BIAS_MAX_PX,
                        CLICK_LOG_PATH, CLOSE_BUTTONS_PATH, CONFIG_PATH,
                        FLOW_DIR, NAV_ENTRIES_PATH, NAV_SCENES_PATH, STEP_TYPES,
                        TEMPLATE_DIR)
from ._exceptions import (_STOP_EV, BranchAborted, FlowFailed, StopRequested,
                        clear_stop, request_stop, stop_requested)
from ._failures import (_FAIL_LOCK, _FAIL_SEQ, _FAILURES, clear_failures,
                        get_failures, report_failure)
from ._geometry import Point
from ._stat import _new_ocr_stat, _stat_add, _ts
from .engine._core import OCREngine
from ._flowmgr import load_flows, main, select_flow

from dataclasses import dataclass, field  # noqa: F401  (旧模块属性面)
from pathlib import Path  # noqa: F401
import hashlib  # noqa: F401
import json  # noqa: F401
import math  # noqa: F401
import os  # noqa: F401
import re  # noqa: F401
import sys  # noqa: F401
import threading  # noqa: F401
import time  # noqa: F401
import metrics_recorder  # noqa: F401
import numpy as np  # noqa: F401
from ocr_ui import get_engine_region, ocr_find, ocr_image, set_thread_limit  # noqa: F401

del engine  # 子包属性不属旧模块符号面; `import ocr_engine.engine.X` 仍可用(sys.modules 已缓存; 仅 `ocr_engine.engine` 属性访问路径不会重建)
