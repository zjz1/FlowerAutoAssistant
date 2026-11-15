"""
FlowerAutoAssistant - 整轮度量基座（度量批 2026-11-13）
================================================
每轮开始/结束把 [OCR统计] 摘要 + 内存采样追加写入 data/metrics/rounds.jsonl（JSONL, 一行一条事件）。

立项依据（重构评估报告_20261113.md「度量基座」线）:
- OCR9 验收线「≥3 轮 [OCR统计]/[粗OCR] 落盘」——本模块即该落盘通道;
- 裁定二 3「端到端整轮编排开销未测（MIXED_ROUTE.md §6）」——本模块的整轮计时字段即为该补测的
  数据入口; GPU/混合路由批的整轮 A/B 对拍取数于此。

设计红线（对齐评估报告铁律与既有契约）:
- **纯观测落盘**: 不 print 一行（stdout 行为逐字节不变, 不碰 [OCR统计]/[OCR来源]/[OCR健康]/
  [粗OCR] 等被离线分诊消费的文本契约）; 不改引擎任何判定路径/返回值; 不加配置键
  （零 entries.json/FLOWS/config.example 三方同步面）。
- **静默容错**: 任何异常一律吞掉（写盘失败不影响流程, 也不在 stdout 留痕;
  最近一次失败原因存 metrics_recorder.last_error 供人工排查）。
- **标准库零依赖**: 内存采样走 ctypes(psapi)/resource/procfs, 无第三方包 —— 与 README
  「标准库零依赖」卖点一致（评估报告 §5 N14 引用）。
- **落盘位置**: data/metrics/rounds.jsonl —— data/* 已被 .gitignore 整体出仓（运行产物区）,
  与 data/fail_cache/（里程碑 94 存证）同区不同目录, 互不干扰。

每轮记录形态（两条事件, 由 ocr_engine.run_daily / run_flow 挂钩写入）:
  {"event": "round_start", "ts", "epoch", "source": "daily"|"flow", "name",
   "screen": [w, h] | null, "memory": {采样}, "ocr_stat": {起点快照}}
  {"event": "round_end",   "ts", "epoch", "source", "name", "duration_s": 整轮耗时(墙钟),
   "interrupted": 是否经异常/停止请求退出, "result": 编排统计 | null,
   "memory": {采样}, "ocr_stat": {结束快照(=整轮 [OCR统计] 摘要, 含 by_src)},
   "ocr_stat_delta": {对起点快照的数值增量 —— run_flow 单跑不重置计数器, 以此得本轮口径}}
"""
from __future__ import annotations

import ctypes
import json
import sys
import threading
import time
from pathlib import Path

# data/metrics/ 与引擎 data/ 同根（Path(__file__) = 本模块所在目录 = 仓库根）,
# 与 ocr_engine.dump_full_frame 的 data/fail_cache 同一选址模式: 不依赖进程 CWD。
_METRICS_DIR = Path(__file__).resolve().parent / "data" / "metrics"
_METRICS_FILE = _METRICS_DIR / "rounds.jsonl"

_WRITE_LOCK = threading.Lock()      # WebUI job 线程/主线程并发写同一 JSONL, 行级串行化
last_error: str | None = None       # 最近一次写盘失败原因(仅供人工检查, 模块自身不打印)


# ---------------------------------------------------------------------------
# 内存采样（纯标准库; 采样不到时如实给 None, 绝不抛出）
# ---------------------------------------------------------------------------
def sample_memory() -> dict:
    """当前进程内存采样。Windows 走 psapi GetProcessMemoryInfo(工作集=RSS);
    POSIX 优先 /proc/self/status 的 VmRSS(当前值), 不可用回退 resource.ru_maxrss(峰值)。
    返回 {"rss_bytes", "peak_rss_bytes", "rss_mode"}; 全部失败 rss_bytes=None, mode="unavailable"。"""
    out: dict = {"rss_bytes": None, "peak_rss_bytes": None, "rss_mode": "unavailable"}
    try:
        if hasattr(ctypes, "windll") and sys.platform == "win32":
            class _PMCI(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.c_uint32), ("PageFaultCount", ctypes.c_uint32),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            pmci = _PMCI()
            pmci.cb = ctypes.sizeof(_PMCI)
            k32 = ctypes.windll.kernel32
            psapi = ctypes.windll.psapi
            k32.GetCurrentProcess.restype = ctypes.c_void_p      # 伪句柄 (HANDLE)-1, 需按指针宽度取回
            psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PMCI), ctypes.c_uint32]
            if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmci), pmci.cb):
                out["rss_bytes"] = int(pmci.WorkingSetSize)
                out["peak_rss_bytes"] = int(pmci.PeakWorkingSetSize)
                out["rss_mode"] = "workingset"
            return out
        # POSIX: /proc/self/status 的 VmRSS 是当前工作集(kB), 最接近 Windows workingset 口径
        try:
            txt = Path("/proc/self/status").read_text(encoding="utf-8", errors="ignore")
            for line in txt.splitlines():
                if line.startswith("VmRSS:"):
                    out["rss_bytes"] = int(line.split()[1]) * 1024
                    out["rss_mode"] = "vmrss"
                    break
            if out["rss_bytes"] is not None:
                return out
        except Exception:
            pass
        import resource  # POSIX 兜底: 峰值 RSS(Linux 单位 kB, macOS 单位 B)
        ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        out["rss_bytes"] = int(ru) * (1 if sys.platform == "darwin" else 1024)
        out["rss_mode"] = "maxrss_peak"
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# 统计快照 / 增量（只读, 不改传入对象）
# ---------------------------------------------------------------------------
def _snapshot(obj) -> "dict | None":
    """深拷贝为 JSON 安全结构（数字/字符串/嵌套字典; 兜底 default=str）, 失败返回 None。"""
    if not isinstance(obj, dict):
        return None
    try:
        return json.loads(json.dumps(obj, ensure_ascii=False, default=str))
    except Exception:
        return None


def _by_src_delta(end, start) -> dict:
    """[OCR统计].by_src 的嵌套增量: {kind: {来源: 次数差}}; 差为 0 的来源不保留(压缩体积)。"""
    end = end if isinstance(end, dict) else {}
    start = start if isinstance(start, dict) else {}
    out: dict = {}
    for kind, d in end.items():
        d = d if isinstance(d, dict) else {}
        s = start.get(kind) if isinstance(start.get(kind), dict) else {}
        row: dict = {}
        for src, n in d.items():
            sv = s.get(src, 0) if isinstance(s, dict) else 0
            try:
                n2 = n - sv
            except Exception:
                n2 = n
            if n2:
                row[str(src)] = n2
        if row:
            out[str(kind)] = row
    return out


def _stat_delta(end, start) -> "dict | None":
    """[OCR统计] 快照 end 对 start 的数值增量(顶层计数逐 key 相减, by_src 递归);
    供 run_flow 单跑口径 —— 单跑路径不重置 _ocr_stat, 结束快照含进程累计, 增量才是本轮。"""
    if not isinstance(end, dict):
        return None
    base = start if isinstance(start, dict) else {}
    delta: dict = {}
    for k, v in end.items():
        if k == "by_src":
            delta[k] = _by_src_delta(v, base.get(k))
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            s = base.get(k)
            try:
                delta[k] = v - (s if isinstance(s, (int, float)) else 0)
            except Exception:
                delta[k] = v
        else:
            delta[k] = v
    return delta


# ---------------------------------------------------------------------------
# 落盘（静默容错: 失败只记 last_error, 不抛出、不打印）
# ---------------------------------------------------------------------------
def _write(record: dict) -> bool:
    global last_error
    try:
        _METRICS_DIR.mkdir(parents=True, exist_ok=True)
        with _WRITE_LOCK:
            with open(_METRICS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        return True
    except Exception as e:
        last_error = repr(e)
        return False


def metrics_round_start(source: str, name: str, screen=None, ocr_stat=None) -> "dict | None":
    """轮开始事件: 内存采样 + 画面尺寸 + [OCR统计] 起点快照 追加落盘。
    成功返回该事件记录(作为 metrics_round_end 的句柄), 失败返回 None(end 调用随之空转)。"""
    rec = {
        "event": "round_start",
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "epoch": round(time.time(), 3),
        "source": str(source),
        "name": str(name),
        "screen": [int(screen[0]), int(screen[1])] if screen else None,
        "memory": sample_memory(),
        "ocr_stat": _snapshot(ocr_stat),
    }
    return rec if _write(rec) else None


def metrics_round_end(handle, ocr_stat=None, result=None, interrupted=False) -> bool:
    """轮结束事件: 整轮耗时 + 结束内存采样 + [OCR统计] 结束快照(=整轮摘要) + 对起点增量 追加落盘。
    handle=None/非法(起点落盘失败)时静默空转 —— 度量永远不影响流程。"""
    if not isinstance(handle, dict) or handle.get("event") != "round_start":
        return False
    end_stat = _snapshot(ocr_stat)
    rec = {
        "event": "round_end",
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "epoch": round(time.time(), 3),
        "source": handle.get("source"),
        "name": handle.get("name"),
        "duration_s": round(time.time() - handle.get("epoch", time.time()), 3),
        "interrupted": bool(interrupted),
        "result": _snapshot(result) if isinstance(result, dict) else None,
        "memory": sample_memory(),
        "ocr_stat": end_stat,
        "ocr_stat_delta": _stat_delta(end_stat, handle.get("ocr_stat")),
    }
    return _write(rec)
