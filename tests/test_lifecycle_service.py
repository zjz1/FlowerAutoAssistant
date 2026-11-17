# -*- coding: utf-8 -*-
"""服务生命周期基线（Stage 4）：probe / health / wait_ready / spawn / stop。

全部离线：用临时 ThreadingHTTPServer 充当 FAA 服务，不连 ADB、不加载引擎。
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from app import lifecycle_service as lifecycle


def _reply(handler: BaseHTTPRequestHandler, obj, code: int = 200) -> None:
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_http(routes: dict, shutdown_event: threading.Event | None = None):
    """启动临时 HTTP 服务；routes: 路径 -> (状态码, JSON 对象)。"""
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            code, obj = routes.get(path, (404, {"error": "notfound"}))
            _reply(self, obj, code)

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/shutdown":
                if shutdown_event is not None:
                    shutdown_event.set()
                _reply(self, {"ok": True, "message": "服务已关闭"})
                return
            _reply(self, {"error": "notfound"}, 404)

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True, name="fake-faa").start()
    return srv, srv.server_address[1]


class LifecycleServiceTests(unittest.TestCase):
    def test_probe_free_on_closed_port(self):
        self.assertEqual(lifecycle.probe(_free_port(), timeout=0.5), "free")

    def test_probe_faa_via_health(self):
        srv, port = _start_http({"/api/health": (200, {"service": "faa", "ok": True})})
        try:
            self.assertEqual(lifecycle.probe(port, timeout=1.0), "faa")
            data = lifecycle.health(port, timeout=1.0)
            self.assertEqual(data["service"], "faa")
        finally:
            srv.shutdown()
            srv.server_close()

    def test_probe_faa_via_status_fallback(self):
        # health 上线前的旧实例：只有 /api/status 的 flow_dir+ui_build
        srv, port = _start_http({
            "/api/status": (200, {"flow_dir": "/x/flows", "ui_build": "1"}),
        })
        try:
            self.assertEqual(lifecycle.probe(port, timeout=1.0), "faa")
            self.assertIsNone(lifecycle.health(port, timeout=1.0))
        finally:
            srv.shutdown()
            srv.server_close()

    def test_probe_other_on_unrelated_http(self):
        srv, port = _start_http({"/": (200, {"hello": "world"})})
        try:
            self.assertEqual(lifecycle.probe(port, timeout=1.0), "other")
        finally:
            srv.shutdown()
            srv.server_close()

    def test_wait_ready_true_and_shutdown_request(self):
        event = threading.Event()
        srv, port = _start_http({"/api/health": (200, {"service": "faa"})}, event)
        try:
            self.assertTrue(lifecycle.wait_ready(port, timeout=3.0))
            self.assertTrue(lifecycle.request_shutdown(port, timeout=2.0))
            self.assertTrue(event.wait(1.0))          # 请求确实送达
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertTrue(lifecycle.wait_stopped(port, timeout=3.0))

    def test_wait_ready_false_when_proc_exited(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        try:
            proc.wait(timeout=10)
            self.assertFalse(lifecycle.wait_ready(_free_port(), timeout=5.0, proc=proc))
        finally:
            proc.wait(timeout=5)

    def test_ensure_service_reuses_existing(self):
        srv, port = _start_http({"/api/health": (200, {"service": "faa"})})
        try:
            with mock.patch("app.lifecycle_service.spawn") as spawn:
                state, svc = lifecycle.ensure_service(port, timeout=1.0)
            self.assertEqual(state, "faa")
            self.assertIsNone(svc)
            spawn.assert_not_called()
        finally:
            srv.shutdown()
            srv.server_close()

    def test_ensure_service_failed_when_spawned_proc_exits(self):
        class _FakeSvc:
            def __init__(self):
                self.proc = subprocess.Popen([sys.executable, "-c", "pass"])
                self.proc.wait(timeout=10)

            def alive(self):
                return False

        svc = _FakeSvc()

        def fake_spawn(port, parent_pid=None):
            self.assertIsNone(parent_pid)
            return svc

        state, got = lifecycle.ensure_service(_free_port(), timeout=0.3, spawn_fn=fake_spawn)
        self.assertEqual(state, "failed")
        self.assertIs(got, svc)

    def test_spawn_builds_parent_pid_args(self):
        fake_proc = mock.MagicMock()
        with mock.patch("app.lifecycle_service.subprocess.Popen", return_value=fake_proc) as popen, \
                mock.patch("app.lifecycle_service.threading.Thread") as thread:
            svc = lifecycle.spawn(8765, python_exe="python.exe",
                                  script="webui.py", parent_pid=4321)
        args = popen.call_args.args[0]
        self.assertEqual(args[0], "python.exe")
        self.assertEqual(args[args.index("--port") + 1], "8765")
        self.assertEqual(args[args.index("--parent-pid") + 1], "4321")
        thread.assert_called_once()
        self.assertEqual(svc.port, 8765)


if __name__ == "__main__":
    unittest.main()
