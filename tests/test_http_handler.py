# -*- coding: utf-8 -*-
"""HTTP Handler 拆分基线：路由 mixin 组装、兼容入口、health/ready 契约。"""
from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

import webui
from app import engine_service
from transport.http.base import HandlerBase
from transport.http.device import DeviceRoutes
from transport.http.handler import Handler
from transport.http.log import LogRoutes
from transport.http.meta import MetaRoutes
from transport.http.pages import PageRoutes
from transport.http.router import RouterMixin
from transport.http.run import RunRoutes
from transport.http.status import StatusRoutes
from transport.http.template import TemplateRoutes


class HttpHandlerTests(unittest.TestCase):
    def test_handler_is_composed_of_route_mixins(self):
        for cls in (HandlerBase, RouterMixin, PageRoutes, TemplateRoutes,
                    DeviceRoutes, StatusRoutes, MetaRoutes, RunRoutes, LogRoutes):
            self.assertTrue(issubclass(Handler, cls), cls.__name__)

    def test_compat_entry_exports(self):
        self.assertIs(webui.Handler, Handler)
        self.assertEqual(len(webui._POST_ROUTES), 15)
        self.assertTrue(callable(webui.set_server))
        self.assertTrue(callable(webui.main))

    def test_route_methods_are_split(self):
        for name in ("_serve_page", "_tplt_init", "_screen", "_daily",
                     "_health", "_ready", "_run", "_log", "_shutdown"):
            self.assertTrue(hasattr(Handler, name), name)


class HttpHealthContractTests(unittest.TestCase):
    """Stage 4：/api/health、/api/ready 的字段与“不创建引擎”约束。"""

    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.thread.join(timeout=3)

    def _get(self, path: str) -> dict:
        with urllib.request.urlopen(self.base + path, timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_health_contract_without_creating_engine(self):
        before = engine_service.peek_engine()
        data = self._get("/api/health")
        self.assertEqual(data["service"], "faa")
        self.assertTrue(data["ok"])
        self.assertEqual(data["port"], self.srv.server_address[1])
        self.assertIn("running", data)
        self.assertIn("uptime_s", data)
        self.assertIs(engine_service.peek_engine(), before)   # 探针绝不创建引擎

    def test_ready_contract(self):
        data = self._get("/api/ready")
        self.assertTrue(data["ready"])
        self.assertIn("connected", data)
        self.assertIn("engine_loaded", data)


if __name__ == "__main__":
    unittest.main()
