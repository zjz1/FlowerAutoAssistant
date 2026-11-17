# -*- coding: utf-8 -*-
"""故障存证截图缓存服务：统计 / 清理 / 归档 / 提示状态。

从 webui.py 迁出（Stage 1）。不依赖 HTTP，可被 CLI 复用。
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path

from app.engine_service import peek_engine
from app.log_service import append as log_append

BASE = Path(__file__).resolve().parents[1]
FAIL_CACHE_DIR = BASE / "data" / "fail_cache"
FAIL_ARCHIVE_DIR = BASE / "data" / "fail_archives"

_CACHE_PROMPT_PENDING = True      # 本次服务会话是否还未弹出过缓存提醒
LAST_ARCHIVE = None               # 最近一次归档: {ts,count,bytes,files:set}
_STAT_LOCK = threading.Lock()
_STAT_CACHE: dict | None = None
_STAT_TS = 0.0
_STAT_TTL = 10.0


def stat(force: bool = False) -> dict:
    """统计缓存: 总字节/张数/会话数/最早一张时间(按文件名内嵌时间戳)。"""
    global _STAT_CACHE, _STAT_TS
    now = time.time()
    with _STAT_LOCK:
        cached = _STAT_CACHE
        cached_ts = _STAT_TS
    if not force and cached is not None and (now - cached_ts) < _STAT_TTL:
        return cached
    total = 0
    count = 0
    sessions = []
    files = set()
    oldest = None
    try:
        if not FAIL_CACHE_DIR.exists():
            out = {"bytes": 0, "count": 0, "sessions": 0, "oldest": None, "session": "",
                   "session_files": 0, "files": files}
            with _STAT_LOCK:
                _STAT_CACHE = out
                _STAT_TS = time.time()
            return out
        for d in sorted(FAIL_CACHE_DIR.iterdir()):
            if not d.is_dir():
                continue
            n = 0
            for f in d.iterdir():
                if f.is_file() and f.suffix.lower() in (".jpg", ".png"):
                    total += f.stat().st_size
                    count += 1
                    n += 1
                    files.add(f"{d.name}/{f.name}")
                    parts = f.stem.split("_")
                    ts = parts[1] if len(parts) > 2 else None
                    if ts and ts.isdigit() and len(ts) == 8:
                        if oldest is None or ts < oldest:
                            oldest = ts
            if n:
                sessions.append(d.name)
    except Exception as e:
        print(f"[截图缓存] 统计异常(不影响流程): {e}")
    # 当前会话戳：只读 engine，不触发创建/加载 OCR
    eng = peek_engine()
    cur = getattr(eng, "_session_stamp", "") or ""
    cur_files = 0
    if cur and (FAIL_CACHE_DIR / cur).exists():
        cur_files = sum(1 for f in (FAIL_CACHE_DIR / cur).iterdir() if f.is_file())
    out = {"bytes": total, "count": count, "sessions": len(sessions),
           "oldest": oldest, "session": cur, "session_files": cur_files, "files": files}
    with _STAT_LOCK:
        _STAT_CACHE = out
        _STAT_TS = time.time()
    return out


def invalidate_stat() -> None:
    global _STAT_CACHE, _STAT_TS
    with _STAT_LOCK:
        _STAT_CACHE = None
        _STAT_TS = 0.0


def clean(mode: str = "all", days: int | None = None) -> dict:
    """清理缓存像素（index.jsonl 墓碑永久保留）。mode: all | days。"""
    stat(force=True)
    if not FAIL_CACHE_DIR.exists():
        return {"removed": 0, "bytes": 0, "sessions": 0, "kept": 0}
    cutoff = None
    if mode == "days" and days:
        cutoff = time.strftime("%Y%m%d", time.localtime(time.time() - int(days) * 86400))
    removed = rbytes = rsess = kept = 0
    evicted_files = set()
    for d in sorted(FAIL_CACHE_DIR.iterdir()):
        if not d.is_dir():
            continue
        files = [f for f in d.iterdir() if f.is_file() and f.suffix.lower() in (".jpg", ".png")]
        if not files:
            continue
        stamps = [f.stem.split("_")[1] for f in files
                  if len(f.stem.split("_")) > 2 and f.stem.split("_")[1].isdigit()]
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
    marked = 0
    idx = FAIL_CACHE_DIR / "index.jsonl"
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
    invalidate_stat()
    return {"removed": removed, "bytes": rbytes, "sessions": rsess, "kept": kept}


def archive(ts: str) -> dict:
    """把缓存目录现存全部截图复制到 data/fail_archives/<ts>/ + manifest。"""
    global LAST_ARCHIVE
    st = stat(force=True)
    sess = st.get("session") or ""
    dst = FAIL_ARCHIVE_DIR / ts
    copied = []
    total = 0
    sess_count = 0
    try:
        dst.mkdir(parents=True, exist_ok=True)
        if FAIL_CACHE_DIR.exists():
            for d in sorted(FAIL_CACHE_DIR.iterdir()):
                if not d.is_dir():
                    continue
                files = sorted(f for f in d.iterdir()
                               if f.is_file() and f.suffix.lower() in (".jpg", ".png"))
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
        idxmap, evicted = {}, []
        idx = FAIL_CACHE_DIR / "index.jsonl"
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
                 "#      「(已淘汰)」= 该图已被缓存清理(像素已删), 但其存证记录(时间/tag/全量OCR文本)",
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
        LAST_ARCHIVE = {"ts": ts, "count": len(copied), "bytes": total, "files": set(copied)}
    invalidate_stat()
    return {"dir": str(dst), "count": len(copied), "bytes": total,
            "sessions": len({c.split("/")[0] for c in copied}), "session_files": sess_count,
            "evicted": len([f for f in evicted if f not in copied])}


def consume_prompt(cmb: float, threshold: float) -> bool:
    global _CACHE_PROMPT_PENDING
    prompt = bool(_CACHE_PROMPT_PENDING and cmb >= threshold)
    _CACHE_PROMPT_PENDING = False
    return prompt


def last_archive():
    return LAST_ARCHIVE
