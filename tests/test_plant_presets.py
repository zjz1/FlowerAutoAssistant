# -*- coding: utf-8 -*-
"""种植增强（2026-11-20）：种子数据库、名称校验、数量计算（fixed/auto/360）。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import plant


class SeedDatabaseTests(unittest.TestCase):
    def setUp(self):
        plant.reload_presets()

    def tearDown(self):
        plant.reload_presets()

    def test_shipped_db_has_three_peach_colors(self):
        lib = plant.seed_library()
        self.assertEqual(set(lib), {"白色桃花", "粉色桃花", "绿色桃花"})
        for info in lib.values():
            self.assertEqual(info["cost"], 2)
            self.assertEqual(info["flower"], "桃花")
        self.assertTrue(lib["绿色桃花"]["rare"])
        self.assertFalse(lib["白色桃花"]["rare"])
        self.assertFalse(lib["粉色桃花"]["rare"])

    def test_resolve_accepts_alias_and_suffix(self):
        self.assertEqual(plant.resolve_seed_name("桃花")[2], "白色桃花")
        self.assertEqual(plant.resolve_seed_name("")[2], "白色桃花")
        self.assertEqual(plant.resolve_seed_name("白色桃花种子")[2], "白色桃花")
        self.assertEqual(plant.resolve_seed_name("粉色桃花花种")[2], "粉色桃花")

    def test_resolve_rejects_unknown_or_wrong_color(self):
        for raw in ("蓝色桃花", "白色铃兰", "绿色铃兰"):
            ok, msg, seed = plant.resolve_seed_name(raw)
            self.assertFalse(ok, raw)
            self.assertIsNone(seed)
            self.assertIn("不在种子库", msg)

    def test_missing_or_broken_db_raises_actionable_error(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "plant_presets.json"
            bad.write_text('{"flowers": []}', encoding="utf-8")
            plant.reload_presets()
            with mock.patch.object(plant, "PLANT_PRESETS_PATH", bad):
                with self.assertRaises(ValueError) as ctx:
                    plant.load_presets()
                self.assertIn("flowers", str(ctx.exception))
            plant.reload_presets()

    def test_duplicate_seed_rejected(self):
        data = {"flowers": [{"name": "桃花", "colors": [
            {"name": "白色", "seed": "白色桃花", "cost": 2},
            {"name": "白色2", "seed": "白色桃花", "cost": 2},
        ]}]}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "plant_presets.json"
            p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            plant.reload_presets()
            with mock.patch.object(plant, "PLANT_PRESETS_PATH", p):
                with self.assertRaises(ValueError) as ctx:
                    plant.load_presets()
                self.assertIn("种子重复", str(ctx.exception))
            plant.reload_presets()

    def test_cost_out_of_range_rejected(self):
        data = {"flowers": [{"name": "桃花", "colors": [
            {"name": "白色", "seed": "白色桃花", "cost": 3},
        ]}]}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "plant_presets.json"
            p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            plant.reload_presets()
            with mock.patch.object(plant, "PLANT_PRESETS_PATH", p):
                with self.assertRaises(ValueError) as ctx:
                    plant.load_presets()
                self.assertIn("0~2", str(ctx.exception))
            plant.reload_presets()


class TargetCountTests(unittest.TestCase):
    """compute_target_count：fixed clamp / auto 肥力+槽位+库存 / 360 上限 / 稀有。"""

    def test_fixed_clamps_to_1_360(self):
        self.assertEqual(plant.compute_target_count("fixed", 3, n=0, plantable=58,
                                                    fertility=120, cost=2), 3)
        self.assertEqual(plant.compute_target_count("fixed", 0, n=0, plantable=58,
                                                    fertility=120, cost=2), 1)
        self.assertEqual(plant.compute_target_count("fixed", 9999, n=0, plantable=58,
                                                    fertility=120, cost=2), 360)

    def test_auto_without_buy_capped_by_stock(self):
        self.assertEqual(plant.compute_target_count(
            "auto", 1, n=5, plantable=58, fertility=120, cost=2, auto_buy=False), 5)
        self.assertEqual(plant.compute_target_count(
            "auto", 1, n=0, plantable=58, fertility=120, cost=2, auto_buy=False), 0)

    def test_auto_with_buy_ignores_stock(self):
        # min(槽位 58, 360, 肥力 120/2=60) = 58
        self.assertEqual(plant.compute_target_count(
            "auto", 1, n=0, plantable=58, fertility=120, cost=2, auto_buy=True), 58)

    def test_auto_fertility_limit(self):
        # min(58, 360, 3//2=1) = 1
        self.assertEqual(plant.compute_target_count(
            "auto", 1, n=0, plantable=58, fertility=3, cost=2, auto_buy=True), 1)
        self.assertEqual(plant.compute_target_count(
            "auto", 1, n=10, plantable=58, fertility=0, cost=2, auto_buy=True), 0)

    def test_auto_cost_zero_has_no_fertility_limit(self):
        self.assertEqual(plant.compute_target_count(
            "auto", 1, n=0, plantable=999, fertility=0, cost=0, auto_buy=True), 360)

    def test_auto_360_cap(self):
        self.assertEqual(plant.compute_target_count(
            "auto", 1, n=0, plantable=999, fertility=10000, cost=2, auto_buy=True), 360)

    def test_rare_forces_stock_cap_even_with_buy(self):
        # 稀有种子不可购买：即使 auto_buy=True 也只按现有库存
        self.assertEqual(plant.compute_target_count(
            "auto", 1, n=4, plantable=58, fertility=120, cost=2,
            auto_buy=True, rare=True), 4)


class HarvestDecisionTests(unittest.TestCase):
    """收获判定：P ⊆ A 才收花；稀有强制受保护；读取失败由调用方保守跳过。"""

    def test_all_pending_allowed(self):
        ok, protected = plant.decide_harvest(
            {"白色桃花", "粉色桃花"}, ["白色桃花", "粉色桃花"])
        self.assertTrue(ok)
        self.assertEqual(protected, [])

    def test_any_protected_skips(self):
        ok, protected = plant.decide_harvest(
            {"白色桃花", "绿色桃花"}, ["白色桃花", "粉色桃花"],
            rare={"绿色桃花"})
        self.assertFalse(ok)
        self.assertEqual(protected, ["绿色桃花"])

    def test_rare_forced_protected_even_if_listed(self):
        ok, protected = plant.decide_harvest(
            {"绿色桃花"}, ["白色桃花", "粉色桃花", "绿色桃花"],
            rare={"绿色桃花"})
        self.assertFalse(ok)
        self.assertEqual(protected, ["绿色桃花"])

    def test_empty_pending_allows_harvest(self):
        ok, protected = plant.decide_harvest(set(), ["白色桃花"])
        self.assertTrue(ok)
        self.assertEqual(protected, [])

    def test_match_full_and_split_names(self):
        self.assertEqual(plant._match_seed_names(["白色桃花"]), {"白色桃花"})
        self.assertEqual(plant._match_seed_names(["粉色", "桃花"]), {"粉色桃花"})
        self.assertEqual(plant._match_seed_names(["待授粉", "绿色桃花"]), {"绿色桃花"})
        self.assertIsNone(plant._match_seed_names(["待授粉", "未知花朵"]))


class PlantTargetGuardTests(unittest.TestCase):
    """实机 2026-11-21：花园已满/肥力不足/无库存时跳过种植，不产生假失败。"""

    def setUp(self):
        plant.reload_presets()

    def tearDown(self):
        plant.reload_presets()

    @staticmethod
    def _target():
        return plant.PlantTarget(seed="白色桃花", detail="白色桃花花种",
                                 search_kw="桃花", cost=2)

    def _run(self, base, grid):
        eng = type("_Eng", (), {})()
        with mock.patch.object(plant, "read_panel_info", return_value=base), \
             mock.patch.object(plant, "_find_grid_seed", return_value=grid) as fg, \
             mock.patch.object(plant, "_choose_quantity") as cq:
            ok = plant._plant_target(
                eng, self._target(), plant.PlantOptions(count_mode="fixed", count=1),
                {"opened": True})
        return ok, fg, cq

    def test_full_garden_skips_before_seed_grid(self):
        ok, fg, cq = self._run({"plantable_total": 0, "fertility_remaining": 358}, (object(), 311))
        self.assertTrue(ok)
        fg.assert_not_called()
        cq.assert_not_called()

    def test_fertility_shortage_skips(self):
        ok, fg, cq = self._run({"plantable_total": 5, "fertility_remaining": 1}, (object(), 311))
        self.assertTrue(ok)
        fg.assert_not_called()
        cq.assert_not_called()

    def test_zero_stock_without_buy_skips(self):
        ok, _fg, cq = self._run({"plantable_total": 5, "fertility_remaining": 358}, (object(), 0))
        self.assertTrue(ok)
        cq.assert_not_called()


if __name__ == "__main__":
    unittest.main()
