# -*- coding: utf-8 -*-
"""HTTP 服务启动入口（webui.py 兼容 shim 调用）。

Stage 4：服务是**独立后台进程**，客户端（浏览器 / pywebview / WPF）只连不持有；
`--parent-pid` 让壳被强杀时服务随父进程退出，不留孤儿监听端口。
"""
from __future__ import annotations

import argparse
import sys
import time
from http.server import ThreadingHTTPServer

from app import engine_service, lifecycle_service, log_service, run_service
from ocr_engine import ADB_ADDRESS, ADB_PATH

from . import common
from .handler import Handler

EXIT_PORT_IN_USE = 2


def _bind(port: int) -> ThreadingHTTPServer:
    try:
        return ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        # 端口绑定即单实例锁：已有服务时客户端应先 probe 复用，而不是重复拉起
        print(f"[webui] 无法绑定端口 {port}: {e}", file=sys.stderr)
        print("[webui] 可能已有 FAA 实例在运行；客户端应先探测复用。", file=sys.stderr)
        sys.exit(EXIT_PORT_IN_USE)


def _force_utf8_pipes(streams=None) -> None:
    """把被管道接管的 stdout/stderr 统一为 UTF-8（Phase 2 冻结包修复）。

    冻结包( PyInstaller )里 PYTHONIOENCODING 不生效时, 管道输出按 locale(cp936) 编码,
    .NET 壳按 UTF-8 解码 → 中文日志变替换符。这里只改**非 tty**流(管道/重定向),
    控制台直跑(tty)保持系统编码不变。reconfigure 不存在/已关闭时静默跳过。
    """
    for stream in (sys.stdout, sys.stderr) if streams is None else streams:
        try:
            if stream is not None and not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main() -> None:
    _force_utf8_pipes()
    parser = argparse.ArgumentParser(description="FAA Web UI")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--address", default=ADB_ADDRESS)
    parser.add_argument("--adb", default=ADB_PATH)
    parser.add_argument("--parent-pid", type=int, default=0,
                        help="父进程 PID：父进程退出时本服务自动停（壳拉起时使用）")
    # 1.0 Phase 4：环境自检 / 脱敏诊断包（均为一次性命令，不启动服务）
    parser.add_argument("--check-env", action="store_true", help="检查运行环境后退出")
    parser.add_argument("--json", action="store_true", help="配合 --check-env: JSON 输出")
    parser.add_argument("--deep", action="store_true", help="配合 --check-env: 额外加载 OCR 模型")
    parser.add_argument("--export-diag", metavar="ZIP", help="导出脱敏诊断包后退出")
    args = parser.parse_args()

    if args.check_env:
        from diagnostics.env_check import main as env_main
        sys.exit(env_main(json_out=args.json, deep=args.deep))
    if args.export_diag:
        from diagnostics.bundle import main as diag_main
        sys.exit(diag_main(args.export_diag))

    # 用命令行优先的 ADB 参数重新初始化单例
    if args.address != ADB_ADDRESS or args.adb != ADB_PATH:
        engine_service.configure_engine(args.adb, args.address)

    # 每次启动都清空日志缓存(内存 + 磁盘)
    log_service.reset_history()
    run_service.set_running(False)
    log_service.append(f"[webui] 服务启动 {time.strftime('%Y-%m-%d %H:%M:%S')} "
                       f"-> http://127.0.0.1:{args.port}/\n")

    srv = _bind(args.port)
    common.SERVER = srv

    if args.parent_pid > 0:
        lifecycle_service.watch_parent(args.parent_pid, srv.shutdown)
        log_service.append(f"[webui] 已登记父进程看护 (pid={args.parent_pid})\n")

    print("\n=== FAA Web UI ===")
    print(f"打开浏览器: http://127.0.0.1:{args.port}/")
    print(f"ADB: {args.adb}  {args.address}")
    print("按 Ctrl+C 退出\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[WebUI] 已退出")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
