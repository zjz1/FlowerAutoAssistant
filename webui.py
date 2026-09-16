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
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ocr_engine import OCREngine, load_flows, select_flow, ADB_ADDRESS, ADB_PATH, request_stop

BASE = Path(__file__).parent
ENGINE: OCREngine | None = None
ENGINE_LOCK = threading.Lock()
_SERVER = None  # 当前 http server 实例, 用于 /api/shutdown

_TPL_DIR = BASE / "resource" / "template"          # 模板目录
_TPL_IMG = None                                    # 模板标注工具最近一次截图缓存(BGR)
_TPL_IMG_LOCK = threading.Lock()

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


def _tpl_probe_boxes(img, x0, y0, x1, y1, n=3):
    """区域内按前景颜色连通域探测图形按钮候选框(返回绝对像素 bbox 列表, 按面积降序)。"""
    import cv2
    import numpy as np
    reg = img[y0:y1, x0:x1]
    h, w = reg.shape[:2]
    if h < 4 or w < 4 or reg.size == 0:
        return []
    # 背景色: 取区域四围边框像素的中值
    edge = np.concatenate([reg[0:2].reshape(-1, 3), reg[-2:].reshape(-1, 3),
                           reg[:, 0:2].reshape(-1, 3), reg[:, -2:].reshape(-1, 3)])
    bg = np.median(edge, axis=0)
    diff = np.sqrt(((reg.astype(np.int16) - bg.astype(np.int16)) ** 2).sum(-1))
    fg = (diff > 28).astype(np.uint8)
    # 去噪后找连通域
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    cnt, labels, stats, _ = cv2.connectedComponentsWithStats(fg, 8)
    cand = []
    max_area = 0.85 * w * h
    for i in range(1, cnt):
        _x, _y, _w, _h, a = stats[i]
        if a < 24 or a > max_area:
            continue
        cand.append({"x0": x0 + int(_x), "y0": y0 + int(_y),
                     "x1": x0 + int(_x + _w), "y1": y0 + int(_y + _h), "area": int(a)})
    cand.sort(key=lambda b: -b["area"])
    return cand[:n]


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
        if p == "/tpltool" and self.command == "GET":
            return self._serve_tpl_page()
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
        if api == "config" and self.command == "GET":
            eng = get_engine()
            return self._send_json({
                "enable_switch": bool(eng.config.get("enable_switch", False)),
                "target_tail": eng.config.get("target_tail", ""),
                "claim_online": bool(eng.config.get("claim_online", True)),
                "claim_party": bool(eng.config.get("claim_party", True)),
            })
        if api == "daily" and self.command == "GET":
            return self._daily()
        if api == "run_daily" and self.command == "POST":
            return self._run_daily_sel()
        if api == "set_config" and self.command == "POST":
            data = self._read_json()
            eng = get_engine()
            pre = bool(eng.config.get("enable_switch", False))
            if "enable_switch" in data:
                eng.update_config(enable_switch=bool(data["enable_switch"]))
            if "target_tail" in data:
                eng.update_config(target_tail=str(data["target_tail"]))
            if "claim_online" in data:
                eng.update_config(claim_online=bool(data["claim_online"]))
            if "claim_party" in data:
                eng.update_config(claim_party=bool(data["claim_party"]))
            now = bool(eng.config.get("enable_switch", False))
            log_append(f"[config] 切换账号功能 {'启用' if now else '关闭'}"
                       + (f", 目标尾部={eng.config.get('target_tail')}" if now else ""))
            log_append(f"[config] 领取奖励功能1在线礼包={'开' if eng.config.get('claim_online') else '关'}"
                       f", 功能2花灵派对={'开' if eng.config.get('claim_party') else '关'}")
            return self._send_json({
                "ok": True, "changed": pre != now, "enable_switch": now,
                "claim_online": bool(eng.config.get("claim_online", True)),
                "claim_party": bool(eng.config.get("claim_party", True)),
            })

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
        if api == "stop" and self.command == "POST":
            return self._stop()
        if api == "log" and self.command == "GET":
            return self._log()
        if api == "shutdown" and self.command == "POST":
            return self._shutdown()

        # ---- 模板标注工具 API ----
        if api == "tpl_init" and self.command == "GET":
            return self._tpl_init()
        if api == "tpl_probe" and self.command == "POST":
            return self._tpl_probe()
        if api == "tpl_save" and self.command == "POST":
            return self._tpl_save()

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

    # ---- 模板标注工具 ----
    def _serve_tpl_page(self):
        html = BASE / "tpltool.html"
        if not html.exists():
            return self._send_json({"error": "tpltool.html missing"}, 500)
        body = html.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _tpl_files() -> list[dict]:
        """返回模板目录文件(名称+是否含蒙版)。"""
        _TPL_DIR.mkdir(parents=True, exist_ok=True)
        out = []
        for f in sorted(_TPL_DIR.glob("*.png")):
            name = f.name[:-4]
            if name.endswith(".mask"):
                continue
            out.append({"name": name, "size": f"{f.stat().st_size} B",
                        "mask": (_TPL_DIR / f"{name}.mask.png").exists()})
        return out

    def _tpl_init(self):
        """连接并截图, 返回图像(jpeg)+尺寸+现有模板列表+可选区内探测候选。"""
        eng = get_engine()
        if not _is_connected(eng):
            return self._send_json({"error": "未连接", "status": _status()}, 503)
        img = eng.screenshot()
        if img is None:
            return self._send_json({"error": "截图失败"}, 500)
        with _TPL_IMG_LOCK:
            global _TPL_IMG
            _TPL_IMG = img.copy()
        jpg = _img_to_jpeg_b64(img)
        return self._send_json({"jpeg": jpg, "w": int(img.shape[1]), "h": int(img.shape[0]),
                                "templates": self._tpl_files()})

    def _tpl_probe(self):
        """在指定区域内按颜色前景连通域探测图形按钮候选框(回填识别框)。"""
        with _TPL_IMG_LOCK:
            img = _TPL_IMG
        if img is None:
            return self._send_json({"error": "请先载图"}, 400)
        data = self._read_json()
        x0, y0, x1, y1 = (int(data[k]) for k in ("x0", "y0", "x1", "y1"))
        x0, x1 = sorted((x0, x1)); y0, y1 = sorted((y0, y1))
        boxes = _tpl_probe_boxes(img, x0, y0, x1, y1)
        return self._send_json({"boxes": boxes})

    def _tpl_save(self):
        """按选框裁模板, 可选用画笔蒙版生成匹配掩码 <name>.mask.png。"""
        with _TPL_IMG_LOCK:
            img = _TPL_IMG
        if img is None:
            return self._send_json({"error": "请先载图"}, 400)
        data = self._read_json()
        name = re.sub(r"[^0-9A-Za-z_.\-]", "_", str(data.get("name", "")).strip() or "tpl")
        base = name[:-4] if name.lower().endswith(".png") else name
        if not base:
            return self._send_json({"error": "模板名不能为空"}, 400)
        x0, y0, x1, y1 = (int(data[k]) for k in ("x0", "y0", "x1", "y1"))
        x0, x1 = sorted((x0, x1)); y0, y1 = sorted((y0, y1))
        if x1 - x0 < 2 or y1 - y0 < 2:
            return self._send_json({"error": "选框过小"}, 400)
        h, w = img.shape[:2]
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, x1), min(h, y1)
        _TPL_DIR.mkdir(parents=True, exist_ok=True)
        crop = img[y0:y1, x0:x1].copy()
        tw, th = x1 - x0, y1 - y0
        mask_pts = [p for p in data.get("maskPts") or []
                    if isinstance(p, (list, tuple)) and len(p) >= 2]
        if mask_pts:
            import cv2
            import numpy as np
            brush = int(data.get("maskBrush", 4)) or 4
            mask = np.zeros((th, tw), np.uint8)
            for (px, py) in mask_pts:
                ix = int(min(max(px, x0), x1 - 1)) - x0
                iy = int(min(max(py, y0), y1 - 1)) - y0
                cv2.circle(mask, (ix, iy), max(1, brush), 255, -1)
            cv2.imwrite(str(_TPL_DIR / f"{base}.mask.png"), mask)
        cv2.imwrite(str(_TPL_DIR / f"{base}.png"), crop)
        log_append(f"[tpltool] 已采集模板 {base} {tw}x{th} 蒙版{'有' if mask_pts else '无'}")
        return self._send_json({"ok": True, "name": base, "size": f"{tw}x{th}",
                                "mask": bool(mask_pts)})

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

    # ---- API: 每日编排 (使用界面读取任务列表) ----
    def _daily(self):
        eng = get_engine()
        plan = None
        import json as _json
        p = BASE / "flows" / "daily.json"
        if p.exists():
            try:
                plan = _json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                plan = None
        # 中文任务名映射 (id -> 显示名)
        id2name = {
            "startup": "开始启动",
            "signin": "签到",
            "plant": "种植任务",
            "social": "社交任务",
            "energy": "体力任务",
            "daily": "每日任务",
            "idle": "挂机",
            "claim": "领取奖励",
        }
        modules = []
        # 各模块的可配置面板 meta (右侧 ⚙ 设置面板渲染数据)
        def _module_settings(mid):
            if mid == "claim":
                return [
                    {"key": "claim_online", "type": "switch", "label": "功能1 · 在线礼包",
                     "desc": "抽奖耗尽次数 + 时间档位领取", "value": bool(eng.config.get("claim_online", True))},
                    {"key": "claim_party", "type": "switch", "label": "功能2 · 花灵派对",
                     "desc": "进入派对并领取 6 个在线时长礼包", "value": bool(eng.config.get("claim_party", True))},
                ]
            if mid == "startup":
                return [
                    {"key": "enable_switch", "type": "switch", "label": "切换账号",
                     "desc": "登录前自动切换到目标账号", "value": bool(eng.config.get("enable_switch", False))},
                    {"key": "target_tail", "type": "text", "label": "目标账号尾部",
                     "desc": "匹配 abc****de 的末尾数字", "value": eng.config.get("target_tail", "")},
                ]
            return []
        if plan and plan.get("modules"):
            for m in plan["modules"]:
                mid = m.get("id")
                modules.append({
                    "id": mid,
                    "flow": m.get("flow"),
                    "name": id2name.get(mid, mid),
                    "required": bool(m.get("required", False)),
                    "settings": _module_settings(mid),
                })
        return self._send_json({
            "name": plan.get("name") if plan else "每日挂机编排",
            "modules": modules,
            "enable_switch": bool(eng.config.get("enable_switch", False)),
            "target_tail": eng.config.get("target_tail", ""),
        })

    # ---- API: 按勾选模块运行每日编排 (使用界面「开始一轮」) ----
    def _run_daily_sel(self):
        data = self._read_json()
        selected = data.get("selected", [])
        mode = data.get("mode", "use")
        _set_mode(mode)
        import json as _json
        p = BASE / "flows" / "daily.json"
        if not p.exists():
            return self._send_json({"error": "daily.json 缺失"}, 500)
        try:
            plan = _json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            return self._send_json({"error": f"daily.json 解析失败: {e}"}, 500)
        all_modules = plan.get("modules", [])
        # 去掉任何必选标记: 全部 on_fail 统一为 skip, 勾选才跑
        chosen = []
        for m in all_modules:
            if m.get("id") not in selected:
                continue
            m = dict(m)
            m["on_fail"] = "skip"
            chosen.append(m)
        if not chosen:
            return self._send_json({"error": "未勾选任何任务"}, 400)
        plan["modules"] = chosen
        plan["description"] = "Web UI 使用界面按勾选模块调度"
        name = plan.get("name", "每日编排")
        def job():
            eng = get_engine()
            if not _is_connected(eng):
                eng.connect()
            import sys
            real_out, real_err = sys.stdout, sys.stderr
            sys.stdout = _TeeOut(real_out, _LOGS)
            sys.stderr = _TeeOut(real_err, _LOGS)
            try:
                log_append(f"[run] ==== {name} (勾选 {len(chosen)} 模块) 开始 ====")
                eng.run_daily(plan)
                log_append(f"[run] ==== {name} 完成 ====")
            except Exception as e:
                log_append(f"[run] 流程异常: {e}")
            finally:
                sys.stdout, sys.stderr = real_out, real_err
        threading.Thread(target=job, daemon=True).start()
        return self._send_json({"ok": True, "started": name, "count": len(chosen)})

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

    # ---- API: 停止流程 (UI「停止」按钮, 不关闭服务) ----
    def _stop(self):
        request_stop()
        log_append("[stop] 已请求停止当前所有流程 (WebUI 服务保持运行)")
        return self._send_json({"ok": True, "message": "已请求停止当前流程"})

    # ---- API: 关闭服务 (UI「关闭服务」按钮) ----
    def _shutdown(self):
        global _SERVER
        log_append("[webui] 收到关闭服务请求, 正在退出...")
        self._send_json({"ok": True, "message": "服务已关闭"})
        srv = _SERVER
        if srv is not None:
            # 在独立线程执行, 避免阻塞当前请求响应
            threading.Timer(0.3, lambda: (srv.shutdown(), srv.server_close())).start()
        return

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
        if resource != "/api/connect" and resource != "/api/set_mode" and resource != "/api/click" and resource != "/api/back" and resource != "/api/run" and resource != "/api/set_config" and resource != "/api/run_daily" and resource != "/api/shutdown" and resource != "/api/tpl_probe" and resource != "/api/tpl_save":
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
    global ENGINE, _SERVER
    if args.address != ADB_ADDRESS or args.adb != ADB_PATH:
        ENGINE = OCREngine(adb_path=args.adb, address=args.address)

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    _SERVER = srv
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