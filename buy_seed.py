# -*- coding: utf-8 -*-
"""购买种子（独立功能，暂不属于种植任务）。

流程（2026-11-17 用户定稿）：
  家园 -> 左上「园艺店」-> 购买种子页 -> 搜索「颜色+花名+种子」-> 选中
  -> 设置数量(1~99) -> 购买 -> 二次确认「确定」-> 关闭奖励弹窗。
多次购买重复“数量->购买->确认->关弹窗”；切换种子走 兑换种子 -> 购买种子 重置搜索框。

测试目标（用户指定）：白色铃兰种子 x1（免费）。
"""
from __future__ import annotations

import re
import subprocess
import time

from ocr_engine import stop_requested
from plant import _click_text_fine, _save_shot, _texts

SHOP_ENTRY_REGION = [0.0, 0.0, 0.28, 0.12]        # 左上角「园艺店」
SEARCH_BOX_REGION = [0.18, 0.85, 0.40, 0.96]      # 请输入关键字
RIGHT_DETAIL_REGION = [0.70, 0.05, 1.0, 0.90]     # 右侧种子详情/已拥有
BUY_BTN_REGION = [0.80, 0.85, 0.96, 0.95]         # 购买
CONFIRM_REGION = [0.22, 0.18, 0.82, 0.85]         # 二次确认弹窗
IME_OK_REGION = [0.85, 0.88, 1.0, 1.0]            # 系统键盘确定
REWARD_REGION = [0.20, 0.10, 0.85, 0.98]          # 奖励/结果弹窗
SPINNER_MAX_DX_REL = -0.13                        # 数量数字相对「最大」的横向偏移（实机标定）


def _ensure_garden(eng) -> bool:
    if eng.locate(["离开"], region_rel=[0.78, 0.85, 1.0, 1.0],
                  need_refine=False, log_miss=False):
        return True
    if eng.click_text(["家园"], region_rel=[0.78, 0.85, 1.0, 1.0],
                      min_score=0.4, no_fallback=True):
        t0 = time.time()
        while time.time() - t0 < 8:
            if eng.locate(["离开"], region_rel=[0.78, 0.85, 1.0, 1.0],
                          need_refine=False, log_miss=False):
                return True
            time.sleep(1.0)
    print("    [买种] 未能进入家园场景")
    return False


def _open_shop(eng) -> bool:
    joined = " ".join(str(b.get("text", "")) for b in eng.ocr_blocks(None))
    if "购买种子" in joined and "兑换种子" in joined:
        print("    [买种] 园艺店已打开")
        return True
    if not _ensure_garden(eng):
        return False
    if not eng.click_text(["园艺店"], region_rel=SHOP_ENTRY_REGION,
                          min_score=0.3, no_fallback=True):
        print("    [买种] 未找到「园艺店」")
        return False
    t0 = time.time()
    while time.time() - t0 < 8:
        joined = " ".join(str(b.get("text", "")) for b in eng.ocr_blocks(None))
        if "购买种子" in joined and "兑换种子" in joined:
            print(f"    [买种] 园艺店就绪({time.time() - t0:.1f}s)")
            return True
        time.sleep(1.0)
    print("    [买种] 园艺店就绪超时")
    return False


def _ensure_buy_tab(eng) -> bool:
    if not eng.click_text(["购买种子"], region_rel=[0.02, 0.12, 0.16, 0.30],
                          min_score=0.3, no_fallback=True):
        print("    [买种] 未找到「购买种子」页签")
        return False
    time.sleep(1.0)
    return True


def _clear_focused(eng, n=24):
    """清空当前输入框: 移到末尾后连按退格。"""
    adb, addr = eng.adb_path, eng.address
    try:
        subprocess.run([adb, "-s", addr, "shell", "input", "keyevent", "123"],
                       capture_output=True, timeout=10)
        subprocess.run([adb, "-s", addr, "shell", "input", "keyevent"] + ["67"] * n,
                       capture_output=True, timeout=20)
    except Exception as e:
        print(f"    [买种] 清空输入框失败: {e}")


def _input_seed_name(eng, seed_name: str) -> bool:
    if not eng.click_text(["请输入关键字"], region_rel=SEARCH_BOX_REGION,
                          min_score=0.3, no_fallback=True):
        print("    [买种] 未找到搜索框「请输入关键字」")
        return False
    time.sleep(1.0)
    _clear_focused(eng)
    adb, addr = eng.adb_path, eng.address
    try:
        r = subprocess.run([adb, "-s", addr, "shell", "input", "text", seed_name],
                           capture_output=True, timeout=20)
        print(f"    [买种] adb input text {seed_name!r} rc={r.returncode}")
    except Exception as e:
        print(f"    [买种] 输入失败: {e}")
        return False
    time.sleep(0.8)
    # 系统键盘确定
    if not _click_text_fine(eng, "确定", IME_OK_REGION):
        print("    [买种] 未找到输入法「确定」")
        return False
    time.sleep(2.0)
    return True


def _detail_texts(eng):
    return _texts(eng.ocr_blocks(None, RIGHT_DETAIL_REGION))


def _verify_detail_name(eng, seed_name: str) -> bool:
    texts = _detail_texts(eng)
    hit = any(seed_name in t for t in texts)
    print(f"    [买种] 右侧详情: {texts[:12]} -> {'命中' if hit else '未命中'} {seed_name}")
    return hit


def _read_owned(eng):
    blocks = eng.ocr_blocks(None, RIGHT_DETAIL_REGION)
    anchor = next((b for b in blocks if "已拥有" in str(b.get("text", ""))), None)
    nums = [b for b in blocks if re.fullmatch(r"\d+", str(b.get("text", "")).strip())]
    if not nums:
        return None
    if anchor is not None:
        ax, ay = anchor["center"]
        nums.sort(key=lambda b: abs(b["center"][0] - ax) + abs(b["center"][1] - ay))
    return int(str(nums[0].get("text", "")).strip())


def _set_quantity(eng, count: int) -> bool:
    """设置购买数量。数量=1 时默认已是 1, 只做记录; >1 时点数字输入。"""
    if count == 1:
        print("    [买种] 数量=1（默认），免调整")
        return True
    blocks = eng.ocr_blocks(None, RIGHT_DETAIL_REGION)
    mx = next((b for b in blocks if "最大" in str(b.get("text", ""))), None)
    if mx is None:
        print("    [买种] 未找到「最大」锚点, 无法定位数量框")
        return False
    w, h = eng.screen_w or 1, eng.screen_h or 1
    x = int(mx["center"][0] + SPINNER_MAX_DX_REL * w)
    y = int(mx["center"][1])
    print(f"    [买种] 点数量框 ({x},{y})")
    eng.click_abs(x, y)
    time.sleep(0.8)
    _clear_focused(eng)
    adb, addr = eng.adb_path, eng.address
    try:
        subprocess.run([adb, "-s", addr, "shell", "input", "text", str(count)],
                       capture_output=True, timeout=20)
    except Exception as e:
        print(f"    [买种] 数量输入失败: {e}")
        return False
    if not _click_text_fine(eng, "确定", IME_OK_REGION):
        print("    [买种] 数量输入未找到确定")
        return False
    time.sleep(0.8)
    print(f"    [买种] 已设置数量 {count}")
    return True


def _pick_confirm_button(blocks):
    """二次确认弹窗: 取精确「确定/确认」按钮（排除「确定要花费…」句），取最右。"""
    btns = [b for b in blocks if str(b.get("text", "")).strip() in ("确定", "确认")]
    if not btns:
        return None
    btns.sort(key=lambda b: -b["center"][0])
    return btns[0]


def _buy(eng, seed_name: str, count: int, owned_before):
    if not eng.click_text(["购买"], region_rel=BUY_BTN_REGION,
                          min_score=0.3, no_fallback=True):
        print("    [买种] 未找到「购买」按钮")
        return False
    time.sleep(1.5)
    _save_shot(eng, "buy_confirm")
    blocks = eng.ocr_blocks(None, CONFIRM_REGION)
    texts = _texts(blocks)
    joined = " ".join(texts)
    print(f"    [买种] 二次确认实读: {texts[:15]}")
    if seed_name not in joined:
        print(f"    [买种] 二次确认未出现目标种子名 {seed_name!r}, 不点确定")
        eng.close_dialog()
        return False
    # 数量核对: 弹窗内若出现数字, 必须包含目标数量
    nums = re.findall(r"\d+", joined)
    if nums and str(count) not in nums:
        print(f"    [买种] 二次确认数量不符 目标={count} 实读={nums[:10]}, 不点确定")
        eng.close_dialog()
        return False
    btn = _pick_confirm_button(blocks)
    if btn is None:
        print("    [买种] 二次确认未找到精确「确定/确认」按钮")
        return False
    print(f"    [买种] 点二次确认「{btn['text'].strip()}」-> {btn['center']}")
    eng.click_abs(int(btn["center"][0]), int(btn["center"][1]))
    time.sleep(1.5)

    # 奖励/结果弹窗
    t0 = time.time()
    reward = None
    while time.time() - t0 < 8:
        joined = " ".join(str(b.get("text", "")) for b in eng.ocr_blocks(None))
        if "恭喜获得" in joined or "点击任意处关闭" in joined or "购买成功" in joined:
            reward = joined
            break
        time.sleep(0.8)
    if reward is not None:
        for text in ("恭喜获得", "点击任意处关闭", "确定"):
            if eng.click_text([text], region_rel=REWARD_REGION,
                              min_score=0.3, no_fallback=True):
                time.sleep(1.0)
                break
        print("    [买种] 奖励弹窗已处理")
    else:
        print("    [买种] 购买后未见奖励/成功弹窗")

    # 库存复核: 已拥有 +count
    owned_after = None
    t0 = time.time()
    while time.time() - t0 < 5:
        owned_after = _read_owned(eng)
        if (owned_before is not None and owned_after is not None
                and owned_after == owned_before + count):
            break
        time.sleep(1.0)
    print(f"    [买种] 已拥有: {owned_before} -> {owned_after} (期望 +{count})")
    if owned_before is not None and owned_after is not None:
        return owned_after == owned_before + count
    return reward is not None


def buy_seed_in_shop(eng, seed_name: str, count: int = 1) -> bool:
    """购买种子界面已打开时的单次购买（供花仙乐园「兑换花种」任务复用）。

    默认已选中白色铃兰种子时只需 OCR 校验右侧详情，不重复搜索；详情不符才搜索。
    """
    if not _ensure_buy_tab(eng):
        return False
    if not _verify_detail_name(eng, seed_name):
        print("    [买种] 当前详情非目标种子, 执行搜索")
        if not _input_seed_name(eng, seed_name):
            return False
        if not _verify_detail_name(eng, seed_name):
            return False
    owned_before = _read_owned(eng)
    if not _set_quantity(eng, count):
        return False
    return _buy(eng, seed_name, count, owned_before)


def run_buy_seed(eng, seed_name: str, count: int = 1) -> bool:
    """购买指定种子 count 次(单次 1~99)。返回 True=购买流程完成（不保证库存 delta 一定符合）。"""
    print(f"\n[买种] ===== 购买种子: {seed_name} x{count} =====")
    if stop_requested():
        return False
    if not (1 <= int(count) <= 99):
        print("    [买种] 数量超出 1~99")
        return False
    if not _open_shop(eng):
        return False
    if not _ensure_buy_tab(eng):
        return False
    if not _input_seed_name(eng, seed_name):
        _save_shot(eng, "buy_search_failed")
        return False
    if not _verify_detail_name(eng, seed_name):
        _save_shot(eng, "buy_detail_miss")
        print("    [买种] 搜索后详情不是目标种子, 不购买")
        return False
    owned_before = _read_owned(eng)
    if not _set_quantity(eng, count):
        return False
    ok = _buy(eng, seed_name, count, owned_before)
    _save_shot(eng, "buy_end")
    print(f"[买种] ===== {'完成' if ok else '失败'} =====")
    return ok
