"""
FlowerAutoAssistant - 本地 Web UI（自测 / 使用模式）
==============================================
标准库实现, 无第三方依赖。浏览器打开 http://127.0.0.1:<port>/ 即可操作。

功能:
- 实时画面: 定时抓取模拟器截图, 叠加 OCR 识别出的文字框, 便于核对按钮位置
- 点击操作: 在画面上点击即对模拟器发点击, 并支持发送返回键
- 运行流程: 下拉选择 flows/*.json 或每日编排, 一键运行, 日志实时滚动
- 流程/知识库查看: 浏览 flows 与 data/click_log.json / close_buttons.json
- 模式切换: 「测试」模式每步截图保存点击区;「使用」模式正常运行

用法:
    python webui.py [--port 8765] [--address 127.0.0.1:16384] [--adb <path>]
"""
from __future__ import annotations

import argparse
import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ocr_engine import OCREngine, load_flows, select_flow, ADB_ADDRESS, ADB_PATH

BASE = Path(__file__).parent
ENGINE: OCREngine | None = None
ENGINE_LOCK = threading.Lock()

# ---- 运行日志环形缓冲 (支持增量拉取) ----
_LOG_LOCK = threading.Lock()
_LOGS: list[str] = []


def log_append(text: str) -> None:
    with _LOG_LOCK:
        _LOGS.append(text)


class _TeeOut:
    """把 print 输出同时写入日志缓冲, 便于前端实时流式查看。"""
    def __init__(self, real, buf):
        self._real = real
        self._buf = buf

    def write(self, s: str) -> int:
        if s:
            with _LOG_LOCK:
                self._buf.append(s)
        try:
            return self._real.write(s)
        except Exception:
            return len(s)

    def flush(self) -> None:
        try:
            self._real.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        return False


def get_engine() -> OCREngine:
    """返回全局单例引擎。"""
    global ENGINE
    with ENGINE_LOCK:
        if ENGINE is None:
            ENGINE = OCREngine(adb_path=ADB_PATH, address=ADB_ADDRESS)
        return ENGINE


def _img_to_jpeg_b64(img) -> str:
    import cv2
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 78])
    if not ok:
        return ""
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _ocr_boxes(img) -> list[dict]:
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


def _is_connected(eng) -> bool:
    return bool(getattr(eng, "_ctrl", None) and eng._ctrl.connected)


def _status() -> dict:
    eng = get_engine()
    return {
        "connected": _is_connected(eng),
        "screen": [eng.screen_w, eng.screen_h] if eng.screen_w else None,
        "flow_dir": str(BASE / "flows"),
        "debug_click": bool(getattr(eng, "debug_click", False)),
    }


def _set_mode(mode: str) -> None:
    """切换测试/使用模式。测试模式=每步截图保存点击区。"""
    eng = get_engine()
    eng.debug_click = (mode == "test")
    if eng.debug_click:
        eng.debug_dir = BASE / "data" / "click_debug"
        eng.debug_dir.mkdir(parents=True, exist_ok=True)
        eng._click_seq = getattr(eng, "_click_seq", 0)


class Handler(BaseHTTPRequestHandler):
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

    def _route(self):
        p = self.path.split("?", 1)[0]
        if p == "/" and self.command == "GET":
            return self._serve_page()
        # API 全部带 /api 前缀
        if not p.startswith("/api/"):
            self._send_json({"error": "notfound"}, 404)
            return
        api = p[len("/api/"):]

        if api == "status" and self.command == "GET":
            return self._send_json(_status())
        if api == "flows" and self.command == "GET":
            flows = []
            for f in load_flows():
                fname = f.get("_file")
                flows.append({
                    "name": f.get("name"),
                    "file": fname,
                    "description": f.get("description", ""),
                    "modules": f.get("modules", []),
                })
            return self._send_json({"flows": flows})
        if api == "kb" and self.command == "GET":
            return self._send_json(self._kb())

        if api == "connect" and self.command == "POST":
            return self._connect()
        if api == "set_mode" and self.command == "POST":
            data = self._read_json()
            _set_mode(data.get("mode", "use"))
            return self._send_ok()
        if api == "screen" and self.command == "GET":
            return self._screen()
        if api == "click" and self.command == "POST":
            return self._click()
        if api == "back" and self.command == "POST":
            return self._back()
        if api == "run" and self.command == "POST":
            return self._run()
        if api == "log" and self.command == "GET":
            return self._log()

        self._send_json({"error": "no such api"}, 404)

    # ---- 页面 ----
    def _serve_page(self):
        html = BASE / "webui.html"
        if not html.exists():
            return self._send_json({"error": "webui.html missing"}, 500)
        body = html.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ---- API: KB ----
    def _kb(self):
        kb = {"click_log": {}, "close_buttons": []}
        cl = BASE / "data" / "click_log.json"
        if cl.exists():
            try:
                kb["click_log"] = json.loads(cl.read_text(encoding="utf-8"))
            except Exception:
                pass
        cb = BASE / "data" / "close_buttons.json"
        if cb.exists():
            try:
                kb["close_buttons"] = json.loads(cb.read_text(encoding="utf-8"))
            except Exception:
                pass
        return kb

    # ---- API: 连接 ----
    def _connect(self):
        eng = get_engine()
        ok = eng.connect()
        return self._send_json({"ok": ok, **(_status() if ok else {})}, 200 if ok else 502)

    # ---- API: 截图 + OCR 标注 ----
    def _screen(self):
        eng = get_engine()
        if not _is_connected(eng):
            return self._send_json({"error": "未连接", "status": _status()}, 503)
        img = eng.screenshot()
        if img is None:
            return self._send_json({"error": "截图失败"}, 500)
        jpg = _img_to_jpeg_b64(img)
        return self._send_json({
            "jpeg": jpg,
            "w": eng.screen_w, "h": eng.screen_h,
            "boxes": _ocr_boxes(img),
        })

    # ---- API: 点击 (支持 rel 相对坐标) ----
    def _click(self):
        eng = get_engine()
        if not _is_connected(eng):
            return self._send_json({"error": "未连接"}, 503)
        data = self._read_json()
        if "rel" in data:
            rx, ry = data["rel"]
            eng.click_rel(rx, ry)
        elif "x" in data and "y" in data:
            eng.click_abs(int(data["x"]), int(data["y"]))
        else:
            return self._send_json({"error": "需要 {rel:[rx,ry]} 或 {x,y}"}, 400)
        return self._send_ok()

    # ---- API: 返回键 ----
    def _back(self):
        eng = get_engine()
        ok = eng.back() if _is_connected(eng) else False
        return self._send_json({"ok": ok}, 200 if ok else 503)

    # ---- API: 运行流程 (后台线程 + 日志) ----
    def _run(self):
        data = self._read_json()
        key = data.get("flow", "")
        mode = data.get("mode", "use")
        _set_mode(mode)
        flows = load_flows()
        target = select_flow(flows, key)
        if target is None:
            return self._send_json({"error": f"未找到流程: {key}"}, 400)
        name = target.get("name")
        def job():
            eng = get_engine()
            if not _is_connected(eng):
                eng.connect()
            import sys
            real_out, real_err = sys.stdout, sys.stderr
            sys.stdout = _TeeOut(real_out, _LOGS)
            sys.stderr = _TeeOut(real_err, _LOGS)
            try:
                log_append(f"[run] ==== {name} 开始 ====")
                if "modules" in target:
                    eng.run_daily(target)
                else:
                    eng.run_flow(target)
                log_append(f"[run] ==== {name} 完成 ====")
            except Exception as e:
                log_append(f"[run] 流程异常: {e}")
            finally:
                sys.stdout, sys.stderr = real_out, real_err
        threading.Thread(target=job, daemon=True).start()
        return self._send_json({"ok": True, "started": name})

    # ---- API: 增量日志 ----
    def _log(self):
        after = int(self._query("after") or 0)
        with _LOG_LOCK:
            if after >= len(_LOGS):
                return self._send_json({"next": after, "lines": []})
            lines = _LOGS[after:]
        return self._send_json({"next": after + len(lines), "lines": lines})

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
        resource = self.path.split("?", 1)[0]
        if resource != "/api/connect" and resource != "/api/set_mode" and resource != "/api/click" and resource != "/api/back" and resource != "/api/run":
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
        try:
            super().log_message(fmt, *args)
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="FAA Web UI")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--address", default=ADB_ADDRESS)
    parser.add_argument("--adb", default=ADB_PATH)
    args = parser.parse_args()

    # 用命令行优先的 ADB 参数重新初始化单例
    global ENGINE
    if args.address != ADB_ADDRESS or args.adb != ADB_PATH:
        ENGINE = OCREngine(adb_path=args.adb, address=args.address)

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"\n=== FAA Web UI ===")
    print(f"打开浏览器: http://127.0.0.1:{args.port}/")
    print(f"ADB: {args.adb}  {args.address}")
    print(f"按 Ctrl+C 退出\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[WebUI] 已退出")
        srv.server_close()


if __name__ == "__main__":
    main()