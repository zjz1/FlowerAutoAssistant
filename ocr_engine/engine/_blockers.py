"""阻断层/覆盖层注册表（1.0 #11）：数据驱动的检测与关闭。

背景: 等级提升/领取成功/资源更新/「提示」这类覆盖层会盖住正常 UI —— 场景判定失败、
右上角关闭按钮被遮、点击落空。旧实现把这些弹窗的判据硬编码在 reward_dialog / close_dialog /
ensure_home 三处；本模块把「怎么认（match）」和「怎么关（dismiss）」收敛到
`data/blockers.json`，新增弹窗只加数据。

检测成本: 一次 OCR 全帧（`_ocr_candidates`），同时匹配表内全部条目；
关闭策略复用既有原语（reward_dialog / click_text / close_dialog），不重复实现点击逻辑。
"""
from __future__ import annotations

import json
import time

from .._constants import BLOCKERS_PATH
from .._geometry import Point


class _BlockersMixin:
    # ---- 注册表加载 ----
    def _load_blockers(self) -> list[dict]:
        """加载 data/blockers.json（进程内缓存；reload_blockers() 可清）。"""
        cached = self.__dict__.get("_blockers_cache")
        if cached is not None:
            return cached
        items: list[dict] = []
        try:
            if BLOCKERS_PATH.exists():
                data = json.loads(BLOCKERS_PATH.read_text(encoding="utf-8"))
                raw = data.get("blockers") if isinstance(data, dict) else data
                if isinstance(raw, list):
                    items = [x for x in raw if isinstance(x, dict) and x.get("id")]
        except Exception as e:  # noqa: BLE001 —— 注册表坏了不阻断运行, 退化为无阻断层
            print(f"[阻断层] 注册表加载失败: {e}")
        self._blockers_cache = items
        return items

    def reload_blockers(self) -> None:
        """清缓存（测试 / 用户改完 JSON 后热生效）。"""
        self._blockers_cache = None

    # ---- 检测 ----
    def detect_blocker(self, img=None) -> dict | None:
        """单次 OCR 匹配注册表；返回首个命中条目（含 id/name/entry/命中文本/命中点）。

        返回 None = 当前画面没有已知阻断层。只做判定, 不点击、不改状态。
        """
        blockers = self._load_blockers()
        if not blockers:
            return None
        img = img if img is not None else self.screenshot()
        if img is None:
            return None
        blocks, _sub, _used = self._ocr_candidates(img, None, need_refine=False)
        texts = [(b, str(b.get("text") or "").strip()) for b in blocks]
        sw, sh = getattr(self, "screen_w", 0), getattr(self, "screen_h", 0)
        for entry in blockers:
            match = entry.get("match") or {}
            kws = [k for k in (match.get("any") or []) if isinstance(k, str) and k]
            if not kws:
                continue
            exact = bool(match.get("exact", False))
            exclude = [k for k in (match.get("exclude") or []) if isinstance(k, str) and k]
            hit = None
            for blk, txt in texts:
                if not txt or any(x in txt for x in exclude):
                    continue
                if exact:
                    ok = txt in kws
                else:
                    ok = any(k in txt for k in kws)
                if ok:
                    hit = (blk, txt)
                    break
            if hit is None:
                continue
            blk, txt = hit
            center = blk.get("center") or (0, 0)
            return {
                "id": entry["id"],
                "name": entry.get("name") or entry["id"],
                "entry": entry,
                "text": txt,
                "pt": Point(int(center[0]), int(center[1]), sw, sh),
            }
        return None

    # ---- 关闭 ----
    def dismiss_blocker(self, info: dict) -> bool:
        """按条目 dismiss.strategy 关闭；返回是否确认关闭（策略自身语义）。"""
        entry = info.get("entry") or {}
        dismiss = entry.get("dismiss") or {}
        strategy = dismiss.get("strategy", "reward_dialog")
        tries = max(1, int(dismiss.get("tries", 2)))

        if strategy == "reward_dialog":
            kws = dismiss.get("keywords") or (entry.get("match") or {}).get("any")
            # wait=0: 检测阶段已确认在屏, 不再等出现；quiet: 纯守卫不登记失败
            return self.reward_dialog({"wait": 0.0, "tries": tries, "quiet": True,
                                       "required": False, "keywords": kws})

        if strategy == "click_text":
            buttons = [x for x in (dismiss.get("text") or []) if isinstance(x, str) and x]
            for _ in range(tries):
                for kw in buttons:
                    if self.click_text([kw], min_score=dismiss.get("min_score", 0.4),
                                       region_rel=dismiss.get("region_rel"),
                                       no_fallback=True):
                        return True
                time.sleep(0.5)
            return False

        if strategy == "close_dialog":
            # _in_blocker_clear 由 clear_blockers 置位, close_dialog 会跳过再次清阻断层, 不会递归
            return self.close_dialog(only_types=dismiss.get("only_types"))

        print(f"[阻断层] 未知关闭策略 '{strategy}'（{entry.get('id')}）")
        return False

    # ---- 一站式 ----
    def clear_blockers(self, img=None, max_rounds: int = 2) -> list[dict]:
        """检测并关闭阻断层，返回已处理列表 `[{"id","ok","name"}]`；空列表 = 无阻断层。

        max_rounds: 覆盖层可能叠层（奖励弹窗关掉后又弹等级提升），默认最多处理 2 轮；
        处理失败即停止（继续点下去只会空转）。
        """
        handled: list[dict] = []
        prev = getattr(self, "_in_blocker_clear", False)
        self._in_blocker_clear = True
        try:
            for _ in range(max(1, int(max_rounds))):
                info = self.detect_blocker(img=img)
                if info is None:
                    break
                ok = self.dismiss_blocker(info)
                handled.append({"id": info["id"], "name": info["name"], "ok": bool(ok)})
                print(f"[阻断层] {info['name']} -> {'已关闭' if ok else '未确认关闭'}")
                img = None          # 下一轮重新截图
                if not ok:
                    break
                time.sleep(0.4)
        finally:
            self._in_blocker_clear = prev
        return handled
