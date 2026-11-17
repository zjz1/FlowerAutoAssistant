# -*- coding: utf-8 -*-
"""FlowerAutoAssistant HTTP 服务兼容入口。

Stage 3 第二阶段后，Handler 已拆到 `transport/http/` 的路由 mixin；
本文件只保留兼容导出与 `python webui.py` 启动入口，不再承载业务逻辑。
"""
from __future__ import annotations

from app.run_service import running as _running, set_running as _set_running
from transport.http import common as _common
from transport.http.common import (BASE, _CONFIG_KEYS, _LOG_MAX_LINES,
                                   _MODULE_SETTINGS, _POST_ROUTES,
                                   _log_reset_history, log_append)
from transport.http.handler import Handler
from transport.http.server import main


def set_server(srv) -> None:
    """兼容 webui_app.py：把服务实例登记到 transport 层。"""
    _common.set_server(srv)


def __getattr__(name):
    # 兼容只读访问 webui._SERVER（写入请走 set_server）
    if name == "_SERVER":
        return _common.SERVER
    raise AttributeError(name)


if __name__ == "__main__":
    main()
