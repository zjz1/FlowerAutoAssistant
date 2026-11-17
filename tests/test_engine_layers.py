# -*- coding: utf-8 -*-
"""OCREngine 职责层基线（Stage 3 第二阶段）。"""
from __future__ import annotations

import unittest

from ocr_engine import OCREngine
from ocr_engine.engine._layers import (ActionLayer, DeviceLayer, FlowLayer,
                                       LocatorLayer, OcrLayer)


class EngineLayerTests(unittest.TestCase):
    def test_engine_has_five_layers(self):
        self.assertEqual(OCREngine.__bases__,
                         (DeviceLayer, OcrLayer, LocatorLayer, ActionLayer, FlowLayer))

    def test_layers_are_subclasses(self):
        for layer in (DeviceLayer, OcrLayer, LocatorLayer, ActionLayer, FlowLayer):
            self.assertTrue(issubclass(OCREngine, layer), layer.__name__)

    def test_flat_method_surface_preserved(self):
        for name in ("screenshot", "ocr_blocks", "locate", "click_text",
                     "close_dialog", "judge_scene", "run_flow", "run_daily"):
            self.assertTrue(hasattr(OCREngine, name), name)


if __name__ == "__main__":
    unittest.main()
