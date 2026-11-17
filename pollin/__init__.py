# -*- coding: utf-8 -*-
"""好友采粉闭环（facade）。

Stage 5（2026-11-17）自单文件 pollin.py（1500 行）拆分为：
    constants → primitives → popups → navigation → list_panel → collect → runner
依赖单向、无循环；本文件再导出全部旧公开符号，`import pollin` /
`from pollin import ensure_home` 的消费面零改动。
根 pollin.py 保留为 `python pollin.py state|all` CLI shim。

模块职责：
    constants    常量/阈值/区域（相对坐标，分辨率无关）
    primitives   存在性判断 / 轮询 / 帧差 / 按钮精识 / ADB 输入 / 存证
    popups       无花粉提示框 / 半透明奖励弹窗 / 弹层脱困
    navigation   场景判据 / 进园等待 / 右上角关闭 / 回家链 / 离园·关列表
    list_panel   开列表 / 切页签 / 翻页 / 可采粉标记扫描
    collect      单个好友采集
    runner       单类别编排 / 闭环入口 / state|all CLI
"""
from __future__ import annotations

from .constants import *  # noqa: F401,F403
from .primitives import *  # noqa: F401,F403
from .popups import *  # noqa: F401,F403
from .navigation import *  # noqa: F401,F403
from .list_panel import *  # noqa: F401,F403
from .collect import *  # noqa: F401,F403
from .runner import *  # noqa: F401,F403
