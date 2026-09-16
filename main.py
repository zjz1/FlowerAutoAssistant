"""
FlowerAutoAssistant - 主入口主循环
========================
- 连接模拟器 (ADB)
- 按需加载并循环执行挂机流程 (flows/*.json)
- 端到端验证: 截图 -> OCR -> 定位 -> 点击
- 日志输出 + 可中断 (Ctrl+C)
- 断线/失败重连保护

用法:
    python main.py                          # 连接并执行每日挂机流程 1 次
    python main.py --flow 每日 --loop 0    # 无限循环执行"每日挂机"流程
    python main.py --loop 5               # 执行 5 次
    python main.py --list                 # 列出可用流程
    python main.py --address 127.0.0.1:5555  # 指定 ADB 地址
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

from ocr_engine import OCREngine, load_flows, select_flow, ADB_ADDRESS, ADB_PATH, request_stop, stop_requested

_RUNNING = True


def _on_signal(sig, frame):
    global _RUNNING
    print("\n[中断] 收到停止信号, 将在本次流程结束后退出...")
    _RUNNING = False
    request_stop()  # 同步请求停止正在执行的流程步骤


def parse_args():
    p = argparse.ArgumentParser(description="FAA 一键挂机主程序")
    p.add_argument("--flow", default="每日", help="流程关键字 (默认: 每日)")
    p.add_argument("--loop", type=int, default=1, help="循环次数, 0=无限 (默认: 1)")
    p.add_argument("--address", default=ADB_ADDRESS, help=f"ADB 地址 (默认: {ADB_ADDRESS})")
    p.add_argument("--adb", default=ADB_PATH, help="adb 可执行文件路径")
    p.add_argument("--interval", type=float, default=1.0, help="每轮循环之间间隔秒 (默认 1.0)")
    p.add_argument("--tail", default=None, help="切换账号目标账户尾部数字 (覆盖 data/config.json 的 target_tail, 默认 None=用配置)")
    p.add_argument("--list", action="store_true", help="列出可用流程并退出")
    return p.parse_args()


def main():
    args = parse_args()
    signal.signal(signal.SIGINT, _on_signal)

    flows = load_flows()
    if args.list:
        print("可用流程:")
        for f in flows:
            print(f"  - {f.get('name')}  [{f.get('_file')}]")
        return

    target = select_flow(flows, args.flow)
    if target is None:
        print(f"未找到流程包含关键字 '{args.flow}'. 可用: {[f.get('name') for f in flows]}")
        return

    eng = OCREngine(adb_path=args.adb, address=args.address)
    if args.tail is not None:
        eng.config["target_tail"] = str(args.tail)
        print(f"[配置] 切换账号目标账户尾部: {args.tail}")
    if not eng.connect():
        print("[错误] 连接模拟器失败, 请确认模拟器已启动且 ADB 可用")
        return

    rounds = args.loop
    if rounds < 0:
        rounds = 1
    count = 0
    print(f"\n===== 开始自动挂机 =====")
    print(f"流程: {target.get('name')}")
    print(f"循环: {'无限' if rounds == 0 else f'{rounds} 次'}")
    print(f"模拟器: {args.address}")
    print(f"按 Ctrl+C 停止\n")

    while _RUNNING and not stop_requested():
        if rounds > 0 and count >= rounds:
            break
        count += 1
        print(f"\n--------- 第 {count} 轮 ---------")
        try:
            eng.run_flow(target) if "modules" not in target else eng.run_daily(target)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[异常] 第 {count} 轮执行出错: {e}")
            # 尝试重连
            try:
                print("[重连] 尝试重新连接...")
                eng.connect()
            except Exception as ce:
                print(f"[重连失败] {ce}")
                break
        if _RUNNING:
            time.sleep(args.interval)

    print(f"\n===== 挂机结束, 共执行 {count} 轮 =====")


if __name__ == "__main__":
    main()