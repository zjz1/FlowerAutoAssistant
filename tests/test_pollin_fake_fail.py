# -*- coding: utf-8 -*-
"""采粉 5s 超时假 fail 修复（2026-11-18）离线回归。

实机证据：点采粉后 5s 帧差超时被判 fail，但下一步 open_friend_list 立即发现
「没有花粉」提示框 —— 小/半透明弹窗的帧差可能低于 0.02，或弹窗晚于窗口出现。
"""
from __future__ import annotations

import unittest
from unittest import mock

from pollin import collect as collect_mod


class NoPollenAfterTimeoutTests(unittest.TestCase):
    def test_popup_on_screen_is_reclassified_as_empty(self):
        with mock.patch.object(collect_mod, "no_pollen_popup", return_value=True) as popup, \
                mock.patch.object(collect_mod, "dismiss_no_pollen_popup") as dismiss:
            self.assertTrue(collect_mod._no_pollen_after_timeout(object(), object()))
        popup.assert_called_once()
        dismiss.assert_called_once()

    def test_no_popup_stays_fail_without_click(self):
        with mock.patch.object(collect_mod, "no_pollen_popup", return_value=False), \
                mock.patch.object(collect_mod, "dismiss_no_pollen_popup") as dismiss:
            self.assertFalse(collect_mod._no_pollen_after_timeout(object(), object()))
        dismiss.assert_not_called()


class _FakeEng:
    screen_w = 1280
    screen_h = 720

    def __init__(self):
        self.scenes = []

    def screenshot(self):
        return object()

    def set_scene(self, name):
        self.scenes.append(name)

    def click_abs(self, x, y):
        pass


class CollectOneTimeoutTests(unittest.TestCase):
    def test_timeout_with_popup_returns_empty(self):
        """5s 帧差超时 + 弹窗在屏 -> collect_one 返回 empty(不再误记 fail)。"""
        eng = _FakeEng()
        with mock.patch.object(collect_mod, "in_garden", return_value=True), \
                mock.patch.object(collect_mod, "click_btn_fine"), \
                mock.patch.object(collect_mod, "wait_until", side_effect=[True, False]), \
                mock.patch.object(collect_mod, "_no_pollen_after_timeout", return_value=True) as popup, \
                mock.patch.object(collect_mod, "close_quick_action_menu"), \
                mock.patch.object(collect_mod, "dismiss_reward_popup"), \
                mock.patch.object(collect_mod, "has", return_value=True):
            self.assertEqual(collect_mod.collect_one(eng, 987, 196), "empty")
        popup.assert_called_once()


if __name__ == "__main__":
    unittest.main()
