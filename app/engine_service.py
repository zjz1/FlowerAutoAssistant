# -*- coding: utf-8 -*-
"""引擎单例与画面/OCR 服务。

从 webui.py 迁出（Stage 1）。webui 只作为 HTTP 适配器，不再持有引擎生命周期。
"""
from __future__ import annotations

import base64
import threading
from pathlib import Path

from ocr_engine import ADB_ADDRESS, ADB_PATH, OCREngine

BASE = Path(__file__).resolve().parents[1]

ENGINE: OCREngine | None = None
ENGINE_LOCK = threading.Lock()


def get_engine() -> OCREngine:
    """返回全局单例引擎（必要时创建）。"""
    global ENGINE
    with ENGINE_LOCK:
        if ENGINE is None:
            ENGINE = OCREngine(adb_path=ADB_PATH, address=ADB_ADDRESS)
        return ENGINE


def peek_engine() -> OCREngine | None:
    """只读当前引擎，不触发创建（避免 /api/status 在未连接时加载 OCR 模型）。"""
    return ENGINE


def configure_engine(adb_path: str, address: str) -> None:
    """用命令行参数重建单例（服务启动时调用）。"""
    global ENGINE
    with ENGINE_LOCK:
        ENGINE = OCREngine(adb_path=adb_path, address=address)


def is_connected(eng) -> bool:
    return bool(getattr(eng, "_ctrl", None) and eng._ctrl.connected)


def img_to_jpeg_b64(img) -> str:
    import cv2
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 78])
    if not ok:
        return ""
    return base64.b64encode(buf.tobytes()).decode("ascii")


def ocr_boxes(img) -> list[dict]:
    """对画面做一次 OCR, 返回文字块(含相对坐标 0~1)。"""
    if img is None or not getattr(get_engine(), "screen_w", 0):
        return []
    from ocr_ui import ocr_image
    w = get_engine().screen_w
    h = get_engine().screen_h
    out = []
    for b in ocr_image(img):
        x1, y1, x2, y2 = b["box"]
        out.append({
            "text": b.get("text", ""),
            "score": round(b.get("score", 1.0), 2),
            "rel": [round((x1 + x2) / 2 / w, 4), round((y1 + y2) / 2 / h, 4)],
            "box": [round(x1 / w, 4), round(y1 / h, 4),
                    round(x2 / w, 4), round(y2 / h, 4)],
        })
    return out
