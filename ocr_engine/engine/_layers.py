# -*- coding: utf-8 -*-
"""OCREngine 的职责层（Stage 3 第二阶段）。

把原来 19 个 Mixin 直接铺在 OCREngine 基类列表里的结构，收敛为 5 个职责层：
  - DeviceLayer：注册表 / 配置 / 点击日志 / 设备连接与截图；
  - OcrLayer：OCR 识别与采集；
  - LocatorLayer：文本定位 / 场景判据 / 模板 / 关闭弹窗 / 奖励弹窗；
  - ActionLayer：点击守卫；
  - FlowLayer：流程执行 / 步骤处理器 / 业务原子（购买/种植/花仙乐园）/ 编排。

各层仍以 Mixin 方式把方法平铺到 OCREngine 实例上，**不改变任何调用面**；
分层只用于表达职责边界，后续若要改组合式实现，可逐层替换。
"""
from __future__ import annotations

from ._buy import _BuyMixin
from ._buyseed import _BuySeedMixin
from ._clicklog import _ClickLogMixin
from ._closebtn import _CloseButtonMixin
from ._collect import _CollectMixin
from ._config import _ConfigMixin
from ._device import _DeviceMixin
from ._fairyland import _FairylandMixin
from ._findtext import _FindTextMixin
from ._flowexec import _FlowExecMixin
from ._guard import _GuardMixin
from ._judges import _JudgeMixin
from ._ocr import _OcrMixin
from ._orchestrate import _OrchestrateMixin
from ._plant import _PlantMixin
from ._registry import _RegistryMixin
from ._reward import _RewardMixin
from ._steps import _StepHandlersMixin
from ._template import _TemplateMixin


class DeviceLayer(_RegistryMixin, _ConfigMixin, _ClickLogMixin, _DeviceMixin):
    """设备与基础状态：注册表、配置、点击日志、连接/截图/点击。"""


class OcrLayer(_OcrMixin, _CollectMixin):
    """OCR 识别与采集。"""


class LocatorLayer(_CloseButtonMixin, _RewardMixin, _FindTextMixin,
                   _JudgeMixin, _TemplateMixin):
    """定位与判据：文本、场景、数字、模板、关闭/奖励弹窗。"""


class ActionLayer(_GuardMixin):
    """点击动作与守卫。"""


class FlowLayer(_FlowExecMixin, _StepHandlersMixin, _BuyMixin, _BuySeedMixin,
                _PlantMixin, _FairylandMixin, _OrchestrateMixin):
    """流程执行、步骤处理器与业务原子。"""
