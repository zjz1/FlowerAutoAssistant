"""设备连接/截图/点击/滑动/返回键。

E01(batch-03, 2026-11-14) 自单文件 ocr_engine.py 机械拆包: 本文件各段为原文件对应
行段的**逐行原文**(唯 __file__ 锚点因包层级 +1 机械重锚定, 见 ast_hash_compare.py
allowlist)。行为等价口径: 帧集回归 0 退化 + 闸门全绿 + import 面零改动。
原行段映射: evidence/batch-03/tiles_manifest.json。
"""
from __future__ import annotations

import os
import time

from pathlib import Path

import numpy as np

from .._failures import report_failure

class _DeviceMixin:
    # ---- 设备 ----

    # ---- Q04(batch-05, 2026-11-14): MAA Job 统一下发封装(wait + 成败核验, 纯观测) ----
    def _post(self, ctrl, action: str, *args, desc: str = ""):
        """`ctrl.post_<action>(*args).wait()` + Job 成败核验。返回 job 本身
        (screencap 调用方需再 .get() 取图; 其余调用点忽略返回值, 控制流与旧版一致)。

        原 7 处调用点(post_screencap/post_click/post_swipe/post_touch_down/
        post_touch_move/post_touch_up/post_stop_app)只 .wait() 不查成败 —— maa.job.Job
        既有 succeeded/failed/status 属性(venv maa/job.py:69)而本仓零使用, ADB 断连/
        点击被吞只能靠「画面没变」分钟级间接推断。本封装为**纯观测**(清单铁律):
        失败经 report_failure 打 [失败] 行(落运行日志 + WebUI 弹窗清单), 不重试、
        不改变调用方控制流 —— 判定行为零变化。
        job 无 succeeded 属性(非 MAA Job 的假引擎桩)时按旧语义不登记, 便于 mock。
        """
        job = getattr(ctrl, "post_" + action)(*args)
        job.wait()
        if not getattr(job, "succeeded", True):
            report_failure(self._module,
                           f"MAA 动作 {action} 未成功(job.succeeded=False)"
                           + (f" [{desc}]" if desc else ""))
        return job

    def connect(self) -> bool:
        from maa.controller import AdbController
        from maa.toolkit import Toolkit

        Toolkit.init_option("./")
        ctrl = AdbController(adb_path=self.adb_path, address=self.address)
        ctrl.post_connection().wait()
        if not ctrl.connected:
            print("[错误] 连接失败")
            return False
        self._ctrl = ctrl
        self.debug_click = bool(os.environ.get("FAA_DEBUG_CLICK", ""))
        self._click_seq = 0
        if self.debug_click:
            self.debug_dir = Path(__file__).resolve().parent.parent.parent / "data" / "click_debug"
            self.debug_dir.mkdir(parents=True, exist_ok=True)
        # 连接即读取画面尺寸(2026-10-06 用户要求, 2026-10-07 细化为两套):
        # ① 工作区(screen_w/h): MAA 首帧, 先清零再探, 重连/换模拟器必拿当前值, 供
        #    全部相对坐标运算使用(与 MAA 点击同空间, 自洽);
        # ② 实机分辨率(display_w/h): adb 原生截图直读(不经 MAA 长边缩放), 供 WebUI
        #    展示与用户多分辨率适配决策; 读取失败时置 0, WebUI 回退显示工作区。
        self.screen_w = 0
        self.screen_h = 0
        if self.screenshot() is not None:
            print(f"[连接] 引擎工作区: {self.screen_w}x{self.screen_h}")
        else:
            print("[连接] 警告: 连接后首帧截图失败, 工作区尺寸留待下次截图时读取")
        self.display_w, self.display_h = 0, 0
        try:
            import subprocess
            raw = subprocess.run(
                [self.adb_path, "-s", self.address, "exec-out", "screencap", "-p"],
                capture_output=True, timeout=15).stdout
            import cv2 as _cv2
            dimg = _cv2.imdecode(np.frombuffer(raw, np.uint8), _cv2.IMREAD_COLOR)
            if dimg is not None:
                self.display_h, self.display_w = dimg.shape[:2]
        except Exception as e:
            print(f"[连接] 实机分辨率直读失败(仅影响显示, 不影响运行): {e}")
        if self.display_w:
            tag = " (MAA 长边缩放)" if self.display_w != self.screen_w or self.display_h != self.screen_h else ""
            print(f"[连接] 实机分辨率: {self.display_w}x{self.display_h} / 引擎工作区: {self.screen_w}x{self.screen_h}{tag}")
        else:
            print(f"[连接] 实机分辨率未读到, 显示回退引擎工作区 {self.screen_w}x{self.screen_h}")
        return True

    def screenshot(self) -> np.ndarray | None:
        """截图, 并记录当前屏幕尺寸。返回 BGR ndarray。
        同时记录最近一帧 last_frame/last_frame_ts, 供 WebUI 预览在流程运行期直接复用
        (见 webui._screen) —— 引擎本就连续截图, 预览不再自己截, 消除两者对 ADB 控制器的争抢。

        Q04(batch-05): ①截图耗时并入 [OCR统计] 的 shot_n/shot_t(纯新增键, 既有键不动) ——
        输入管道是主要慢因之一(模拟器输入延迟可达数十秒), 此前 OCR/截图耗时无法分账;
        ②post_screencap 的 Job 成败经 _post 核验, 失败打 [失败] 行 —— 原 img None 时
        静默 return None, 下游只表现为「画面没变」, 分钟级延迟才暴露。判定行为零变化:
        失败时仍返回 None, 下游「画面没变」分支照旧。
        """
        t0 = time.perf_counter()
        img = self._post(self._ctrl, "screencap", desc="截图").get()
        dt = time.perf_counter() - t0
        st = getattr(self, "_ocr_stat", None)
        if st is not None:
            st["shot_n"] = st.get("shot_n", 0) + 1
            st["shot_t"] = st.get("shot_t", 0.0) + dt
        if img is None:
            return None
        # img shape = (H, W, 3)
        self.screen_h, self.screen_w = img.shape[:2]
        self.last_frame = img
        self.last_frame_ts = time.monotonic()
        return img

    def click_abs(self, x: int, y: int) -> None:
        if getattr(self, "debug_click", False):
            self._snapshot_click(int(x), int(y))
        self._post(self._ctrl, "click", int(x), int(y), desc=f"绝对({x},{y})")
        print(f"[点击] 绝对({x},{y})")

    def _snapshot_click(self, x: int, y: int) -> None:
        """调试: 点击前截图, 用红框标注点击点并保存, 便于逐帧核对点击区域。"""
        try:
            img = self.screenshot()
            if img is None:
                return
            import cv2
            img = img.copy()
            cv2.rectangle(img, (x - 25, y - 25), (x + 25, y + 25), (0, 0, 255), 2)
            cv2.circle(img, (x, y), 5, (0, 0, 255), -1)
            self._click_seq += 1
            fp = self.debug_dir / f"click_{self._click_seq:03d}_({x}_{y}).png"
            cv2.imwrite(str(fp), img)
            self._last_snapshot = fp
            print(f"[截图] 点击区域已保存 -> {fp.name}")
        except Exception as e:
            print(f"[截图调试] 失败: {e}")

    def click_rel(self, rx: float, ry: float) -> None:
        """按相对坐标点击 (自适应屏幕尺寸)。
        若屏幕尺寸未知(尚未截图)则先截图获取; 避免相对坐标算成 (0,0)。
        """
        if not self.screen_w or not self.screen_h:
            self.screenshot()
        if not self.screen_w or not self.screen_h:
            print("[点击] 相对坐标失败: 屏幕尺寸未知")
            return
        x = int(rx * self.screen_w)
        y = int(ry * self.screen_h)
        print(f"[点击] 相对({rx:.3f},{ry:.3f}) -> 绝对({x},{y})")
        self.click_abs(x, y)

    def swipe_rel(self, rx1: float, ry1: float, rx2: float, ry2: float,
                  duration_ms: int = 300) -> None:
        """按相对坐标执行滑动手势(滚屏/拖动, 2026-10-06 方案一引入, 供好友列表底行补救等)。
        ⚠ 规则6边界(2026-10-06 用户裁定): 滑动是**手势动作**, 没有「识别目标」可定位 ——
        起终点是手势参数而非点击坐标, 用相对坐标随分辨率自适应, 不属被禁的『直接坐标点击』;
        点击类操作仍必须 OCR/template/场景识别实时定位后才进行。
        屏幕尺寸未知时先截图获取, 避免换算成 (0,0)。
        """
        if not self.screen_w or not self.screen_h:
            self.screenshot()
        if not self.screen_w or not self.screen_h:
            print("[滑动] 失败: 屏幕尺寸未知")
            return
        x1, y1 = int(rx1 * self.screen_w), int(ry1 * self.screen_h)
        x2, y2 = int(rx2 * self.screen_w), int(ry2 * self.screen_h)
        self._post(self._ctrl, "swipe", x1, y1, x2, y2, int(duration_ms),
                   desc=f"({x1},{y1})->({x2},{y2})")
        print(f"[滑动] 相对({rx1:.3f},{ry1:.3f})->({rx2:.3f},{ry2:.3f}) "
              f"绝对({x1},{y1})->({x2},{y2}) {duration_ms}ms")

    def back(self) -> bool:
        """发送 Android 返回键 (adb shell input keyevent 4)。用于关闭弹窗/返回上一级。
        返回 True/False。失败时回退点击屏幕左上角。
        """
        import subprocess
        try:
            # 尝试用 adb 命令行发 keyevent (返回键 code=4)
            subprocess.run(
                [self.adb_path, "-s", self.address, "shell", "input", "keyevent", "4"],
                capture_output=True, timeout=5, check=True,
            )
            print("[back] 已发送返回键 keyevent=4")
            return True
        except Exception as e:
            print(f"[back] adb keyevent 失败({e}), 回退点击左上角")
            self.click_abs(20, 20)
            return False
