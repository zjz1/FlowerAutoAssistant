"""停止机制离线自测: 验证 request_stop 能在流程运行中中断 run_flow/run_daily 而不关闭进程。

归档于 dev_tools/self_test/ —— 回归「停止当前所有流程但不关闭服务」功能。无需连设备/模拟器。
用法(项目根下): .venv\\Scripts\\python.exe -u dev_tools\\self_test\\test_stop.py
"""
import sys, threading, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 项目根

import ocr_engine as E


def test_flow_interrupt():
    """run_flow 在步骤间被停止信号中断, 进程(线程)不退出。"""
    E.clear_stop()
    eng = E.OCREngine(adb_path=E.ADB_PATH, address="127.0.0.1:1")  # 不连接设备
    flow = {"name": "test_stop", "steps": [
        {"type": "sleep", "seconds": 2},
        {"type": "sleep", "seconds": 2},
        {"type": "sleep", "seconds": 2},
    ]}
    t = threading.Thread(target=lambda: eng.run_flow(flow))
    t.start()
    time.sleep(0.5)          # step1 仍在 sleep 中
    E.request_stop()         # 请求停止 -> 应在 step 边界中断
    t.join(8)
    assert not t.is_alive(), "run_flow 未被停止信号中断, 线程仍存活"
    assert E.stop_requested(), "停止标志应仍为置位(供外层感知)"
    print("OK  run_flow 运行中被停止信号中断, 进程未退出")


def test_restart_clears():
    """新一轮 run_flow 入口会 clear_stop, 可再次运行。"""
    E.clear_stop()
    assert not E.stop_requested()
    print("OK  clear_stop 后停止标志为 False")


if __name__ == "__main__":
    test_flow_interrupt()
    test_restart_clears()
    print("\n全部停止机制自测通过 ✅")