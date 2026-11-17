# -*- coding: utf-8 -*-
"""HTTP 路由 mixin：服务健康与就绪（Stage 4）。

`/api/health` 是客户端判断“端口上是不是 FAA 服务”的唯一握手点
（见 `app/lifecycle_service.probe`）；两个端点都只做轻量读取，
绝不创建引擎（`peek_engine`），避免探测动作加载 OCR 模型。
"""
from __future__ import annotations

import os

from .common import *  # noqa: F401,F403

_STARTED_AT = time.time()


class MetaRoutes:
    def _health(self):
        """存活探针：服务进程在、HTTP 可应答即可；字段供壳做关窗判断。"""
        eng = peek_engine()
        try:
            port = self.server.server_address[1] if self.server else None
        except Exception:
            port = None
        self._send_json({
            "service": "faa",
            "ok": True,
            "pid": os.getpid(),
            "port": port,
            "uptime_s": round(time.time() - _STARTED_AT, 1),
            "running": run_service.running(),
            "engine_loaded": eng is not None,
        })

    def _ready(self):
        """就绪：HTTP 服务已可接收请求；connected/engine_loaded 仅信息性。

        引擎按需懒加载，未连接设备不代表服务未就绪（连接是客户端动作）。
        """
        eng = peek_engine()
        self._send_json({
            "ready": True,
            "connected": bool(eng is not None and is_connected(eng)),
            "engine_loaded": eng is not None,
            "running": run_service.running(),
        })
