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

from ocr_engine import (OCREngine, load_flows, select_flow, ADB_ADDRESS, ADB_PATH,
                        request_stop, get_failures, clear_failures)

BASE = Path(__file__).parent
ENGINE: OCREngine | None = None
ENGINE_LOCK = threading.Lock()
_SERVER = None  # 当前 http server 实例, 用于 /api/shutdown

# 流程运行状态(供前端「运行时关页面确认弹窗」判断, 2026-09-30)
_RUNNING_LOCK = threading.Lock()
_RUNNING = False


def _set_running(v: bool) -> None:
    global _RUNNING
    with _RUNNING_LOCK:
        _RUNNING = v


def _running() -> bool:
    with _RUNNING_LOCK:
        return _RUNNING

# 模板标注工具(人机协同标注): 只记录坐标标注, 不直接保存模板文件
_ANNOT_FILE = BASE / "data" / "tplt_annotations.jsonl"   # 提交给助手的标注记录(追加)
_ANNOT_LOCK = threading.Lock()

# ---- 允许 POST 的 API 白名单 ----
# 只有列在这里的路径才会被 do_POST 交给路由处理, 其余一律 405。
# ⚠ 新增/改动任何 POST 接口时**必须同步这里**, 否则前端会收到 "method not allowed"。
_POST_ROUTES = {
    "/api/connect", "/api/set_mode", "/api/click", "/api/run",
    "/api/stop", "/api/set_config", "/api/run_daily", "/api/shutdown",
    "/api/tplt_load", "/api/tplt_submit", "/api/tplt_contour",
    "/api/failures_clear", "/api/log_clear",
    "/api/fail_cache_clean", "/api/fail_cache_open",   # 里程碑 94 截图缓存
}

# ---- 运行日志环形缓冲 (支持增量拉取) ----
_LOG_LOCK = threading.Lock()
_LOGS: list[str] = []
# 日志磁盘备份: 服务**运行期间**把日志追加落盘(便于本次会话崩溃后排查)。
# 注意: **每次服务启动都会清空**内存缓冲与磁盘文件, 因此备份不跨会话保留 —— 重开 webui
# 后不会再看到上一次会话的残留日志 (需求 2026-10-01)。
_LOG_FILE = BASE / "data" / "webui_runtime_log.txt"
# HTTP 访问日志分流(2026-10-06, 来自协作区 zcode-20261006-2): Handler.log_message 原走 super()
# 写 sys.stderr, 而运行期 stderr 被 _TeeOut 收进运行日志 —— 16:35 实测一次运行导出 3555 行
# 里 1993 行(56%)是 "GET /api/*" 噪声, 严重干扰日志分析。访问行改为落本专用文件(每次服务
# 启动随 _log_reset_history 一并清空, 与运行日志同一「干净状态起步」哲学, 2026-10-01),
# 控制台与运行日志都不再出现。
_HTTP_LOG_FILE = BASE / "data" / "webui_http_log.txt"
_HTTP_LOG_LOCK = threading.Lock()


def _log_persist(text: str) -> None:
    """把日志分片追加到磁盘备份(仅追加; 失败静默, 不阻塞主流程)。

    首次写盘时确保 data/ 目录存在 —— 全新克隆可能缺该目录, 否则日志永远不落盘且无人知晓。
    """
    try:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass


def log_append(text: str) -> None:
    with _LOG_LOCK:
        _LOGS.append(text)
    _log_persist(text)


def _log_reset_history() -> None:
    """启动时清空上一次会话的日志缓存(内存缓冲 + 磁盘备份一并重置)。

    需求(2026-10-01): 每次服务启动都从干净状态开始 —— 服务重启后重开页面不再看到
    上一次会话残留的日志。磁盘备份以**截断**方式重建(而非追加), 避免旧内容越堆越多;
    运行期间落盘的备份仅用于本次会话内崩溃排查, 不跨会话保留。
    """
    with _LOG_LOCK:
        _LOGS.clear()
    try:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG_FILE, "w", encoding="utf-8"):
            pass
    except Exception:
        pass
    # HTTP 访问日志同哲学: 每次服务启动一并清空(2026-10-06, 来自协作区 zcode-20261006-2)
    try:
        _HTTP_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_HTTP_LOG_FILE, "w", encoding="utf-8"):
            pass
    except Exception:
        pass


# ---- 故障存证截图: 缓存/归档/清理 (里程碑 94, 用户方案) ----
# 设计(用户 2026-10-17/18 定案):
#  ①截图**当场同步写盘**在 data/fail_cache/<会话戳>/ (零运行内存; 跨服务重启保留不清);
#  ②**不设自动上限**(不写死张数/MB, 也不在落盘路径做任何统计 → 零额外开销);
#  ③**服务启动时统计一次**缓存大小; 页面首次加载若 ≥ fail_cache_prompt_mb(默认 100, 可在 WebUI 改)
#    则弹提醒, 由**用户选择**清理粒度(全部/>30天/>7天/>1天/暂不) —— 系统永不自动删;
#  ④清理**只删像素**, index.jsonl 元数据墓碑**永久保留**(信息不死: 时间/tag/全量OCR文本仍在),
#    且被清条目标 evicted=true; 清理前后各写一行日志(删除必须"有声", 不静默);
#  ⑤「浏览截图」按钮打开缓存根目录(服务端资源管理器);
#  ⑥点「保存日志」时把**本次会话**的截图复制到 data/fail_archives/<导出时刻>/ + manifest,
#    并把归档路径/张数/淘汰情况写进日志头段(日志内 [故障存证] 行已自带文件名, 天然对应)。
_FAIL_CACHE_DIR = BASE / "data" / "fail_cache"
_FAIL_ARCHIVE_DIR = BASE / "data" / "fail_archives"
_CACHE_PROMPT_PENDING = True      # 本次服务会话是否还未弹出过缓存提醒(刷新页面不重复弹)


def _fail_cache_stat() -> dict:
    """统计缓存: 总字节/张数/会话数/最早一张时间(按**文件名内嵌时间戳**, 不用 mtime —— 复制迁移后 mtime 不可靠)。"""
    total = 0
    count = 0
    sessions = []
    oldest = None
    try:
        if not _FAIL_CACHE_DIR.exists():
            return {"bytes": 0, "count": 0, "sessions": 0, "oldest": None, "session": "", "session_files": 0}
        for d in sorted(_FAIL_CACHE_DIR.iterdir()):
            if not d.is_dir():
                continue
            n = 0
            for f in d.iterdir():
                if f.is_file() and f.suffix.lower() in (".jpg", ".png"):
                    total += f.stat().st_size
                    count += 1
                    n += 1
                    ts = f.stem.split("_")[1] if len(f.stem.split("_")) > 2 else None
                    if ts and ts.isdigit() and len(ts) == 8:
                        if oldest is None or ts < oldest:
                            oldest = ts
            if n:
                sessions.append(d.name)
    except Exception as e:
        print(f"[截图缓存] 统计异常(不影响流程): {e}")
    # 当前会话戳: 直接读模块全局(不用 get_engine() —— 那会在未连接时**创建引擎/加载 OCR 模型**)
    cur = getattr(globals().get("ENGINE"), "_session_stamp", "") or ""
    cur_files = 0
    if cur and (_FAIL_CACHE_DIR / cur).exists():
        cur_files = sum(1 for f in (_FAIL_CACHE_DIR / cur).iterdir() if f.is_file())
    return {"bytes": total, "count": count, "sessions": len(sessions),
            "oldest": oldest, "session": cur, "session_files": cur_files}


def _fail_cache_clean(mode: str = "all", days: int | None = None) -> dict:
    """清理缓存**像素**(用户触发; index.jsonl 墓碑永久保留)。mode: all | days(需 days>0)。

    返回 {removed, bytes, sessions, kept}; 全过程写日志(有声删除), 被删条目标 evicted=true。
    mode="all" 连**本次会话目录**一并清(用户裁决: 日志清了截图就不需要了);
    mode="days" 按会话目录内**最早一张**(文件名时间戳)判定, 今日会话天然不满足"早于 N 天前"故自动保留。
    """
    import json
    stat = _fail_cache_stat()
    if not _FAIL_CACHE_DIR.exists():
        return {"removed": 0, "bytes": 0, "sessions": 0, "kept": 0}
    cutoff = None
    if mode == "days" and days:
        cutoff = time.strftime("%Y%m%d", time.localtime(time.time() - int(days) * 86400))
    removed = rbytes = rsess = kept = 0
    evicted_files = set()
    for d in sorted(_FAIL_CACHE_DIR.iterdir()):
        if not d.is_dir():
            continue
        files = [f for f in d.iterdir() if f.is_file() and f.suffix.lower() in (".jpg", ".png")]
        if not files:
            continue
        # 会话目录内以**最早一张**（按文件名时间戳）判定是否整目录清理
        stamps = [f.stem.split("_")[1] for f in files if len(f.stem.split("_")) > 2 and f.stem.split("_")[1].isdigit()]
        sess_stamp = min(stamps) if stamps else "99999999"
        if mode == "all" or (cutoff and sess_stamp < cutoff):
            for f in files:
                try:
                    rbytes += f.stat().st_size
                    f.unlink()
                    removed += 1
                    evicted_files.add(f"{d.name}/{f.name}")
                except Exception:
                    pass
            rsess += 1
            try:
                d.rmdir()
            except Exception:
                pass
        else:
            kept += len(files)
    # 墓碑: 把 index.jsonl 中被删条目改 evicted=true(记录保留, 只加删除标记)
    marked = 0
    idx = _FAIL_CACHE_DIR / "index.jsonl"
    if evicted_files and idx.exists():
        try:
            lines = idx.read_text(encoding="utf-8").splitlines()
            out = []
            for ln in lines:
                if not ln.strip():
                    continue
                try:
                    e = json.loads(ln)
                    if e.get("file") in evicted_files and not e.get("evicted"):
                        e["evicted"] = True
                        e["evicted_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                        marked += 1
                    out.append(json.dumps(e, ensure_ascii=False))
                except Exception:
                    out.append(ln)
            idx.write_text("\n".join(out) + "\n", encoding="utf-8")
        except Exception as e:
            print(f"[截图缓存] 墓碑标注失败(不影响清理): {e}")
    log_append(f"[截图缓存] 已清理 {removed} 张 / {rbytes/1048576:.1f} MB / {rsess} 个会话"
               f" (mode={mode}{', days=' + str(days) if days else ''}; 保留 {kept} 张; "
               f"墓碑标注 {marked} 条 —— 元数据与 OCR 文本仍保留在 index.jsonl)\n")
    return {"removed": removed, "bytes": rbytes, "sessions": rsess, "kept": kept}


def _fail_cache_archive(ts: str) -> dict:
    """把**缓存目录中现存的全部截图**复制到 data/fail_archives/<ts>/（保留会话子目录结构）+ 写 manifest。

    用户原话: 「点击保存运行日志时, 会将缓存目录的截图复制到一个归档文件夹」—— 即复制缓存的**全部**,
    而非仅本次会话(也避免依赖"服务是否已连接引擎"), 一次导出=缓存的一次快照。
    返回 {dir, count, bytes, sessions, session_files, evicted}。
    """
    import json, shutil
    stat = _fail_cache_stat()
    sess = stat.get("session") or ""
    dst = _FAIL_ARCHIVE_DIR / ts
    copied = []
    total = 0
    sess_count = 0
    try:
        dst.mkdir(parents=True, exist_ok=True)
        if _FAIL_CACHE_DIR.exists():
            for d in sorted(_FAIL_CACHE_DIR.iterdir()):
                if not d.is_dir():
                    continue
                files = sorted(f for f in d.iterdir() if f.is_file() and f.suffix.lower() in (".jpg", ".png"))
                if not files:
                    continue
                sub = dst / d.name
                sub.mkdir(parents=True, exist_ok=True)
                for f in files:
                    shutil.copy2(f, sub / f.name)
                    copied.append(f"{d.name}/{f.name}")
                    total += (sub / f.name).stat().st_size
                    if d.name == sess:
                        sess_count += 1
        # manifest: 逐张 文件名 ↔ 中文tag ↔ 时刻; 并标注缓存中被清理(evicted)的条目
        idxmap, evicted = {}, []
        idx = _FAIL_CACHE_DIR / "index.jsonl"
        if idx.exists():
            for ln in idx.read_text(encoding="utf-8").splitlines():
                try:
                    e = json.loads(ln)
                except Exception:
                    continue
                idxmap[e.get("file", "")] = e
                if e.get("evicted"):
                    evicted.append(e.get("file", ""))
        lines = [f"# 归档清单 (生成 {time.strftime('%Y-%m-%d %H:%M:%S')})",
                 f"# 归档目录: data/fail_archives/{ts}",
                 f"# 归档张数: {len(copied)} 张 / {total} 字节 ({total/1048576:.2f} MB)"
                 f"  其中本次会话 {sess_count} 张",
                 "# 说明: 日志正文 [故障存证] 行末已自带文件名, 与下表一一对应;",
                 "#      「(已淘汰)」= 该图已被缓存清理(像素已删), 但其**存证记录(时间/tag/全量OCR文本)**",
                 "#      永久保留在 data/fail_cache/index.jsonl, 可按文件名回查 —— 不是导出出错。",
                 "-" * 70]
        for n in copied:
            e = idxmap.get(n, {})
            lines.append(f"{n:56s} {str(e.get('tag','?'))[:16]:16s} {e.get('ts','')}")
        for f in evicted:
            if f not in copied:
                e = idxmap.get(f, {})
                lines.append(f"{f:56s} {str(e.get('tag','?'))[:16]:16s} {e.get('ts','')}  ← (已淘汰)")
        (dst / "manifest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as e:
        log_append(f"[截图归档] 归档异常(不影响日志导出): {e}\n")
    return {"dir": str(dst), "count": len(copied), "bytes": total,
            "sessions": len({c.split("/")[0] for c in copied}), "session_files": sess_count,
            "evicted": len([f for f in evicted if f not in copied])}


class _TeeOut:
    """把 print 输出同时写入日志缓冲, 便于前端实时流式查看。"""
    def __init__(self, real, buf):
        self._real = real
        self._buf = buf

    def write(self, s: str) -> int:
        if s:
            with _LOG_LOCK:
                self._buf.append(s)
            _log_persist(s)
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


def _ui_build() -> str:
    """webui.html 版本戳(文件 mtime_ns)。

    响应「/」时注入页面 <meta name="ui-build">, /api/status 同步返回 ui_build;
    前端比对两者, 不一致 = 浏览器里的页面落后于服务端(webui 升级重启后未刷新的
    旧标签页), 前端顶部横幅提示刷新 (2026-10-12 用户确认方案, 根治
    「重启 webui 服务后旧页面静默运行」—— 关闭确认不弹问题即此因)。
    """
    try:
        return str((BASE / "webui.html").stat().st_mtime_ns)
    except OSError:
        return ""


def _status() -> dict:
    global _CACHE_PROMPT_PENDING
    eng = get_engine()
    # screen=实机分辨率(adb 直读, 2026-10-07 用户反馈修正); 读取失败回退引擎工作区
    # (MAA 截图长边 1280 缩放, 与实机可能不同)。work=引擎工作区, 前端悬停提示用。
    disp = getattr(eng, "display_w", 0)
    # 里程碑 94: 截图缓存大小(前端常驻显示) + 首次加载是否弹提醒(服务端记录, 刷新页面不重复弹)
    cst = _fail_cache_stat()
    thr = float(eng.config.get("fail_cache_prompt_mb", 100) or 100)
    cmb = cst["bytes"] / 1048576
    prompt = bool(_CACHE_PROMPT_PENDING and cmb >= thr)
    _CACHE_PROMPT_PENDING = False
    return {
        "connected": _is_connected(eng),
        "screen": ([eng.display_w, eng.display_h] if disp
                   else ([eng.screen_w, eng.screen_h] if eng.screen_w else None)),
        "work": [eng.screen_w, eng.screen_h] if eng.screen_w else None,
        "flow_dir": str(BASE / "flows"),
        "debug_click": bool(getattr(eng, "debug_click", False)),
        "running": _running(),
        # 运行中模块(run_daily 维护): 前端据此锁定该模块的 ⚙ 与设置面板(2026-10-11 用户需求)
        "current_module": getattr(eng, "current_module", None),
        # 关闭页面确认开关(纯 WebUI 偏好, 引擎不读); 流程运行中前端仍强制确认
        "confirm_page_close": bool(eng.config.get("confirm_page_close", True)),
        # webui.html 版本戳: 前端与自身 meta 比对判断页面是否落后于服务端 (2026-10-12)
        "ui_build": _ui_build(),
        # 里程碑 94: 截图缓存(前端状态栏常驻显示 + 首屏超阈值弹提醒)
        "fail_cache": {"mb": round(cmb, 2), "count": cst["count"], "sessions": cst["sessions"],
                       "oldest": cst["oldest"], "threshold_mb": thr, "exceed": cmb >= thr,
                       "prompt": prompt},
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
                "claim_hb": bool(eng.config.get("claim_hb", False)),
                "enable_pollin": bool(eng.config.get("enable_pollin", True)),
                "enable_like": bool(eng.config.get("enable_like", False)),
                "log_click_pos": bool(eng.config.get("log_click_pos", False)),
                "use_cache_pos": bool(eng.config.get("use_cache_pos", False)),
                "fail_cache_prompt_mb": float(eng.config.get("fail_cache_prompt_mb", 100) or 100),
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
            if "claim_hb" in data:
                eng.update_config(claim_hb=bool(data["claim_hb"]))
            if "enable_shine" in data:
                eng.update_config(enable_shine=bool(data["enable_shine"]))
            if "enable_pollin" in data:
                eng.update_config(enable_pollin=bool(data["enable_pollin"]))
            if "enable_like" in data:
                eng.update_config(enable_like=bool(data["enable_like"]))
            if "log_click_pos" in data:
                eng.update_config(log_click_pos=bool(data["log_click_pos"]))
            if "use_cache_pos" in data:
                eng.update_config(use_cache_pos=bool(data["use_cache_pos"]))
            # 2026-10-11 补: 里程碑 82 给 ⚙ 面板加 enable_mine/enable_rabbit 时漏了本处理器,
            # 勾选被静默丢弃(config.json 无键, if_config 读 None) —— 用户实测矿洞勾选无效即此因。
            if "enable_mine" in data:
                eng.update_config(enable_mine=bool(data["enable_mine"]))
            if "enable_rabbit" in data:
                eng.update_config(enable_rabbit=bool(data["enable_rabbit"]))
            if "enable_water" in data:
                eng.update_config(enable_water=bool(data["enable_water"]))
            if "confirm_page_close" in data:
                eng.update_config(confirm_page_close=bool(data["confirm_page_close"]))
            # 里程碑 94: 截图缓存提醒阈值(MB) —— 必进白名单, 否则 WebUI 保存被静默丢弃(里程碑 87 教训)
            if "fail_cache_prompt_mb" in data:
                try:
                    eng.update_config(fail_cache_prompt_mb=max(1.0, float(data["fail_cache_prompt_mb"])))
                except (TypeError, ValueError):
                    pass
            now = bool(eng.config.get("enable_switch", False))
            log_append(f"[config] 切换账号功能 {'启用' if now else '关闭'}"
                       + (f", 目标尾部={eng.config.get('target_tail')}" if now else ""))
            log_append(f"[config] 领取奖励功能1在线礼包={'开' if eng.config.get('claim_online') else '关'}"
                       f", 功能2花灵派对={'开' if eng.config.get('claim_party') else '关'}"
                       f", 功能3奇妙花宝={'开' if eng.config.get('claim_hb') else '关'}"
                       f", 闪耀委托挑战={'开' if eng.config.get('enable_shine') else '关'}"
                       f", 摇钱树浇水={'开' if eng.config.get('enable_water', True) else '关'}"
                       f", 矿洞探险={'开' if eng.config.get('enable_mine', False) else '关'}"
                       f", 守望兔子={'开' if eng.config.get('enable_rabbit', False) else '关'}"
                       f", 好友采粉={'开' if eng.config.get('enable_pollin', True) else '关'}"
                       f", 社区点赞={'开' if eng.config.get('enable_like', False) else '关'}")
            log_append(f"[config] 记录按钮位置={'开' if eng.config.get('log_click_pos', False) else '关'}"
                       f", 使用缓存位置={'开' if eng.config.get('use_cache_pos', False) else '关'}"
                       f" (两项默认关闭; 关闭时只认实时识别, 不用历史坐标盲点)")
            return self._send_json({
                "ok": True, "changed": pre != now, "enable_switch": now,
                "claim_online": bool(eng.config.get("claim_online", True)),
                "claim_party": bool(eng.config.get("claim_party", True)),
                "claim_hb": bool(eng.config.get("claim_hb", False)),
                "enable_shine": bool(eng.config.get("enable_shine", False)),
                "enable_pollin": bool(eng.config.get("enable_pollin", True)),
                "enable_like": bool(eng.config.get("enable_like", False)),
                "log_click_pos": bool(eng.config.get("log_click_pos", False)),
                "use_cache_pos": bool(eng.config.get("use_cache_pos", False)),
            })

        if api == "connect" and self.command == "POST":
            return self._connect()
        if api == "set_mode" and self.command == "POST":
            data = self._read_json()
            _set_mode(data.get("mode", "use"))
            return self._send_ok()
        if api == "screen" and self.command == "GET":
            return self._screen()
        if api == "ocr" and self.command == "GET":
            return self._ocr()
        if api == "failures" and self.command == "GET":
            return self._failures()
        if api == "failures_clear" and self.command == "POST":
            clear_failures()
            return self._send_ok()
        if api == "click" and self.command == "POST":
            return self._click()
        if api == "run" and self.command == "POST":
            return self._run()
        if api == "stop" and self.command == "POST":
            return self._stop()
        if api == "log" and self.command == "GET":
            return self._log()
        if api == "log_download" and self.command == "GET":
            return self._log_download()
        if api == "log_clear" and self.command == "POST":
            return self._log_clear()
        # ---- 故障存证截图: 缓存信息 / 清理 / 浏览目录 (里程碑 94) ----
        if api == "fail_cache_info" and self.command == "GET":
            st = _fail_cache_stat()
            thr = float(get_engine().config.get("fail_cache_prompt_mb", 100) or 100)
            return self._send_json({**st, "mb": st["bytes"] / 1048576, "threshold_mb": thr,
                                    "exceed": st["bytes"] / 1048576 >= thr})
        if api == "fail_cache_clean" and self.command == "POST":
            data = self._read_json() if int(self.headers.get("Content-Length") or 0) else {}
            return self._send_json({"ok": True,
                                    **_fail_cache_clean(str(data.get("mode") or "all"), data.get("days"))})
        if api == "fail_cache_open" and self.command == "POST":
            import os
            try:
                _FAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                os.startfile(str(_FAIL_CACHE_DIR))
                log_append(f"[截图缓存] 已打开缓存目录: {_FAIL_CACHE_DIR}\n")
                return self._send_json({"ok": True, "dir": str(_FAIL_CACHE_DIR)})
            except Exception as e:
                return self._send_json({"ok": False, "error": str(e)}, 500)
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
        # 版本戳注入: 页面据此与 /api/status 的 ui_build 比对, 旧页面顶部横幅提示刷新 (2026-10-12)
        body = body.replace(b"__UI_BUILD__", _ui_build().encode("ascii"))
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
        try:
            target.relative_to(allow)
        except ValueError:
            return self._send_json({"error": "仅允许载入 debug/ 目录下的图片"}, 400)
        if not target.is_file():
            return self._send_json({"error": "文件不存在"}, 400)
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

    # ---- API: 截图 (只回图像, 不做 OCR) ----
    def _screen(self):
        """预览帧: 只做「JPEG 编码」, **不做 OCR**; 流程运行期直接复用引擎最近一帧, 不再自己截图。

        ⚠ 性能(2026-10-02): 原实现在这里每帧做一次**全屏 OCR** 并返回文字框,
          前端每 1.5s 拉一次 → 单轮 1183 次全屏 OCR, 是「跑一轮 CPU >50%」的主凶。
          文字框已拆到按需接口 GET /api/ocr。
        ⚠ 性能(2026-10-03): 运行期引擎本身在连续截图, 预览再各自 post_screencap 会与引擎
          争抢同一 ADB 控制器(拖慢引擎步骤)。改为: 引擎 2s 内截过帧 → 直接返回其 last_frame
          (只花 JPEG 编码, 不动 ADB); 超过 2s(空闲期)才自己截 —— 空闲期行为与原来一致。
        """
        eng = get_engine()
        if not _is_connected(eng):
            return self._send_json({"error": "未连接", "status": _status()}, 503)
        img = getattr(eng, "last_frame", None)
        if img is None or (time.monotonic() - getattr(eng, "last_frame_ts", 0.0)) > 2.0:
            img = eng.screenshot()
        if img is None:
            return self._send_json({"error": "截图失败"}, 500)
        jpg = _img_to_jpeg_b64(img)
        return self._send_json({
            "jpeg": jpg,
            "w": eng.screen_w, "h": eng.screen_h,
        })

    # ---- API: 按需 OCR 标注框 (用户点「取框」/勾选 OCR 标注时才调) ----
    def _ocr(self):
        eng = get_engine()
        if not _is_connected(eng):
            return self._send_json({"error": "未连接", "status": _status()}, 503)
        img = eng.screenshot()
        if img is None:
            return self._send_json({"error": "截图失败"}, 500)
        return self._send_json({"boxes": _ocr_boxes(img)})

    # ---- API: 功能失败清单 (增量拉取, 供前端弹窗提醒) ----
    def _failures(self):
        after = 0
        try:
            after = max(0, int(self._query("after") or 0))
        except (TypeError, ValueError):
            after = 0
        items, nxt = get_failures(after)
        return self._send_json({"items": items, "next": nxt})

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
                    {"key": "claim_hb", "type": "switch", "label": "功能3 · 奇妙花宝",
                     "desc": "家园→奇妙花宝→奇妙特权，领奇妙礼包每日/每周/每月三档", "value": bool(eng.config.get("claim_hb", False))},
                ]
            if mid == "startup":
                return [
                    {"key": "enable_switch", "type": "switch", "label": "切换账号",
                     "desc": "登录前自动切换到目标账号", "value": bool(eng.config.get("enable_switch", False))},
                    {"key": "target_tail", "type": "text", "label": "目标账号尾部",
                     "desc": "匹配 abc****de 的末尾数字", "value": eng.config.get("target_tail", "")},
                ]
            if mid == "social":
                # 2026-10-07 用户反馈: ⚙ 只有 startup/claim 可点, 其余模块被 disabled —— 补齐
                # social 的真实 if_config 开关(与 flow_social.json §4.1.1~4.1.4/4.2/4.3
                # 一一对应, 默认值与 data/config.example.json 一致)。plant/energy/daily/idle
                # 四个流程无任何 if_config, 返回 [] → ⚙ 可点开面板显示「暂无独立子功能」说明。
                # 2026-10-11: 新增浇水开关 enable_water(4.1.1, 默认 true); 同批修 set_config
                # 白名单缺 enable_mine/enable_rabbit 导致勾选被静默丢弃的缺陷(见上)。
                return [
                    {"key": "enable_water", "type": "switch", "label": "摇钱树浇水",
                     "desc": "家族活动 4.1.1 · 每日浇水 X/3(含生效复核: 点击被吞自动重试 1 次)", "value": bool(eng.config.get("enable_water", True))},
                    {"key": "enable_shine", "type": "switch", "label": "闪耀委托挑战",
                     "desc": "家族活动 4.1.2 · 每日 10-21 时开放时段内执行", "value": bool(eng.config.get("enable_shine", False))},
                    {"key": "enable_mine", "type": "switch", "label": "矿洞探险",
                     "desc": "家族活动 4.1.3 · 每日礼包领取/次日「明日再来」跳过", "value": bool(eng.config.get("enable_mine", False))},
                    {"key": "enable_rabbit", "type": "switch", "label": "守望兔子",
                     "desc": "家族活动 4.1.4 · 占位待开发, 开启暂无实际动作", "value": bool(eng.config.get("enable_rabbit", False))},
                    {"key": "enable_pollin", "type": "switch", "label": "好友采粉",
                     "desc": "4.2 · 密友+好友逐页采集花粉, 无可采则回自己家园", "value": bool(eng.config.get("enable_pollin", True))},
                ]
            if mid == "daily":
                # 2026-10-12 用户决策: 社区点赞自社交模块迁入每日任务(点赞唯一价值=完成每日任务;
                # daily 按手账「献上点赞」行进度 a<b 门控执行, 已完成/行缺失跳过)。
                return [
                    {"key": "enable_like", "type": "switch", "label": "社区点赞",
                     "desc": "完成手账「为精美搭配献上点赞吧」任务(每期上限 20 次; 任务已完成则跳过)",
                     "value": bool(eng.config.get("enable_like", False))},
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
            # 全局识别设置(默认关; 供右栏「识别设置」面板回显)
            "log_click_pos": bool(eng.config.get("log_click_pos", False)),
            "use_cache_pos": bool(eng.config.get("use_cache_pos", False)),
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
        # on_fail 处置(2026-10-06 用户方案A): 勾选模块统一 skip「跳过继续」, 但
        # **保留 daily.json 里声明为 stop_round 的模块**(当前即 startup) —— 启动失败
        # 即真异常(#1 修复后签到窗盖底栏的误报已根治), 按用户 10-03 决策「宁可当天
        # 不跑, 也不能用错误账号/未登录状态跑完」应整轮停止, 不再被统一 skip 废掉。
        # 此前无条件改写使该保护在勾选路径从未生效(16:35 实弹: startup 软失败靠
        # skip 才没中止整轮, 当日属侥幸)。startup 真失败时后续模块只会各自空转,
        # 白跑 ~10-20 分钟且日志全红 —— 整轮停止正是为这种时刻设计的。
        chosen = []
        for m in all_modules:
            if m.get("id") not in selected:
                continue
            m = dict(m)
            if m.get("on_fail") != "stop_round":
                m["on_fail"] = "skip"
            chosen.append(m)
        if not chosen:
            return self._send_json({"error": "未勾选任何任务"}, 400)
        plan["modules"] = chosen
        plan["description"] = "Web UI 使用界面按勾选模块调度"
        name = plan.get("name", "每日编排")
        if _running():
            return self._send_json({"error": "已有流程在运行, 请先停止"}, 409)
        def job():
            eng = get_engine()
            try:
                if not _is_connected(eng):
                    eng.connect()
            except Exception as e:
                log_append(f"[run] 连接失败: {e}")
            _set_running(True)
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
                _set_running(False)
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
        if _running():
            return self._send_json({"error": "已有流程在运行, 请先停止"}, 409)
        def job():
            eng = get_engine()
            try:
                if not _is_connected(eng):
                    eng.connect()
            except Exception as e:
                log_append(f"[run] 连接失败: {e}")
            _set_running(True)
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
                _set_running(False)
        threading.Thread(target=job, daemon=True).start()
        return self._send_json({"ok": True, "started": name})

    # ---- API: 增量日志 ----
    def _log(self):
        # after 防负(BUG-10, 2026-10-03): 负数会让 _LOGS[after:] 变成"取末尾 N 条"的 Python 负切片,
        # 返回错行的日志且 next 变负, 前端增量轮询从此错乱。与 /api/failures 的 max(0,...) 同款防御。
        after = max(0, int(self._query("after") or 0))
        with _LOG_LOCK:
            if after >= len(_LOGS):
                return self._send_json({"next": after, "lines": []})
            lines = _LOGS[after:]
        return self._send_json({"next": after + len(lines), "lines": lines})

    # ---- API: 导出日志为 txt 文件 ----
    def _log_download(self):
        """把服务端日志缓冲**全量**导出为 .txt 下载。

        注意: 导出的是服务端缓冲的全部内容(含页面打开之前、**本次会话内**的历史),
        不只是前端 DOM 里已收到的那部分; 因此刷新页面后依然能拿到完整日志。
        服务每次启动都会清空缓冲(_log_reset_history), 故不包含上一次会话的日志 (2026-10-01)。
        """
        with _LOG_LOCK:
            lines = list(_LOGS)
        text = "".join(lines)
        ts = time.strftime("%Y%m%d_%H%M%S")
        # 里程碑 94: 归档本次会话的截图(复制) + manifest, 并把契约写进日志头段
        arc = _fail_cache_archive(ts)
        stat = _fail_cache_stat()
        head = (f"# FlowerAutoAssistant 运行日志\n"
                f"# 导出时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                # _LOGS 存的是 _TeeOut.write() 的写入分片(print 的正文与换行是两次 write),
                # len(_LOGS) 是分片数 ≠ 行数(实测 2113 分片只对应 1202 行), 必须按实际换行数统计。
                f"# 总行数: {text.count(chr(10))}\n"
                f"# 归档目录: data/fail_archives/{ts}\n"
                f"# 归档截图: {arc['count']} 张 / {arc['bytes']/1048576:.2f} MB"
                f" (覆盖 {arc['sessions']} 个会话; 其中本次会话 {arc['session_files']} 张)\n"
                f"# 截图清单: data/fail_archives/{ts}/manifest.txt (文件名 ↔ 中文tag ↔ 时刻)\n"
                f"# 对应关系: 正文 [故障存证] 行末已自带文件名; 若该文件被缓存清理(像素已删), 其\n"
                f"#           存证记录(时间/tag/全量OCR文本)永久保留在 data/fail_cache/index.jsonl\n"
                + "-" * 40 + "\n")
        # 前缀 \ufeff(BOM) 让 Windows 记事本按 UTF-8 打开, 避免中文乱码
        body = ("\ufeff" + head + text).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Disposition",
                         f'attachment; filename="faa_log_{ts}.txt"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- API: 清空运行日志 (UI「清除日志」按钮, 2026-10-03) ----
    def _log_clear(self):
        """清空服务端日志缓冲 + 磁盘备份, 让页面从干净状态重看一轮日志。

        与启动时的 `_log_reset_history` 同语义(内存与磁盘一并清), 这里复用同一函数。
        与「保存日志」配对: 只清前端 DOM 会变成"页面空的、导出却还是旧的"(导出读的是服务端缓冲),
        只清服务端又会让下次增量拉取从新缓冲中部开始 —— 故三者必须一起动, 且**回 next=0**,
        前端收到后必须把 logCursor 复位(见 webui.html clearLog)。
        清完补一条标记日志, 让"清理确实生效、何时清理"可被验证(否则清空后页面一片空白, 无从判断)。

        ⚠ 里程碑 94(用户裁决): 本按钮**同时清理截图缓存像素**(日志没了, 截图自然也不需要);
        index.jsonl 元数据墓碑**保留**(记录不死), 被清图标注 evicted。清理行由 _fail_cache_clean 落到日志。
        """
        _log_reset_history()
        log_append(f"[webui] 运行日志已被手动清除 {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        _fail_cache_clean("all")   # 同时清缓存像素(本次会话目录同样清理 —— 用户明确要求"没有日志就不需要截图")
        return self._send_json({"ok": True, "next": 0})

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
        if self.path.split("?", 1)[0] not in _POST_ROUTES:
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
        # HTTP 访问行分流到专用文件(2026-10-06, 来自协作区 zcode-20261006-2): 不再走
        # super() 写 sys.stderr —— 运行期 stderr 被 _TeeOut 收进运行日志, 16:35 实测一次
        # 运行 56% 行数是 "GET /api/*" 噪声。行格式与 BaseHTTPRequestHandler.log_message
        # 保持一致, 仅落盘目标不同(data/webui_http_log.txt, 每次服务启动清空)。
        try:
            line = "%s - - [%s] %s\n" % (
                self.address_string(), self.log_date_time_string(), fmt % args)
            with _HTTP_LOG_LOCK:
                with open(_HTTP_LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(line)
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

    # 每次启动都清空日志缓存(内存 + 磁盘), 避免重开 webui 后仍看到上一次会话的残留日志 (2026-10-01)
    _log_reset_history()
    _set_running(False)
    # 启动即写一条日志: 既是落盘链路的第一条实证(此前启动横幅走裸 print, 不落盘 → 文件永远不生成),
    # 也让「清空缓存后从干净状态起步、且本次启动可见」这件事可被验证 (2026-10-01)。
    log_append(f"[webui] 服务启动 {time.strftime('%Y-%m-%d %H:%M:%S')} "
               f"-> http://127.0.0.1:{args.port}/\n")

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