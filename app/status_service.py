# -*- coding: utf-8 -*-
"""状态服务：/api/status 的聚合逻辑。

从 webui.py 迁出（Stage 1）。不依赖 HTTP，可被 CLI/原生壳复用。
"""
from __future__ import annotations

from pathlib import Path

from app import failcache_service, run_service
from app.engine_service import get_engine, is_connected

BASE = Path(__file__).resolve().parents[1]


def ui_build() -> str:
    """webui.html 版本戳(文件 mtime_ns)，前端据此判断页面是否落后于服务端。"""
    try:
        return str((BASE / "webui.html").stat().st_mtime_ns)
    except OSError:
        return ""


def status() -> dict:
    eng = get_engine()
    disp = getattr(eng, "display_w", 0)
    cst = failcache_service.stat()
    thr = float(eng.config.get("fail_cache_prompt_mb", 100) or 100)
    cmb = cst["bytes"] / 1048576
    prompt = failcache_service.consume_prompt(cmb, thr)
    arc = failcache_service.last_archive()
    return {
        "connected": is_connected(eng),
        "screen": ([eng.display_w, eng.display_h] if disp
                   else ([eng.screen_w, eng.screen_h] if eng.screen_w else None)),
        "work": [eng.screen_w, eng.screen_h] if eng.screen_w else None,
        "flow_dir": str(BASE / "flows"),
        "debug_click": bool(getattr(eng, "debug_click", False)),
        "running": run_service.running(),
        "current_module": getattr(eng, "current_module", None),
        "confirm_page_close": bool(eng.config.get("confirm_page_close", True)),
        "ui_build": ui_build(),
        "fail_cache": {"mb": round(cmb, 2), "count": cst["count"], "sessions": cst["sessions"],
                       "oldest": cst["oldest"], "threshold_mb": thr, "exceed": cmb >= thr,
                       "prompt": prompt,
                       "archived": ({"ts": arc["ts"], "count": arc["count"],
                                     "mb": round(arc["bytes"] / 1048576, 2),
                                     "all": bool(cst["files"]) and cst["files"] <= arc["files"]}
                                    if arc else None)},
    }


# 兼容旧名
_status = status
_ui_build = ui_build
