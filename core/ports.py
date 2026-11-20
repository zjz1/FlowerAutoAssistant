# -*- coding: utf-8 -*-
"""核心端口定义（Stage 3）。

业务模块依赖这些 Protocol，而不是具体 `OCREngine` 类：
  - `UiPort`：截图 / OCR / 定位 / 点击 / 关闭弹窗；
  - `TemplatePort`：模板匹配与点击；
  - `JudgePort`：场景、数字/比例、奖励弹窗判据；
  - `DevicePort`：连接、滑动、屏幕尺寸、ADB 地址；
  - `ConfigPort`：配置读写；
  - `FlowPort`：流程/每日编排执行；
  - `EnginePort`：以上能力的组合，供业务模块统一标注。

运行时不改变任何行为；`OCREngine` 以结构化子类型自然满足这些 Protocol。
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

# OCR 块 / 点坐标等结构由引擎返回；端口层不重复定义具体形状，避免与实现耦合。
OcrBlock = dict[str, Any]
PointLike = Any


@runtime_checkable
class DevicePort(Protocol):
    screen_w: int
    screen_h: int
    adb_path: str
    address: str

    def connect(self) -> bool: ...
    def swipe_rel(self, rx1: float, ry1: float, rx2: float, ry2: float,
                  duration_ms: int = 300) -> Any: ...
    def click_rel(self, rx: float, ry: float) -> Any: ...


@runtime_checkable
class UiPort(Protocol):
    screen_w: int
    screen_h: int
    adb_path: str
    address: str

    def screenshot(self) -> Any: ...
    def ocr_blocks(self, img=None, region_rel=None) -> list[OcrBlock]: ...
    def ocr_direct(self, img, src: str = "ocr") -> list[OcrBlock]: ...
    def locate(self, keywords, img=None, min_score: float = 0.4, exact: bool = False,
               region_rel=None, exclude=None, need_refine: bool = True,
               log_miss: bool = True) -> PointLike | None: ...
    def locate_fine(self, kws, region_rel=None, upscale: int = 2,
                    min_score: float = 0.4, img=None, exact: bool = False,
                    exclude=None) -> PointLike | None: ...
    def click_abs(self, x: int, y: int) -> Any: ...
    def click_text(self, keywords, img=None, fallback_rel=None,
                   min_score: float = 0.4, exact: bool = False, region_rel=None,
                   exclude=None, no_fallback: bool = False) -> bool: ...
    def close_dialog(self, img=None, anchor_kw=None, dx_range=None, dy_tol=None,
                     min_score: float = 0.3, only_types=None, verify_wait: float = 1.0,
                     max_tries: int = 2) -> bool: ...


@runtime_checkable
class TemplatePort(Protocol):
    def locate_template(self, template: str, img=None, threshold: float = 0.8,
                        region_rel=None, scale_range=(0.7, 1.0), metric: str = "sqdiff",
                        return_score: bool = False, quiet: bool = False) -> Any: ...
    def locate_template_all(self, template: str, img=None, threshold: float = 0.8,
                            region_rel=None, scale_range=(0.7, 1.0),
                            nms_gap_rel: float = 0.05) -> list[Any]: ...
    def click_template(self, template: str, img=None, threshold: float = 0.8,
                       region_rel=None, scale_range=(0.7, 1.0), fallback_rel=None,
                       no_fallback: bool = False, metric: str = "sqdiff",
                       offset_rel=None) -> Any: ...


@runtime_checkable
class JudgePort(Protocol):
    def judge_scene(self, name: str, img=None, min_score: float = 0.4,
                    quiet: bool = False) -> bool: ...
    def set_scene(self, name: str, quiet: bool = False) -> Any: ...
    def parse_fraction_at(self, region_rel, img=None, tol: float = 0.01) -> Any: ...
    def parse_count_at(self, region_rel, img=None, tol: int = 120,
                       min_score: float = 0.0) -> Any: ...
    def pink_ratio_at(self, pt, img, color_cfg, tol) -> Any: ...
    def has_reward_popup(self, img=None, region_rel=None, keywords=None) -> bool: ...
    def reward_dialog(self, step) -> Any: ...
    def get_ocr_stat(self) -> dict: ...


@runtime_checkable
class ConfigPort(Protocol):
    config: dict[str, Any]

    def update_config(self, **kwargs) -> Any: ...


@runtime_checkable
class FlowPort(Protocol):
    def run_flow(self, flow: dict) -> Any: ...
    def run_daily(self, plan: dict) -> Any: ...


@runtime_checkable
class EnginePort(UiPort, TemplatePort, JudgePort, DevicePort, ConfigPort, FlowPort,
                 Protocol):
    """业务模块使用的完整引擎能力面。"""
