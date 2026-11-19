# -*- coding: utf-8 -*-
"""升级/解锁全屏弹窗（等级提升 + 点击任意处关闭）处理回归。

2026-11-19 实机日志：claim 领取时间礼包后弹出「等级提升 / 147→148 / 已全部解锁 /
点击任意处关闭」全屏覆盖层。旧 reward_dialog 无「恭喜获得」标题，落到页脚文字
(640,676) 点击穿透；claim/daily 连续空转直至软失败。
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from ocr_engine.engine._closebtn import _CloseButtonMixin
from ocr_engine.engine._reward import _RewardMixin


class _RewardFake(_RewardMixin):
    def __init__(self, points):
        self.screen_w = 1280
        self.screen_h = 720
        self.config = {}
        self.points = points
        self.calls = []

    def screenshot(self):
        return object()

    def locate(self, texts, **kwargs):
        self.calls.append((tuple(texts), kwargs))
        for t in texts:
            if t in self.points:
                return self.points[t]
        return None


class _CloseFake(_CloseButtonMixin):
    def __init__(self, has_reward=True, closed=True):
        self.screen_w = 1280
        self.screen_h = 720
        self.config = {}
        self._has_reward = has_reward
        self._closed = closed
        self.reward_calls = []

    def screenshot(self):
        return object()

    def find_all_close_buttons(self, img=None, only_types=None):
        return []

    def has_reward_popup(self, img=None, region_rel=None, keywords=None):
        return self._has_reward

    def reward_dialog(self, step):
        self.reward_calls.append(step)
        return self._closed


class UpgradeOverlayTests(unittest.TestCase):
    def test_reward_popup_prefers_levelup_title_over_footer(self):
        eng = _RewardFake({
            "等级提升": SimpleNamespace(x=642, y=159),
            "点击任意处关闭": SimpleNamespace(x=640, y=676),
        })
        self.assertTrue(eng.has_reward_popup(img=object()))
        pt = eng._reward_popup_point(img=object())
        self.assertIsNotNone(pt)
        self.assertEqual((pt.x, pt.y), (642, 159), "应优先点标题(弹窗内部), 不点页脚防穿透")

    def test_close_dialog_falls_back_to_reward_overlay(self):
        eng = _CloseFake(has_reward=True, closed=True)
        self.assertTrue(eng.close_dialog(img=object()))
        self.assertEqual(len(eng.reward_calls), 1)
        self.assertEqual(eng.reward_calls[0]["name"], "全屏覆盖层")

    def test_close_dialog_returns_false_without_reward_overlay(self):
        eng = _CloseFake(has_reward=False)
        self.assertFalse(eng.close_dialog(img=object()))
        self.assertFalse(eng.reward_calls)


if __name__ == "__main__":
    unittest.main()
