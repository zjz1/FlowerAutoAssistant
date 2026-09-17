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

from ocr_engine import OCREngine, load_flows, select_flow, ADB_ADDRESS, ADB_PATH, request_stop

BASE = Path(__file__).parent
ENGINE: OCREngine | None = None
ENGINE_LOCK = threading.Lock()
_SERVER = None  # 当前 http server 实例, 用于 /api/shutdown

# 模板标注工具(人机协同标注): 只记录坐标标注, 不直接保存模板文件
_ANNOT_FILE = BASE / "data" / "tplt_annotations.jsonl"   # 提交给助手的标注记录(追加)
_ANNOT_LOCK = threading.Lock()

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
                "enable_shine": bool(eng.config.get("enable_shine", False)),
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
            if "enable_shine" in data:
                eng.update_config(enable_shine=bool(data["enable_shine"]))
            now = bool(eng.config.get("enable_switch", False))
            log_append(f"[config] 切换账号功能 {'启用' if now else '关闭'}"
                       + (f", 目标尾部={eng.config.get('target_tail')}" if now else ""))
            log_append(f"[config] 领取奖励功能1在线礼包={'开' if eng.config.get('claim_online') else '关'}"
                       f", 功能2花灵派对={'开' if eng.config.get('claim_party') else '关'}"
                       f", 闪耀委托挑战={'开' if eng.config.get('enable_shine') else '关'}")
            return self._send_json({
                "ok": True, "changed": pre != now, "enable_switch": now,
                "claim_online": bool(eng.config.get("claim_online", True)),
                "claim_party": bool(eng.config.get("claim_party", True)),
                "enable_shine": bool(eng.config.get("enable_shine", False)),
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

        # ---- 模板标注工具 API (人机协同标注, 只回传坐标, 不直接存模板) ----
        if api == "tplt_init" and self.command == "GET":
            return self._tplt_init()
        if api == "tplt_load" and self.command == "POST":
            return self._tplt_load()
        if api == "tplt_submit" and self.command == "POST":
            return self._tplt_submit()
        if api == "tplt_contour" and self.command == "POST":
            return self._tplt_contour()

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

    def _tplt_init(self):
        """复用主界面已连引擎截图, 返回 jpeg + 尺寸。未连接则提示先到主界面连接。"""
        eng = get_engine()
        if not _is_connected(eng):
            return self._send_json({"error": "未连接: 请先到主界面完成「连接设备」后再使用", "status": _status()}, 503)
        img = eng.screenshot()
        if img is None:
            return self._send_json({"error": "截图失败"}, 500)
        jpg = _img_to_jpeg_b64(img)
        return self._send_json({"jpeg": jpg, "w": int(img.shape[1]), "h": int(img.shape[0])})

    def _tplt_load(self):
        """可选: 按已知图片载入(仅允许 debug/ 下文件路径), 返回其 base64 jpeg 供标注。不做探测回填。"""
        data = self._read_json()
        path = str(data.get("path") or "")
        target = (BASE / path).resolve()
        allow = (BASE / "debug").resolve()
        if not str(target).startswith(str(allow)) or not target.is_file():
            return self._send_json({"error": "仅允许载入 debug/ 目录下的图片"}, 400)
        import cv2
        img = cv2.imread(str(target))
        if img is None:
            return self._send_json({"error": "读取图片失败"}, 400)
        jpg = _img_to_jpeg_b64(img)
        return self._send_json({"jpeg": jpg, "w": int(img.shape[1]), "h": int(img.shape[0]),
                                "loaded": target.name})

    def _tplt_contour(self):
        """在截图指定矩形(abs 像素)内自动提取主轮廓, 返回有序闭合点列(绝对像素)。
        用于 tpltool 闭环: 用户框选后请求一次, 回填为可调整的连续水线轮廓底稿。
        """
        data = self._read_json()
        eng = get_engine()
        if not _is_connected(eng):
            return self._send_json({"error": "未连接: 请先到主界面完成「连接设备」后再使用"}, 503)
        img = eng.screenshot()
        if img is None:
            return self._send_json({"error": "截图失败"}, 500)
        h, w = img.shape[:2]
        try:
            x0, y0, x1, y1 = [int(data[k]) for k in ("x0", "y0", "x1", "y1")]
        except Exception:
            return self._send_json({"error": "缺少矩形 x0/y0/x1/y1"}, 400)
        # 收窄到画面并保证最小尺寸
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, x1), min(h, y1)
        if x1 - x0 < 4 or y1 - y0 < 4:
            return self._send_json({"error": "矩形过小"}, 400)
        import cv2
        import numpy as np
        roi = img[y0:y1, x0:x1]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        # 均值漂移+OTSU 突出前景主体, 形态闭合联通碎块
        blur = cv2.pyrMeanShiftFiltering(roi, 7, 21)
        g2 = cv2.cvtColor(blur, cv2.COLOR_BGR2GRAY)
        _, th = cv2.threshold(g2, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, kern, iterations=2)
        cnts, _ = cv2.findContours(th[:, :], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            return self._send_json({"error": "未在区域内检测到前景轮廓"}, 404)
        c = max(cnts, key=cv2.contourArea)
        # 缺省时外周: 用轮廓 + 外接矩形合成封闭环, 降低阈值退化风险
        if cv2.contourArea(c) < 8:
            return self._send_json({"error": "前景占比过小, 请扩大框选"}, 404)
        c = c[:, 0, :]  # Nx2
        # 平滑: 用 approxPolyDP 适度简化, 返回绝对坐标
        eps = 0.5
        ap = cv2.approxPolyDP(c, eps, True).reshape(-1, 2)
        pts = [[int(x0 + p[0]), int(y0 + p[1])] for p in ap]
        return self._send_json({"ok": True, "points": pts, "n": len(pts)})

    def _tplt_submit(self):
        """提交标注(画面尺寸 + 关注矩形 + 重点坐标集 + 每标注意图 + 本次标注id), 后端只记录坐标, 不直接存模板。"""
        data = self._read_json()
        try:
            w, h = int(data.get("w") or 0), int(data.get("h") or 0)
        except Exception:
            w = h = 0
        if w <= 0 or h <= 0:
            return self._send_json({"error": "缺少画面尺寸"}, 400)
        # 方案A: 附带原始截图, 保存到 data/annot_shots/{annotation_id}.png, 坐标与画面绑定
        shot_saved = ""
        shot = str(data.get("shot") or "")
        if shot and "," in shot and shot.startswith("data:image/"):
            try:
                import base64 as _b64
                b64 = shot.split(",", 1)[1]
                raw = _b64.b64decode(b64)
                shot_dir = BASE / "data" / "annot_shots"
                shot_dir.mkdir(parents=True, exist_ok=True)
                shot_name = str(data.get("annotation_id") or "ann") + ".png"
                (shot_dir / shot_name).write_bytes(raw)
                shot_saved = str(Path("data") / "annot_shots" / shot_name)
            except Exception as e:
                log_append(f"[tpltool] 保存标注截图失败: {e}")
        record = {
            "annotation_id": str(data.get("annotation_id") or ""),
            "ts": int(time.time()),
            "image_size": [w, h],
            "shot": shot_saved,
            "rects": data.get("rects") or [],
            "points": data.get("points") or [],
            "strokes": data.get("strokes") or [],
            # 每标注可含一条有序闭合轮廓 points 序列(绝对像素, 保留顺序), 供模型沿轮廓生成 mask 模板
            "contours": data.get("contours") or [],
            # 综合标注: 每项含 id/intent/rect+points(+points_rel)+contour(+contour_rel), 见 coord_note
            "annotations": data.get("annotations") or [],
            "coord_note": data.get("coord_note") or "",
            "meta": data.get("meta") or {},
        }
        try:
            with _ANNOT_LOCK:
                _ANNOT_FILE.parent.mkdir(parents=True, exist_ok=True)
                with _ANNOT_FILE.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            return self._send_json({"error": f"记录标注失败: {e}"}, 500)
        log_append(f"[tpltool] 接收标注 #{record['annotation_id']} "
                   f"矩形{len(record['rects'])}, 重点笔画{len(record['strokes'])}, 描边轮廓{len(record['contours'])}")
        return self._send_json({"ok": True, "annotation_id": record["annotation_id"]})

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
        if resource != "/api/connect" and resource != "/api/set_mode" and resource != "/api/click" and resource != "/api/back" and resource != "/api/run" and resource != "/api/set_config" and resource != "/api/run_daily" and resource != "/api/shutdown" and resource != "/api/tplt_load" and resource != "/api/tplt_submit" and resource != "/api/tplt_contour":
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