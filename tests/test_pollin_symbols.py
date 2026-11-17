# -*- coding: utf-8 -*-
"""pollin facade 契约：Stage 5 分包后旧公共符号仍可从 `import pollin` 取得。"""
from __future__ import annotations

import unittest
from pathlib import Path

import pollin

ROOT = Path(__file__).resolve().parents[1]


class PollinSymbolTests(unittest.TestCase):
    def test_public_entrypoints_exist(self):
        expected = {
            "run_friend_pollin", "ensure_home", "run_category", "collect_one",
            "open_friend_list", "dismiss_no_pollen_popup", "scan_marks",
            "save_escape_evidence", "at_home_main", "in_list", "in_garden",
            "social_usable", "leave_garden", "leave_friend_list",
            "click_top_right_close", "click_btn_fine", "has_social",
            "read_page", "read_total", "goto_page", "switch_tab", "slot_of",
            "dismiss_reward_popup", "escape_overlay", "frame_diff",
            "wait_until", "wait_screen_change", "wait_stable",
            "wait_enter_garden", "adb_text", "adb_key",
            "close_quick_action_menu",
        }
        missing = sorted(name for name in expected if not hasattr(pollin, name))
        self.assertFalse(missing, f"pollin facade 缺少公共符号: {missing}")

    def test_constants_still_exported(self):
        for name in ("TPL_GREEN", "GREEN_TH", "TAB_REGION", "CATEGORIES",
                     "SAFE_SLOT_MAX", "CORNER_CLOSE_TEMPLATES", "NO_POLLEN_KWS"):
            self.assertTrue(hasattr(pollin, name), name)

    def test_root_module_is_thin_shim(self):
        lines = (ROOT / "pollin.py").read_text(encoding="utf-8").splitlines()
        self.assertLess(len(lines), 30, "pollin.py 应保持为兼容 shim")

    def test_package_submodules_exist(self):
        pkg = ROOT / "pollin"
        for name in ("constants", "primitives", "popups", "navigation",
                     "list_panel", "collect", "runner"):
            self.assertTrue((pkg / f"{name}.py").exists(), name)


if __name__ == "__main__":
    unittest.main()
