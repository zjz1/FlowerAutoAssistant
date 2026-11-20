# -*- coding: utf-8 -*-
"""运行日志服务：环形缓冲 + 磁盘备份 + 增量游标 + print 捕获。

从 webui.py 迁出（Stage 1）。HTTP 适配器只调用 append/reset/get_since/snapshot。
"""
from __future__ import annotations

import threading
from pathlib import Path

from core.limits import SESSION_BUFFER_MAX
from diagnostics.redact import redact_text

BASE = Path(__file__).resolve().parents[1]

LOG_LOCK = threading.Lock()
LOGS: list[str] = []
LOG_MAX_LINES = SESSION_BUFFER_MAX   # 最多保留的写入分片数(print 正文与换行各算一片); 超出从头部丢弃
LOG_BASE = 0                   # 被丢弃的头部片数, /api/log 的游标 = 全局序号
LOG_FILE = BASE / "data" / "webui_runtime_log.txt"
# HTTP 访问日志分流：避免 GET /api/* 噪声进入运行日志
HTTP_LOG_FILE = BASE / "data" / "webui_http_log.txt"
HTTP_LOG_LOCK = threading.Lock()

# 2026-11-21 审阅 W5-004: 单会话日志文件 100MB 保护。到达上限后停止写盘(不删已有内容),
# 内存日志/SSE/下载继续可用; 启动或「清空日志」时重置计数并恢复写入。
LOG_FILE_MAX_BYTES = 100 * 1024 * 1024
HTTP_LOG_MAX_BYTES = 100 * 1024 * 1024
_PERSIST_LOCK = threading.Lock()
_persist_bytes: int | None = None
_persist_capped = False
_http_log_bytes: int | None = None
_http_log_capped = False


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _size_label(n: int) -> str:
    return f"{n // (1024 * 1024)}MB" if n >= 1024 * 1024 else f"{n}B"


def _persist(text: str) -> None:
    """把日志分片追加到磁盘备份; 单会话超过 100MB 后停止写盘并提示一次。"""
    global _persist_bytes, _persist_capped
    data = text.encode("utf-8")
    warning = None
    with _PERSIST_LOCK:
        if _persist_capped:
            return
        if _persist_bytes is None:
            _persist_bytes = _file_size(LOG_FILE)
        if _persist_bytes + len(data) > LOG_FILE_MAX_BYTES:
            _persist_capped = True
            warning = (f"[日志] 运行日志已达 {_size_label(LOG_FILE_MAX_BYTES)} 上限, "
                       f"停止写入磁盘; 内存日志与下载功能仍可用")
        else:
            try:
                LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(text)
                _persist_bytes += len(data)
            except Exception:
                pass
    if warning:
        print(warning)


def persist_http(text: str) -> None:
    """HTTP 访问日志落盘(独立 100MB 上限; 超限停止写盘并提示一次)。"""
    global _http_log_bytes, _http_log_capped
    data = text.encode("utf-8")
    warning = None
    with HTTP_LOG_LOCK:
        if _http_log_capped:
            return
        if _http_log_bytes is None:
            _http_log_bytes = _file_size(HTTP_LOG_FILE)
        if _http_log_bytes + len(data) > HTTP_LOG_MAX_BYTES:
            _http_log_capped = True
            warning = (f"[日志] HTTP 访问日志已达 {_size_label(HTTP_LOG_MAX_BYTES)} 上限, "
                       f"停止写入磁盘")
        else:
            try:
                HTTP_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(HTTP_LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(text)
                _http_log_bytes += len(data)
            except Exception:
                pass
    if warning:
        print(warning)


def _append(text: str) -> None:
    """追加一个日志分片；超过上限时丢弃最旧的头部并推进全局序号。"""
    global LOG_BASE
    with LOG_LOCK:
        LOGS.append(text)
        overflow = len(LOGS) - LOG_MAX_LINES
        if overflow > 0:
            del LOGS[:overflow]
            LOG_BASE += overflow


def append(text: str) -> None:
    """写入一条日志。1.0 #20: 入内存/落盘前统一脱敏（账号尾号/本机路径/ADB 路径/密钥）。"""
    text = redact_text(text)
    _append(text)
    _persist(text)


def reset_history() -> None:
    """启动/清空时重置日志缓存与磁盘备份，同时解除 100MB 写盘保护。"""
    global LOG_BASE, _persist_bytes, _persist_capped, _http_log_bytes, _http_log_capped
    with LOG_LOCK:
        LOGS.clear()
        LOG_BASE = 0
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "w", encoding="utf-8"):
            pass
    except Exception:
        pass
    try:
        HTTP_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(HTTP_LOG_FILE, "w", encoding="utf-8"):
            pass
    except Exception:
        pass
    with _PERSIST_LOCK:
        _persist_bytes = None      # 下次写入时按实际文件大小惰性初始化
        _persist_capped = False
    with HTTP_LOG_LOCK:
        _http_log_bytes = None
        _http_log_capped = False


def get_since(after: int) -> tuple[int, list[str]]:
    """增量读取：返回 (next, lines)。after 为负数按 0；落后于已丢弃头部时从现存最早续读。"""
    after = max(0, int(after or 0))
    with LOG_LOCK:
        base = LOG_BASE
        if after < base:
            after = base
        end = base + len(LOGS)
        if after >= end:
            return end, []
        return end, LOGS[after - base:]


def read_increment(last_chunk: str, cursor: int) -> tuple[int, list[str], str]:
    """SSE 原子增量：在同一把锁内完成「缓冲替换检测 + 续读 + 末分片指纹更新」。

    cursor 是**全局序号**（含已丢弃的 LOG_BASE），不是 LOGS 列表下标；
    指纹必须用 LOGS[cursor - 1 - base] 取，否则缓冲满 LOG_MAX_LINES 后
    每次都会误判「缓冲被替换」并重放全量。
    """
    with LOG_LOCK:
        base = LOG_BASE
        n = len(LOGS)
        end = base + n
        if cursor > end or cursor < base or (
                cursor > base and LOGS[cursor - 1 - base] != last_chunk):
            cursor = base
        if cursor >= end:
            return end, [], (LOGS[-1] if LOGS else last_chunk)
        lines = LOGS[cursor - base:]
        return end, lines, LOGS[-1]


def snapshot() -> list[str]:
    with LOG_LOCK:
        return list(LOGS)


class TeeOut:
    """把 print 输出同时写入日志缓冲, 便于前端实时流式查看。"""
    def __init__(self, real, buf):
        self._real = real
        self._buf = buf

    def write(self, s: str) -> int:
        if s:
            clean = redact_text(s)
            _append(clean)
            _persist(clean)
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


# 兼容旧名
log_append = append
_TeeOut = TeeOut
_LOG_MAX_LINES = LOG_MAX_LINES
