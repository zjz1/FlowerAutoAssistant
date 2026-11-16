"""buy_seed 步骤处理器: 购买指定种子（独立功能）。"""
from __future__ import annotations

from .._failures import report_failure


class _BuySeedMixin:
    def _step_buy_seed(self, step: dict, kws, pad: str, indent: int):
        from buy_seed import run_buy_seed

        seed = str(step.get("seed") or "").strip()
        count = int(step.get("count", 1) or 1)
        if not seed:
            print(f"{pad}[买种] 缺少 seed 参数")
            report_failure(self._module, "购买种子: 缺少 seed 参数")
            return
        print(f"{pad}[买种] 购买种子 {seed} x{count}")
        try:
            ok = run_buy_seed(self, seed, count)
        except Exception as e:
            print(f"{pad}[买种] 异常: {e}")
            report_failure(self._module, f"购买种子异常: {e}")
            return
        if not ok:
            report_failure(self._module, f"购买种子失败: {seed} x{count}")
