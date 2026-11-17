# -*- coding: utf-8 -*-
"""运行控制服务：运行状态机、互斥门、后台线程、日志换轨。

从 webui.py 迁出（Stage 1）。Handler 只负责参数校验与响应序列化。
"""
from __future__ import annotations

import sys
import threading

from app.engine_service import get_engine, is_connected
from app.log_service import LOGS, TeeOut, append as log_append

_LOCK = threading.Lock()
_RUNNING = False


class RunConflict(Exception):
    """已有流程在运行。"""


def set_running(value: bool) -> None:
    global _RUNNING
    with _LOCK:
        _RUNNING = value


def running() -> bool:
    with _LOCK:
        return _RUNNING


def try_claim() -> bool:
    """原子 check-and-set：空闲则置 running=True 并返回 True。"""
    global _RUNNING
    with _LOCK:
        if _RUNNING:
            return False
        _RUNNING = True
        return True


def _spawn(name: str, runner, start_line: str, thread_name: str = "faa-run") -> None:
    """后台线程：连接 → stdout/stderr 换轨 → runner(eng) → 恢复 → running=False。"""
    def job():
        eng = get_engine()
        try:
            if not is_connected(eng):
                eng.connect()
        except Exception as e:
            log_append(f"[run] 连接失败: {e}")
            set_running(False)
            return

        with _LOCK:
            real_out, real_err = sys.stdout, sys.stderr
            sys.stdout = TeeOut(real_out, LOGS)
            sys.stderr = TeeOut(real_err, LOGS)
        try:
            eng = get_engine()
            try:
                if not is_connected(eng):
                    eng.connect()
            except Exception as e:
                log_append(f"[run] 连接失败: {e}")
            sys.stdout = TeeOut(real_out, LOGS)
            sys.stderr = TeeOut(real_err, LOGS)
            log_append(start_line)
            runner(eng)
            log_append(f"[run] ==== {name} 完成 ====")
        except Exception as e:
            log_append(f"[run] 流程异常: {e}")
        finally:
            with _LOCK:
                sys.stdout, sys.stderr = real_out, real_err
            set_running(False)

    try:
        threading.Thread(target=job, daemon=True, name=thread_name).start()
    except Exception:
        set_running(False)
        raise


def start_flow(target: dict, name: str) -> None:
    """运行单流程（target 含 modules 时走 run_daily）。"""
    if not try_claim():
        raise RunConflict
    def runner(eng):
        if "modules" in target:
            eng.run_daily(target)
        else:
            eng.run_flow(target)
    _spawn(name, runner, f"[run] ==== {name} 开始 ====")


def start_daily(plan: dict, name: str, count: int) -> None:
    """运行每日编排。"""
    if not try_claim():
        raise RunConflict
    _spawn(name, lambda eng: eng.run_daily(plan),
           f"[run] ==== {name} (勾选 {count} 模块) 开始 ====", thread_name="faa-daily")


# 兼容旧名
_running = running
_set_running = set_running
_try_claim_running = try_claim
