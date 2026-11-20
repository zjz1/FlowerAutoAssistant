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
        from plant import PlantOptions, run_plant_flower

        # 选种模式: manual=按 plant_flower_type/步骤 flower; preset=数据库预设
        seed_mode = str(self.config.get("plant_seed_mode", "manual") or "manual")
        if seed_mode == "preset":
            flower = str(self.config.get("plant_seed_preset", "白色桃花") or "白色桃花")
        else:
            flower = str(step.get("flower") or self.config.get("plant_flower_type", "桃花") or "桃花")
        try:
            options = PlantOptions(
                count_mode=str(self.config.get("plant_count_mode", "fixed") or "fixed"),
                count=int(self.config.get("plant_count", 1) or 1),
                buy_missing=bool(self.config.get("plant_buy_missing", False)),
                auto_buy=bool(self.config.get("plant_auto_buy", False)),
            )
        except (TypeError, ValueError):
            options = PlantOptions()
        print(f"{pad}[种植] 种植花朵: 模式={seed_mode}, 花种={flower}, "
              f"数量={options.count_mode}({options.count}), "
              f"缺种购买={'开' if options.buy_missing else '关'}, "
              f"auto购买={'开' if options.auto_buy else '关'}")
        try:
            ok = run_plant_flower(self, flower, options=options)
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
