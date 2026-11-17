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
        used = {k for keys in schema.MODULE_SETTINGS.values() for k in keys}
        self.assertEqual(meta, used)

    def test_file_only_keys_not_settable(self):
        for key in ("baobao_buy_floor", "baobao_buy_max", "guard_reuse", "region_ocr"):
            self.assertIn(key, schema.ALL_KEYS)
            self.assertNotIn(key, schema.SETTABLE_KEYS)
        self.assertIn("finish_action", schema.SETTABLE_KEYS)

    def test_flow_keys_are_defined(self):
        unknown = _flow_keys() - set(schema.ALL_KEYS)
        self.assertFalse(unknown, f"flow 使用未定义键: {sorted(unknown)}")


if __name__ == "__main__":
    unittest.main()
