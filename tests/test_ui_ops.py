# -*- coding: utf-8 -*-
"""通用 UI 原语基线：文本清洗、输入框三态聚焦、奖励弹窗关闭。"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import ui_ops
from tests.fake_engine import FakeEngine, block, point

REGION = [0.10, 0.10, 0.50, 0.20]


class UiOpsTests(unittest.TestCase):
    def test_texts_strips(self):
        self.assertEqual(ui_ops.texts([block(" 甲 "), block("乙")]), ["甲", "乙"])

    def test_focus_input_placeholder(self):
        eng = FakeEngine(click_text_result=True)
        self.assertTrue(ui_ops.focus_input(eng, REGION))
        self.assertEqual(eng.calls[0][0], "click_text")

    def test_focus_input_existing_text(self):
        eng = FakeEngine(click_text_result=False,
                         blocks={tuple(REGION): [block("旧关键字", 20, 30)]})
        self.assertTrue(ui_ops.focus_input(eng, REGION))
        self.assertIn(("click_abs", 20, 30), eng.calls)

    def test_focus_input_anchor_fallback(self):
        eng = FakeEngine(click_text_result=False,
                         blocks={tuple(REGION): []},
                         locate_results={"购买工具": point(100, 200)})
        self.assertTrue(ui_ops.focus_input(
            eng, REGION, anchor="购买工具",
            anchor_region=[0.0, 0.0, 0.3, 0.3],
            from_anchor_rel=[0.1, 0.02]))
        self.assertIn(("click_abs", 292, 221), eng.calls)

    def test_focus_input_not_found(self):
        eng = FakeEngine(click_text_result=False, blocks={})
        self.assertFalse(ui_ops.focus_input(eng, REGION))

    @patch("ui_ops.time.sleep", return_value=None)
    def test_close_reward_first_keyword(self, _sleep):
        eng = FakeEngine(click_text_result=True)
        self.assertTrue(ui_ops.close_reward_popup(eng, ("恭喜获得", "点击任意处关闭")))
        self.assertEqual(eng.calls[0][0], "click_text")

    @patch("ui_ops.time.sleep", return_value=None)
    def test_close_reward_fallback_close_dialog(self, _sleep):
        eng = FakeEngine(click_text_result=False)
        self.assertTrue(ui_ops.close_reward_popup(eng, ("恭喜获得",)))
        self.assertIn(("close_dialog",), eng.calls)

    @patch("ui_ops.time.sleep", return_value=None)
    def test_close_reward_confirm(self, _sleep):
        eng = FakeEngine(click_text_result=True,
                         blocks={None: [block("提示"), block("确定")]})
        self.assertTrue(ui_ops.close_reward_popup(
            eng, ("恭喜获得", "点击任意处关闭"), confirm=True))
        self.assertEqual(eng.calls[0][0], "click_text")


if __name__ == "__main__":
    unittest.main()
