# -*- coding: utf-8 -*-
"""P0/P1 纯函数基线：花种解析、详情字段、二次确认按钮、权威价格。"""
from __future__ import annotations

import unittest

import buy_seed
import plant
from tests.fake_engine import FakeEngine, block


class PlantResolveTests(unittest.TestCase):
    def test_default_peach(self):
        self.assertEqual(plant._resolve_seed("桃花").seed, "白色桃花")
        self.assertEqual(plant._resolve_seed("").seed, "白色桃花")

    def test_explicit_variants(self):
        self.assertEqual(plant._resolve_seed("白色桃花").seed, "白色桃花")
        self.assertEqual(plant._resolve_seed("粉色桃花").seed, "粉色桃花")
        self.assertEqual(plant._resolve_seed("白色桃花种子").seed, "白色桃花")

    def test_search_keyword_is_base_flower(self):
        self.assertEqual(plant._resolve_seed("粉色桃花").search_kw, "桃花")

    def test_unsupported_returns_none(self):
        self.assertIsNone(plant._resolve_seed("白色铃兰"))

    def test_calibrated_cost(self):
        # 2026-11-20: 桃花三色肥力消耗均确认为 2（数据库 cost_source=confirmed）
        self.assertEqual(plant._resolve_seed("白色桃花").cost, 2)
        self.assertEqual(plant._resolve_seed("粉色桃花").cost, 2)
        self.assertEqual(plant._resolve_seed("绿色桃花").cost, 2)

    def test_rare_flag(self):
        self.assertFalse(plant._resolve_seed("白色桃花").rare)
        self.assertFalse(plant._resolve_seed("粉色桃花").rare)
        self.assertTrue(plant._resolve_seed("绿色桃花").rare)


class BuySeedHelperTests(unittest.TestCase):
    def test_norm_text(self):
        self.assertEqual(buy_seed._norm_text(" 白色：铃兰·种子 "), "白色铃兰种子")

    def test_detail_name_requires_exact_match(self):
        eng = FakeEngine()
        detail = {"texts": ["白色铃兰种子", "已拥有：152"]}
        self.assertTrue(buy_seed._verify_detail_name(eng, "白色铃兰种子", detail))
        self.assertFalse(buy_seed._verify_detail_name(eng, "铃兰种子", detail))

    def test_owned_only_same_row(self):
        eng = FakeEngine(screen_h=1080)
        blocks = [
            block("已拥有", 100, 100),
            block("152", 150, 102),
            block("69", 150, 160),   # 下一行「消耗」，不能取
        ]
        self.assertEqual(buy_seed._owned_from_blocks(eng, blocks), 152)

    def test_cost_from_anchor_row(self):
        eng = FakeEngine(screen_h=1080)
        blocks = [
            block("已拥有", 100, 100),
            block("152", 150, 102),
            block("消耗", 100, 130),
            block("6", 150, 132),
        ]
        self.assertEqual(buy_seed._cost_from_blocks(eng, blocks), 6)

    def test_parse_confirm_price(self):
        self.assertEqual(buy_seed._parse_confirm_price(["确定要花费0仙豆"]), 0)
        self.assertEqual(buy_seed._parse_confirm_price(["确定要花费O仙豆"]), 0)
        self.assertEqual(buy_seed._parse_confirm_price(["确定要花费6仙豆"]), 6)
        self.assertIsNone(buy_seed._parse_confirm_price(["购买1个白色铃兰种子吗？"]))

    def test_pick_confirm_excludes_sentence_and_takes_rightmost(self):
        blocks = [
            block("确定要花费0仙豆", 639, 296),
            block("确定", 700, 470),
            block("确定", 776, 470),
        ]
        btn = buy_seed._pick_confirm_button(blocks)
        self.assertIsNotNone(btn)
        self.assertEqual(btn["center"][0], 776)

    def test_pick_confirm_none_when_only_sentence(self):
        blocks = [block("确定要花费0仙豆", 639, 296)]
        self.assertIsNone(buy_seed._pick_confirm_button(blocks))


if __name__ == "__main__":
    unittest.main()
