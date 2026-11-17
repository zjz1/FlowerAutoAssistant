# -*- coding: utf-8 -*-
"""离线测试用的假引擎：只实现被测函数需要的公开能力，不连 ADB/OCR。"""
from __future__ import annotations

from types import SimpleNamespace


class FakeEngine:
    def __init__(self, screen_w=1920, screen_h=1080, blocks=None,
                 locate_results=None, click_text_result=True):
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.blocks = blocks or {}          # {region_tuple_or_None: [block,...]}
        self.locate_results = locate_results or {}  # {keyword: Point/None}
        self.click_text_result = click_text_result
        self.calls = []
        self.adb_path = "adb"
        self.address = "127.0.0.1:16384"
        self.config = {}

    def ocr_blocks(self, img=None, region_rel=None):
        key = tuple(region_rel) if region_rel is not None else None
        return list(self.blocks.get(key, []))

    def click_text(self, texts, **kwargs):
        self.calls.append(("click_text", tuple(texts), kwargs.get("region_rel")))
        return self.click_text_result

    def click_abs(self, x, y):
        self.calls.append(("click_abs", int(x), int(y)))

    def locate(self, texts, **kwargs):
        self.calls.append(("locate", tuple(texts), kwargs.get("region_rel")))
        for t in texts:
            if t in self.locate_results:
                return self.locate_results[t]
        return None

    def close_dialog(self):
        self.calls.append(("close_dialog",))


def block(text, x=0, y=0):
    return {"text": text, "center": [x, y],
            "box": [x - 10, y - 5, x + 10, y + 5]}


def point(x, y):
    return SimpleNamespace(x=x, y=y)
