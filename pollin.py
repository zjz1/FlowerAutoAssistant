# -*- coding: utf-8 -*-
"""好友采粉闭环（兼容入口 / CLI shim）。

Stage 5（2026-11-17）：实现已拆到 pollin/ 包（facade 再导出全部旧符号）；
本文件保留 `python pollin.py state|all` 直执行入口，import 面零改动。
"""
from __future__ import annotations

from pollin import *  # noqa: F401,F403 —— 全部旧公开符号(经包 facade 再导出)
from pollin import main  # noqa: F401 —— CLI 入口(本文件 __main__ 直执行用)

if __name__ == "__main__":
    main()
