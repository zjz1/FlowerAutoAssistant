"""动作结果校验（1.0 #10）：点后统一分类 changed / no_change / blocker / empty / failed。

动机: 「点击返回 ok」只说明点击事件发出去了，不等于界面响应了。旧代码各业务链自己写
「等一秒再 OCR 看看」的变体，结论口径不一（有的把异常当成功，有的把慢加载当失败）。
本模块把「点后到底发生了什么」收敛成一个可复用判定：

    failed    截图缺失 / 尺寸不一致 —— 无法判定（不等于失败，交调用方按原语义处理）
    empty     命中 empty_keywords（如「没有花粉」）—— 业务上的“空结果”，不是错误
    blocker   命中 data/blockers.json 的覆盖层（等级提升 / 奖励 / 更新提示…）
    changed   帧差达到阈值，或 expected_keywords 出现 —— 动作生效
    no_change 以上都没发生 —— 点了但界面没动（被吞 / 目标不可点）

默认**不改变任何既有流程行为**：click_text 只有步骤显式写 `"verify": true` 才采集前后帧；
close_dialog / ensure_home 走阻断层注册表（#11），不走这里的全帧差。
"""
from __future__ import annotations

import time


class _VerifyMixin:
    # 帧差阈值: 160x90 灰度缩略图上差异像素占比。0.008 ≈ 0.8% 屏幕面积 ——
    # 静态界面 + 渲染抖动实测远低于此值；按钮按下高亮/面板切换远高于此值。
    VERIFY_DIFF_MIN = 0.008
    VERIFY_THUMB_SIZE = (160, 90)
    VERIFY_PIXEL_DELTA = 12

    def frame_diff_ratio(self, before, after) -> float | None:
        """两帧差异像素占比（0~1）。任一帧缺失或尺寸不同返回 None（无法判定）。"""
        import cv2
        if before is None or after is None:
            return None
        if getattr(before, "shape", None) != getattr(after, "shape", None):
            return None
        a = cv2.cvtColor(cv2.resize(before, self.VERIFY_THUMB_SIZE), cv2.COLOR_BGR2GRAY)
        b = cv2.cvtColor(cv2.resize(after, self.VERIFY_THUMB_SIZE), cv2.COLOR_BGR2GRAY)
        d = cv2.absdiff(a, b)
        return float((d > self.VERIFY_PIXEL_DELTA).mean())

    def _texts_on(self, img) -> list[str]:
        """一次 OCR 取全帧文本（供 empty/expected 判定复用）。"""
        blocks, _sub, _used = self._ocr_candidates(img, None, need_refine=False)
        return [str(b.get("text") or "").strip() for b in blocks]

    def classify_action(self, before, after, *, expected_keywords=None,
                        empty_keywords=None, diff_min=None) -> dict:
        """纯分类（不点击、不关弹窗）。返回 {result, diff, blocker, reason}。"""
        if before is None or after is None:
            return {"result": "failed", "diff": None, "blocker": None,
                    "reason": "缺少截图(截图失败)"}

        if empty_keywords:
            texts = self._texts_on(after)
            if any(k and k in t for k in empty_keywords for t in texts):
                return {"result": "empty", "diff": None, "blocker": None,
                        "reason": "命中空结果关键字"}

        info = self.detect_blocker(img=after)
        if info is not None:
            return {"result": "blocker", "diff": None, "blocker": info["id"],
                    "reason": f"覆盖层 {info['name']}"}

        if expected_keywords:
            texts = self._texts_on(after)
            if any(k and k in t for k in expected_keywords for t in texts):
                return {"result": "changed", "diff": None, "blocker": None,
                        "reason": "期望文字已出现"}

        diff = self.frame_diff_ratio(before, after)
        if diff is None:
            return {"result": "failed", "diff": None, "blocker": None,
                    "reason": "两帧尺寸不一致"}
        threshold = self.VERIFY_DIFF_MIN if diff_min is None else float(diff_min)
        result = "changed" if diff >= threshold else "no_change"
        return {"result": result, "diff": diff, "blocker": None,
                "reason": f"帧差 {diff:.4f} {'>=' if result == 'changed' else '<'} {threshold:g}"}

    def verify_action(self, before, *, wait: float = 0.8, expected_keywords=None,
                      empty_keywords=None, diff_min=None, dismiss_blocker: bool = False) -> dict:
        """点后校验: 等 `wait` 秒 → 截图 → classify_action（可选自动关闭阻断层）。"""
        time.sleep(max(0.0, float(wait)))
        after = self.screenshot()
        out = self.classify_action(before, after, expected_keywords=expected_keywords,
                                   empty_keywords=empty_keywords, diff_min=diff_min)
        if dismiss_blocker and out["result"] == "blocker":
            out["dismissed"] = self.clear_blockers(img=after)
        return out
