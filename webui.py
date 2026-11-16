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


def _try_claim_running() -> bool:
    """原子 check-and-set(Q01, batch-04): 空闲则置 running=True 并返回 True; 已运行返回 False。

    改前两个运行入口(/api/run 与 /api/run_daily)在 HTTP 线程 `_running()` 判定 → 200 返回 →
    job 子线程 `eng.connect()`(数秒) 之后才 `_set_running(True)` —— 判定与置位之间是无锁窗口。
    载体 ThreadingHTTPServer 每请求一线程, 前端仅点击时 disable + 1.5s 轮询回传 running,
    双击/双按钮/双入口并发即可同时穿过窗口各起一份 job, 两线程并发驱动同一引擎单例
    (ENGINE_LOCK 只保护创建): ①交替点击模拟器; ②花宝购买硬上限 self._buy_count(单轮 1 次
    防烧仙豆)并发下失效 = 真实金钱资源; ③失败登记/OCR 统计交叉污染。
    现判定与置位在同一把 _RUNNING_LOCK 临界区内完成, 第二请求必 409 —— 事故从
    「偶发难复现」变「结构性不可能」。
    """
    global _RUNNING
    with _RUNNING_LOCK:
        if _RUNNING:
            return False
        _RUNNING = True
        return True

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
_LOG_MAX_LINES = 20000          # 最多保留的写入分片数(print 正文与换行各算一片); 超出从头部丢弃
_LOG_BASE = 0                   # 被丢弃的头部片数, /api/log 的游标 = 全局序号
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


def _append_log(text: str) -> None:
    """追加一个日志分片；超过上限时丢弃最旧的头部并推进全局序号。"""
    global _LOG_BASE
    with _LOG_LOCK:
        _LOGS.append(text)
        overflow = len(_LOGS) - _LOG_MAX_LINES
        if overflow > 0:
            del _LOGS[:overflow]
            _LOG_BASE += overflow


def log_append(text: str) -> None:
    _append_log(text)
    _log_persist(text)


def _log_reset_history() -> None:
    """启动时清空上一次会话的日志缓存(内存缓冲 + 磁盘备份一并重置)。

    需求(2026-10-01): 每次服务启动都从干净状态开始 —— 服务重启后重开页面不再看到
    上一次会话残留的日志。磁盘备份以**截断**方式重建(而非追加), 避免旧内容越堆越多;
    运行期间落盘的备份仅用于本次会话内崩溃排查, 不跨会话保留。
    """
    global _LOG_BASE
    with _LOG_LOCK:
        _LOGS.clear()
        _LOG_BASE = 0
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
#  ③**统计结果缓存 10s**（W2-003）：/api/status 每 1.5s 轮询不重复遍历大目录；清理/归档强制刷新；
#    页面首次加载若 ≥ fail_cache_prompt_mb(默认 100, 可在 WebUI 改)
#    则弹提醒, 由**用户选择**清理粒度(全部/>30天/>7天/>1天/暂不) —— 系统永不自动删;
#  ④清理**只删像素**, index.jsonl 元数据墓碑**永久保留**(信息不死: 时间/tag/全量OCR文本仍在),
#    且被清条目标 evicted=true; 清理前后各写一行日志(删除必须"有声", 不静默);
#  ⑤「浏览截图」按钮打开缓存根目录(服务端资源管理器);
#  ⑥点「保存日志」时把**本次会话**的截图复制到 data/fail_archives/<导出时刻>/ + manifest,
#    并把归档路径/张数/淘汰情况写进日志头段(日志内 [故障存证] 行已自带文件名, 天然对应)。
#  ⑦「清除日志」会连缓存像素一起删(里程碑 94), 但若这些像素**已被⑥归档**, 提示文案必须改口径
#    (2026-10-26 用户反馈: 保存后再清除仍提示"将删除截图缓存/不可恢复", 属误导) ——
#    故归档时记录文件名集合, 状态接口回传 archived.all; 全部已归档则说明"只删副本, 归档不受影响"。
_FAIL_CACHE_DIR = BASE / "data" / "fail_cache"
_FAIL_ARCHIVE_DIR = BASE / "data" / "fail_archives"
_CACHE_PROMPT_PENDING = True      # 本次服务会话是否还未弹出过缓存提醒(刷新页面不重复弹)
_LAST_ARCHIVE = None              # 最近一次「保存日志」归档: {ts,count,bytes,files:set(相对路径)}
# W2-003: /api/status 每 1.5s 调一次, 不能每次都遍历 fail_cache；缓存 10s, 清理/归档时强制刷新。
_FAIL_CACHE_STAT_LOCK = threading.Lock()
_FAIL_CACHE_STAT_CACHE: dict | None = None
_FAIL_CACHE_STAT_TS = 0.0
_FAIL_CACHE_STAT_TTL = 10.0


def _fail_cache_stat(force: bool = False) -> dict:
    """统计缓存: 总字节/张数/会话数/最早一张时间(按**文件名内嵌时间戳**, 不用 mtime —— 复制迁移后 mtime 不可靠)。

    files = 现存像素的相对路径集合(`<会话>/<文件名>`), 供「是否全部已归档」比对(2026-10-26)。
    结果缓存 10s(W2-003): /api/status 每 1.5s 调用, 避免反复遍历大目录; 清理/归档传 force=True。
    """
    global _FAIL_CACHE_STAT_CACHE, _FAIL_CACHE_STAT_TS
    now = time.time()
    with _FAIL_CACHE_STAT_LOCK:
        cached = _FAIL_CACHE_STAT_CACHE
        cached_ts = _FAIL_CACHE_STAT_TS
    if not force and cached is not None and (now - cached_ts) < _FAIL_CACHE_STAT_TTL:
        return cached
    total = 0
    count = 0
    sessions = []
    files = set()
    oldest = None
    try:
        if not _FAIL_CACHE_DIR.exists():
            out = {"bytes": 0, "count": 0, "sessions": 0, "oldest": None, "session": "",
                   "session_files": 0, "files": files}
            with _FAIL_CACHE_STAT_LOCK:
                _FAIL_CACHE_STAT_CACHE = out
                _FAIL_CACHE_STAT_TS = time.time()
            return out
        for d in sorted(_FAIL_CACHE_DIR.iterdir()):
            if not d.is_dir():
                continue
            n = 0
            for f in d.iterdir():
                if f.is_file() and f.suffix.lower() in (".jpg", ".png"):
                    total += f.stat().st_size
                    count += 1
                    n += 1
                    files.add(f"{d.name}/{f.name}")
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
    out = {"bytes": total, "count": count, "sessions": len(sessions),
           "oldest": oldest, "session": cur, "session_files": cur_files, "files": files}
    with _FAIL_CACHE_STAT_LOCK:
        _FAIL_CACHE_STAT_CACHE = out
        _FAIL_CACHE_STAT_TS = time.time()
    return out


def _invalidate_fail_cache_stat() -> None:
    """清理/归档后让下一次 /api/status 重新统计。"""
    global _FAIL_CACHE_STAT_CACHE, _FAIL_CACHE_STAT_TS
    with _FAIL_CACHE_STAT_LOCK:
        _FAIL_CACHE_STAT_CACHE = None
        _FAIL_CACHE_STAT_TS = 0.0


def _fail_cache_clean(mode: str = "all", days: int | None = None) -> dict:
    """清理缓存**像素**(用户触发; index.jsonl 墓碑永久保留)。mode: all | days(需 days>0)。

    返回 {removed, bytes, sessions, kept}; 全过程写日志(有声删除), 被删条目标 evicted=true。
    mode="all" 连**本次会话目录**一并清(用户裁决: 日志清了截图就不需要了);
    mode="days" 按会话目录内**最早一张**(文件名时间戳)判定, 今日会话天然不满足"早于 N 天前"故自动保留。
    """
    import json
    stat = _fail_cache_stat(force=True)
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
    _invalidate_fail_cache_stat()
    return {"removed": removed, "bytes": rbytes, "sessions": rsess, "kept": kept}


def _fail_cache_archive(ts: str) -> dict:
    """把**缓存目录中现存的全部截图**复制到 data/fail_archives/<ts>/（保留会话子目录结构）+ 写 manifest。

    用户原话: 「点击保存运行日志时, 会将缓存目录的截图复制到一个归档文件夹」—— 即复制缓存的**全部**,
    而非仅本次会话(也避免依赖"服务是否已连接引擎"), 一次导出=缓存的一次快照。
    返回 {dir, count, bytes, sessions, session_files, evicted}。
    """
    global _LAST_ARCHIVE
    import json, shutil
    stat = _fail_cache_stat(force=True)
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
    else:
        # 记录本次归档覆盖的文件集合: 清除日志时据此判断「缓存像素是否全部已有归档副本」
        _LAST_ARCHIVE = {"ts": ts, "count": len(copied), "bytes": total, "files": set(copied)}
    _invalidate_fail_cache_stat()
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
            _append_log(s)
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
        # 2026-10-26: archived.all = 现存缓存像素是否**全部**已有「保存日志」归档副本
        # (供「清除日志」提示改口径: 已归档则只删副本, 不再警告"不可恢复")
        "fail_cache": {"mb": round(cmb, 2), "count": cst["count"], "sessions": cst["sessions"],
                       "oldest": cst["oldest"], "threshold_mb": thr, "exceed": cmb >= thr,
                       "prompt": prompt,
                       "archived": ({"ts": _LAST_ARCHIVE["ts"], "count": _LAST_ARCHIVE["count"],
                                     "mb": round(_LAST_ARCHIVE["bytes"] / 1048576, 2),
                                     "all": bool(cst["files"]) and cst["files"] <= _LAST_ARCHIVE["files"]}
                                    if _LAST_ARCHIVE else None)},
    }


def _set_mode(mode: str) -> None:
    """切换测试/使用模式。测试模式=每步截图保存点击区。"""
    eng = get_engine()
    eng.debug_click = (mode == "test")
    if eng.debug_click:
        eng.debug_dir = BASE / "data" / "click_debug"
        eng.debug_dir.mkdir(parents=True, exist_ok=True)
        eng._click_seq = getattr(eng, "_click_seq", 0)


# ---- F06+W03(batch-04, 2026-11-14): set_config 键元数据表 —— 单一事实来源 ----
# 背景(评估报告 R3/R8): 新增 1 个配置键此前要同步改 4-5 处 —— ①set_config 白名单 if-chain、
# ②[config] 日志文案、③set_config 响应回显、④⚙面板 _module_settings meta、⑤WPF
# FaaProxy.SetConfigKeys(FaaProxy.cs:241-251, 不改 C#) —— 里程碑 82/87「勾选被静默丢弃」
# 两次事故均因 if-chain 漏键(事故注释曾钉在原 if-chain 内: 82=enable_mine/enable_rabbit
# 漏处理器致矿洞勾选无效; 87=fail_cache_prompt_mb「必进白名单」教训)。
# 本表把 webui 侧①~④全部改为由同一张表生成: 新增键 = 表内加一行 + (如需 ⚙ 面板)
# _MODULE_SETTINGS 归组; ⑤由 tools/check_project.py webui 契约段对账提取比对(漂移即 WARN)。
# 字段:
#   type        bool/text/int/float/enum —— set_config 入参解析方式;
#   bad_int     int 键解析失败回退值;  clamp (lo,hi) —— int 键钳制;
#   min_v       float 键下限(解析失败跳过不落盘);
#   enum_values/enum_error —— enum 键合法值集 / 白名单外 400 文案(拒收不落配置不静默改默认);
#   log_line    [config] 日志行号(1/2/3); log_fmt: "sw"=开/关, "sw2"=启用/关闭(空格分隔),
#               "raw"=原值; log_default: 缺省值, _NO_DEFAULT 表示 .get 不带默认值(逐字节保持
#               改前形态); log_cond="switch_now"=仅切换账号启用时渲染;
#               log_value="now"=取应用后的 enable_switch 现值; 整键 None=不出现在日志文案;
#   echo        回显缺省(None=不回显; "post"=回显应用后的 enable_switch 现值;
#               "enum_none"=str(get(key,'none') or 'none'); 布尔值=bool(get(key, 该值)));
#   meta        (面板label, 面板desc), None=不在 ⚙ 面板; meta_default=面板回显缺省。
# 表内键序 = set_config 应用顺序(与改前 if-chain 逐键一致; finish_action 的 400 中断位次
# 亦与改前一致: 已应用键保持已应用, 其后键不再处理 —— 表内其后果真无键)。
# 注意: 日志文案键序 ≠ 应用键序(见 _CONFIG_LOG_ORDER) —— enable_water/mine/rabbit 是
# 后补进 if-chain 的, 历史文案顺序不随其后补位次改变。
_NO_DEFAULT = object()   # 哨兵: 日志 .get 不带默认值(区别于缺省 False)

_CONFIG_KEYS: dict[str, dict] = {
    # 切换账号(startup ⚙): 日志行1 用应用后现值渲染(改前即 now 局部变量语义)
    "enable_switch": dict(
        type="bool", log_line=1, log_label="切换账号功能", log_fmt="sw2", log_value="now",
        echo="post", meta=("切换账号", "登录前自动切换到目标账号"), meta_default=False),
    "target_tail": dict(
        type="text", log_line=1, log_label="目标尾部", log_fmt="raw", log_cond="switch_now",
        meta=("目标账号尾部", "匹配 abc****de 的末尾数字"), meta_default=""),
    # claim ⚙ 三键: 日志 .get 不带默认值(改前原形态; 缺键时 None → 「关」)
    "claim_online": dict(
        type="bool", log_line=2, log_label="领取奖励功能1在线礼包", log_fmt="sw",
        log_default=_NO_DEFAULT, echo=True,
        meta=("功能1 · 在线礼包", "抽奖耗尽次数 + 时间档位领取"), meta_default=True),
    "claim_party": dict(
        type="bool", log_line=2, log_label="功能2花灵派对", log_fmt="sw",
        log_default=_NO_DEFAULT, echo=True,
        meta=("功能2 · 花灵派对", "进入派对并领取 6 个在线时长礼包"), meta_default=True),
    "claim_hb": dict(
        type="bool", log_line=2, log_label="功能3奇妙花宝", log_fmt="sw",
        log_default=_NO_DEFAULT, echo=True,
        meta=("功能3 · 奇妙花宝", "家园→奇妙花宝→奇妙特权，领奇妙礼包每日/每周/每月三档"), meta_default=False),
    # 花仙乐园(2026-11-17): 不进 [config] 日志行(避免改既有日志契约), 仅 ⚙ 面板 + set_config 白名单
    "claim_fairyland": dict(
        type="bool",
        meta=("花仙乐园", "在线骰子 + 每日任务（兑换/浇水/仙豆；购买花种占位）"),
        meta_default=True),
    "enable_shine": dict(
        type="bool", log_line=2, log_label="闪耀委托挑战", log_fmt="sw",
        log_default=_NO_DEFAULT, echo=True,
        meta=("闪耀委托挑战", "家族活动 4.1.2 · 每日 10-21 时开放时段内执行"), meta_default=False),
    "enable_pollin": dict(
        type="bool", log_line=2, log_label="好友采粉", log_fmt="sw",
        log_default=True, echo=True,
        meta=("好友采粉", "4.2 · 密友+好友逐页采集花粉, 无可采则回自己家园"), meta_default=True),
    "enable_like": dict(
        type="bool", log_line=2, log_label="社区点赞", log_fmt="sw",
        log_default=False, echo=True,
        meta=("社区点赞", "完成手账「为精美搭配献上点赞吧」任务(每期上限 20 次; 任务已完成则跳过)"),
        meta_default=False),
    "enable_hot_sale": dict(
        type="bool", log_line=2, log_label="浏览热卖", log_fmt="sw",
        log_default=False,
        meta=("浏览热卖", "完成手账「查看最新热卖套装」任务(点行内前往进页浏览即完成, 不碰抽取按钮; "
              "2026-10-27 自社区点赞拆分独立)"), meta_default=False),
    "enable_baobao": dict(
        type="bool", log_line=2, log_label="花宝照顾", log_fmt="sw",
        log_default=False,
        meta=("花宝照顾", "完成手账「在花园中照顾小花宝一次」任务(道具手套拖拽, 消耗手套道具)"),
        meta_default=False),
    # G1 v2(2026-11-03): 花宝道具自动补货开关(缺键默认 true, 与 config.example 一致)
    "enable_baobao_buy": dict(
        type="bool", log_line=2, log_label="花宝补货", log_fmt="sw", log_default=True,
        meta=("花宝自动补货", "挠痒痒 0 库存时受控购买 22 仙豆/个(单轮最多 1 次; 余额低于 10000 停止; "
              "确认框全文核对+差额复核)"), meta_default=True),
    # 种植模块(2026-11-16 用户定稿): 四功能。种植花朵当前仅桃花; 归位自己家园已实现,
    # 种花动作与另外三功能先占位(默认关闭, 开启暂无实际动作)。无 log_line/echo ——
    # 不改既有 [config] 日志行与 set_config 回显键面(同 use_angle_cls 口径)。
    "plant_flower": dict(
        type="bool",
        meta=("种植花朵", "当前仅桃花; 已实现『确保在自己家园』归位, 种花动作占位待补"),
        meta_default=False),
    "plant_flower_type": dict(
        type="text",
        meta=("花种选择", "当前仅支持：桃花(后续扩展)"),
        meta_default="桃花"),
    "plant_pollinate": dict(
        type="bool",
        meta=("花朵授粉", "占位待开发, 开启暂无实际动作"),
        meta_default=False),
    "plant_harvest": dict(
        type="bool",
        meta=("收获花朵", "已实现: 可收获/可授粉判定; 无待授粉才一键收花"),
        meta_default=False),
    "plant_buy_seed": dict(
        type="bool",
        meta=("购买种子", "占位待开发, 开启暂无实际动作"),
        meta_default=False),
    "log_click_pos": dict(
        type="bool", log_line=3, log_label="记录按钮位置", log_fmt="sw", log_default=False,
        echo=False, meta=None),
    "use_cache_pos": dict(
        type="bool", log_line=3, log_label="使用缓存位置", log_fmt="sw", log_default=False,
        echo=False, meta=None),
    # W1(2026-10-27): OCR 推理线程数(0=不限制); ONNX 会话级, 改后需重启 webui 生效
    "ocr_threads": dict(type="int", bad_int=2, clamp=(0, 8), meta=None),
    # 2026-10-11 补: 里程碑 82 给 ⚙ 面板加 enable_mine/enable_rabbit 时漏了本处理器,
    # 勾选被静默丢弃(config.json 无键, if_config 读 None) —— 用户实测矿洞勾选无效即此因。
    "enable_mine": dict(
        type="bool", log_line=2, log_label="矿洞探险", log_fmt="sw", log_default=False,
        meta=("矿洞探险", "家族活动 4.1.3 · 每日礼包领取/次日「明日再来」跳过"), meta_default=False),
    "enable_rabbit": dict(
        type="bool", log_line=2, log_label="守望兔子", log_fmt="sw", log_default=False,
        meta=("守望兔子", "家族活动 4.1.4 · 占位待开发, 开启暂无实际动作"), meta_default=False),
    "enable_water": dict(
        type="bool", log_line=2, log_label="摇钱树浇水", log_fmt="sw", log_default=True,
        meta=("摇钱树浇水", "家族活动 4.1.1 · 每日浇水 X/3(含生效复核: 点击被吞自动重试 1 次)"),
        meta_default=True),
    "confirm_page_close": dict(type="bool", meta=None),
    # 里程碑 94: 截图缓存提醒阈值(MB) —— 必进白名单, 否则 WebUI 保存被静默丢弃(里程碑 87 教训)
    "fail_cache_prompt_mb": dict(type="float", min_v=1.0, meta=None),
    # 完成动作(2026-11-10, 完成后关闭客户端): 仅接受 none/close_client 二值, 之外一律 400
    # 拒收(不落配置, 不静默改成默认); 合法值经 eng.update_config 落内存+持久化, 供 run_daily
    # 无编排级动作时兜底读取。
    "finish_action": dict(
        type="enum", enum_values=("none", "close_client"),
        enum_error="finish_action 仅接受 none/close_client, 收到: {v!r}",
        echo="enum_none", meta=None),
    # OCR3(batch-08, 2026-11-14): 执行后端三档开关(cpu/dml/cuda, 默认 cpu=零行为)。
    # enum 白名单外 400 拒收(finish_action 同型); **无回显键、无 [config] 日志行** ——
    # set_config 响应键面(SET_CONFIG_ECHO_KEYS)与 [config] 三行文案是逐字节契约(api_contract_selftest
    # 钉住), 本键只经 /api/daily 识别设置回显 + webui.html 右栏下拉落键。改后重启生效
    # (ocr_ui 单例按首次 get_engine 时的档位构建; GPU 档构建失败自动回退 cpu 并在日志如实记录)。
    "ocr_execution_provider": dict(
        type="enum", enum_values=("cpu", "dml", "cuda"),
        enum_error="ocr_execution_provider 仅接受 cpu/dml/cuda, 收到: {v!r}", meta=None),
    # OCR2(batch-10, 2026-11-15): cls 方向分类器开关(RapidOCR use_angle_cls 构造参数透传,
    # 默认 true = 改动前行为逐字节等价)。bool 键; **无回显键、无 [config] 日志行**(键面/
    # 文案逐字节契约不动), 经 /api/daily 识别设置回显 + webui.html 右栏勾选落键。改后重启
    # 生效(ocr_ui 单例按首次 get_engine 时的值构建)。默认 true 是本批终态: det736 配对
    # A/B(实机授权, batch-12)落盘且过 0 退化门才允许默认翻 false —— 不得凭 det32/64
    # 数字默认关(负清单 N8); 速度口径标签: cls 关 median 快 11.0~11.3% 为 det32/64 实验口径,
    # det736 生产口径待本批 A/B。
    "use_angle_cls": dict(type="bool", meta=None),
}

# ⚙ 面板各模块键归属与顺序(_module_settings 渲染顺序; 键文案/缺省在 _CONFIG_KEYS.meta):
# 2026-10-07 用户反馈: ⚙ 只有 startup/claim 可点, 其余模块被 disabled —— 补齐 social 的
# 真实 if_config 开关(与 flow_social.json §4.1.1~4.1.4/4.2/4.3 一一对应, 默认值与
# data/config.example.json 一致)。plant/energy/daily/idle 四个流程无任何 if_config,
# 返回 [] → ⚙ 可点开面板显示「暂无独立子功能」说明。2026-10-11: 新增浇水开关
# enable_water(4.1.1, 默认 true)。2026-10-12: 社区点赞自社交模块迁入每日任务(daily 按
# 手账「献上点赞」行进度 a<b 门控执行, 已完成/行缺失跳过)。
# 2026-11-16: plant 不再是空面板 —— 种植模块四功能(种植花朵/花种选择/授粉/收获/购买种子),
# 前两项已接入, 其余三项占位默认关闭。
_MODULE_SETTINGS: dict[str, tuple[str, ...]] = {
    "claim": ("claim_online", "claim_party", "claim_hb", "claim_fairyland"),
    "startup": ("enable_switch", "target_tail"),
    "plant": ("plant_flower", "plant_flower_type", "plant_pollinate", "plant_harvest", "plant_buy_seed"),
    "social": ("enable_water", "enable_shine", "enable_mine", "enable_rabbit", "enable_pollin"),
    "daily": ("enable_like", "enable_hot_sale", "enable_baobao", "enable_baobao_buy"),
}

# [config] 日志行键序(与改前文案逐字节一致; 故意 ≠ 表的应用键序 —— 后补键不打乱历史顺序):
_CONFIG_LOG_ORDER: dict[int, tuple[str, ...]] = {
    1: ("enable_switch", "target_tail"),
    2: ("claim_online", "claim_party", "claim_hb", "enable_shine", "enable_water",
        "enable_mine", "enable_rabbit", "enable_pollin", "enable_like",
        "enable_hot_sale", "enable_baobao", "enable_baobao_buy"),
    3: ("log_click_pos", "use_cache_pos"),
}
_CONFIG_LOG_SUFFIX: dict[int, str] = {
    3: " (两项默认关闭; 关闭时只认实时识别, 不用历史坐标盲点)",
}


def _apply_config_key(eng: OCREngine, key: str, spec: dict, value) -> str | None:
    """按表规格校验并落一个配置键(eng.update_config = 内存+data/config.json 双写)。

    返回 None=成功; str=400 错误文案(enum 键白名单外: 拒收不落配置, 且中断本请求后续
    处理 —— 已应用键保持已应用, 与改前 finish_action 分支原语义一致)。
    """
    t = spec["type"]
    if t == "bool":
        eng.update_config(**{key: bool(value)})
    elif t == "text":
        eng.update_config(**{key: str(value)})
    elif t == "int":
        try:
            n = int(value)
        except (TypeError, ValueError):
            n = spec["bad_int"]                    # ocr_threads: 解析失败回 2(改前原语义)
        lo, hi = spec["clamp"]
        n = max(lo, min(hi, n))                    # ocr_threads: max(0, min(8, thr))(改前原语义)
        eng.update_config(**{key: n})
    elif t == "float":
        try:
            eng.update_config(**{key: max(spec["min_v"], float(value))})
        except (TypeError, ValueError):
            pass                                   # fail_cache_prompt_mb: 坏值跳过不落盘(改前原语义)
    elif t == "enum":
        v = str(value or "")
        if v not in spec["enum_values"]:
            return spec["enum_error"].format(v=v)
        eng.update_config(**{key: v})
    return None


def _config_log_segment(eng: OCREngine, key: str, spec: dict, now: bool) -> str | None:
    """生成一个键的 [config] 日志片段; None=本行不渲染该键(如 target_tail 在切换账号关时)。"""
    if spec.get("log_cond") == "switch_now" and not now:
        return None
    if spec["log_fmt"] == "raw":
        return f"{spec['log_label']}={eng.config.get(key)}"
    if spec.get("log_value") == "now":
        v = now
    elif spec.get("log_default") is _NO_DEFAULT:
        v = eng.config.get(key)
    else:
        v = eng.config.get(key, spec["log_default"])
    if spec["log_fmt"] == "sw2":
        return f"{spec['log_label']} {'启用' if v else '关闭'}"
    return f"{spec['log_label']}={'开' if v else '关'}"


def _config_log_lines(eng: OCREngine, now: bool) -> list[str]:
    """生成 set_config 的 [config] 日志行(固定 3 行, 无论本请求改了哪些键 —— 与改前一致)。

    文案/键序/.get 缺省形态与改前逐字节一致(键序见 _CONFIG_LOG_ORDER)。
    """
    out: list[str] = []
    for ln in (1, 2, 3):
        segs = [s for s in (_config_log_segment(eng, k, _CONFIG_KEYS[k], now)
                            for k in _CONFIG_LOG_ORDER[ln]) if s is not None]
        line = "[config] " + segs[0] + "".join(", " + s for s in segs[1:]) \
            + _CONFIG_LOG_SUFFIX.get(ln, "")
        out.append(line)
    return out


def _config_echo(eng: OCREngine, now: bool, pre: bool) -> dict:
    """set_config 响应。回显键集/键序/缺省形态与改前逐字节一致(键序 = 表序过滤 echo≠None)。"""
    out: dict = {"ok": True, "changed": pre != now}
    for key, spec in _CONFIG_KEYS.items():
        e = spec.get("echo")
        if e is None:
            continue
        if e == "post":
            out[key] = now
        elif e == "enum_none":
            out[key] = str(eng.config.get(key, "none") or "none")
        else:
            out[key] = bool(eng.config.get(key, e))
    return out


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
        # W1(2026-10-27, zcode-20261028-6): 删除 GET /api/config —— 前端零消费方
        # (webui.html/tpltool.html 全文 0 引用, codex-20261025-4 已核实并留主 agent 裁量);
        # 现行设置回显统一走 /api/daily(modules[].settings + 识别设置字段), 保存统一走 /api/set_config。
        if api == "daily" and self.command == "GET":
            return self._daily()
        if api == "run_daily" and self.command == "POST":
            return self._run_daily_sel()
        if api == "set_config" and self.command == "POST":
            data = self._read_json()
            eng = get_engine()
            pre = bool(eng.config.get("enable_switch", False))
            # F06+W03(batch-04): 全部键由 _CONFIG_KEYS 元数据表驱动(白名单/校验/日志/回显/
            # ⚙meta 五处同源, 表见模块级定义与历史事故注释)。键序与改前 if-chain 逐键一致;
            # enum 键白名单外 400 中断(已应用键保持已应用, 改前 finish_action 原语义);
            # 三种特殊校验器逐字节保持: ocr_threads 钳制(max(0,min(8)), 解析失败回 2) /
            # fail_cache_prompt_mb 下限 1.0(解析失败跳过不落盘) / finish_action 400 拒收不落配置。
            for key, spec in _CONFIG_KEYS.items():
                if key not in data:
                    continue
                err = _apply_config_key(eng, key, spec, data[key])
                if err is not None:
                    return self._send_json({"error": err}, 400)
            now = bool(eng.config.get("enable_switch", False))
            for line in _config_log_lines(eng, now):
                log_append(line)
            return self._send_json(_config_echo(eng, now, pre))

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
        if api == "stream" and self.command == "GET":   # SSE 推送(2026-11-10 新增, 既有端点零改动)
            return self._stream()
        if api == "log_clear" and self.command == "POST":
            return self._log_clear()
        # ---- 故障存证截图: 缓存信息 / 清理 / 浏览目录 (里程碑 94) ----
        if api == "fail_cache_info" and self.command == "GET":
            st = _fail_cache_stat()
            st["files"] = sorted(st["files"])  # D7(方案批 D 表 D7): set 不可 JSON 序列化致本接口 500, 进 JSON 前转有序列表; _status() 内部仍用原 set 做子集比对, 故不改 _fail_cache_stat 返回类型
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
        # W2-004: annotation_id 只保留安全字符, 防止 ../ 或绝对路径写出 annot_shots 之外。
        raw_id = str(data.get("annotation_id") or "")
        annotation_id = "".join(ch for ch in raw_id if ch.isalnum() or ch in "-_")[:80] or "ann"
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
                shot_name = annotation_id + ".png"
                (shot_dir / shot_name).write_bytes(raw)
                shot_saved = str(Path("data") / "annot_shots" / shot_name)
            except Exception as e:
                log_append(f"[tpltool] 保存标注截图失败: {e}")
        record = {
            "annotation_id": annotation_id,
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
        # W1(2026-10-27): 连接结果写入运行日志(此前仅 HTTP 响应, 日志面板无连接记录,
        # 失败时用户在页面上只能看到按钮状态, 排障缺上下文)
        if ok:
            log_append(f"[连接] 手动连接成功 (引擎工作区 {eng.screen_w}x{eng.screen_h})")
        else:
            log_append("[连接] 手动连接失败 —— 请检查模拟器/ADB 地址(127.0.0.1:16384)后重试")
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
            # F06+W03(batch-04): ⚙ 面板 meta 由 _MODULE_SETTINGS(归属与顺序) × _CONFIG_KEYS
            # (文案/缺省/type) 表生成, 与 set_config 白名单同源 —— 新增面板键不再可能被白名单
            # 静默丢弃(里程碑 82/87「勾选被静默丢弃」事故类的结构性消除)。
            # 历史注释随迁: 2026-10-07 ⚙ 只有 startup/claim 可点 → 补齐 social 真实 if_config
            # 开关(与 flow_social.json §4.1.1~4.1.4/4.2/4.3 一一对应, 默认值与
            # data/config.example.json 一致); plant/energy/daily/idle 无 if_config 返回 [] →
            # ⚙ 面板显示「暂无独立子功能」。2026-10-11 新增 enable_water(4.1.1, 默认 true)。
            # 2026-10-12 社区点赞自社交模块迁入每日任务(daily 按手账「献上点赞」行进度 a<b
            # 门控执行, 已完成/行缺失跳过)。
            out = []
            for key in _MODULE_SETTINGS.get(mid, ()):
                spec = _CONFIG_KEYS[key]
                label, desc = spec["meta"]
                if spec["type"] == "text":
                    val = eng.config.get(key, spec.get("meta_default", ""))
                    mtype = "text"
                else:
                    val = bool(eng.config.get(key, spec.get("meta_default", False)))
                    mtype = "switch"
                out.append({"key": key, "type": mtype, "label": label, "desc": desc,
                            "value": val})
            return out
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
            # W1(2026-10-27): 删除顶层 enable_switch/target_tail —— 消费方(右栏旧「账号切换」面板)
            # 已由 codex-20261025-4 删除, 现网回显唯一来源=modules[].settings(startup ⚙)。
            # 全局识别设置(供右栏「识别设置」面板回显); ocr_threads 改后重启生效(ONNX 会话)
            # ocr_execution_provider 同口径(OCR3 batch-08: 执行后端三档, 默认 cpu; 改后重启生效)
            # use_angle_cls 同口径(OCR2 batch-10: cls 方向分类器, 默认 true=现状逐字节等价;
            # det736 A/B 落盘(batch-12)前默认保持 true, 不得凭 det32/64 数字默认关 —— 负清单 N8)
            "log_click_pos": bool(eng.config.get("log_click_pos", False)),
            "use_cache_pos": bool(eng.config.get("use_cache_pos", False)),
            "ocr_threads": int(eng.config.get("ocr_threads", 2)),
            "ocr_execution_provider": str(eng.config.get("ocr_execution_provider", "cpu")),
            "use_angle_cls": bool(eng.config.get("use_angle_cls", True)),
        })

    # ---- API: 按勾选模块运行每日编排 (使用界面「开始一轮」) ----
    def _run_daily_sel(self):
        data = self._read_json()
        selected = data.get("selected", [])
        mode = data.get("mode", "use")
        # 完成动作(2026-11-10, 完成后关闭客户端): 解析 data.finish_action, 仅接受
        # none/close_client 二值 —— 其余值一律 400 拒收, 绝不静默落进编排(防拼错键名
        # 造成意外关闭客户端)。缺省 "none" = 零行为变化(引擎收尾不做任何动作)。
        finish_action = str(data.get("finish_action", "none") or "none")
        if finish_action not in ("none", "close_client"):
            return self._send_json(
                {"error": f"finish_action 仅接受 none/close_client, 收到: {finish_action!r}"}, 400)
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
        # 完成动作随编排传给引擎: 引擎 run_daily 全部模块跑完后按该值决定是否关闭客户端
        # (none=无动作; close_client=关客户端。引擎侧同样只认这两值, 其余按 none 处理)。
        plan["finish_action"] = finish_action
        name = plan.get("name", "每日编排")
        # Q01(batch-04): check-and-set 原子化(_try_claim_running), 且置位提前到 spawn 前 ——
        # 改前置位发生在 job 内 connect()(数秒) 之后, 与 /api/run 构成双入口 TOCTOU 无锁窗口。
        if not _try_claim_running():
            return self._send_json({"error": "已有流程在运行, 请先停止"}, 409)
        def job():
            eng = get_engine()
            try:
                if not _is_connected(eng):
                    eng.connect()
            except Exception as e:
                log_append(f"[run] 连接失败: {e}")
                # Q01: connect 异常 = 本轮未开始即失败, 回滚 running=false 并终止
                # (验收线: connect 失败后 /api/status.running 恢复 false)。
                _set_running(False)
                return
            import sys
            # Q01: stdout/stderr 换轨段按 job 互斥 —— 保存+换轨在同一把 _RUNNING_LOCK 临界区
            # 内完成, 恢复段同锁串行化; 流程互斥已由 running 原子门保证且恢复先于
            # _set_running(False), 后启动者不可能捕获到前一个 job 的 _TeeOut(嵌套消除)。
            with _RUNNING_LOCK:
                real_out, real_err = sys.stdout, sys.stderr
                sys.stdout = _TeeOut(real_out, _LOGS)
                sys.stderr = _TeeOut(real_err, _LOGS)
            try:
                eng = get_engine()
                try:
                    if not _is_connected(eng):
                        eng.connect()
                except Exception as e:
                    log_append(f"[run] 连接失败: {e}")
                sys.stdout = _TeeOut(real_out, _LOGS)
                sys.stderr = _TeeOut(real_err, _LOGS)
                log_append(f"[run] ==== {name} (勾选 {len(chosen)} 模块) 开始 ====")
                eng.run_daily(plan)
                log_append(f"[run] ==== {name} 完成 ====")
            except Exception as e:
                log_append(f"[run] 流程异常: {e}")
            finally:
                with _RUNNING_LOCK:
                    sys.stdout, sys.stderr = real_out, real_err
                _set_running(False)
        try:
            threading.Thread(target=job, daemon=True, name="faa-daily").start()
        except Exception:
            _set_running(False)
            raise
        return self._send_json({"ok": True, "started": name, "count": len(chosen)})

    # ---- API: 运行流程 (后台线程 + 日志) ----
    def _run(self):
        data = self._read_json()
        key = data.get("flow", "")
        mode = data.get("mode", "use")
        flows = load_flows()
        target = select_flow(flows, key)
        if target is None:
            return self._send_json({"error": f"未找到流程: {key}"}, 400)
        name = target.get("name")
        # Q01(batch-04): 与 _run_daily_sel 同款 —— 原子 check-and-set + 置位提前到 spawn 前,
        # 消除两入口共享的无锁窗口(详见 _try_claim_running 注释)。
        if not _try_claim_running():
            return self._send_json({"error": "已有流程在运行, 请先停止"}, 409)
        try:
            _set_mode(mode)
        except Exception:
            _set_running(False)
            raise
        def job():
            eng = get_engine()
            try:
                if not _is_connected(eng):
                    eng.connect()
            except Exception as e:
                log_append(f"[run] 连接失败: {e}")
                # Q01: connect 异常 = 本轮未开始即失败, 回滚 running=false 并终止。
                _set_running(False)
                return
            import sys
            # Q01: stdout/stderr 换轨段按 job 互斥(同 _run_daily_sel, 嵌套消除)。
            with _RUNNING_LOCK:
                real_out, real_err = sys.stdout, sys.stderr
                sys.stdout = _TeeOut(real_out, _LOGS)
                sys.stderr = _TeeOut(real_err, _LOGS)
            try:
                eng = get_engine()
                try:
                    if not _is_connected(eng):
                        eng.connect()
                except Exception as e:
                    log_append(f"[run] 连接失败: {e}")
                sys.stdout = _TeeOut(real_out, _LOGS)
                sys.stderr = _TeeOut(real_err, _LOGS)
                log_append(f"[run] ==== {name} 开始 ====")
                if "modules" in target:
                    eng.run_daily(target)
                else:
                    eng.run_flow(target)
                log_append(f"[run] ==== {name} 完成 ====")
            except Exception as e:
                log_append(f"[run] 流程异常: {e}")
            finally:
                with _RUNNING_LOCK:
                    sys.stdout, sys.stderr = real_out, real_err
                _set_running(False)
        try:
            threading.Thread(target=job, daemon=True, name="faa-run").start()
        except Exception:
            _set_running(False)
            raise
        return self._send_json({"ok": True, "started": name})

    # ---- API: 增量日志 ----
    def _log(self):
        # after 防负(BUG-10, 2026-10-03): 负数会让 _LOGS[after:] 变成"取末尾 N 条"的 Python 负切片,
        # 返回错行的日志且 next 变负, 前端增量轮询从此错乱。与 /api/failures 的 max(0,...) 同款防御。
        after = max(0, int(self._query("after") or 0))
        with _LOG_LOCK:
            base = _LOG_BASE
            if after < base:                 # 客户端游标落后于已丢弃的头部: 从现存最早一片续读
                after = base
            end = base + len(_LOGS)
            if after >= end:
                return self._send_json({"next": end, "lines": []})
            lines = _LOGS[after - base:]
        return self._send_json({"next": end, "lines": lines})

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

    # ---- API: SSE 推送 (2026-11-10 新增 GET /api/stream; 既有端点与 webui.html 零改动) ----
    def _sse_send(self, event: str, data) -> bool:
        """发送一条 SSE 事件并逐事件 flush。连接断开(客户端关页/网络中断)返回 False,
        调用方据此干净退出线程, 不留孤儿循环。event 为空串 = 心跳(SSE 注释行,
        EventSource 不派发为事件, 仅保活兼探活 —— 每次心跳都是一次真实写探测)。"""
        try:
            if event:
                payload = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            else:
                payload = f": ping {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            self.wfile.write(payload.encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return False

    def _stream(self):
        """GET /api/stream —— SSE 推送通道(纯新增; 浏览器轮询回退通道不变)。

        事件契约:
        - event: log      内部 _LOGS 游标增量: 0.8s 轮询内部缓冲, 有新分片才推;
                          data = {"next": int, "lines": [str,...]}(与 GET /api/log 同形)。
                          游标从 0 起步(连上即回放本次会话已有分片, 与 /api/log?after=0 同语义);
                          以「已消费末分片指纹」检测缓冲被整体替换(log_clear, 替换后缓冲=[标记行])
                          → 游标归零重放, 保证清除后的日志仍推得出去。
        - event: status   1.5s 检测 /api/status 载荷变化, 变更才推(载荷与 GET /api/status 同形);
                          连接建立后立即推一次首帧状态, 之后仅在实际变化时推送。
        - event: failures 失败游标增量(0.8s; data 与 GET /api/failures 同形 {items,next});
                          仅新增失败才推。
        - event: frame    仅 ?frames=1 时附带: 引擎 last_frame 指纹(hashlib.blake2b)变化才
                          编码 jpeg b64 推送(data 与 GET /api/screen 同形 {jpeg,w,h})。
                          ⚠ 绝不主动 ADB 截帧(不调 eng.screenshot, 只读引擎已有的 last_frame);
                          空闲期引擎不产新帧 → 指纹不变 → 无新帧就不推。
        - 心跳            每 15s 一条 ": ping" 注释行保活。
        - 断开             写失败(BrokenPipeError/ConnectionResetError 等)→ 线程干净退出,
                          无孤儿循环; 本端点不落任何盘、不改任何状态。
        """
        import hashlib   # 局部导入: 对既有 import 块零改动
        frames = (self._query("frames") == "1")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        log_cur = 0          # _LOGS 游标(0=回放已有分片)
        last_chunk = ""      # 已消费末分片指纹: 缓冲被整体替换(log_clear)时据此归零重放
        fail_cur = 0         # 失败游标(0=回放既有失败, 与前端 failSeen 初值一致)
        last_status = None   # 上次推送的 status 载荷指纹
        last_frame_sig = None
        t_log = t_fail = t_status = t_frame = 0.0
        t_beat = time.monotonic()
        while True:
            now = time.monotonic()
            if now - t_log >= 0.8:
                t_log = now
                with _LOG_LOCK:
                    n = len(_LOGS)
                    if log_cur > n or (log_cur > 0 and _LOGS[log_cur - 1] != last_chunk):
                        log_cur = 0      # 缓冲被清空/整体替换(log_clear 后缓冲=[标记行]) → 归零重放
                    new = list(_LOGS[log_cur:])
                    log_cur = len(_LOGS)
                    if new:
                        last_chunk = _LOGS[-1]
                if new and not self._sse_send("log", {"next": log_cur, "lines": new}):
                    return
            if now - t_fail >= 0.8:
                t_fail = now
                try:
                    items, nxt = get_failures(fail_cur)
                except Exception:
                    items, nxt = [], fail_cur
                if items and not self._sse_send("failures", {"items": items, "next": nxt}):
                    return
                if nxt > fail_cur:
                    fail_cur = nxt
            if now - t_status >= 1.5:
                t_status = now
                try:
                    payload = _status()
                except Exception:
                    payload = None
                if payload is not None:
                    fp = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                    if fp != last_status:
                        if not self._sse_send("status", payload):
                            return
                        last_status = fp
            if frames and now - t_frame >= 1.5:
                t_frame = now
                eng = ENGINE                 # 只读既有单例: 不经 get_engine() 避免误建引擎
                img = getattr(eng, "last_frame", None) if eng is not None else None
                if img is not None:
                    sig = hashlib.blake2b(img.tobytes(), digest_size=16).hexdigest()
                    if sig != last_frame_sig:
                        last_frame_sig = sig
                        if not self._sse_send("frame", {"jpeg": _img_to_jpeg_b64(img),
                                                        "w": getattr(eng, "screen_w", 0),
                                                        "h": getattr(eng, "screen_h", 0)}):
                            return
            if now - t_beat >= 15.0:
                t_beat = now
                if not self._sse_send("", None):
                    return
            time.sleep(0.2)

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