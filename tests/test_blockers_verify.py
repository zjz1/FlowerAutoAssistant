# -*- coding: utf-8 -*-
"""1.0 #10/#11: 阻断层注册表 + 动作结果校验（verify_action）。

- blockers.json 是数据契约（新增弹窗只加数据）→ 先校验数据本身；
- detect_blocker 一次 OCR 匹配全部条目（exact/exclude 语义）；
- dismiss_blocker 策略分派复用既有原语；
- classify_action 五分类：failed / empty / blocker / changed / no_change；
- _finish_click 只让 no_change 否决战果（failed 不否决点击本身）。
"""
from __future__ import annotations

import unittest

import numpy as np

from ocr_engine._geometry import Point
from ocr_engine.engine._blockers import _BlockersMixin
from ocr_engine.engine._guard import _GuardMixin
from ocr_engine.engine._verify import _VerifyMixin

KNOWN_STRATEGIES = {"reward_dialog", "click_text", "close_dialog"}


def _block(text: str, center=(640, 360)) -> dict:
    return {"text": text, "center": center, "score": 0.9}


class _BlockersStub(_BlockersMixin):
    """真实注册表 + 桩 OCR；dismiss 走真实策略分派，点击原语记录调用。"""

    def __init__(self, texts):
        self.blocks = [_block(t) for t in texts]
        self.reward_calls = []
        self.click_calls = []
        self.close_calls = []

    def _ocr_candidates(self, img, region_rel=None, need_refine=False):
        return list(self.blocks), [], None

    def screenshot(self):
        return object()

    def reward_dialog(self, step):
        self.reward_calls.append(step)
        return True

    def click_text(self, keywords, **kwargs):
        self.click_calls.append((keywords, kwargs))
        return True

    def close_dialog(self, **kwargs):
        self.close_calls.append(kwargs)
        return True


class BlockerRegistryTests(unittest.TestCase):
    def test_shipped_registry_is_valid_and_covers_four_classes(self):
        stub = _BlockersStub([])
        entries = stub._load_blockers()
        ids = [e["id"] for e in entries]
        self.assertGreaterEqual(len(entries), 4)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("level_up", ids)
        self.assertIn("reward_common", ids)
        self.assertIn("resource_update", ids)
        self.assertIn("notice_prompt", ids)
        for e in entries:
            self.assertTrue(e.get("match", {}).get("any"), e["id"])
            self.assertIn(e.get("dismiss", {}).get("strategy"), KNOWN_STRATEGIES, e["id"])

    def test_detect_matches_each_class(self):
        cases = {
            "等级提升": "level_up",
            "恭喜获得": "reward_common",
            "有需要更新的内容，共57个": "resource_update",
            "提示": "notice_prompt",
            "点击任意处关闭": "reward_footer",
        }
        for text, expected in cases.items():
            info = _BlockersStub([text]).detect_blocker()
            self.assertIsNotNone(info, text)
            self.assertEqual(info["id"], expected, text)
            self.assertIsInstance(info["pt"], Point)

    def test_detect_exact_and_exclude(self):
        self.assertIsNone(_BlockersStub(["温馨提示"]).detect_blocker())
        self.assertIsNone(_BlockersStub(["提示：请稍候"]).detect_blocker())  # exact
        self.assertIsNone(_BlockersStub(["普通文字"]).detect_blocker())

    def test_dismiss_strategies_dispatch(self):
        stub = _BlockersStub(["等级提升"])
        self.assertTrue(stub.dismiss_blocker(stub.detect_blocker()))
        self.assertEqual(stub.reward_calls[0]["tries"], 2)

        stub = _BlockersStub(["有需要更新的内容"])
        self.assertTrue(stub.dismiss_blocker(stub.detect_blocker()))
        self.assertEqual(stub.click_calls[0][0], ["确定"])

        stub = _BlockersStub(["提示"])
        self.assertTrue(stub.dismiss_blocker(stub.detect_blocker()))
        self.assertEqual(stub.close_calls[0]["only_types"], ["anchor_color"])

    def test_clear_blockers_stops_when_closed(self):
        stub = _BlockersStub(["等级提升"])

        def _dismiss(info):
            stub.blocks = []      # 关闭后画面干净
            return True

        stub.dismiss_blocker = _dismiss
        handled = stub.clear_blockers()
        self.assertEqual([x["id"] for x in handled], ["level_up"])
        self.assertTrue(handled[0]["ok"])

    def test_clear_blockers_stops_on_failure(self):
        stub = _BlockersStub(["等级提升"])
        stub.dismiss_blocker = lambda info: False
        handled = stub.clear_blockers()
        self.assertEqual(len(handled), 1)
        self.assertFalse(handled[0]["ok"])


class _VerifyStub(_VerifyMixin):
    def __init__(self, texts=None, blocker=None):
        self.blocks = [_block(t) for t in (texts or [])]
        self.blocker = blocker

    def _ocr_candidates(self, img, region_rel=None, need_refine=False):
        return list(self.blocks), [], None

    def detect_blocker(self, img=None):
        return self.blocker

    def screenshot(self):
        return None


def _frame(fill: int = 0):
    return np.full((720, 1280, 3), fill, np.uint8)


class VerifyActionTests(unittest.TestCase):
    def test_frame_diff_ratio(self):
        stub = _VerifyStub()
        a = _frame(0)
        self.assertEqual(stub.frame_diff_ratio(a, a.copy()), 0.0)
        b = a.copy()
        b[:, :640] = 255
        self.assertGreater(stub.frame_diff_ratio(a, b), 0.3)
        self.assertIsNone(stub.frame_diff_ratio(a, None))
        self.assertIsNone(stub.frame_diff_ratio(a, np.zeros((100, 100, 3), np.uint8)))

    def test_classify_failed_when_frame_missing(self):
        out = _VerifyStub().classify_action(None, _frame())
        self.assertEqual(out["result"], "failed")

    def test_classify_empty_beats_blocker(self):
        stub = _VerifyStub(texts=["没有花粉"], blocker={"id": "reward_common", "name": "x"})
        out = stub.classify_action(_frame(), _frame(), empty_keywords=["没有花粉"])
        self.assertEqual(out["result"], "empty")

    def test_classify_blocker(self):
        stub = _VerifyStub(blocker={"id": "level_up", "name": "等级提升"})
        out = stub.classify_action(_frame(), _frame())
        self.assertEqual(out["result"], "blocker")
        self.assertEqual(out["blocker"], "level_up")

    def test_classify_expected_keyword_is_changed(self):
        stub = _VerifyStub(texts=["点击进入游戏"])
        out = stub.classify_action(_frame(), _frame(), expected_keywords=["点击进入游戏"])
        self.assertEqual(out["result"], "changed")

    def test_classify_no_change_vs_changed(self):
        stub = _VerifyStub()
        self.assertEqual(stub.classify_action(_frame(0), _frame(1))["result"], "no_change")
        b = _frame(0)
        b[:, :] = 255
        self.assertEqual(stub.classify_action(_frame(0), b)["result"], "changed")

    def test_finish_click_only_no_change_vetoes(self):
        class _ClickStub(_GuardMixin):
            def __init__(self, result):
                self.result = result

            def verify_action(self, before, wait=0.8, **kwargs):
                return {"result": self.result, "diff": 0.0, "blocker": None}

        pt = Point(1, 2, 1280, 720)
        self.assertFalse(_ClickStub("no_change")._finish_click(True, object(), ["a"], pt))
        for ok in ("changed", "failed", "empty", "blocker"):
            self.assertTrue(_ClickStub(ok)._finish_click(True, object(), ["a"], pt), ok)
        # verify=False: 不校验、直接保持原语义
        self.assertTrue(_ClickStub("no_change")._finish_click(False, None, ["a"], pt))


if __name__ == "__main__":
    unittest.main()
