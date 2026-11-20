# -*- coding: utf-8 -*-
"""配置 schema 基线：示例配置、面板归属、文件级键、流程键。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from config import schema

ROOT = Path(__file__).resolve().parents[1]


def _flow_keys():
    keys = set()

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            if node.get("type") == "if_config" and isinstance(node.get("key"), str):
                keys.add(node["key"])
            for v in node.values():
                if isinstance(v, (list, dict)):
                    walk(v)

    for f in (ROOT / "flows").rglob("*.json"):
        walk(json.loads(f.read_text(encoding="utf-8")))
    return keys


class ConfigSchemaTests(unittest.TestCase):
    def test_example_matches_schema(self):
        data = json.loads((ROOT / "data" / "config.example.json").read_text(encoding="utf-8"))
        self.assertEqual(schema.validate_example(data), [])

    def test_example_config_order_and_defaults(self):
        cfg = schema.example_config()
        self.assertEqual(tuple(cfg), schema.EXAMPLE_ORDER)
        for key, value in cfg.items():
            self.assertEqual(value, schema.DEFAULTS[key], key)

    def test_module_settings_cover_meta_exactly(self):
        meta = {k for k, spec in schema.CONFIG_KEYS.items() if spec.get("meta")}
        meta -= set(schema.SETTINGS_PAGE_KEYS)
        used = {k for keys in schema.MODULE_SETTINGS.values() for k in keys}
        self.assertEqual(meta, used)

    def test_file_only_keys_not_settable(self):
        for key in ("schema_version", "baobao_buy_floor", "baobao_buy_max",
                    "guard_reuse", "region_ocr"):
            self.assertIn(key, schema.ALL_KEYS)
            self.assertNotIn(key, schema.SETTABLE_KEYS)
        self.assertIn("finish_action", schema.SETTABLE_KEYS)

    def test_minimize_to_tray_default_off(self):
        # 2026-11-19: WPF 设置页开关，默认关闭（最小化保留在任务栏）
        self.assertIn("minimize_to_tray", schema.SETTABLE_KEYS)
        self.assertFalse(schema.default_for("minimize_to_tray"))

    def test_flow_keys_are_defined(self):
        unknown = _flow_keys() - set(schema.ALL_KEYS)
        self.assertFalse(unknown, f"flow 使用未定义键: {sorted(unknown)}")


class ConfigMigrationTests(unittest.TestCase):
    """1.0 #13: 旧配置升级只补不改不删，且幂等。"""

    def test_missing_keys_filled_version_bumped(self):
        old = {"target_tail": "61", "_my_note": "keep me", "unknown_future_key": 7}
        new, notes = schema.migrate_config(old)
        self.assertTrue(notes)
        self.assertEqual(new["schema_version"], schema.CONFIG_SCHEMA_VERSION)
        self.assertEqual(new["target_tail"], "61")             # 已有值不覆盖
        self.assertEqual(new["_my_note"], "keep me")           # 注释键保留
        self.assertEqual(new["unknown_future_key"], 7)         # 未知键保留
        for key in schema.EXAMPLE_ORDER:                        # 缺失键补齐
            self.assertIn(key, new)
        self.assertEqual(schema.validate_config(new), [])

    def test_idempotent(self):
        cfg = schema.example_config()
        new, notes = schema.migrate_config(cfg)
        self.assertEqual(notes, [])
        self.assertEqual(new, cfg)

    def test_newer_version_not_downgraded(self):
        old = {"schema_version": schema.CONFIG_SCHEMA_VERSION + 1, "target_tail": "12"}
        new, notes = schema.migrate_config(old)
        self.assertTrue(notes)
        self.assertEqual(new["schema_version"], schema.CONFIG_SCHEMA_VERSION + 1)
        self.assertNotIn("claim_online", new)   # 不按旧 schema 猜测补键

    def test_validate_config_rejects_wrong_type_but_allows_unknown(self):
        bad = {"claim_online": "yes", "whatever": 1}
        self.assertTrue(schema.validate_config(bad))
        self.assertEqual(schema.validate_config({"claim_online": True, "whatever": 1}), [])


if __name__ == "__main__":
    unittest.main()
