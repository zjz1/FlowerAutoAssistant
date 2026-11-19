# -*- coding: utf-8 -*-
"""1.0 #7: 首次运行自动从 config.example.json 生成 config.json。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ocr_engine.engine._config import _ConfigMixin


class _FakeConfig(_ConfigMixin):
    pass


class ConfigFirstRunTests(unittest.TestCase):
    def test_copies_example_when_config_missing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            example = root / "config.example.json"
            example.write_text('{"target_tail": "12", "claim_online": true}', encoding="utf-8")
            cfg_path = root / "config.json"
            import ocr_engine.engine._config as mod
            with mock.patch.object(mod, "CONFIG_PATH", cfg_path):
                cfg = _FakeConfig()._load_config()
            self.assertTrue(cfg_path.exists())
            self.assertEqual(cfg["target_tail"], "12")
            self.assertTrue(cfg["claim_online"])

    def test_missing_example_keeps_empty_config(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cfg_path = root / "config.json"
            import ocr_engine.engine._config as mod
            with mock.patch.object(mod, "CONFIG_PATH", cfg_path):
                cfg = _FakeConfig()._load_config()
            self.assertEqual(cfg, {})
            self.assertFalse(cfg_path.exists())

    def test_existing_config_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            example = root / "config.example.json"
            example.write_text('{"target_tail": "99"}', encoding="utf-8")
            cfg_path = root / "config.json"
            cfg_path.write_text('{"target_tail": "12"}', encoding="utf-8")
            import ocr_engine.engine._config as mod
            with mock.patch.object(mod, "CONFIG_PATH", cfg_path):
                cfg = _FakeConfig()._load_config()
            self.assertEqual(json.loads(cfg_path.read_text(encoding="utf-8"))["target_tail"], "12")
            self.assertEqual(cfg["target_tail"], "12")


if __name__ == "__main__":
    unittest.main()
