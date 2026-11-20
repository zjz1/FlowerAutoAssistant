# -*- coding: utf-8 -*-
"""运行服务基线：互斥门、冲突、流程/编排启动编排。"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app import run_service


class _Eng:
    def __init__(self):
        self.calls = []

    def run_flow(self, target):
        self.calls.append(("flow", target.get("name")))

    def run_daily(self, plan):
        self.calls.append(("daily", plan.get("name")))


class RunServiceTests(unittest.TestCase):
    def setUp(self):
        run_service.set_running(False)

    def tearDown(self):
        run_service.set_running(False)

    def test_claim_is_atomic(self):
        self.assertTrue(run_service.try_claim())
        self.assertFalse(run_service.try_claim())
        self.assertTrue(run_service.running())
        run_service.set_running(False)
        self.assertTrue(run_service.try_claim())

    def test_start_flow_conflict(self):
        run_service.set_running(True)
        with self.assertRaises(run_service.RunConflict):
            run_service.start_flow({"name": "x"}, "x")

    def test_start_flow_spawns_runner(self):
        captured = {}

        def fake_spawn(name, runner, start_line, thread_name="faa-run"):
            captured.update(name=name, runner=runner, line=start_line, thread=thread_name)

        with patch.object(run_service, "_spawn", fake_spawn):
            run_service.start_flow({"name": "单流程"}, "单流程")
        eng = _Eng()
        captured["runner"](eng)
        self.assertEqual(eng.calls, [("flow", "单流程")])
        self.assertEqual(captured["thread"], "faa-run")

    def test_start_flow_with_modules_uses_daily(self):
        captured = {}

        def fake_spawn(name, runner, start_line, thread_name="faa-run"):
            captured["runner"] = runner

        with patch.object(run_service, "_spawn", fake_spawn):
            run_service.start_flow({"name": "编排", "modules": []}, "编排")
        eng = _Eng()
        captured["runner"](eng)
        self.assertEqual(eng.calls, [("daily", "编排")])

    def test_start_daily_uses_daily_thread(self):
        captured = {}

        def fake_spawn(name, runner, start_line, thread_name="faa-run"):
            captured.update(name=name, runner=runner, line=start_line, thread=thread_name)

        with patch.object(run_service, "_spawn", fake_spawn):
            run_service.start_daily({"name": "每日"}, "每日", 2)
        eng = _Eng()
        captured["runner"](eng)
        self.assertEqual(eng.calls, [("daily", "每日")])
        self.assertEqual(captured["thread"], "faa-daily")
        self.assertIn("勾选 2 模块", captured["line"])

    def test_spawn_connect_failure_skips_runner(self):
        """W2-001: connect() 返回 False 时不得启动 runner, running 必须回滚。"""
        class _OfflineEng:
            def connect(self):
                return False

        events = []
        run_service.set_running(True)
        with patch.object(run_service, "get_engine", lambda: _OfflineEng()), \
             patch.object(run_service, "is_connected", lambda e: False), \
             patch.object(run_service, "log_append", lambda s: events.append(s)):
            run_service._spawn("离线", lambda e: events.append("runner"), "[run] 开始")
            for _ in range(50):
                if not run_service.running():
                    break
                import time
                time.sleep(0.01)
        self.assertNotIn("runner", events)
        self.assertFalse(run_service.running())


if __name__ == "__main__":
    unittest.main()
