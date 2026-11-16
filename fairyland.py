# -*- coding: utf-8 -*-
"""花仙乐园领取（领取奖励模块）：在线骰子 + 每日任务。

流程（2026-11-17 用户定稿）：
  家园(自己/好友均可) -> 菜单 -> 花仙乐园 -> 在线领取一键领取 -> 关奖励弹窗
  -> 每日任务 -> 白色雪绒花/蓝色月季花兑换(各关奖励弹窗)
  -> 给他人浇水5次(5/5才领) -> 园艺店仙豆兑换花种3次(3/3才领, 未完成走购买占位)
  -> 关闭花仙乐园回家园。

按钮置灰判据（用户确认）：按钮底色变灰。实机采样 2026-11-17：
  置灰「领取」HSV S≈7~11；已领/不可领「一键领取」S≈37；可点「兑换/一键领取」S≈47~48
  -> 阈值 S>=40 判可点（37 的模糊态按不可领处理，避免空点）。
"""
from __future__ import annotations

import re
import time

from ocr_engine import stop_requested
from plant import _save_shot, _texts
from buy_seed import buy_seed_in_shop

# ---- 区域（相对坐标，实机标定 2026-11-17） ----
MENU_REGION = [0.0, 0.0, 0.25, 0.16]            # 左上角「菜单」
FAIRYLAND_ENTRY_REGION = [0.0, 0.0, 0.35, 0.70]  # 菜单内「花仙乐园」
TAB_REGION = [0.10, 0.04, 0.45, 0.18]           # 在线领取/每日任务 标签
REWARD_REGION = [0.20, 0.10, 0.85, 0.98]        # 奖励弹窗
SAT_TH = 40                                      # 按钮底色饱和度阈值: >=40 可点, <40 置灰/不可领

NUM_PAIR_RE = re.compile(r"(\d+)\s*/\s*(\d+)")


# ---------------- 基础 ----------------

def _button_enabled(eng, block, img=None) -> bool:
    """按钮底色饱和度判据（用户确认置灰=底色变灰）。"""
    try:
        import cv2
        img = img if img is not None else eng.screenshot()
        if img is None:
            return False
        w, h = eng.screen_w or 1, eng.screen_h or 1
        cx, cy = block["center"]
        x1 = max(0, int(cx - 0.02 * w))
        x2 = min(w, int(cx + 0.02 * w))
        y1 = max(0, int(cy - 0.011 * h))
        y2 = min(h, int(cy + 0.011 * h))
        patch = img[y1:y2, x1:x2]
        if patch.size == 0:
            return False
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        s = float(hsv[:, :, 1].mean())
        txt = str(block.get("text", "")).strip()
        print(f"    [乐园] 按钮「{txt}」底色 S={s:.1f} -> {'可点' if s >= SAT_TH else '置灰'}")
        return s >= SAT_TH
    except Exception as e:
        print(f"    [乐园] 按钮底色判据失败(按置灰处理): {e}")
        return False


def _ensure_garden(eng) -> bool:
    """自己/好友家园均可: 右下角有「离开」即在家园; 否则户外点「家园」。"""
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
    print("    [乐园] 未能进入家园场景")
    return False


def _open_fairyland(eng) -> bool:
    """已打开则复用；否则 家园 -> 菜单 -> 花仙乐园。"""
    blocks = eng.ocr_blocks(None)
    joined = " ".join(str(b.get("text", "")) for b in blocks)
    if "累计在线时间" in joined and "每日任务" in joined:
        print("    [乐园] 花仙乐园已打开")
        return True

    if not _ensure_garden(eng):
        return False
    # 菜单已展开时「花仙乐园」可见, 不再点菜单(再点会收起)
    if not eng.locate(["花仙乐园"], region_rel=FAIRYLAND_ENTRY_REGION,
                      need_refine=False, log_miss=False):
        if not eng.click_text(["菜单"], region_rel=MENU_REGION,
                              min_score=0.3, no_fallback=True):
            print("    [乐园] 未找到「菜单」")
            return False
        time.sleep(1.5)
    if not eng.click_text(["花仙乐园"], region_rel=FAIRYLAND_ENTRY_REGION,
                          min_score=0.3, no_fallback=True):
        print("    [乐园] 未找到「花仙乐园」")
        return False
    time.sleep(1.5)

    # 菜单入口可能直接开奖励面板, 也可能先到花仙乐园主界面(掷骰子棋盘)
    joined = " ".join(str(b.get("text", "")) for b in eng.ocr_blocks(None))
    if "累计在线时间" not in joined and "每日任务" not in joined:
        if "GO" in joined or "宝藏扭蛋" in joined or "花仙乐园" in joined:
            # 主界面左侧「获取骰子」按钮(OCR 可能分两行: 获取 / 骰子)
            if not eng.click_text(["获取骰子", "获取"], region_rel=[0.0, 0.10, 0.18, 0.26],
                                  min_score=0.3, no_fallback=True):
                print("    [乐园] 主界面未找到「获取骰子」")
                return False
            time.sleep(1.5)

    t0 = time.time()
    while time.time() - t0 < 8:
        joined = " ".join(str(b.get("text", "")) for b in eng.ocr_blocks(None))
        if "累计在线时间" in joined or "每日任务" in joined:
            print(f"    [乐园] 奖励面板就绪({time.time() - t0:.1f}s)")
            return True
        time.sleep(1.0)
    print("    [乐园] 奖励面板就绪超时")
    return False


def _click_tab(eng, name: str) -> bool:
    if not eng.click_text([name], region_rel=TAB_REGION,
                          min_score=0.3, no_fallback=True):
        print(f"    [乐园] 未找到标签「{name}」")
        return False
    time.sleep(1.2)
    return True


def _reward_wait(eng, timeout=8.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if stop_requested():
            return None
        blocks = eng.ocr_blocks(None)
        joined = " ".join(str(b.get("text", "")) for b in blocks)
        if "恭喜获得" in joined or "点击任意处关闭" in joined:
            print(f"    [乐园] 奖励弹窗出现({time.time() - t0:.1f}s)")
            return blocks
        time.sleep(0.8)
    print("    [乐园] 奖励弹窗未出现")
    return None


def _close_reward(eng) -> bool:
    # 点标题区, 避免点页脚穿透底层(项目既有约定)
    for text in ("恭喜获得", "点击任意处关闭"):
        if eng.click_text([text], region_rel=REWARD_REGION,
                          min_score=0.3, no_fallback=True):
            time.sleep(1.2)
            joined = " ".join(str(b.get("text", "")) for b in eng.ocr_blocks(None))
            if "恭喜获得" not in joined and "点击任意处关闭" not in joined:
                print("    [乐园] 奖励弹窗已关闭")
                return True
    print("    [乐园] 奖励弹窗未确认关闭, 回退 close_dialog")
    eng.close_dialog()
    time.sleep(1.2)
    return True


def _claim_online(eng) -> None:
    print("\n[乐园] --- 在线领取 ---")
    if not _click_tab(eng, "在线领取"):
        return
    blocks = [b for b in eng.ocr_blocks(None)
              if "一键领取" in str(b.get("text", ""))]
    if not blocks:
        print("    [乐园] 无「一键领取」按钮 = 已领完/无奖励, 跳过")
        return
    btn = blocks[0]
    if not _button_enabled(eng, btn):
        print("    [乐园] 一键领取置灰, 跳过")
        return
    eng.click_abs(int(btn["center"][0]), int(btn["center"][1]))
    time.sleep(1.5)
    if _reward_wait(eng, 8.0) is not None:
        _close_reward(eng)
    else:
        print("    [乐园] 一键领取后未见奖励弹窗(继续)")


# ---------------- 每日任务 ----------------

def _read_task_row(eng, name: str):
    """任务名行锚定: 返回 (name_block, progress(n,total), button_block) 或 None。"""
    blocks = eng.ocr_blocks(None)
    h = eng.screen_h or 1
    name_b = next((b for b in blocks if name in str(b.get("text", ""))), None)
    if name_b is None:
        return None
    ny = name_b["center"][1]
    row = [b for b in blocks if abs(b["center"][1] - ny) <= 0.075 * h]
    prog = None
    for b in row:
        m = NUM_PAIR_RE.search(str(b.get("text", "")))
        if m and b["center"][0] < 0.70 * (eng.screen_w or 1):
            prog = (int(m.group(1)), int(m.group(2)))
            break
    btn = None
    for b in row:
        t = str(b.get("text", ""))
        if ("领取" in t or "兑换" in t) and b["center"][0] > 0.72 * (eng.screen_w or 1):
            if btn is None or abs(b["center"][1] - ny) < abs(btn["center"][1] - ny):
                btn = b
    return name_b, prog, btn


def _handle_exchange(eng, name: str) -> None:
    print(f"\n[乐园] --- 兑换: {name} ---")
    row = _read_task_row(eng, name)
    if row is None:
        print(f"    [乐园] 未找到任务行「{name}」, 跳过")
        return
    _, progress, btn = row
    print(f"    [乐园] 进度={progress} 按钮={btn.get('text') if btn else None}")
    if btn is None:
        print("    [乐园] 未找到「兑换」按钮, 跳过")
        return
    if not _button_enabled(eng, btn):
        print("    [乐园] 兑换置灰(花朵不足), 跳过")
        return
    eng.click_abs(int(btn["center"][0]), int(btn["center"][1]))
    time.sleep(1.5)
    if _reward_wait(eng, 8.0) is not None:
        _close_reward(eng)


def _handle_water(eng) -> None:
    print("\n[乐园] --- 给他人浇水5次 ---")
    row = _read_task_row(eng, "给他人浇水5次")
    if row is None:
        print("    [乐园] 未找到浇水任务行, 跳过")
        return
    _, progress, btn = row
    print(f"    [乐园] 进度={progress}")
    if progress != (5, 5):
        print("    [乐园] 未达 5/5, 不领取")
        return
    if btn is None:
        print("    [乐园] 未找到「领取」按钮, 跳过")
        return
    if not _button_enabled(eng, btn):
        print("    [乐园] 领取置灰, 跳过")
        return
    eng.click_abs(int(btn["center"][0]), int(btn["center"][1]))
    time.sleep(1.5)
    if _reward_wait(eng, 8.0) is not None:
        _close_reward(eng)


def _return_to_daily(eng) -> bool:
    """购买种子界面关闭后回到花仙乐园每日任务页。"""
    joined = " ".join(str(b.get("text", "")) for b in eng.ocr_blocks(None))
    if "累计在线时间" in joined or "每日任务" in joined:
        return _click_tab(eng, "每日任务")
    if "GO" in joined or "宝藏扭蛋" in joined or "获取" in joined:
        if eng.click_text(["获取骰子", "获取"], region_rel=[0.0, 0.10, 0.18, 0.26],
                          min_score=0.3, no_fallback=True):
            time.sleep(1.5)
            return _click_tab(eng, "每日任务")
    # 兜底: 重新走家园->菜单->花仙乐园
    return _open_fairyland(eng) and _click_tab(eng, "每日任务")


def _handle_bean(eng) -> None:
    print("\n[乐园] --- 园艺店仙豆兑换花种3次 ---")
    row = _read_task_row(eng, "园艺店仙豆兑换花种3次")
    if row is None:
        print("    [乐园] 未找到仙豆任务行, 跳过")
        return
    _, progress, btn = row
    print(f"    [乐园] 进度={progress}")
    if progress is None:
        print("    [乐园] 进度未读到, 不领取")
        return
    n, total = progress
    if n < total:
        need = total - n
        print(f"    [乐园] 未完成 {n}/{total}: 跳购买种子补 {need} 次白色铃兰种子")
        # 任务行内「兑换花种」快捷按钮（x 约 0.573, y 与任务名同排）
        if not eng.click_text(["兑换花种"], region_rel=[0.50, 0.38, 0.65, 0.49],
                              min_score=0.3, no_fallback=True):
            print("    [乐园] 未找到「兑换花种」, 跳过")
            return
        time.sleep(2.0)
        # 等购买种子界面
        t0 = time.time()
        while time.time() - t0 < 8:
            joined = " ".join(str(b.get("text", "")) for b in eng.ocr_blocks(None))
            if "购买种子" in joined or "白色铃兰种子" in joined:
                break
            time.sleep(1.0)
        for i in range(need):
            print(f"    [乐园] 购买白色铃兰种子 第 {i + 1}/{need} 次")
            if not buy_seed_in_shop(eng, "白色铃兰种子", 1):
                print("    [乐园] 购买种子失败, 关闭购买界面")
                eng.close_dialog()
                return
        # 关闭购买种子界面 -> 花仙乐园
        eng.close_dialog()
        time.sleep(1.5)
        if not _return_to_daily(eng):
            print("    [乐园] 关闭购买界面后未能回到每日任务")
            return
        # 重新读任务; 3/3 才领取
        t0 = time.time()
        while time.time() - t0 < 6:
            row = _read_task_row(eng, "园艺店仙豆兑换花种3次")
            if row is not None and row[1] == (total, total):
                break
            time.sleep(1.0)
        if row is None or row[1] != (total, total):
            print(f"    [乐园] 购买后进度未到 {total}/{total}: "
                  f"{row[1] if row else None}, 不领取")
            return
        _, progress, btn = row
        print(f"    [乐园] 购买后进度={progress}")
    if btn is None:
        print("    [乐园] 未找到「领取」按钮, 跳过")
        return
    if not _button_enabled(eng, btn):
        print("    [乐园] 领取置灰, 跳过")
        return
    eng.click_abs(int(btn["center"][0]), int(btn["center"][1]))
    time.sleep(1.5)
    if _reward_wait(eng, 8.0) is not None:
        _close_reward(eng)


def _close_fairyland(eng) -> bool:
    """关闭花仙乐园: 先关奖励面板(在线领取/每日任务), 再关花仙乐园主界面, 复核回家园。

    实机 2026-11-17: close_dialog 两次可分别关掉奖励面板与主界面棋盘;
    模板 close_corner_pink.png 在个别态只有 0.792, 故以 close_dialog 为主、模板为兜底。
    """
    for i in range(2):
        joined = " ".join(str(b.get("text", "")) for b in eng.ocr_blocks(None))
        if "累计在线时间" in joined or "每日任务" in joined:
            print("    [乐园] 关闭奖励面板")
            eng.close_dialog()
            time.sleep(1.5)
            continue
        if "花仙乐园" in joined and ("GO" in joined or "宝藏扭蛋" in joined):
            print("    [乐园] 关闭花仙乐园主界面")
            eng.close_dialog()
            time.sleep(1.5)
            continue
        break
    joined = " ".join(str(b.get("text", "")) for b in eng.ocr_blocks(None))
    if "累计在线时间" in joined or "每日任务" in joined or "花仙乐园" in joined:
        print("    [乐园] 面板关闭未确认, 尝试模板兜底")
        eng.click_template("close_corner_pink.png",
                           region_rel=[0.94, 0.0, 1.0, 0.09],
                           threshold=0.75, no_fallback=True)
        time.sleep(1.2)
    return _ensure_garden(eng)


# ---------------- 主入口 ----------------

def run_fairyland_claim(eng) -> bool:
    print("\n[乐园] ===== 花仙乐园领取 =====")
    if stop_requested():
        return False
    if not _open_fairyland(eng):
        _save_shot(eng, "fairyland_open_failed")
        return False

    _claim_online(eng)
    _save_shot(eng, "fairyland_online")

    if not _click_tab(eng, "每日任务"):
        return False
    # 等待任务列表
    t0 = time.time()
    while time.time() - t0 < 8:
        joined = " ".join(str(b.get("text", "")) for b in eng.ocr_blocks(None))
        if all(n in joined for n in ("白色雪绒花", "蓝色月季花")):
            break
        time.sleep(1.0)
    _save_shot(eng, "fairyland_daily")

    for name in ("白色雪绒花", "蓝色月季花"):
        _handle_exchange(eng, name)
    _handle_water(eng)
    _handle_bean(eng)

    ok = _close_fairyland(eng)
    _save_shot(eng, "fairyland_end")
    print(f"[乐园] ===== 完成: 关闭回园={ok} =====")
    return ok
