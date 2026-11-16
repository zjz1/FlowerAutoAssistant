"""fairyland_claim 步骤处理器: 花仙乐园领取（在线骰子 + 每日任务）。"""
from __future__ import annotations

from .._failures import report_failure


class _FairylandMixin:
    def _step_fairyland_claim(self, step: dict, kws, pad: str, indent: int):
        from fairyland import run_fairyland_claim

        print(f"{pad}[乐园] 花仙乐园领取")
        try:
            ok = run_fairyland_claim(self)
        except Exception as e:
            print(f"{pad}[乐园] 异常: {e}")
            report_failure(self._module, f"花仙乐园领取异常: {e}")
            return
        if not ok:
            report_failure(self._module, "花仙乐园领取失败")
