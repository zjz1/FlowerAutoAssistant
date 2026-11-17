# -*- coding: utf-8 -*-
"""HTTP 适配器共享依赖面。

只做“把服务层/常量集中到一个命名空间”，不承载业务逻辑。
各路由 mixin 通过 `from .common import *` 使用同一组依赖，避免每个文件重复
十几行 import 且漏项。
"""
from __future__ import annotations

import base64
import json
import threading
import time
from pathlib import Path

from ocr_engine import (ADB_ADDRESS, ADB_PATH, clear_failures, get_failures,
                        load_flows, request_stop, select_flow)
from app import (config_service, engine_service, failcache_service, log_service,
                 run_service, status_service)
from app.config_service import (_CONFIG_KEYS, _MODULE_SETTINGS, _apply_config_key,
                                _config_echo, _config_log_lines,
                                set_mode as _set_mode)
from app.engine_service import (get_engine, img_to_jpeg_b64, is_connected,
                                ocr_boxes, peek_engine)
from app.failcache_service import (FAIL_CACHE_DIR as _FAIL_CACHE_DIR,
                                   archive as _fail_cache_archive,
                                   clean as _fail_cache_clean,
                                   stat as _fail_cache_stat)
from app.log_service import (HTTP_LOG_FILE as _HTTP_LOG_FILE,
                             HTTP_LOG_LOCK as _HTTP_LOG_LOCK,
                             LOG_MAX_LINES as _LOG_MAX_LINES,
                             append as log_append,
                             reset_history as _log_reset_history)
from app.status_service import status as _status, ui_build as _ui_build

# transport/http/common.py -> 仓库根
BASE = Path(__file__).resolve().parents[2]
ANNOT_FILE = BASE / "data" / "tplt_annotations.jsonl"
ANNOT_LOCK = threading.Lock()
_ANNOT_FILE = ANNOT_FILE
_ANNOT_LOCK = ANNOT_LOCK

# 允许 POST 的 API 白名单（新增/改动 POST 接口必须同步这里）
_POST_ROUTES = {
    "/api/connect", "/api/set_mode", "/api/click", "/api/run",
    "/api/stop", "/api/set_config", "/api/run_daily", "/api/shutdown",
    "/api/tplt_load", "/api/tplt_submit", "/api/tplt_contour",
    "/api/failures_clear", "/api/log_clear",
    "/api/fail_cache_clean", "/api/fail_cache_open",
}
POST_ROUTES = _POST_ROUTES

# 当前 http server 实例（/api/shutdown 用）
SERVER = None


def set_server(srv) -> None:
    global SERVER
    SERVER = srv


def shutdown_server() -> None:
    srv = SERVER
    if srv is not None:
        # 独立线程执行，避免阻塞当前请求响应
        threading.Timer(0.3, lambda: (srv.shutdown(), srv.server_close())).start()


__all__ = [
    "base64", "json", "threading", "time", "Path",
    "BASE", "ANNOT_FILE", "ANNOT_LOCK", "_ANNOT_FILE", "_ANNOT_LOCK",
    "_POST_ROUTES", "POST_ROUTES",
    "SERVER", "shutdown_server", "set_server",
    "ADB_ADDRESS", "ADB_PATH", "clear_failures", "get_failures", "load_flows",
    "request_stop", "select_flow",
    "config_service", "engine_service", "failcache_service", "log_service",
    "run_service", "status_service",
    "_CONFIG_KEYS", "_MODULE_SETTINGS", "_apply_config_key", "_config_echo",
    "_config_log_lines", "_set_mode",
    "_FAIL_CACHE_DIR", "_fail_cache_archive", "_fail_cache_clean",
    "_fail_cache_stat",
    "get_engine", "img_to_jpeg_b64", "is_connected", "ocr_boxes", "peek_engine",
    "_HTTP_LOG_FILE", "_HTTP_LOG_LOCK", "_LOG_MAX_LINES", "log_append",
    "_log_reset_history",
    "_status", "_ui_build",
]
