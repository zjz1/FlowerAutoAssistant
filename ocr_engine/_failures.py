"""功能失败登记(WebUI 弹窗数据源)。

E01(batch-03, 2026-11-14) 自单文件 ocr_engine.py 机械拆包: 本文件各段为原文件对应
行段的**逐行原文**(唯 __file__ 锚点因包层级 +1 机械重锚定, 见 ast_hash_compare.py
allowlist)。行为等价口径: 帧集回归 0 退化 + 闸门全绿 + import 面零改动。
原行段映射: evidence/batch-03/tiles_manifest.json。
"""
from __future__ import annotations

import threading
import time
from collections import deque
# ---------------------------------------------------------------------------
# 功能失败登记: 供「任意功能失败就提醒」(WebUI 弹窗, 2026-10-02 需求)。
# 只登记**真实失败**(等待超时 / 放弃 / 跑满轮数 / 模块异常), 不得把缓存回退当失败或成功判据。
# 登记 = ① print(带 [失败] 前缀, 落盘进运行日志) ② 存内存清单, 供 WebUI 增量拉取弹窗。
# 2026-11-20: 内存清单设上限(保留最近 1000 条), 长跑不线性增长; id 仍单调递增。
# ---------------------------------------------------------------------------
_FAIL_LOCK = threading.Lock()
_FAILURES: deque = deque(maxlen=1000)
_FAIL_SEQ = 0


def report_failure(module: str, detail: str) -> None:
    """登记一次功能失败。module=当前模块/场景, detail=人可读原因。"""
    global _FAIL_SEQ
    with _FAIL_LOCK:
        _FAIL_SEQ += 1
        _FAILURES.append({
            "id": _FAIL_SEQ,
            "ts": time.strftime("%H:%M:%S"),
            "module": str(module or "未分类"),
            "detail": str(detail),
        })
    print(f"[失败] [{module or '未分类'}] {detail}")


def get_failures(after: int = 0) -> tuple[list[dict], int]:
    """取 id > after 的失败清单, 返回 (items, 最新 id)。供 WebUI 增量轮询。"""
    with _FAIL_LOCK:
        items = [dict(f) for f in _FAILURES if f["id"] > after]
        return items, _FAIL_SEQ


def clear_failures() -> None:
    """清空失败清单(不影响已打印落盘的日志)。"""
    with _FAIL_LOCK:
        _FAILURES.clear()
