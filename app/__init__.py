# -*- coding: utf-8 -*-
"""应用服务层（Stage 1）。

依赖方向：adapters(webui.py) → app/* → core(ocr_engine / 业务模块)。
本包不 import webui，保证可被 CLI、测试、原生壳复用。
"""
