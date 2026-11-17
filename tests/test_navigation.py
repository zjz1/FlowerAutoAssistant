# -*- coding: utf-8 -*-
"""导航原语基线：任意家园归位三分支。"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import navigation
from tests.fake_engine import FakeEngine, point


class GardenFake(FakeEngine):
    def __init__(self, garden=True, respond=True):
        super().__init__()
        self.garden = garden
        self.respond = respond

    def locate(self, texts, **kwargs):
        self.calls.append(("locate", tuple(texts)))
        return point(1, 1) if self.garden else None

    def click_text(self, texts, **kwargs):
        self.calls.append(("click_text", tuple(texts)))
        if self.respond:
            self.garden = True
        return True


class NavigationTests(unittest.TestCase):
    def test_already_in_garden(self):
        eng = GardenFake(garden=True)
        self.assertTrue(navigation.ensure_any_garden(eng))
        self.assertEqual(eng.calls[0][0], "locate")

    @patch("navigation.time.sleep", return_value=None)
    def test_outdoor_clicks_home(self, _sleep):
        eng = GardenFake(garden=False, respond=True)
        self.assertTrue(navigation.ensure_any_garden(eng))
        self.assertIn(("click_text", ("家园",)), eng.calls)

    @patch("navigation.time.sleep", return_value=None)
    def test_failure_returns_false(self, _sleep):
        eng = GardenFake(garden=False, respond=False)
        self.assertFalse(navigation.ensure_any_garden(eng, timeout=0))


if __name__ == "__main__":
    unittest.main()
