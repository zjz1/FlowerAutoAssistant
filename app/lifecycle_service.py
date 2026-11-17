# -*- coding: utf-8 -*-
"""服务进程生命周期：端口探测 / 就绪等待 / 拉起 / 优雅停 / 父进程看护。

Stage 4（2026-11-17）：把原先散落在 `webui_app.py`（Python 壳）与
`native/FAA.WpfGui/Services/FaaProcessHost.cs`（C# 壳）里的生命周期逻辑，
收敛为唯一可复用的 Python 实现。

分层约束：
- 只依赖标准库，不 import 引擎 / `http.server`，壳客户端可在不加载 OCR 的
  前提下使用（“壳只连接不持有引擎”）；
- 服务端只使用其中的 `watch_parent`，不反向依赖壳；
- 唯一事实源是 `docs/API_CONTRACT.md` 的 `/api/health`：`service == "faa"`。

生命周期口径（一个后台服务进程 + 多客户端）：
    探测(faa/other/free) → free 则拉起独立进程 → 等 health 就绪 →
    客户端订阅 /api/stream（SSE）；关窗时只停自己拉起的那个进程。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DEFAULT_PORT = 8765
HEALTH_PATH = "/api/health"
STATUS_PATH = "/api/status"
READY_TIMEOUT_S = 120.0

# 回环地址探测/停服一律绕过系统代理（HTTP_PROXY 可能把 127.0.0.1 也劫走）
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _url(port: int, path: str) -> str:
    return f"http://127.0.0.1:{int(port)}{path}"


def _get_json(port: int, path: str, timeout: float) -> dict:
    req = urllib.request.Request(_url(port, path),
                                 headers={"Accept": "application/json"})
    with _OPENER.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _port_open(port: int, timeout: float) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def probe(port: int, timeout: float = 3.0) -> str:
    """端口归属三态：'faa'=已有 FAA 服务 / 'other'=被其它程序占用 / 'free'=空闲。

    以 `/api/health` 的 `service: "faa"` 为准；旧服务没有 health 端点时回退
    `/api/status` 的 `flow_dir`+`ui_build` 两键（已在跑的旧实例仍可被复用）。
    """
    if not _port_open(port, timeout):
        return "free"
    try:
        data = _get_json(port, HEALTH_PATH, timeout)
        if isinstance(data, dict) and data.get("service") == "faa":
            return "faa"
    except Exception:
        pass
    try:
        data = _get_json(port, STATUS_PATH, timeout)
        if isinstance(data, dict) and "flow_dir" in data and "ui_build" in data:
            return "faa"
    except Exception:
        pass
    return "other"


def health(port: int, timeout: float = 3.0) -> dict | None:
    """读取 `/api/health`；服务不可达或不是 FAA 时返回 None。"""
    try:
        data = _get_json(port, HEALTH_PATH, timeout)
    except Exception:
        return None
    if isinstance(data, dict) and data.get("service") == "faa":
        return data
    return None


def wait_ready(port: int, timeout: float = READY_TIMEOUT_S, interval: float = 0.3,
               proc: subprocess.Popen | None = None) -> bool:
    """等待服务就绪（probe == 'faa'）；`proc` 提前退出时立即返回 False。"""
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        if proc is not None and proc.poll() is not None:
            return False
        if probe(port, timeout=1.0) == "faa":
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def request_shutdown(port: int, timeout: float = 3.0) -> bool:
    """POST `/api/shutdown`；服务端先回响应，再由其自身线程停服。"""
    try:
        req = urllib.request.Request(
            _url(port, "/api/shutdown"), data=b"{}",
            headers={"Content-Type": "application/json"}, method="POST")
        with _OPENER.open(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def wait_stopped(port: int, timeout: float = 15.0, interval: float = 0.2) -> bool:
    """等待端口释放（服务进程退出后 `server_close` 会关监听 socket）。"""
    deadline = time.monotonic() + max(0.0, timeout)
    while _port_open(port, 0.5):
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)
    return True


class ServiceProcess:
    """壳拉起的服务子进程句柄；保留 stderr 尾行供启动失败诊断。"""

    def __init__(self, proc: subprocess.Popen, port: int, tail: deque):
        self.proc = proc
        self.port = int(port)
        self._tail = tail

    def alive(self) -> bool:
        return self.proc.poll() is None

    def tail(self, n: int = 8) -> str:
        return " | ".join(list(self._tail)[-n:])

    def stop(self, graceful_timeout: float = 15.0) -> str:
        """优雅停：POST /api/shutdown → 等进程退出 → 超时杀进程树。"""
        if self.proc.poll() is not None:
            return "进程已退出"
        confirmed = request_shutdown(self.port, timeout=3.0)
        exited = False
        try:
            self.proc.wait(timeout=graceful_timeout)
            exited = True
        except subprocess.TimeoutExpired:
            pass
        if not exited:
            self._kill_tree()
        wait_stopped(self.port, timeout=3.0)
        return ("优雅退出" if confirmed else "进程自行退出") if exited else "超时后强杀进程树"

    def _kill_tree(self) -> None:
        """强杀整棵进程树（与 WPF `Kill(entireProcessTree: true)` 对齐）。"""
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    check=False)
            else:
                self.proc.kill()
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


def spawn(port: int, python_exe: str | None = None, script: str | Path | None = None,
          parent_pid: int | None = None, cwd: str | Path | None = None) -> ServiceProcess:
    """拉起独立服务进程（`webui.py --port N [--parent-pid P]`）。

    子进程 stdout 丢弃（服务自身有运行日志）；stderr 由守护线程收集尾行，
    只在启动失败时用于错误提示，避免管道写满阻塞服务。
    """
    exe = str(python_exe or sys.executable)
    script_path = Path(script) if script else BASE / "webui.py"
    args = [exe, str(script_path), "--port", str(int(port))]
    if parent_pid:
        args += ["--parent-pid", str(int(parent_pid))]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    kwargs = dict(cwd=str(cwd or BASE), env=env,
                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                  stderr=subprocess.PIPE)
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(args, **kwargs)

    tail: deque = deque(maxlen=40)

    def _drain() -> None:
        try:
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip()
                if line:
                    tail.append(line)
        except Exception:
            pass

    threading.Thread(target=_drain, daemon=True, name="faa-svc-stderr").start()
    return ServiceProcess(proc, port, tail)


def ensure_service(port: int, timeout: float = READY_TIMEOUT_S,
                   parent_pid: int | None = None, spawn_fn=None
                   ) -> tuple[str, ServiceProcess | None]:
    """三态收口：复用已有实例 / 拒绝非 FAA 占用 / 拉起新进程并等就绪。

    返回 `(state, svc)`：
    - `("faa", None)`      ：复用了已有实例（调用方不负责停）；
    - `("faa", svc)`       ：由本次调用拉起（调用方负责停）；
    - `("other", None)`    ：端口被非 FAA 程序占用；
    - `("failed", svc)`    ：拉起了但未就绪（svc 可能仍存活，调用方应 stop）。

    并发拉起竞态：spawn 后若子进程提前退出，再探一次端口 —— 若已是 faa，
    说明另一个实例抢先绑定，按“复用已有实例”返回，避免双服务/端口冲突。
    """
    state = probe(port)
    if state != "free":
        return state, None
    proc = (spawn_fn or spawn)(port, parent_pid=parent_pid)
    if wait_ready(port, timeout=timeout, proc=proc.proc):
        return "faa", proc
    if not proc.alive() and probe(port) == "faa":
        return "faa", None
    return "failed", proc


def watch_parent(parent_pid: int, on_exit) -> threading.Thread:
    """父进程退出看护（守护线程）：父进程消失时调用 `on_exit`。

    壳被强杀（任务管理器/控制台被关）时保证服务不变成孤儿监听端口；
    父进程正常退出同样生效。on_exit 在独立线程执行，调用方自行保证线程安全。
    """
    def _loop() -> None:
        if os.name == "nt":
            parent_gone = _wait_parent_windows(int(parent_pid))
        else:
            while True:
                try:
                    os.kill(int(parent_pid), 0)
                except OSError:
                    break
                time.sleep(1.0)
            parent_gone = True
        if not parent_gone:
            return                  # 无法看护（如权限不足）时不误停服务
        try:
            on_exit()
        except Exception:
            pass

    t = threading.Thread(target=_loop, daemon=True, name="faa-parent-watch")
    t.start()
    return t


def _wait_parent_windows(parent_pid: int) -> bool:
    """Windows: 等父进程句柄信号；返回 True=父进程已退出，False=无法看护。"""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

    SYNCHRONIZE = 0x00100000
    WAIT_TIMEOUT = 0x00000102
    ERROR_INVALID_PARAMETER = 87
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, parent_pid)
    if not handle:
        # pid 不存在 = 父进程已退出；其它错误（如权限不足）不误判为退出
        return ctypes.get_last_error() == ERROR_INVALID_PARAMETER
    try:
        while kernel32.WaitForSingleObject(handle, 1000) == WAIT_TIMEOUT:
            pass
    finally:
        kernel32.CloseHandle(handle)
    return True
