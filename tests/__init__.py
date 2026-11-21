# -*- coding: utf-8 -*-
"""测试包入口：强制 UTF-8 输出。

Windows CI（非中文 locale）下 stdout/stderr 可能是 cp1252，测试里打印中文会
抛 UnicodeEncodeError。测试进程统一改成 UTF-8，避免把编码问题误报成用例失败。
"""
from __future__ import annotations

import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 —— 非 tty / 不支持 reconfigure 时忽略
        pass
