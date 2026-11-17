# -*- coding: utf-8 -*-
"""HTTP 路由 mixin：base。"""
from __future__ import annotations

from .common import *  # noqa: F401,F403
from http.server import BaseHTTPRequestHandler

class HandlerBase(BaseHTTPRequestHandler):
    server_version = "FAA WebUI/1.0"

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_ok(self):
        self._send_json({"ok": True})

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n <= 0:
                return {}
            raw = self.rfile.read(n)
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _sse_send(self, event: str, data) -> bool:
        """发送一条 SSE 事件并逐事件 flush。连接断开(客户端关页/网络中断)返回 False,
        调用方据此干净退出线程, 不留孤儿循环。event 为空串 = 心跳(SSE 注释行,
        EventSource 不派发为事件, 仅保活兼探活 —— 每次心跳都是一次真实写探测)。"""
        try:
            if event:
                payload = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            else:
                payload = f": ping {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            self.wfile.write(payload.encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return False

    def _query(self, name: str) -> str | None:
        q = self.path.split("?", 1)[1] if "?" in self.path else ""
        for kv in q.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                if k == name:
                    return v
        return None

    def do_GET(self):
        try:
            self._route()
        except Exception as e:
            try:
                self._send_json({"error": str(e)}, 500)
            except Exception:
                pass

    def do_POST(self):
        if self.path.split("?", 1)[0] not in _POST_ROUTES:
            self._send_json({"error": "method not allowed"}, 405)
            return
        try:
            self._route()
        except Exception as e:
            try:
                self._send_json({"error": str(e)}, 500)
            except Exception:
                pass

    def log_message(self, fmt, *args):
        # 精简访问日志, 避免刷屏
        if self.path and self.path.startswith("/api/log"):
            return
        # HTTP 访问行分流到专用文件(2026-10-06, 来自协作区 zcode-20261006-2): 不再走
        # super() 写 sys.stderr —— 运行期 stderr 被 _TeeOut 收进运行日志, 16:35 实测一次
        # 运行 56% 行数是 "GET /api/*" 噪声。行格式与 BaseHTTPRequestHandler.log_message
        # 保持一致, 仅落盘目标不同(data/webui_http_log.txt, 每次服务启动清空)。
        try:
            line = "%s - - [%s] %s\n" % (
                self.address_string(), self.log_date_time_string(), fmt % args)
            with _HTTP_LOG_LOCK:
                with open(_HTTP_LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(line)
        except Exception:
            pass
