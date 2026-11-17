# -*- coding: utf-8 -*-
"""「快捷操作」收菜单区域修复（2026-11-18）离线回归。

背景：旧实现用 BOTTOM_BAR_REGION（社交区 x0.28~0.55）定位「快捷操作」（实测 x≈0.69），
区域外导致永不命中；日志自带「区域外含同字块(疑似区域坐标不对)」警告。
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from pollin.collect import QUICK_ACTION_REGION, close_quick_action_menu


def _point(x, y):
    return SimpleNamespace(x=x, y=y)


class _FakeEngine:
    """菜单状态可控：点击「快捷操作」后按 close_on_click 决定是否收起。"""

    screen_w = 1280
    screen_h = 720

    def __init__(self, menu_open=True, close_on_click=True):
        self.menu_open = menu_open
        self.close_on_click = close_on_click
        self.calls = []

    def screenshot(self):
        return None

    def locate(self, texts, **kwargs):
        kws = [texts] if isinstance(texts, str) else list(texts)
        self.calls.append(("locate", tuple(kws), kwargs.get("region_rel")))
        if not self.menu_open:
            return None
        if "采粉" in kws:
            return _point(994, 603)
        if "快捷操作" in kws:
            return _point(885, 685)
        return None

    def click_abs(self, x, y):
        self.calls.append(("click_abs", int(x), int(y)))
        if self.close_on_click and (int(x), int(y)) == (885, 685):
            self.menu_open = False


class QuickActionMenuTests(unittest.TestCase):
    def test_clicks_with_quick_action_region_and_confirms_closed(self):
        eng = _FakeEngine(menu_open=True, close_on_click=True)
        self.assertTrue(close_quick_action_menu(eng, img=object()))
        locates = [c for c in eng.calls if c[0] == "locate"]
        self.assertTrue(
            any(c[1] == ("快捷操作",) and tuple(c[2] or ()) == tuple(QUICK_ACTION_REGION)
                for c in locates),
            f"未按 QUICK_ACTION_REGION 定位: {locates}")
        clicks = [c for c in eng.calls if c[0] == "click_abs"]
        self.assertEqual(clicks, [("click_abs", 885, 685)])

    def test_returns_false_when_click_swallowed_without_retry(self):
        # 2026-11-18 实机: 点击命中后 1.5s 菜单仍在屏(可能被吞) -> 如实 False, 不重试
        eng = _FakeEngine(menu_open=True, close_on_click=False)
        self.assertFalse(close_quick_action_menu(eng, img=object()))
        clicks = [c for c in eng.calls if c[0] == "click_abs"]
        self.assertEqual(len(clicks), 1, "只允许一次点击, 防把刚关上的菜单又点开")

    def test_no_click_when_menu_not_open(self):
        eng = _FakeEngine(menu_open=False)
        self.assertFalse(close_quick_action_menu(eng, img=object()))
        self.assertFalse([c for c in eng.calls if c[0] == "click_abs"])

    def test_region_covers_button_and_excludes_social_area(self):
        x1, _, x2, _ = QUICK_ACTION_REGION
        button_rel = 885 / 1280          # 实测「快捷操作」中心
        social_rel = 423 / 1280          # 实测「社交」中心
        self.assertLess(x1, button_rel)
        self.assertGreater(x2, button_rel)
        self.assertGreater(x1, social_rel)   # 不再复用社交区


if __name__ == "__main__":
    unittest.main()
