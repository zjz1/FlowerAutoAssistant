# -*- coding: utf-8 -*-
"""配置契约基线：flow 的 if_config 键必须存在于 config.example.json。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def flow_config_keys():
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


class ConfigContractTests(unittest.TestCase):
    def test_flow_keys_exist_in_example(self):
        example = json.loads((ROOT / "data" / "config.example.json").read_text(encoding="utf-8"))
        example_keys = {k for k in example if not k.startswith("_")}
        missing = flow_config_keys() - example_keys
        self.assertFalse(missing, f"config.example.json 缺键: {sorted(missing)}")

    def test_new_module_keys_present(self):
        example = json.loads((ROOT / "data" / "config.example.json").read_text(encoding="utf-8"))
        for key in ("plant_flower", "plant_flower_type", "plant_harvest",
                    "plant_pollinate", "plant_buy_seed", "claim_fairyland"):
            self.assertIn(key, example, f"config.example.json 缺 {key}")


if __name__ == "__main__":
    unittest.main()
