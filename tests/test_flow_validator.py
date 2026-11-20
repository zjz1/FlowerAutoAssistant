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


class _StepHarness:
    """只实现 handler 依赖的最小接口, 用于验证步骤参数是否真正透传。"""

    def __init__(self, hit=True):
        self.hit = hit
        self.calls = []
        self._scene = "初始"
        self.ran = []

    def wait_text(self, kws, **kwargs):
        self.calls.append(("wait_text", kwargs))

    def locate(self, kws, **kwargs):
        self.calls.append(("locate", kwargs))
        return object() if self.hit else None

    def _remember_guard(self, *a, **k):
        pass

    def run_steps(self, steps, indent=1):
        self.ran.append(steps)

    def judge_scene(self, scene, min_score=0.4):
        return self.hit


class StepParamPassingTests(unittest.TestCase):
    """2026-11-20 审阅 W1-003/004/006: wait_text 区域 / if_text exact / scene 命中才登记。"""

    def test_wait_text_passes_region_rel(self):
        from ocr_engine.engine._steps import _StepHandlersMixin
        h = _StepHarness()
        _StepHandlersMixin._step_wait_text(h, {"region_rel": [0.1, 0.2, 0.3, 0.4],
                                               "timeout": 1}, ["家园"], "", 0)
        self.assertEqual(h.calls[0][1]["region_rel"], [0.1, 0.2, 0.3, 0.4])

    def test_if_text_passes_exact_and_sets_scene_on_hit(self):
        from ocr_engine.engine._steps import _StepHandlersMixin
        h = _StepHarness(hit=True)
        _StepHandlersMixin._step_if_text(h, {"text": ["服装"], "exact": True,
                                             "scene": "服装界面"}, ["服装"], "", 0)
        self.assertTrue(h.calls[0][1]["exact"])
        self.assertEqual(h._scene, "服装界面")

    def test_if_text_miss_keeps_scene(self):
        from ocr_engine.engine._steps import _StepHandlersMixin
        h = _StepHarness(hit=False)
        _StepHandlersMixin._step_if_text(h, {"text": ["服装"], "scene": "服装界面"},
                                          ["服装"], "", 0)
        self.assertEqual(h._scene, "初始")


class _ConfigHarness:
    def __init__(self, cfg):
        self.config = cfg

    def resolve(self, val):
        return val


class IfConfigGroupTests(unittest.TestCase):
    """2026-11-21: if_config 支持 keys + any/all（W3-003 阶段0 门控的基础）。"""

    def _eval(self, cfg, step):
        from ocr_engine.engine._judges import _JudgeMixin
        return _JudgeMixin.eval_config(_ConfigHarness(cfg), step)

    def test_any_mode(self):
        step = {"keys": ["a", "b", "c"], "any": True, "value": True}
        self.assertTrue(self._eval({"a": False, "b": True, "c": False}, step))
        self.assertFalse(self._eval({"a": False, "b": False, "c": False}, step))

    def test_all_mode(self):
        step = {"keys": ["a", "b"], "any": False, "value": True}
        self.assertTrue(self._eval({"a": True, "b": True}, step))
        self.assertFalse(self._eval({"a": True, "b": False}, step))

    def test_default_applies_when_key_missing(self):
        step = {"keys": ["a", "b"], "any": True, "value": True, "default": False}
        self.assertFalse(self._eval({}, step))

    def test_old_single_key_still_works(self):
        self.assertTrue(self._eval({"enable_x": True},
                                   {"key": "enable_x", "value": True}))
        self.assertFalse(self._eval({"enable_x": False},
                                    {"key": "enable_x", "value": True}))

    def test_key_and_keys_are_mutually_exclusive(self):
        self.assertFalse(self._eval({"a": True},
                                    {"key": "a", "keys": ["a"], "value": True}))


if __name__ == "__main__":
    unittest.main()
