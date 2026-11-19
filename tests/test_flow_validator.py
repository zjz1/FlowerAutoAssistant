# -*- coding: utf-8 -*-
"""flow 结构校验器用例（1.0 #12 / tools/check_project.py:check_flow_struct）。

用临时目录替换闸门的 FLOWS_DIR，验证坏 flow 会被拒、现有规则不误伤。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import check_project


def _run(files: dict[str, dict]) -> list[str]:
    """把 files 写成临时 flows 目录, 跑 check_flow_struct, 返回 errors。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name, data in files.items():
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        errors: list[str] = []
        with mock.patch.object(check_project, "FLOWS_DIR", root):
            check_project.check_flow_struct(errors, verbose=False)
        return errors


VALID_FLOW = {
    "name": "示例",
    "steps": [
        {"type": "wait_text", "text": ["登录"], "timeout": 10,
         "region_rel": [0.1, 0.2, 0.3, 0.4]},
        {"type": "if_text", "text": "菜单", "region_rel": [0.5, 0.5],
         "then": [{"type": "click_text", "text": ["菜单"], "min_score": 0.4,
                   "fallback_rel": [0.1, 0.9]}]},
    ],
}


class FlowStructTests(unittest.TestCase):
    def test_valid_flow_passes(self):
        self.assertEqual(_run({"flow_ok.json": VALID_FLOW}), [])

    def test_missing_name_and_empty_steps_rejected(self):
        errors = _run({"bad.json": {"steps": []}})
        self.assertTrue(any("缺 name" in e for e in errors), errors)
        self.assertTrue(any("steps 须为非空列表" in e for e in errors), errors)

    def test_region_rel_shape_rejected(self):
        three = {"name": "x", "steps": [{"type": "wait_text", "text": ["a"],
                                         "region_rel": [0.1, 0.2, 0.3]}]}
        reversed_box = {"name": "x", "steps": [{"type": "wait_text", "text": ["a"],
                                                "region_rel": [0.8, 0.2, 0.3, 0.4]}]}
        out_of_range = {"name": "x", "steps": [{"type": "wait_text", "text": ["a"],
                                                "region_rel": [0.0, 0.0, 1.2, 0.4]}]}
        for data in (three, reversed_box, out_of_range):
            self.assertTrue(_run({"bad.json": data}), data)

    def test_keyword_list_rejected(self):
        for text in ([], [""], ["a", 1], None):
            data = {"name": "x", "steps": [{"type": "click_text", "text": text}]}
            errors = _run({"bad.json": data})
            self.assertTrue(any("text" in e for e in errors), (text, errors))

    def test_module_reference_must_exist(self):
        daily = {"name": "编排", "modules": [
            {"id": "a", "flow": "flow_missing.json", "required": False, "on_fail": "skip"},
        ]}
        errors = _run({"daily.json": daily})
        self.assertTrue(any("引用的流程不存在" in e for e in errors), errors)

    def test_module_id_duplicate_and_on_fail_rejected(self):
        daily = {"name": "编排", "modules": [
            {"id": "a", "flow": "a.json", "on_fail": "skip"},
            {"id": "a", "flow": "a.json", "on_fail": "continue"},
        ]}
        errors = _run({"daily.json": daily, "a.json": VALID_FLOW})
        self.assertTrue(any("模块 id 重复" in e for e in errors), errors)
        self.assertTrue(any("on_fail" in e for e in errors), errors)

    def test_registry_shapes(self):
        self.assertEqual(_run({"common/entries.json": {"targets": {"x": {"nav": []}}}}), [])
        self.assertTrue(_run({"common/entries.json": {"targets": {}}}))
        self.assertTrue(_run({"common/scenes.json": {"scenes": []}}))


if __name__ == "__main__":
    unittest.main()
