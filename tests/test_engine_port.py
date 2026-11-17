# -*- coding: utf-8 -*-
"""EnginePort 契约基线：结构化匹配与业务模块标注。"""
from __future__ import annotations

import typing
import unittest

import buy_seed
import community_like
import fairyland
import navigation
import plant
import pollin
import ui_ops
from core.ports import EnginePort, UiPort
from tests.fake_engine import FakeEngine


class FullFakeEngine:
    screen_w = 1920
    screen_h = 1080
    adb_path = "adb"
    address = "127.0.0.1:16384"
    config: dict = {}

    def connect(self, *a, **k): return True
    def swipe_rel(self, *a, **k): return None
    def click_rel(self, *a, **k): return None
    def screenshot(self, *a, **k): return None
    def ocr_blocks(self, *a, **k): return []
    def ocr_direct(self, *a, **k): return []
    def locate(self, *a, **k): return None
    def locate_fine(self, *a, **k): return None
    def click_abs(self, *a, **k): return None
    def click_text(self, *a, **k): return False
    def close_dialog(self, *a, **k): return False
    def locate_template(self, *a, **k): return None
    def locate_template_all(self, *a, **k): return []
    def click_template(self, *a, **k): return None
    def judge_scene(self, *a, **k): return False
    def set_scene(self, *a, **k): return None
    def parse_fraction_at(self, *a, **k): return None
    def parse_count_at(self, *a, **k): return None
    def pink_ratio_at(self, *a, **k): return None
    def has_reward_popup(self, *a, **k): return False
    def reward_dialog(self, *a, **k): return None
    def get_ocr_stat(self, *a, **k): return {}
    def update_config(self, *a, **k): return None
    def run_flow(self, *a, **k): return None
    def run_daily(self, *a, **k): return None


class EnginePortTests(unittest.TestCase):
    def test_full_fake_satisfies_port(self):
        self.assertIsInstance(FullFakeEngine(), EnginePort)
        self.assertIsInstance(FullFakeEngine(), UiPort)

    def test_partial_fake_does_not_satisfy_port(self):
        self.assertNotIsInstance(FakeEngine(), EnginePort)

    def test_business_entrypoints_annotated(self):
        cases = [
            (plant.run_plant_flower, EnginePort),
            (plant.run_plant_harvest, EnginePort),
            (buy_seed.run_buy_seed, EnginePort),
            (fairyland.run_fairyland_claim, EnginePort),
            (pollin.run_friend_pollin, EnginePort),
            (community_like.run_community_like, EnginePort),
        ]
        for fn, expected in cases:
            hints = typing.get_type_hints(fn)
            self.assertIs(hints.get("eng"), expected, fn.__module__ + "." + fn.__name__)

    def test_ui_helpers_use_ui_port(self):
        self.assertIs(typing.get_type_hints(ui_ops.focus_input).get("eng"), UiPort)
        self.assertIs(typing.get_type_hints(navigation.ensure_any_garden).get("eng"), UiPort)

    def test_ocrengine_exposes_port_methods(self):
        from ocr_engine import OCREngine
        methods = (
            "screenshot", "ocr_blocks", "ocr_direct", "locate", "locate_fine",
            "click_abs", "click_text", "close_dialog", "connect", "swipe_rel",
            "click_rel", "locate_template", "locate_template_all", "click_template",
            "judge_scene", "set_scene", "parse_count_at", "parse_fraction_at",
            "pink_ratio_at", "has_reward_popup", "reward_dialog", "get_ocr_stat",
            "update_config", "run_flow", "run_daily",
        )
        for name in methods:
            self.assertTrue(hasattr(OCREngine, name), f"OCREngine 缺少端口方法 {name}")


if __name__ == "__main__":
    unittest.main()
