"""plant_flower 步骤处理器: 种植花朵(桃花系, 花种由 plant_flower_type 选择)。

阶段0『确保在自己家园』由 flow_plant.json 的既有步骤完成; 本步骤负责:
点「一键种植」→ 采集页面信息 → 搜索基础花名 → 精确点选目标颜色变体 →
数量1 → 随机种植 → 详情确认 → 回读校验 → 关面板归位。
具体实现见仓库根 plant.py(与 pollin.py 同型: 业务闭环在独立模块)。
"""
from __future__ import annotations

from .._failures import report_failure


class _PlantMixin:
    def _step_plant_flower(self, step: dict, kws, pad: str, indent: int):
        # 函数内延迟导入: plant.py 顶部 import ocr_engine, 避免包初始化期循环依赖
        from plant import run_plant_flower

        flower = str(step.get("flower") or self.config.get("plant_flower_type", "桃花") or "桃花")
        print(f"{pad}[种植] 种植花朵: 花种={flower}")
        try:
            ok = run_plant_flower(self, flower)
        except Exception as e:
            print(f"{pad}[种植] 异常: {e}")
            report_failure(self._module, f"种植花朵({flower})异常: {e}")
            return
        if not ok:
            report_failure(self._module, f"种植花朵({flower}): 阶段1/2失败")

    def _step_plant_harvest(self, step: dict, kws, pad: str, indent: int):
        from plant import run_plant_harvest

        print(f"{pad}[收获] 花朵收获")
        try:
            ok = run_plant_harvest(self)
        except Exception as e:
            print(f"{pad}[收获] 异常: {e}")
            report_failure(self._module, f"花朵收获异常: {e}")
            return
        if not ok:
            report_failure(self._module, "花朵收获失败")
