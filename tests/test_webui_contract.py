# -*- coding: utf-8 -*-
"""webui 服务契约基线：POST 路由集合、配置键元数据、模块设置归属。"""
from __future__ import annotations

import unittest

import webui


class WebUiContractTests(unittest.TestCase):
    def test_post_routes_inventory(self):
        expected = {
            "/api/connect", "/api/set_mode", "/api/click", "/api/run",
            "/api/stop", "/api/set_config", "/api/run_daily", "/api/shutdown",
            "/api/tplt_load", "/api/tplt_submit", "/api/tplt_contour",
            "/api/failures_clear", "/api/log_clear",
            "/api/fail_cache_clean", "/api/fail_cache_open",
        }
        self.assertEqual(set(webui._POST_ROUTES), expected)

    def test_config_specs_have_type(self):
        self.assertTrue(webui._CONFIG_KEYS)
        for key, spec in webui._CONFIG_KEYS.items():
            self.assertIn("type", spec, f"{key} 缺 type")
            self.assertIn("meta", spec, f"{key} 缺 meta")

    def test_module_settings_subset_of_config_keys(self):
        used = {k for keys in webui._MODULE_SETTINGS.values() for k in keys}
        self.assertTrue(used)
        self.assertTrue(used <= set(webui._CONFIG_KEYS),
                        f"模块设置含未知键: {sorted(used - set(webui._CONFIG_KEYS))}")

    def test_log_buffer_limit(self):
        self.assertGreater(webui._LOG_MAX_LINES, 0)


class PipeEncodingTests(unittest.TestCase):
    """Phase 2: 冻结包管道输出编码(非 tty 才改 UTF-8, tty 保持系统编码)。"""

    class _FakeStream:
        def __init__(self, tty):
            self._tty = tty
            self.calls = []

        def isatty(self):
            return self._tty

        def reconfigure(self, **kw):
            self.calls.append(kw)

    def test_non_tty_reconfigured_tty_untouched(self):
        from transport.http.server import _force_utf8_pipes
        pipe, console = self._FakeStream(False), self._FakeStream(True)
        _force_utf8_pipes([pipe, console])
        self.assertEqual(pipe.calls, [{"encoding": "utf-8", "errors": "replace"}])
        self.assertEqual(console.calls, [])

    def test_stream_without_reconfigure_is_skipped(self):
        from transport.http.server import _force_utf8_pipes

        class _Closed:
            def isatty(self):
                raise ValueError("closed")

        _force_utf8_pipes([_Closed(), None])  # 不抛异常即通过


if __name__ == "__main__":
    unittest.main()
