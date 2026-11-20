# -*- coding: utf-8 -*-
"""HTTP 路由 mixin：base。"""
from __future__ import annotations

from .common import *  # noqa: F401,F403
from http.server import BaseHTTPRequestHandler

class HandlerBase(BaseHTTPRequestHandler):
    server_version = "FAA WebUI/1.0"
    MAX_BODY_BYTES = 1024 * 1024   # 1MB: 本地 UI 的所有 JSON 请求都远小于此值

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
        if not self._host_allowed():
            self._send_json({"error": "host not allowed"}, 403)
            return
        try:
            self._route()
        except Exception as e:
            try:
                self._send_json({"error": str(e)}, 500)
            except Exception:
                pass

    def _host_allowed(self) -> bool:
        """防 DNS rebinding：Host 必须是本机回环（无 Host 的 HTTP/1.0 原生客户端放行）。

        GET 接口虽只读，但会暴露日志/截图/OCR 文本；浏览器把攻击者域名解析到
        127.0.0.1 后，同源策略会放行读取，故所有端点统一校验 Host。
        """
        host = (self.headers.get("Host") or "").strip()
        if not host:
            return True
        try:
            from urllib.parse import urlsplit
            hostname = urlsplit("//" + host).hostname
        except Exception:
            return False
        return hostname in ("127.0.0.1", "localhost", "::1")

    def _origin_allowed(self) -> bool:
        """1.0 #19: POST 的 Origin 白名单（防其他网站借浏览器打本机服务）。

        允许:
          - **无 Origin**：WPF 的 FaaProxy / curl / 脚本等原生客户端不发送 Origin；
          - `http://127.0.0.1[:port]`、`http://localhost[:port]`、`http://[::1][:port]`
            （端口不限：服务可用 --port 换端口）。
        拒绝: 其他站点（含 https、局域网 IP、域名）与 `Origin: null`（file:// 页面）。
        GET 均为只读接口，只受浏览器同源策略约束，不再单独限制。
        """
        origin = self.headers.get("Origin")
        if origin is None or origin == "":
            return True
        try:
            from urllib.parse import urlsplit
            u = urlsplit(origin)
        except Exception:
            return False
        return u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost", "::1")

    def do_POST(self):
        if not self._host_allowed():
            self._send_json({"error": "host not allowed"}, 403)
            return
        if not self._origin_allowed():
            self._send_json({"error": "origin not allowed"}, 403)
            return
        if self.path.split("?", 1)[0] not in _POST_ROUTES:
            self._send_json({"error": "method not allowed"}, 405)
            return
        try:
            body_len = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            body_len = 0
        if body_len > self.MAX_BODY_BYTES:
            self.close_connection = True
            self._send_json({"error": "请求体过大(上限 1MB)"}, 413)
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
            log_service.persist_http(line)
        except Exception:
            pass
