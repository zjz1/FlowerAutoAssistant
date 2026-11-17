# -*- coding: utf-8 -*-
"""Handler 组合：基础 HTTP 能力 + 各路由 mixin。"""
from __future__ import annotations

from .base import HandlerBase
from .device import DeviceRoutes
from .log import LogRoutes
from .meta import MetaRoutes
from .pages import PageRoutes
from .router import RouterMixin
from .run import RunRoutes
from .status import StatusRoutes
from .template import TemplateRoutes


class Handler(HandlerBase, RouterMixin, PageRoutes, TemplateRoutes,
              DeviceRoutes, StatusRoutes, MetaRoutes, RunRoutes, LogRoutes):
    """组装式 Handler；方法体全部在 transport/http/*.py 的 mixin 中。"""
