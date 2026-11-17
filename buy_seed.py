# -*- coding: utf-8 -*-
"""购买种子（独立功能，暂不属于种植任务）。

流程（2026-11-17 用户定稿）：
  家园 -> 左上「园艺店」-> 购买种子页 -> 搜索「颜色+花名+种子」-> 选中
  -> 设置数量(1~99) -> 购买 -> 二次确认「确定」-> 关闭奖励弹窗。
多次购买重复“数量->购买->确认->关弹窗”；切换种子重新搜索（内部先清空旧关键字）。
价格以二次确认弹窗「确定要花费N仙豆」为权威；余额不足时关闭弹窗、不点确定。

已实机（2026-11-17）：白色铃兰种子 x1、x2×2 次（免费）；蓝色牵牛花种子 x1（6 仙豆，
余额同步 -6）；不存在的种子拒绝购买；空搜索框/旧关键字/切换种子均已覆盖。
"""
from __future__ import annotations
from core.ports import EnginePort

import re
import subprocess
import time

from navigation import ensure_any_garden
from ocr_engine import stop_requested
from ui_ops import (IME_OK_REGION, REWARD_REGION_WIDE, close_reward_popup,
                    click_text_fine as _click_text_fine, input_text_ime,
                    save_shot as _save_shot, texts as _texts)

SHOP_ENTRY_REGION = [0.0, 0.0, 0.28, 0.12]        # 左上角「园艺店」
GRID_REGION = [0.17, 0.12, 0.62, 0.86]            # 左侧种子网格
SEARCH_BOX_REGION = [0.18, 0.85, 0.40, 0.96]      # 请输入关键字
SEARCH_BOX_ANCHOR = "购买工具"                     # 搜索框为空时的左下方锚点
SEARCH_BOX_ANCHOR_REGION = [0.0, 0.70, 0.20, 1.0]
SEARCH_BOX_FROM_ANCHOR_REL = [0.159, 0.028]       # 锚点 -> 搜索框中心（实机 2026-11-17 标定）
RIGHT_DETAIL_REGION = [0.70, 0.05, 1.0, 0.90]     # 右侧种子详情/已拥有
BUY_BTN_REGION = [0.80, 0.85, 0.96, 0.95]         # 购买
CONFIRM_REGION = [0.22, 0.18, 0.82, 0.85]         # 二次确认弹窗
REWARD_REGION = REWARD_REGION_WIDE                  # 奖励/结果弹窗（通用大区域）
BALANCE_REGION = [0.70, 0.0, 0.92, 0.08]          # 顶部仙豆余额（实机 2026-11-17 截图标定）
SPINNER_MAX_DX_REL = -0.13                        # 数量数字相对「最大」的横向偏移（实机标定）


def _ensure_garden(eng: EnginePort) -> bool:
    ok = ensure_any_garden(eng)
    if not ok:
        print("    [买种] 未能进入家园场景")
    return ok


def _wait_shop_entry(eng: EnginePort, timeout=8.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if eng.locate(["园艺店"], region_rel=SHOP_ENTRY_REGION,
                      need_refine=False, log_miss=False):
            return True
        time.sleep(0.8)
    return False


def _open_shop(eng: EnginePort) -> bool:
    joined = " ".join(str(b.get("text", "")) for b in eng.ocr_blocks(None))
    if "购买种子" in joined and "兑换种子" in joined:
        print("    [买种] 园艺店已打开")
        return True
    if not _ensure_garden(eng):
        return False
    if not _wait_shop_entry(eng, 3.0):
        # 好友家园同样有「离开」: 离开后回户外, 再点「家园」进自己家园
        print("    [买种] 当前家园无「园艺店」入口, 尝试离开后重进自己家园")
        if eng.click_text(["离开"], region_rel=[0.78, 0.85, 1.0, 1.0],
                          min_score=0.4, no_fallback=True):
            time.sleep(3.0)
            if eng.click_text(["家园"], region_rel=[0.78, 0.85, 1.0, 1.0],
                              min_score=0.4, no_fallback=True):
                _wait_shop_entry(eng, 8.0)
    if not _wait_shop_entry(eng, 2.0):
        print("    [买种] 未找到「园艺店」")
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


def _ensure_buy_tab(eng: EnginePort) -> bool:
    if not eng.click_text(["购买种子"], region_rel=[0.02, 0.12, 0.16, 0.30],
                          min_score=0.3, no_fallback=True):
        print("    [买种] 未找到「购买种子」页签")
        return False
    time.sleep(1.0)
    return True


def _input_seed_name(eng: EnginePort, seed_name: str) -> bool:
    """搜索框输入种子全名（聚焦/清空/adb input/键盘确定 统一走 ui_ops）。"""
    return input_text_ime(
        eng, seed_name, SEARCH_BOX_REGION, IME_OK_REGION,
        placeholder="请输入关键字",
        anchor=SEARCH_BOX_ANCHOR,
        anchor_region=SEARCH_BOX_ANCHOR_REGION,
        from_anchor_rel=SEARCH_BOX_FROM_ANCHOR_REL,
    )


def _norm_text(s) -> str:
    return re.sub(r"[\s:：·•]+", "", str(s))


def _owned_from_blocks(eng: EnginePort, blocks):
    """从已读取的详情块中取「已拥有」数量（只取锚点同排右侧数字）。"""
    anchor = next((b for b in blocks if "已拥有" in str(b.get("text", ""))), None)
    if anchor is None:
        return None
    ax, ay = anchor["center"]
    h = eng.screen_h or 1
    nums = [b for b in blocks
            if re.fullmatch(r"\d+", str(b.get("text", "")).strip())
            and b["center"][0] >= ax
            and abs(b["center"][1] - ay) <= 0.05 * h]
    if not nums:
        return None
    nums.sort(key=lambda b: (abs(b["center"][1] - ay), b["center"][0] - ax))
    return int(str(nums[0].get("text", "")).strip())


def _cost_from_blocks(eng: EnginePort, blocks):
    """从已读取的详情块中取「消耗 N」（当前数量对应的总价）。"""
    anchor = next((b for b in blocks if "消耗" in str(b.get("text", ""))), None)
    if anchor is None:
        return None
    m = re.search(r"消耗\s*[：:]?\s*([0-9Oo]+)", str(anchor.get("text", "")))
    if m:
        return int(m.group(1).replace("O", "0").replace("o", "0"))
    ax, ay = anchor["center"]
    h = eng.screen_h or 1
    nums = [b for b in blocks
            if re.fullmatch(r"[0-9Oo]+", str(b.get("text", "")).strip())
            and b["center"][0] >= ax
            and abs(b["center"][1] - ay) <= 0.03 * h]
    if not nums:
        return None
    nums.sort(key=lambda b: (abs(b["center"][1] - ay), abs(b["center"][0] - ax)))
    return int(str(nums[0].get("text", "")).strip().replace("O", "0").replace("o", "0"))


def _read_detail(eng: EnginePort):
    """一次 OCR 读取右侧详情面板：texts / owned / cost（P0 重构，减少重复 OCR）。"""
    blocks = eng.ocr_blocks(None, RIGHT_DETAIL_REGION)
    return {
        "blocks": blocks,
        "texts": _texts(blocks),
        "owned": _owned_from_blocks(eng, blocks),
        "cost": _cost_from_blocks(eng, blocks),
    }


def _detail_texts(eng: EnginePort, detail=None):
    if detail is not None:
        return detail["texts"]
    return _texts(eng.ocr_blocks(None, RIGHT_DETAIL_REGION))


def _verify_detail_name(eng: EnginePort, seed_name: str, detail=None) -> bool:
    """右侧详情标题必须与目标种子**精确相等**（去空白/标点）。

    不能用子串：搜索无结果时右侧仍保留上一次选中的种子，子串会误判
    （如目标「铃兰种子」会命中旧详情「白色铃兰种子」）。
    """
    texts = _detail_texts(eng, detail)
    want = _norm_text(seed_name)
    hit = any(_norm_text(t) == want for t in texts)
    print(f"    [买种] 右侧详情: {texts[:12]} -> {'命中' if hit else '未命中'} {seed_name}")
    return hit


def _select_seed(eng: EnginePort, seed_name: str) -> bool:
    """搜索后显式选中目标种子：详情已精确匹配则直接用；否则点网格中同名块再复核。"""
    detail = _read_detail(eng)
    if _verify_detail_name(eng, seed_name, detail):
        return True
    blocks = eng.ocr_blocks(None, GRID_REGION)
    want = _norm_text(seed_name)
    cand = next((b for b in blocks if _norm_text(b.get("text", "")) == want), None)
    if cand is None:
        print(f"    [买种] 搜索结果网格未找到「{seed_name}」, 不购买")
        return False
    x, y = cand["center"]
    print(f"    [买种] 点选目标种子「{seed_name}」-> ({x},{y})")
    eng.click_abs(int(x), int(y))
    time.sleep(1.5)
    return _verify_detail_name(eng, seed_name)


def _read_owned(eng: EnginePort, detail=None):
    """读取右侧「已拥有」数量；detail 传入时复用已读取块。"""
    return detail["owned"] if detail is not None else _owned_from_blocks(
        eng, eng.ocr_blocks(None, RIGHT_DETAIL_REGION))


def _read_balance(eng: EnginePort):
    """读取顶部仙豆余额（纯数字块, 取最右）。不可读返回 None，不做猜测。"""
    blocks = eng.ocr_blocks(None, BALANCE_REGION)
    nums = []
    for b in blocks:
        t = str(b.get("text", "")).strip().replace(",", "")
        if re.fullmatch(r"\d+", t):
            nums.append((int(t), b))
    if not nums:
        return None
    nums.sort(key=lambda x: -x[1]["center"][0])
    return nums[0][0]


def _read_detail_cost(eng: EnginePort, detail=None):
    """读取右侧详情「消耗 N」（当前数量对应的总价）。不可读返回 None。"""
    return detail["cost"] if detail is not None else _cost_from_blocks(
        eng, eng.ocr_blocks(None, RIGHT_DETAIL_REGION))


def _parse_confirm_price(texts) -> int | None:
    for t in texts:
        # 免费种子的 0 常被 OCR 读成字母 O
        norm = str(t).replace("O", "0").replace("o", "0")
        m = re.search(r"花费\s*(\d+)\s*仙豆", norm)
        if m:
            return int(m.group(1))
    return None


def _precheck_affordable(eng: EnginePort, count, detail=None):
    """购买前价格/余额预检。返回 (True, price, balance)。

    预检只记录、不拦截：详情「消耗」行的金币图标常被 OCR 多读一位
    （2026-11-17 实测 6 仙豆读成「消耗69」），据此拦截会误杀。
    真正的余额闸门在二次确认弹窗：以「确定要花费N仙豆」为权威价格,
    余额不足则关闭弹窗、不点确定, 不会发生购买。
    """
    detail = detail if detail is not None else _read_detail(eng)
    price = detail["cost"]
    balance = _read_balance(eng)
    print(f"    [买种] 价格预检(仅记录): 消耗={price if price is not None else '?'} "
          f"余额={balance if balance is not None else '?'} 数量={count}")
    return True, price, balance


def _set_quantity(eng: EnginePort, count: int) -> bool:
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


def _confirm_purchase(eng: EnginePort, seed_name: str, count: int,
                      price=None, balance=None) -> tuple[bool, int | None]:
    """点「购买」→ 核对二次确认（种子名/数量/权威花费/余额）→ 点精确「确定」。

    返回 (ok, 权威花费)。ok=False 表示未点击确定（调用方不再做库存复核）。
    """
    if not eng.click_text(["购买"], region_rel=BUY_BTN_REGION,
                          min_score=0.3, no_fallback=True):
        print("    [买种] 未找到「购买」按钮")
        return False, None
    time.sleep(1.5)
    _save_shot(eng, "buy_confirm")
    blocks = eng.ocr_blocks(None, CONFIRM_REGION)
    texts = _texts(blocks)
    joined = " ".join(texts)
    print(f"    [买种] 二次确认实读: {texts[:15]}")
    if seed_name not in joined:
        print(f"    [买种] 二次确认未出现目标种子名 {seed_name!r}, 不点确定")
        eng.close_dialog()
        return False, None
    # 数量核对: 弹窗内若出现数字, 必须包含目标数量
    nums = re.findall(r"\d+", joined)
    if nums and str(count) not in nums:
        print(f"    [买种] 二次确认数量不符 目标={count} 实读={nums[:10]}, 不点确定")
        eng.close_dialog()
        return False, None
    # 价格核对: 以弹窗「确定要花费N仙豆」为权威; 余额不足则拒绝
    confirm_price = _parse_confirm_price(texts)
    if confirm_price is not None:
        if price is not None and confirm_price != price:
            print(f"    [买种] 价格不一致: 详情消耗={price} 确认花费={confirm_price}; 以确认为准")
        if balance is not None and balance < confirm_price:
            print(f"    [买种] 余额不足: 余额={balance} 确认花费={confirm_price}, 不点确定")
            eng.close_dialog()
            return False, confirm_price
        print(f"    [买种] 价格核对: 花费={confirm_price} 余额={balance if balance is not None else '?'}")
    else:
        print("    [买种] 二次确认未读到「花费N仙豆」, 价格校验跳过")
    btn = _pick_confirm_button(blocks)
    if btn is None:
        print("    [买种] 二次确认未找到精确「确定/确认」按钮")
        return False, confirm_price
    print(f"    [买种] 点二次确认「{btn['text'].strip()}」-> {btn['center']}")
    eng.click_abs(int(btn["center"][0]), int(btn["center"][1]))
    time.sleep(1.5)
    return True, confirm_price


def _wait_and_close_reward(eng: EnginePort) -> bool:
    """等奖励/成功弹窗并关闭；返回是否见到弹窗。"""
    t0 = time.time()
    reward = None
    while time.time() - t0 < 8:
        joined = " ".join(str(b.get("text", "")) for b in eng.ocr_blocks(None))
        if "恭喜获得" in joined or "点击任意处关闭" in joined or "购买成功" in joined:
            reward = joined
            break
        time.sleep(0.8)
    if reward is not None:
        close_reward_popup(eng, ("恭喜获得", "点击任意处关闭", "确定"),
                           REWARD_REGION, tag="买种")
        return True
    print("    [买种] 购买后未见奖励/成功弹窗")
    return False


def _verify_purchase(eng: EnginePort, count: int, owned_before, confirm_price,
                     balance, reward: bool) -> bool:
    """购买后复核：已拥有 +count；付费种子另核余额 -confirm_price。"""
    owned_after = None
    t0 = time.time()
    while time.time() - t0 < 5:
        owned_after = _read_owned(eng)
        if (owned_before is not None and owned_after is not None
                and owned_after == owned_before + count):
            break
        time.sleep(1.0)
    print(f"    [买种] 已拥有: {owned_before} -> {owned_after} (期望 +{count})")

    balance_ok = None
    if confirm_price and confirm_price > 0 and balance is not None:
        balance_after = _read_balance(eng)
        if balance_after is not None:
            delta = balance - balance_after
            balance_ok = (delta == confirm_price)
            print(f"    [买种] 余额: {balance} -> {balance_after} "
                  f"(期望 -{confirm_price}) {'OK' if balance_ok else 'FAIL'}")
        else:
            print(f"    [买种] 购买后余额不可读(购买前={balance}, 花费={confirm_price})")

    if owned_before is not None and owned_after is not None:
        owned_ok = owned_after == owned_before + count
        return owned_ok and (balance_ok is not False)
    if balance_ok is not None:
        return balance_ok
    return reward


def _buy(eng: EnginePort, seed_name: str, count: int, owned_before, price=None, balance=None):
    """单次购买编排：确认弹窗 → 奖励弹窗 → 库存/余额复核。"""
    ok, confirm_price = _confirm_purchase(eng, seed_name, count, price, balance)
    if not ok:
        return False
    reward = _wait_and_close_reward(eng)
    return _verify_purchase(eng, count, owned_before, confirm_price, balance, reward)


def buy_seed_in_shop(eng: EnginePort, seed_name: str, count: int = 1) -> bool:
    """购买种子界面已打开时的单次购买（供花仙乐园「兑换花种」任务复用）。

    默认已选中白色铃兰种子时只需 OCR 校验右侧详情，不重复搜索；详情不符才搜索。
    """
    if not _ensure_buy_tab(eng):
        return False
    detail = _read_detail(eng)
    if not _verify_detail_name(eng, seed_name, detail):
        print("    [买种] 当前详情非目标种子, 执行搜索")
        if not _input_seed_name(eng, seed_name):
            return False
        if not _select_seed(eng, seed_name):
            return False
        detail = _read_detail(eng)
    owned_before = detail["owned"]
    if not _set_quantity(eng, count):
        return False
    if count != 1:
        detail = _read_detail(eng)   # 数量变更后重读「消耗」总价
    ok_afford, price, balance = _precheck_affordable(eng, count, detail)
    if not ok_afford:
        return False
    return _buy(eng, seed_name, count, owned_before, price, balance)


def run_buy_seed(eng: EnginePort, seed_name: str, count: int = 1, times: int = 1) -> bool:
    """购买指定种子。

    count = 单次购买数量(1~99); times = 连续购买次数(1~99)。
    返回 True = 全部次数完成且库存/余额复核通过。
    """
    print(f"\n[买种] ===== 购买种子: {seed_name} x{count} × {times}次 =====")
    if stop_requested():
        return False
    if not (1 <= int(count) <= 99):
        print("    [买种] 数量超出 1~99")
        return False
    if not (1 <= int(times) <= 99):
        print("    [买种] 次数超出 1~99")
        return False
    if not _open_shop(eng):
        return False
    if not _ensure_buy_tab(eng):
        return False
    if not _input_seed_name(eng, seed_name):
        _save_shot(eng, "buy_search_failed")
        return False
    if not _select_seed(eng, seed_name):
        _save_shot(eng, "buy_detail_miss")
        print("    [买种] 搜索后详情不是目标种子, 不购买")
        return False
    for i in range(int(times)):
        if stop_requested():
            return False
        if times > 1:
            print(f"    [买种] ----- 第 {i + 1}/{times} 次 -----")
        if i > 0:
            # 上一次购买后页面可能重置: 复核页签/详情，不符则重新搜索
            if not _ensure_buy_tab(eng):
                return False
            if not _verify_detail_name(eng, seed_name):
                if not _input_seed_name(eng, seed_name):
                    return False
                if not _select_seed(eng, seed_name):
                    return False
        if not _set_quantity(eng, count):
            return False
        detail = _read_detail(eng)
        owned_before = detail["owned"]
        ok_afford, price, balance = _precheck_affordable(eng, count, detail)
        if not ok_afford:
            _save_shot(eng, "buy_afford_failed")
            return False
        ok = _buy(eng, seed_name, count, owned_before, price, balance)
        if not ok:
            _save_shot(eng, "buy_failed")
            print(f"[买种] ===== 第 {i + 1}/{times} 次失败 =====")
            return False
    _save_shot(eng, "buy_end")
    print(f"[买种] ===== 完成: {seed_name} x{count} × {times}次 =====")
    return True
