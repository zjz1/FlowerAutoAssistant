# -*- coding: utf-8 -*-
"""通用 UI 操作原语（截图 / 精识 / 输入框聚焦与输入）。

2026-11-17 P0 重构：此前 `_save_shot`/`_texts`/`_fine_blocks`/`_click_text_fine`
散落在 plant.py，buy_seed.py / fairyland.py 反向导入 plant 的私有函数，形成
`fairyland -> buy_seed -> plant -> ocr_engine` 的业务耦合链。本模块只依赖引擎实例
的公开能力（screenshot/ocr_blocks/ocr_direct/click_abs/locate/click_text），
不反向依赖任何业务模块。

日志统一用 `[UI]`/`[截图]` 前缀；截图文件名前缀默认仍是 `plant`，
以保持既有 `debug/plant_*.png` 证据路径不变。
"""
from __future__ import annotations
from core.ports import UiPort

import subprocess
import time

# 系统键盘右下角「确定」（1080p 实机标定；相对坐标与分辨率无关）
IME_OK_REGION = [0.85, 0.88, 1.0, 1.0]
# 奖励/结果弹窗的通用大区域（buy_seed / fairyland 实机标定）
REWARD_REGION_WIDE = [0.20, 0.10, 0.85, 0.98]


def close_reward_popup(eng: UiPort, keywords, region_rel=REWARD_REGION_WIDE, tag: str = "UI",
                       confirm: bool = False, fallback_close: bool = True,
                       fine_fallback: bool = False) -> bool:
    """按给定关键词关闭奖励/结果弹窗（标题优先、页脚兜底）。

    keywords 由调用方按弹窗形态提供：
      - 收获奖励：「确定」「点击任意处关闭」（confirm=False, fine_fallback=True）
      - 花仙乐园：「恭喜获得」「点击任意处关闭」（confirm=True，点后复检）
      - 购买种子：「恭喜获得」「点击任意处关闭」「确定」
    confirm=True 时点完复检文案是否消失；失败再试下一个词。
    fallback_close=True 时全部词未命中则回退 close_dialog（既有行为）。
    fine_fallback=True 时粗 OCR 未命中再走小区域精识（保留收获奖励旧行为）。
    """
    for text in keywords:
        clicked = eng.click_text([text], region_rel=region_rel,
                                 min_score=0.3, no_fallback=True)
        if not clicked and fine_fallback:
            clicked = click_text_fine(eng, text, region_rel)
        if clicked:
            time.sleep(1.2)
            if not confirm:
                print(f"    [{tag}] 奖励弹窗已处理")
                return True
            joined = " ".join(str(b.get("text", "")) for b in eng.ocr_blocks(None))
            if not any(k in joined for k in keywords):
                print(f"    [{tag}] 奖励弹窗已关闭")
                return True
    if fallback_close:
        print(f"    [{tag}] 奖励弹窗未确认关闭, 回退 close_dialog")
        eng.close_dialog()
        time.sleep(1.2)
        return True
    print(f"    [{tag}] 奖励弹窗未找到可点关闭词")
    return False


def save_shot(eng: UiPort, tag: str, prefix: str = "plant", img=None):
    """保存当前帧到 debug/ 供区域标定；失败静默（不影响流程）。

    img 传入时复用已捕获帧，避免同一画面重复 ADB 截图。
    """
    try:
        import cv2
        img = img if img is not None else eng.screenshot()
        if img is None:
            return None
        from pathlib import Path
        d = Path(__file__).resolve().parent / "debug"
        d.mkdir(exist_ok=True)
        p = d / f"{prefix}_{tag}_{time.strftime('%Y%m%d_%H%M%S')}.png"
        cv2.imwrite(str(p), img)
        print(f"    [截图] -> {p}")
        return img
    except Exception as e:
        print(f"    [截图] 失败(不影响流程): {e}")
        return None


def texts(blocks) -> list[str]:
    return [str(b.get("text", "")).strip() for b in blocks]


def fine_blocks(eng: UiPort, region_rel, scale: int = 2, img=None):
    """小区域放大 OCR（状态栏/已选/小字号按钮），坐标映射回全图。

    实机 2026-11-16: 全图 OCR 会把「当前为…晴天…肥力值 120/120…」合并成一块且数字误读,
    裁片 2x 后可稳定读出 120/120；已选区全图常漏读, 2x 后可读「当前已选：0/60」。
    """
    try:
        import cv2
        img = img if img is not None else eng.screenshot()
        if img is None:
            return []
        w, h = eng.screen_w or 1, eng.screen_h or 1
        x1, y1, x2, y2 = region_rel
        cx1, cy1 = int(x1 * w), int(y1 * h)
        cx2, cy2 = int(x2 * w), int(y2 * h)
        crop = img[cy1:cy2, cx1:cx2]
        if crop.size == 0:
            return []
        up = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        blocks = eng.ocr_direct(up, "ui_fine")
        for b in blocks:
            b["center"] = [int(b["center"][0] / scale + cx1), int(b["center"][1] / scale + cy1)]
            b["box"] = [int(b["box"][0] / scale + cx1), int(b["box"][1] / scale + cy1),
                        int(b["box"][2] / scale + cx1), int(b["box"][3] / scale + cy1)]
        return blocks
    except Exception as e:
        print(f"    [UI] 放大 OCR 失败(回退全图): {e}")
        return eng.ocr_blocks(None, region_rel)


def click_text_fine(eng: UiPort, text: str, region_rel) -> bool:
    """小区域精识后按块中心点击（系统键盘「确定」等小字号按钮）。"""
    blocks = fine_blocks(eng, region_rel, 2)
    b = next((x for x in blocks if text in str(x.get("text", ""))), None)
    if b is None:
        return False
    x, y = b["center"]
    print(f"    [UI] 精识点击「{text}」-> ({x},{y})")
    eng.click_abs(int(x), int(y))
    return True


def clear_focused(eng: UiPort, n: int = 24):
    """清空当前输入框: 移到末尾后连按退格。"""
    adb, addr = eng.adb_path, eng.address
    try:
        subprocess.run([adb, "-s", addr, "shell", "input", "keyevent", "123"],
                       capture_output=True, timeout=10)
        subprocess.run([adb, "-s", addr, "shell", "input", "keyevent"] + ["67"] * n,
                       capture_output=True, timeout=20)
    except Exception as e:
        print(f"    [UI] 清空输入框失败: {e}")


def focus_input(eng: UiPort, region_rel, placeholder: str = "请输入关键字",
                anchor: str | None = None, anchor_region=None,
                from_anchor_rel=None) -> bool:
    """聚焦输入框：占位符 → 框内现有文字 → 锚点相对定位（全空时）。

    锚点相对定位只用于「框内既无占位符也无文字」的实机状态（2026-11-17 购买种子），
    坐标由锚点实时命中 + 标定偏移推导，不写死屏幕坐标。
    """
    if placeholder and eng.click_text([placeholder], region_rel=region_rel,
                                      min_score=0.3, no_fallback=True):
        return True
    blocks = eng.ocr_blocks(None, region_rel)
    cand = next((b for b in blocks if str(b.get("text", "")).strip()), None)
    if cand is not None:
        x, y = cand["center"]
        print(f"    [UI] 输入框已有内容「{cand['text']}」-> 点 ({x},{y}) 聚焦")
        eng.click_abs(int(x), int(y))
        return True
    if not (anchor and anchor_region and from_anchor_rel):
        return False
    a = eng.locate([anchor], region_rel=anchor_region,
                   need_refine=False, log_miss=False)
    if a is None:
        return False
    w, h = eng.screen_w or 1, eng.screen_h or 1
    x = int(a.x + from_anchor_rel[0] * w)
    y = int(a.y + from_anchor_rel[1] * h)
    print(f"    [UI] 输入框为空 -> 按「{anchor}」锚点相对点击 ({x},{y})")
    eng.click_abs(x, y)
    return True


def input_text_ime(eng: UiPort, text: str, region_rel, ime_region,
                   placeholder: str = "请输入关键字",
                   anchor: str | None = None, anchor_region=None,
                   from_anchor_rel=None) -> bool:
    """聚焦输入框 → 清空 → adb input text → 点系统键盘「确定」。

    返回 False 仅表示输入链路未完成；输入内容是否生效由调用方按业务需要复核。
    """
    if not focus_input(eng, region_rel, placeholder, anchor, anchor_region, from_anchor_rel):
        print("    [UI] 未找到输入框（无占位符/无现有文字/锚点未命中）")
        return False
    time.sleep(1.0)
    clear_focused(eng)
    adb, addr = eng.adb_path, eng.address
    try:
        r = subprocess.run([adb, "-s", addr, "shell", "input", "text", text],
                           capture_output=True, timeout=20)
        print(f"    [UI] adb input text {text!r} rc={r.returncode}")
    except Exception as e:
        print(f"    [UI] 输入失败: {e}")
        return False
    time.sleep(0.8)
    if not click_text_fine(eng, "确定", ime_region):
        print("    [UI] 未找到输入法「确定」")
        return False
    time.sleep(2.0)
    return True
