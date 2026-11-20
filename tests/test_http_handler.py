# -*- coding: utf-8 -*-
"""HTTP Handler 拆分基线：路由 mixin 组装、兼容入口、health/ready 契约。"""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import webui
from app import engine_service, failcache_service
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
        self.assertEqual(len(webui._POST_ROUTES), 16)
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

    def _post_status(self, path: str, obj: dict):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _post(self, path: str, obj: dict) -> dict:
        status, body = self._post_status(path, obj)
        self.assertEqual(status, 200, body)
        return body

    def test_plant_presets_endpoint(self):
        data = self._get("/api/plant_presets")
        flowers = data.get("flowers")
        self.assertTrue(flowers)
        seeds = {c["seed"] for f in flowers for c in f["colors"]}
        self.assertEqual(seeds, {"白色桃花", "粉色桃花", "绿色桃花"})
        rare = {c["seed"] for f in flowers for c in f["colors"] if c.get("rare")}
        self.assertEqual(rare, {"绿色桃花"})

    def test_daily_exposes_plant_control_types(self):
        data = self._get("/api/daily")
        plant = next(m for m in data["modules"] if m["id"] == "plant")
        by_key = {s["key"]: s for s in plant["settings"]}
        self.assertEqual(by_key["plant_seed_mode"]["type"], "enum")
        self.assertEqual(by_key["plant_count_mode"]["type"], "enum")
        self.assertEqual(by_key["plant_count"]["type"], "int")
        self.assertEqual(by_key["plant_count"]["min"], 1)
        self.assertEqual(by_key["plant_count"]["max"], 360)
        self.assertIn("plant_rare_confirm", data)
        self.assertIn("plant_seed_rare", data)

    def test_preflight_contract(self):
        data = self._post("/api/preflight", {"modules": ["startup", "plant"]})
        self.assertTrue(data["enabled"])
        self.assertTrue(data["disabled"])
        text = data["text"]
        self.assertIn("本次运行时开启了以下功能：", text)
        self.assertIn("本次运行时关闭了以下功能：", text)
        self.assertIn("种植任务", text)
        self.assertNotIn("--", text)

    def test_preflight_rejects_unknown_module(self):
        status, body = self._post_status("/api/preflight", {"modules": ["nope"]})
        self.assertEqual(status, 400)
        self.assertIn("未知模块", body.get("error", ""))

    def test_harvest_allowed_config_validation(self):
        # W4-003: 不写入真实 data/config.json / 真实运行日志 —— 引擎先按真实配置装载,
        # 然后把落盘路径临时重定向到 tempdir。
        import ocr_engine.engine._config as engine_config
        from app import log_service
        engine_service.get_engine()
        old_cfg = engine_config.CONFIG_PATH
        old_log = log_service.LOG_FILE
        with tempfile.TemporaryDirectory() as td:
            engine_config.CONFIG_PATH = Path(td) / "config.json"
            log_service.LOG_FILE = Path(td) / "runtime.txt"
            try:
                status, body = self._post_status("/api/set_config",
                                                 {"plant_harvest_allowed": ["绿色桃花"]})
                self.assertEqual(status, 400)
                self.assertIn("稀有种子", body.get("error", ""))
                status, body = self._post_status("/api/set_config",
                                                 {"plant_harvest_allowed": ["蓝色桃花"]})
                self.assertEqual(status, 400)
                status, body = self._post_status("/api/set_config",
                                                 {"plant_harvest_allowed": ["白色桃花"]})
                self.assertEqual(status, 200)
                self.assertTrue(body.get("ok"))
                # 恢复默认，避免影响同进程其它用例
                self._post("/api/set_config",
                           {"plant_harvest_allowed": ["白色桃花", "粉色桃花"]})
            finally:
                engine_config.CONFIG_PATH = old_cfg
                log_service.LOG_FILE = old_log

    def test_bool_config_rejects_string(self):
        status, body = self._post_status("/api/set_config", {"claim_online": "false"})
        self.assertEqual(status, 400)
        self.assertIn("布尔", body.get("error", ""))

    def test_invalid_log_cursor_returns_400(self):
        req = urllib.request.Request(self.base + "/api/log?after=abc")
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                status, body = resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            status, body = e.code, json.loads(e.read().decode("utf-8"))
        self.assertEqual(status, 400)
        self.assertIn("after", body.get("error", ""))

    def test_non_loopback_host_rejected(self):
        req = urllib.request.Request(self.base + "/api/health", headers={"Host": "evil.example"})
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
        self.assertEqual(status, 403)

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

    def test_fail_cache_info_does_not_mutate_stat_cache(self):
        """2026-11-18 WPF API 自测暴露: router 原地排序 files 把 stat 缓存变成 list,
        紧随的 /api/status 子集比对 set<=set 抛 TypeError -> /api/tplt_init 500。"""
        old_dir = failcache_service.FAIL_CACHE_DIR
        try:
            with tempfile.TemporaryDirectory() as td:
                failcache_service.FAIL_CACHE_DIR = Path(td)
                sess = failcache_service.FAIL_CACHE_DIR / "s1"
                sess.mkdir()
                (sess / "fail_20261118_001_x.jpg").write_bytes(b"x")
                failcache_service.invalidate_stat()
                failcache_service.stat(force=True)

                data = self._get("/api/fail_cache_info")
                self.assertIsInstance(data["files"], list)
                self.assertIsInstance(failcache_service.stat()["files"], set)
        finally:
            failcache_service.FAIL_CACHE_DIR = old_dir
            failcache_service.invalidate_stat()


class HttpOriginWhitelistTests(unittest.TestCase):
    """1.0 #19: POST 的 Origin 白名单（本机 UI 正常，外部来源 403）。"""

    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.srv.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.thread.join(timeout=3)

    def _post(self, path: str, payload: dict, origin: str | None = None):
        headers = {"Content-Type": "application/json"}
        if origin is not None:
            headers["Origin"] = origin
        req = urllib.request.Request(self.base + path, data=json.dumps(payload).encode("utf-8"),
                                     method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_no_origin_allowed(self):
        code, _ = self._post("/api/set_config", {})
        self.assertEqual(code, 200)

    def test_local_origins_allowed(self):
        for origin in (f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}",
                       f"http://[::1]:{self.port}"):
            code, _ = self._post("/api/set_config", {}, origin)
            self.assertEqual(code, 200, origin)

    def test_external_origins_rejected(self):
        for origin in ("http://evil.example", "https://127.0.0.1:8765",
                       "http://192.168.1.10:8765", "null"):
            code, body = self._post("/api/shutdown", {}, origin)
            self.assertEqual(code, 403, origin)
            self.assertEqual(body.get("error"), "origin not allowed")


if __name__ == "__main__":
    unittest.main()
