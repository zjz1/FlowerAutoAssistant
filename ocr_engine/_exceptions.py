"""全局停止机制与三层中止异常(StopRequested/BranchAborted/FlowFailed)。

E01(batch-03, 2026-11-14) 自单文件 ocr_engine.py 机械拆包: 本文件各段为原文件对应
行段的**逐行原文**(唯 __file__ 锚点因包层级 +1 机械重锚定, 见 ast_hash_compare.py
allowlist)。行为等价口径: 帧集回归 0 退化 + 闸门全绿 + import 面零改动。
原行段映射: evidence/batch-03/tiles_manifest.json。
"""
from __future__ import annotations

import threading
# ---------------------------------------------------------------------------
# 全局停止机制: 用于「停止当前所有流程但不关闭服务/进程」。
# 任意调用方(CLI/WebUI/编排)均可 request_stop() 请求停止;
# 引擎在 run_flow/run_daily 入口 clear_stop(), 在步骤/模块/等待循环之间检查
# stop_requested(), 命中即抛出 StopRequested 中断本轮全部流程执行。
# ---------------------------------------------------------------------------
_STOP_EV = threading.Event()


class StopRequested(BaseException):
    """流程被 request_stop() 请求停止时抛出, 用于从深层(等待/循环/嵌套步骤)向上冒泡中断。
    继承 BaseException-> 不会被引擎内的 `except Exception`(run_module 容错)吞掉,
    从而一路穿透到最外层 run_flow/run_daily 的统一停止处理。"""


class BranchAborted(Exception):
    """E2(2026-10-27, zcode-20261028-3): 分支内短路 —— 带 `required: true` 的步骤失败时抛出,
    由 run_steps 捕获后**中止当前 then/else 列表**、继续执行列表之后的步骤。
    与 FlowFailed(模块级中止, on_fail 处置)的区别: 本异常只放弃"当前分支的剩余步骤"
    (例如 if_collected.then 里的任务链), 编排与后续模块不受影响; 失败本身已由
    report_failure 如实登记, 不伪装成功。"""

class FlowFailed(Exception):
    """流程主动判定失败(由流程 JSON 的 `fail_flow` 步骤抛出)。

    与 StopRequested 的区别: StopRequested 是「用户请求停止」(中断整轮, 不算失败);
    FlowFailed 是「本模块确实没做成」(如实上报失败, 由 run_module 收成 'fail', 再交给编排的
    on_fail 决定跳过还是终止本轮)。用于「前置条件不满足时, 继续往下会跑出一整轮假结果」的场景
    ——例如切换账号失败仍去点「登录」, 就会用错误账号跑完当天全部任务。
    继承 Exception -> 会被 run_module 捕获并登记失败, 不会冒泡到进程外。
    """


def request_stop() -> None:
    """请求停止当前正在进行的所有流程。服务/进程保持运行, 可再次开始新一轮。"""
    _STOP_EV.set()


def clear_stop() -> None:
    """清除停止请求(新一轮流程开始前自动调用)。"""
    _STOP_EV.clear()


def stop_requested() -> bool:
    """是否已被请求停止。"""
    return _STOP_EV.is_set()
