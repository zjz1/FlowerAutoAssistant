# -*- coding: utf-8 -*-
"""种植模块 · 种植花朵（当前仅桃花）阶段1：进种植页 → 采集信息 → 搜索花种。

本模块只做用户 2026-11-16 指定的第 2-4 步（第1步『确保在自己家园』在 flow_plant.json 阶段0）：
  2. 在自己家园点「一键种植」进种植页；
  3. 区域 OCR 采集：天气 / 肥力 a/b / 当前已选 c/d；
  4. 点「请输入关键字」→ 输入花名（桃花）→ 确定 → 读取筛选出的花种名称/数量。
不做选种/种植/关面板（后续阶段）。

区域常量均为相对坐标（0~1），只限定 OCR/点击判据，点击仍取实时命中坐标。
初版数值待实机标定：`plant_*` 截图与 `[种植]` 日志会打印实际块坐标。
"""
from __future__ import annotations

import re
import subprocess
import time

from ocr_engine import ADB_ADDRESS, ADB_PATH, stop_requested

# ---- 区域（相对坐标；实机标定后收紧） ----
PLANT_ENTRY_REGION = [0.70, 0.88, 1.0, 1.0]       # 自己家园底栏「一键种植」带
PLANT_PANEL_REGION = [0.02, 0.02, 0.98, 0.98]     # 种植页整体（点击判据范围）
PLANT_STATUS_REGION = [0.35, 0.10, 0.75, 0.15]    # 天气 / 肥力值 a/b（实机标定 2026-11-16）
PLANT_SELECTED_REGION = [0.16, 0.82, 0.35, 0.91]  # 当前已选 c/d（实机标定 2026-11-16）
PLANT_SEARCH_DIALOG_REGION = [0.30, 0.30, 0.75, 0.70]  # 关键字输入框/确定
PLANT_SEED_RESULT_REGION = [0.27, 0.15, 0.95, 0.82]    # 筛选后的种子列表（实机标定 2026-11-16）
IME_OK_REGION = [0.85, 0.88, 1.0, 1.0]            # 系统键盘右下「确定」

PANEL_READY_KWS = ("请输入关键字", "肥力值", "当前已选")
WEATHER_KWS = ("晴", "雨", "阴", "雪")
NUM_PAIR_RE = re.compile(r"(\d+)\s*[/／]\s*(\d+)")
NUM_RE = re.compile(r"^\s*(\d+)\s*$")

# 花种名称 -> 数量 的固定相对偏移（2026-11-16 实机标定: 白色桃花 名称(464,244) 数量(483,215)）
SEED_COUNT_DX_REL = 0.015
SEED_COUNT_DY_REL = -0.040
SEED_COUNT_RADIUS_REL = 0.02

# ---- 阶段2: 种白色桃花（2026-11-17 用户确认） ----
TARGET_COLOR = "白色"
TARGET_COUNT = 1
TARGET_COST = 2          # 白色桃花每株消耗 2 点肥力（用户给定）
QUANTITY_DIALOG_REGION = [0.23, 0.20, 0.77, 0.80]   # 数量窗口（实机标定 2026-11-17: 标题 y≈0.215, 确认 y≈0.729）
DETAIL_DIALOG_REGION = [0.25, 0.25, 0.80, 0.78]     # 种植详情二次确认窗口（待实机标定）
DETAIL_CLOSE_DX_REL = 0.278   # 详情窗口右上角 X 相对名称块的偏移（实机 585,250 -> 941,158）
DETAIL_CLOSE_DY_REL = -0.128

# ---- 花朵收获（2026-11-17 用户流程） ----
HARVEST_LEFT_NAV_REGION = [0.02, 0.15, 0.16, 0.80]   # 左侧 种植/照料/授粉...
HARVEST_TAB_REGION = [0.25, 0.10, 0.95, 0.18]        # 可收获(x)/可授粉(x) 标签带
HARVEST_POLLEN_REGION = [0.13, 0.15, 0.35, 0.55]     # 授粉页左侧花粉列表
HARVEST_BTN_REGION = [0.92, 0.35, 1.0, 0.48]         # 右侧「一键收花」
REWARD_REGION = [0.25, 0.25, 0.80, 0.78]             # 奖励弹窗


# ---------------- 基础 ----------------

def _save_shot(eng, tag: str):
    """保存当前帧到 debug/ 供区域标定；失败静默（不影响流程）。"""
    try:
        import cv2
        img = eng.screenshot()
        if img is None:
            return None
        from pathlib import Path
        d = Path(__file__).resolve().parent / "debug"
        d.mkdir(exist_ok=True)
        p = d / f"plant_{tag}_{time.strftime('%Y%m%d_%H%M%S')}.png"
        cv2.imwrite(str(p), img)
        print(f"    [种植] 截图 -> {p}")
        return img
    except Exception as e:
        print(f"    [种植] 截图失败(不影响流程): {e}")
        return None


def _texts(blocks) -> list[str]:
    return [str(b.get("text", "")).strip() for b in blocks]


def _fine_blocks(eng, region_rel, scale: int = 2, img=None):
    """小区域放大 OCR（状态栏/已选这类小字号），坐标映射回全图。

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
        blocks = eng.ocr_direct(up, "plant_fine")
        for b in blocks:
            b["center"] = [int(b["center"][0] / scale + cx1), int(b["center"][1] / scale + cy1)]
            b["box"] = [int(b["box"][0] / scale + cx1), int(b["box"][1] / scale + cy1),
                        int(b["box"][2] / scale + cx1), int(b["box"][3] / scale + cy1)]
        return blocks
    except Exception as e:
        print(f"    [种植] 放大 OCR 失败(回退全图): {e}")
        return eng.ocr_blocks(None, region_rel)


def _has_kw(blocks, kw: str) -> bool:
    return any(kw in t for t in _texts(blocks))


def _pair_near(blocks, anchor_kw: str):
    """在 blocks 中找 anchor_kw 附近的 a/b 数字对。返回 (a,b,block) 或 None。"""
    anchor = next((b for b in blocks if anchor_kw in str(b.get("text", ""))), None)
    pairs = []
    for b in blocks:
        t = str(b.get("text", ""))
        m = NUM_PAIR_RE.search(t)
        if m:
            pairs.append((int(m.group(1)), int(m.group(2)), b))
    if not pairs:
        return None
    if anchor is not None:
        # anchor 自身带 a/b（如「肥力值：120/120」）
        m = NUM_PAIR_RE.search(str(anchor.get("text", "")))
        if m:
            return int(m.group(1)), int(m.group(2)), anchor
        ax, ay = anchor["center"]
        pairs.sort(key=lambda p: (abs(p[2]["center"][0] - ax) + abs(p[2]["center"][1] - ay)))
    return pairs[0]


def read_panel_info(eng, img=None) -> dict:
    """区域 OCR 采集种植页面信息。缺失字段记 None, 不猜。"""
    status = _fine_blocks(eng, PLANT_STATUS_REGION, 2, img)
    selected = _fine_blocks(eng, PLANT_SELECTED_REGION, 2, img)

    weather = None
    weather_kind = None
    for b in status:
        t = str(b.get("text", "")).strip()
        # 实机 2026-11-17: 「当前为小雨13℃-16℃」（小雨/晴天/阴天…）
        m = re.search(r"当前为\s*([^\d（(]+)", t)
        if m:
            weather_kind = m.group(1).strip(" ：:，,）)")
            weather = weather_kind
            break
        m = re.search(r"(晴天|雨天|阴天|雪天|小雨|中雨|大雨|暴雨|雷阵雨|阵雨)", t)
        if m:
            weather_kind = m.group(1)
            weather = weather_kind
            break
        if any(k in t for k in WEATHER_KWS):
            weather = t
            break

    fert = _pair_near(status, "肥力值")
    sel = _pair_near(selected, "当前已选")

    info = {
        "weather": weather,
        "weather_kind": weather_kind,
        "fertility_remaining": fert[0] if fert else None,
        "fertility_total": fert[1] if fert else None,
        "selected_count": sel[0] if sel else None,
        "plantable_total": sel[1] if sel else None,
        "status_blocks": [(t, b["center"], b.get("score")) for t, b in
                          ((str(x.get("text", "")).strip(), x) for x in status)],
        "selected_blocks": [(t, b["center"], b.get("score")) for t, b in
                            ((str(x.get("text", "")).strip(), x) for x in selected)],
    }
    if info["fertility_remaining"] is not None and info["fertility_total"] is not None:
        if info["fertility_remaining"] > info["fertility_total"]:
            print("    [种植] 肥力解析异常: a>b, 标记为未知")
            info["fertility_remaining"] = info["fertility_total"] = None
    if info["selected_count"] is not None and info["plantable_total"] is not None:
        if info["selected_count"] > info["plantable_total"]:
            print("    [种植] 已选解析异常: c>d, 标记为未知")
            info["selected_count"] = info["plantable_total"] = None

    print(f"    [种植] 页面信息: 天气={info['weather'] or '?'} "
          f"肥力={info['fertility_remaining'] if info['fertility_remaining'] is not None else '?'}/"
          f"{info['fertility_total'] if info['fertility_total'] is not None else '?'} "
          f"已选={info['selected_count'] if info['selected_count'] is not None else '?'}/"
          f"{info['plantable_total'] if info['plantable_total'] is not None else '?'}")
    print(f"    [种植] 区域块: 状态{len(status)} 已选{len(selected)}")
    return info


def _wait_panel_ready(eng, timeout=10.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if stop_requested():
            return False
        img = eng.screenshot()
        blocks = eng.ocr_blocks(img, PLANT_STATUS_REGION) + eng.ocr_blocks(img, PLANT_SELECTED_REGION)
        hit = sum(1 for kw in PANEL_READY_KWS if _has_kw(blocks, kw))
        if hit >= 2:
            print(f"    [种植] 种植页就绪({hit}/3 关键文本, {time.time() - t0:.1f}s)")
            return True
        time.sleep(1.0)
    print(f"    [种植] 种植页就绪超时 {timeout:.0f}s")
    return False


def _wait_dialog(eng, timeout=12.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if stop_requested():
            return False
        for reg in (IME_OK_REGION, PLANT_SEARCH_DIALOG_REGION):
            # 系统键盘的「确定」字号小, 全图 OCR 易漏 —— 小区域 2x 精识
            if _has_kw(_fine_blocks(eng, reg, 2), "确定"):
                print(f"    [种植] 输入框就绪({time.time() - t0:.1f}s)")
                return True
        time.sleep(0.8)
    print(f"    [种植] 输入框就绪超时 {timeout:.0f}s")
    return False


def _adb_input_text(eng, text: str) -> bool:
    """ADB input text 输入（中文是否支持需实机验证；返回进程成功不等于输入生效）。"""
    adb = getattr(eng, "adb_path", ADB_PATH)
    addr = getattr(eng, "address", ADB_ADDRESS)
    try:
        r = subprocess.run([adb, "-s", addr, "shell", "input", "text", text],
                           capture_output=True, timeout=20)
        print(f"    [种植] adb input text {text!r} rc={r.returncode}")
        return r.returncode == 0
    except Exception as e:
        print(f"    [种植] adb input text 失败: {e}")
        return False


def _input_flower(eng, flower: str) -> bool:
    _adb_input_text(eng, flower)
    time.sleep(1.0)
    img = eng.screenshot()
    wide = [0.20, 0.20, 0.95, 0.82]
    blocks = eng.ocr_blocks(img, PLANT_SEARCH_DIALOG_REGION) + eng.ocr_blocks(img, wide)
    if _has_kw(blocks, flower):
        print(f"    [种植] 输入生效: {flower}")
        return True
    print(f"    [种植] 输入未生效(OCR 未读到 {flower!r}); 中止, 不点确定")
    print(f"    [种植] 当前输入区实读: {_texts(blocks)[:12]}")
    return False


def _click_text_fine(eng, text: str, region_rel) -> bool:
    """小区域精识后按块中心点击（系统键盘「确定」等小字号按钮）。"""
    blocks = _fine_blocks(eng, region_rel, 2)
    b = next((x for x in blocks if text in str(x.get("text", ""))), None)
    if b is None:
        return False
    x, y = b["center"]
    print(f"    [种植] 精识点击「{text}」-> ({x},{y})")
    eng.click_abs(int(x), int(y))
    return True


def _confirm_search(eng) -> bool:
    for reg in (IME_OK_REGION, PLANT_SEARCH_DIALOG_REGION):
        if _click_text_fine(eng, "确定", reg):
            time.sleep(1.5)
            return True
    print("    [种植] 未找到「确定」(键盘/对话框区域)")
    return False


def _wait_search_result(eng, flower: str, timeout=10.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if stop_requested():
            return False
        blocks = eng.ocr_blocks(None, PLANT_SEED_RESULT_REGION)
        if _has_kw(blocks, flower):
            print(f"    [种植] 搜索结果命中({time.time() - t0:.1f}s)")
            return True
        time.sleep(1.0)
    print(f"    [种植] 搜索结果超时 {timeout:.0f}s")
    return False


def read_search_result(eng, flower: str) -> dict:
    """读取筛选后的全部花种名称/是否搜出/数量；数量按固定相对偏移取最近数字块。"""
    img = eng.screenshot()
    blocks = eng.ocr_blocks(img, PLANT_SEED_RESULT_REGION)
    names = [b for b in blocks if flower in str(b.get("text", ""))]
    w, h = eng.screen_w or 1, eng.screen_h or 1

    results = []
    for name in names:
        nx, ny = name["center"]
        expected = (nx + SEED_COUNT_DX_REL * w, ny + SEED_COUNT_DY_REL * h)
        best = None
        best_d = 1e9
        for b in blocks:
            m = NUM_RE.match(str(b.get("text", "")))
            if not m:
                continue
            cx, cy = b["center"]
            d = abs(cx - expected[0]) + abs(cy - expected[1])
            if d > SEED_COUNT_RADIUS_REL * (w + h):
                continue
            if d < best_d:
                best_d = d
                best = (int(m.group(1)), b)
        results.append({
            "name": str(name.get("text", "")).strip(),
            "count": best[0] if best else None,
            "name_rel": [round(nx / w, 4), round(ny / h, 4)],
            "count_offset_rel": ([round((best[1]["center"][0] - nx) / w, 4),
                                  round((best[1]["center"][1] - ny) / h, 4)] if best else None),
        })
    res = {"keyword": flower, "found": bool(results), "results": results}
    if not results:
        print(f"    [种植] 搜索结果: {flower} 未搜出")
    else:
        brief = " | ".join(f"{r['name']}={r['count']}" for r in results)
        print(f"    [种植] 搜索结果: {brief}")
        print(f"    [种植] 名称->数量偏移(实机): "
              f"{[r['count_offset_rel'] for r in results if r['count_offset_rel']]}")
    print(f"    [种植] 种子区实读: {_texts(blocks)[:20]}")
    return res


# ---------------- 阶段2: 种白色桃花 ----------------

def _find_grid_seed(eng, seed_exact: str):
    """在种子结果区找精确同名的网格块（带数量角标），返回 (name_block, count) 或 None。

    用户要求: 页面至少两个「种子名称」文字, 必须精准 OCR; 选“带数量角标的种子网格块”。
    其余同名块(如选中列表/提示)因找不到固定偏移的数量角标而被排除。
    """
    blocks = eng.ocr_blocks(None, PLANT_SEED_RESULT_REGION)
    w, h = eng.screen_w or 1, eng.screen_h or 1
    cands = [b for b in blocks if str(b.get("text", "")).strip() == seed_exact]
    print(f"    [种植] 精确匹配「{seed_exact}」: {len(cands)} 块 "
          f"{[b['center'] for b in cands]}")
    for name in cands:
        nx, ny = name["center"]
        expected = (nx + SEED_COUNT_DX_REL * w, ny + SEED_COUNT_DY_REL * h)
        best = None
        best_d = 1e9
        for b in blocks:
            m = NUM_RE.match(str(b.get("text", "")))
            if not m:
                continue
            cx, cy = b["center"]
            d = abs(cx - expected[0]) + abs(cy - expected[1])
            if d > SEED_COUNT_RADIUS_REL * (w + h):
                continue
            if d < best_d:
                best_d = d
                best = (int(m.group(1)), b)
        if best:
            print(f"    [种植] 选中网格块 center={name['center']} 角标={best[0]} "
                  f"(角标块 {best[1]['center']})")
            return name, best[0]
    return None


def _read_quantity_pair(eng, timeout=8.0):
    """等数量窗口的 m/n（m=将种个数, n=已有该种子数）。返回 (m,n,block) 或 None。"""
    t0 = time.time()
    last = []
    w, h = eng.screen_w or 1, eng.screen_h or 1
    cx0, cy0 = w * 0.5, h * 0.5
    while time.time() - t0 < timeout:
        if stop_requested():
            return None
        blocks = _fine_blocks(eng, QUANTITY_DIALOG_REGION, 2)
        last = blocks
        pairs = []
        for b in blocks:
            m = NUM_PAIR_RE.search(str(b.get("text", "")))
            if m:
                pairs.append((int(m.group(1)), int(m.group(2)), b))
        if pairs:
            # 取距窗口中心最近的 a/b, 避免误读背后的面板状态栏(如 358/358)
            pairs.sort(key=lambda p: abs(p[2]["center"][0] - cx0) + abs(p[2]["center"][1] - cy0))
            pair = pairs[0]
            print(f"    [种植] 数量窗口: {pair[0]}/{pair[1]} (块 {pair[2]['center']})")
            return pair
        time.sleep(0.8)
    print(f"    [种植] 数量窗口 m/n 未读到; 实读={_texts(last)[:15]}")
    return None


def _adjust_quantity_to_one(eng, pair) -> bool:
    """把将种个数调到 1。+/- 是图标: 先尝试 OCR 的 -/－/−, 再用 m/n 块左侧相对位置。"""
    m, n, block = pair
    if n < 1:
        print(f"    [种植] 该种子数量为 {n}, 不能种植")
        return False
    if m == TARGET_COUNT:
        print(f"    [种植] 数量已为 {TARGET_COUNT}, 无需调整")
        return True
    w = eng.screen_w or 1
    for i in range(10):
        minus = eng.locate(["-", "－", "−"], region_rel=QUANTITY_DIALOG_REGION,
                           min_score=0.2, need_refine=False, log_miss=False)
        if minus is not None:
            eng.click_abs(int(minus.x), int(minus.y))
        else:
            # 图标 OCR 不到时的相对兜底: 实机「-」在 m/n 块左下方 (相对块坐标推导, 非屏幕写死坐标)
            x = int(block["center"][0] - 0.13 * w)
            y = int(block["center"][1] + 0.06 * (eng.screen_h or 1))
            print(f"    [种植] 「-」图标未识别, 按 m/n 块左下方相对点击 ({x},{y})")
            eng.click_abs(x, y)
        time.sleep(0.5)
        pair = _read_quantity_pair(eng, 3.0)
        if pair is None:
            print("    [种植] 调整数量后 m/n 丢失")
            return False
        m, n, block = pair
        if m == TARGET_COUNT:
            print(f"    [种植] 数量已调到 {TARGET_COUNT}")
            return True
        if m < TARGET_COUNT:
            print(f"    [种植] 数量降到 {m}, 低于目标 {TARGET_COUNT}")
            return False
    print(f"    [种植] 数量调整失败, 仍为 {m}")
    return False


def _confirm_quantity(eng) -> bool:
    for reg in (QUANTITY_DIALOG_REGION,):
        if eng.click_text(["确认"], region_rel=reg, no_fallback=True):
            time.sleep(1.2)
            return True
        if _click_text_fine(eng, "确认", reg):
            time.sleep(1.2)
            return True
    print("    [种植] 数量窗口未找到「确认」")
    return False


def _wait_after_quantity(eng, base: dict, timeout=8.0):
    """数量确认后的状态。返回 (info, mode): mode='selected'=已选1待随机;
    mode='planted'=确认后已直接完成种植(实机可能出现)。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if stop_requested():
            return None
        info = read_panel_info(eng)
        a_ok = (info["fertility_remaining"] is not None
                and base["fertility_remaining"] is not None
                and info["fertility_remaining"] == base["fertility_remaining"] - TARGET_COST)
        if a_ok and info["selected_count"] == TARGET_COUNT:
            print("    [种植] 数量确认后: 已选=1, 待随机种植")
            return info, "selected"
        if (a_ok and info["selected_count"] == 0
                and info["plantable_total"] is not None
                and base["plantable_total"] is not None
                and info["plantable_total"] == base["plantable_total"] - TARGET_COUNT):
            print("    [种植] 数量确认后: 已直接完成种植(可种-1, 肥力-2)")
            return info, "planted"
        time.sleep(1.0)
    print("    [种植] 数量确认后状态不符(已选/肥力/可种), 不继续")
    return None


def _wait_detail_window(eng, detail_name: str, timeout=10.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if stop_requested():
            return None
        blocks = _fine_blocks(eng, DETAIL_DIALOG_REGION, 2)
        if _has_kw(blocks, detail_name):
            print(f"    [种植] 详情窗口就绪({time.time() - t0:.1f}s)")
            return blocks
        time.sleep(0.8)
    print(f"    [种植] 详情窗口超时 {timeout:.0f}s")
    return None


def _verify_detail(eng, blocks, detail_name: str) -> bool:
    """详情窗口: 目标行「白色桃花花种」+ 数量=1；出现计划外花种行则拒绝确认。

    实机 2026-11-17: 单种子时布局为 顶部名称「白色桃花花种」+ 底部「已选择：1/58」+「确认种植」,
    名称与数量不在同一行；优先解析「已选择：m/n」的 m，多行时再退回同行数字。
    """
    h = eng.screen_h or 1
    names = [b for b in blocks if detail_name in str(b.get("text", ""))]
    if not names:
        print(f"    [种植] 详情窗口未读到「{detail_name}」; 实读={_texts(blocks)[:20]}")
        return False
    # 计划外行: 其它含「花种」的名称块
    others = [b for b in blocks
              if "花种" in str(b.get("text", ""))
              and detail_name not in str(b.get("text", ""))]
    if others:
        print(f"    [种植] 详情窗口存在计划外花种行: {_texts(others)[:8]}")
        return False

    # 优先: 「已选择：m/n」
    sel = []
    for b in blocks:
        m = re.search(r"已选择[：:]\s*(\d+)\s*/\s*(\d+)", str(b.get("text", "")))
        if m:
            sel.append((int(m.group(1)), int(m.group(2)), b))
    if sel:
        got, total, b = sel[0]
        print(f"    [种植] 详情核对: {detail_name} 已选择={got}/{total} (计划 {TARGET_COUNT})")
        return got == TARGET_COUNT and total >= TARGET_COUNT

    # 兜底: 名称同行数字（多种子多行布局）
    name = names[0]
    nx, ny = name["center"]
    nums = []
    for b in blocks:
        m = re.match(r"^\s*(\d+)", str(b.get("text", "")))
        if not m:
            continue
        if abs(b["center"][1] - ny) <= 0.035 * h:
            nums.append((int(m.group(1)), b))
    if not nums:
        print(f"    [种植] 详情窗口目标行未读到数量; 实读={_texts(blocks)[:20]}")
        return False
    nums.sort(key=lambda x: abs(x[1]["center"][0] - nx))
    got = nums[0][0]
    print(f"    [种植] 详情核对(同行): {detail_name} = {got} (计划 {TARGET_COUNT})")
    return got == TARGET_COUNT


def _close_detail_window(eng, blocks, detail_name: str) -> bool:
    """详情不符时点右上角 X（由名称块实时坐标 + 相对偏移推导, 非屏幕写死坐标）。"""
    w, h = eng.screen_w or 1, eng.screen_h or 1
    name = next((b for b in blocks if detail_name in str(b.get("text", ""))), None)
    if name is None:
        print("    [种植] 详情窗口无名称锚点, 回退 close_dialog")
        eng.close_dialog()
        return False
    x = int(name["center"][0] + DETAIL_CLOSE_DX_REL * w)
    y = int(name["center"][1] + DETAIL_CLOSE_DY_REL * h)
    print(f"    [种植] 点详情窗口右上角 X -> ({x},{y})")
    eng.click_abs(x, y)
    time.sleep(1.0)
    if not _has_kw(_fine_blocks(eng, DETAIL_DIALOG_REGION, 2), detail_name):
        print("    [种植] 详情窗口已关闭")
        return True
    print("    [种植] 详情窗口仍在, 回退 close_dialog")
    eng.close_dialog()
    return False


def _confirm_detail(eng) -> bool:
    for text in ("确认种植", "确认"):
        if eng.click_text([text], region_rel=DETAIL_DIALOG_REGION, no_fallback=True):
            time.sleep(1.5)
            return True
        if _click_text_fine(eng, text, DETAIL_DIALOG_REGION):
            time.sleep(1.5)
            return True
    print("    [种植] 详情窗口未找到「确认种植/确认」")
    return False


def _wait_detail_closed(eng, detail_name: str, timeout=8.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if stop_requested():
            return False
        if not _has_kw(_fine_blocks(eng, DETAIL_DIALOG_REGION, 2), detail_name):
            print(f"    [种植] 详情窗口已关闭({time.time() - t0:.1f}s)")
            return True
        time.sleep(0.8)
    print(f"    [种植] 详情窗口关闭超时 {timeout:.0f}s")
    return False


def _verify_after_plant(eng, base: dict) -> bool:
    """回读校验: d-1, 肥力 a/b 同步-2, c=0（2026-11-17 实机: 356/356 -> 354/354）。"""
    after = read_panel_info(eng)
    eng.plant_panel_after = after
    d_ok = (after["plantable_total"] is not None
            and base["plantable_total"] is not None
            and after["plantable_total"] == base["plantable_total"] - TARGET_COUNT)
    a_ok = (after["fertility_remaining"] is not None
            and base["fertility_remaining"] is not None
            and after["fertility_remaining"] == base["fertility_remaining"] - TARGET_COST)
    b_ok = (after["fertility_total"] is not None
            and base["fertility_total"] is not None
            and after["fertility_total"] == base["fertility_total"] - TARGET_COST)
    c_ok = after["selected_count"] == 0
    print(f"    [种植] 种植前后: 可种 {base['plantable_total']}->{after['plantable_total']} "
          f"(期望-{TARGET_COUNT}) 肥力 {base['fertility_remaining']}/{base['fertility_total']}"
          f"->{after['fertility_remaining']}/{after['fertility_total']} (期望 a/b 各-{TARGET_COST}) "
          f"已选={after['selected_count']}")
    ok = d_ok and a_ok and b_ok and c_ok
    print(f"    [种植] 种植判据: 可种{'OK' if d_ok else 'FAIL'} "
          f"肥力a{'OK' if a_ok else 'FAIL'} 肥力b{'OK' if b_ok else 'FAIL'} "
          f"已选{'OK' if c_ok else 'FAIL'}")
    return ok


# ---------------- 主入口 ----------------

def run_plant_flower(eng, flower: str = "桃花") -> bool:
    """阶段1+2: 搜索白色桃花 -> 精确点选 -> 数量1 -> 随机种植 -> 详情确认 -> 回读校验。"""
    print(f"\n[种植] ===== 种植花朵(白色+{flower}): 阶段1+2 =====")
    if stop_requested():
        return False

    # 2. 点「一键种植」进种植页
    if not eng.click_text(["一键种植"], region_rel=PLANT_ENTRY_REGION,
                          min_score=0.4, no_fallback=True):
        print("    [种植] 未找到「一键种植」, 中止")
        _save_shot(eng, "no_entry")
        return False
    _save_shot(eng, "entry_clicked")
    if not _wait_panel_ready(eng, 10.0):
        _save_shot(eng, "panel_timeout")
        return False

    # 3. 采集页面信息
    img = _save_shot(eng, "panel")
    info = read_panel_info(eng, img)
    eng.plant_panel_info = info

    # 4. 搜索花种
    if not eng.click_text(["请输入关键字"], region_rel=PLANT_PANEL_REGION,
                          min_score=0.35, no_fallback=True):
        print("    [种植] 未找到「请输入关键字」, 中止")
        _save_shot(eng, "no_search_box")
        return False
    if not _wait_dialog(eng, 12.0):
        _save_shot(eng, "dialog_timeout")
        return False
    _save_shot(eng, "dialog")
    if not _input_flower(eng, flower):
        _save_shot(eng, "input_failed")
        return False
    if not _confirm_search(eng):
        _save_shot(eng, "confirm_failed")
        return False
    if not _wait_search_result(eng, flower, 10.0):
        _save_shot(eng, "result_timeout")
        return False

    res = read_search_result(eng, flower)
    eng.plant_search_result = res
    _save_shot(eng, "result")
    print(f"[种植] ===== 阶段1完成: found={res['found']} 结果数={len(res['results'])} =====")
    if not res["found"]:
        return False

    # ---------------- 阶段2: 种白色桃花 ----------------
    seed_exact = TARGET_COLOR + flower
    if seed_exact != "白色桃花":
        print(f"    [种植] 目前仅支持「白色桃花」, 目标={seed_exact!r}; 中止")
        return False
    detail_name = seed_exact + "花种"
    print(f"\n[种植] ===== 阶段2: {seed_exact} x{TARGET_COUNT} =====")

    base = read_panel_info(eng)
    eng.plant_panel_baseline = base
    if base["plantable_total"] is None or base["fertility_remaining"] is None:
        print("    [种植] 基线 a/d 未读到, 中止(不点种子)")
        return False

    # 精确点选网格块（带数量角标）
    grid = _find_grid_seed(eng, seed_exact)
    if grid is None:
        print(f"    [种植] 未找到带数量角标的精确块「{seed_exact}」, 中止; 不点其它变体")
        _save_shot(eng, "seed_not_found")
        return False
    name_block, badge = grid
    _save_shot(eng, "before_seed_click")
    eng.click_abs(int(name_block["center"][0]), int(name_block["center"][1]))
    time.sleep(1.2)
    _save_shot(eng, "quantity_dialog")

    # 数量窗口
    pair = _read_quantity_pair(eng, 8.0)
    if pair is None:
        print("    [种植] 数量窗口未就绪, 中止")
        return False
    if not _adjust_quantity_to_one(eng, pair):
        _save_shot(eng, "quantity_failed")
        return False
    if not _confirm_quantity(eng):
        _save_shot(eng, "quantity_confirm_failed")
        return False

    # 中间态: 已选=1 待随机；或数量确认已直接完成种植（实机可能）
    state = _wait_after_quantity(eng, base, 8.0)
    if state is None:
        _save_shot(eng, "selected_state_failed")
        return False
    mid, mode = state
    if mode == "planted":
        ok = _verify_after_plant(eng, base)
        _save_shot(eng, "after_plant")
        print(f"[种植] ===== 阶段2{'完成' if ok else '失败'}: {seed_exact} x{TARGET_COUNT} "
              f"(数量确认即完成种植) =====")
        return ok

    # 随机种植
    if not eng.click_text(["随机种植"], region_rel=PLANT_PANEL_REGION,
                          min_score=0.4, no_fallback=True):
        print("    [种植] 未找到「随机种植」, 中止")
        _save_shot(eng, "no_random_plant")
        return False
    time.sleep(1.2)
    _save_shot(eng, "detail_dialog")

    # 二次确认: 白色桃花花种 = 1
    blocks = _wait_detail_window(eng, detail_name, 10.0)
    if blocks is None:
        _save_shot(eng, "detail_timeout")
        return False
    if not _verify_detail(eng, blocks, detail_name):
        print("    [种植] 详情核对不符 -> 关闭窗口(右上角X), 不确认")
        _save_shot(eng, "detail_mismatch")
        _close_detail_window(eng, blocks, detail_name)
        return False
    if not _confirm_detail(eng):
        _save_shot(eng, "detail_confirm_failed")
        return False
    if not _wait_detail_closed(eng, detail_name, 8.0):
        _save_shot(eng, "detail_not_closed")
        return False

    # 回读: d-1, 当前肥力-2, c=0
    ok = _verify_after_plant(eng, base)
    _save_shot(eng, "after_plant")
    print(f"[种植] ===== 阶段2{'完成' if ok else '失败'}: "
          f"{seed_exact} x{TARGET_COUNT} 消耗 {TARGET_COST} 肥力 =====")
    return ok


# ---------------- 花朵收获 ----------------

def _wait_panel_or_open(eng) -> bool:
    """面板已开(左侧有「照料」)则复用；否则点「一键种植」打开。"""
    if eng.locate(["照料"], region_rel=HARVEST_LEFT_NAV_REGION,
                  need_refine=False, log_miss=False):
        print("    [收获] 种植面板已打开")
        return True
    if not eng.click_text(["一键种植"], region_rel=PLANT_ENTRY_REGION,
                          min_score=0.4, no_fallback=True):
        print("    [收获] 未找到「一键种植」, 无法进入面板")
        return False
    time.sleep(2.0)
    return True


def _click_left_nav(eng, text: str) -> bool:
    if not eng.click_text([text], region_rel=HARVEST_LEFT_NAV_REGION,
                          min_score=0.4, no_fallback=True):
        print(f"    [收获] 左侧未找到「{text}」")
        return False
    time.sleep(1.5)
    return True


def _read_harvest_tabs(eng):
    """读取照料页顶部「可收获(x)」「可授粉(y)」。返回 (x, y, texts)。

    实机 2026-11-17: 标签带裁片 2x 会把 5 个标签粘成一块并误读; 全图 OCR 能逐块读准,
    故走全图后按标签带中心过滤(不裁片)。
    """
    w, h = eng.screen_w or 1, eng.screen_h or 1
    x1, y1, x2, y2 = HARVEST_TAB_REGION
    blocks = [b for b in eng.ocr_blocks(None)
              if x1 * w <= b["center"][0] <= x2 * w
              and y1 * h <= b["center"][1] <= y2 * h]
    texts = _texts(blocks)
    joined = " ".join(texts)

    def _parse(label):
        m = re.search(label + r"\s*[（(]\s*(\d+)\s*[)）]", joined)
        if m:
            return int(m.group(1))
        for t in texts:
            m = re.search(label + r"\s*[（(]\s*(\d+)\s*[)）]", t)
            if m:
                return int(m.group(1))
        return None

    x, y = _parse("可收获"), _parse("可授粉")
    print(f"    [收获] 照料页: 可收获={x if x is not None else '?'} "
          f"可授粉={y if y is not None else '?'} 标签={texts[:10]}")
    return x, y, texts


def _wait_care_tabs(eng, timeout=6.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if stop_requested():
            return None
        x, y, texts = _read_harvest_tabs(eng)
        if x is not None:
            return x, y, texts
        time.sleep(1.0)
    print("    [收获] 照料页「可收获(x)」未读到")
    return None


def _wait_pollinate_page(eng, timeout=6.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if stop_requested():
            return False
        blocks = eng.ocr_blocks(None)
        if any("选择花粉颜色" in str(b.get("text", "")) for b in blocks):
            print(f"    [收获] 授粉页就绪({time.time() - t0:.1f}s)")
            return True
        time.sleep(1.0)
    print("    [收获] 授粉页就绪超时")
    return False


def _read_pollinate_page(eng):
    blocks = _fine_blocks(eng, HARVEST_POLLEN_REGION, 2)
    print(f"    [收获] 授粉页左侧实读: {_texts(blocks)[:20]}")
    return blocks


def _close_plant_panel(eng) -> bool:
    """关闭种植面板（走 close_dialog 通用出口, 点后复核面板特征是否消失）。"""
    print("    [收获] 关闭种植面板")
    eng.close_dialog()
    time.sleep(1.5)
    blocks = eng.ocr_blocks(None)
    still = any(("照料" in str(b.get("text", ""))
                 or "可收获" in str(b.get("text", ""))) for b in blocks)
    if still:
        print("    [收获] 面板关闭未确认, 仍见 照料/可收获")
        return False
    print("    [收获] 面板已关闭")
    return True


def _wait_harvest_result(eng, timeout=8.0):
    """点「一键收花」后的结果: ('reward'|'no_harvest'|'unknown', blocks) 或 None。

    实机 2026-11-17: 已有已授粉花朵时, 可收获(x)>0 而可授粉(y)=0, 点一键收花会弹
    「提示 / 花园中目前没有能收获的花朵啦！ / 确定」——按无花可收处理, 点确定关闭, 不算失败。
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        if stop_requested():
            return None
        blocks = eng.ocr_blocks(None)
        joined = " ".join(str(b.get("text", "")) for b in blocks)
        if ("没有能收获的花朵" in joined or "没有可收获" in joined
                or "不能收获" in joined or "无法收获" in joined):
            print(f"    [收获] 失败提示弹窗出现({time.time() - t0:.1f}s): 无可收花")
            return "no_harvest", blocks
        if any(k in joined for k in ("获得", "奖励", "恭喜")):
            print(f"    [收获] 奖励弹窗出现({time.time() - t0:.1f}s)")
            return "reward", blocks
        if "提示" in joined and "确定" in joined:
            print(f"    [收获] 未知提示弹窗({time.time() - t0:.1f}s)")
            return "unknown", blocks
        time.sleep(1.0)
    print("    [收获] 收花后无弹窗")
    return None


def _close_no_harvest_popup(eng) -> bool:
    """关闭「没有能收获的花朵」失败提示（点确定/确认, 点后复核文案消失）。"""
    for text in ("确定", "确认"):
        if eng.click_text([text], region_rel=REWARD_REGION, min_score=0.3,
                          no_fallback=True):
            time.sleep(1.2)
            break
        if _click_text_fine(eng, text, REWARD_REGION):
            time.sleep(1.2)
            break
    else:
        print("    [收获] 失败提示弹窗未找到「确定/确认」")
        eng.close_dialog()
        time.sleep(1.2)
        return False
    joined = " ".join(str(b.get("text", "")) for b in eng.ocr_blocks(None))
    if "没有能收获的花朵" in joined:
        print("    [收获] 失败提示弹窗仍在")
        return False
    print("    [收获] 失败提示弹窗已关闭")
    return True


def _close_reward_popup(eng) -> bool:
    for text in ("确定", "点击任意处关闭"):
        if eng.click_text([text], region_rel=REWARD_REGION, min_score=0.3,
                          no_fallback=True):
            time.sleep(1.2)
            return True
        if _click_text_fine(eng, text, REWARD_REGION):
            time.sleep(1.2)
            return True
    print("    [收获] 奖励弹窗无「确定/点击任意处关闭」, 回退 close_dialog")
    eng.close_dialog()
    time.sleep(1.2)
    return True


def run_plant_harvest(eng) -> bool:
    """花朵收获：照料页读可收获(x) → x=0 关面板；x>0 查可授粉(y) → y=0 收花并关弹窗。"""
    print("\n[收获] ===== 花朵收获 =====")
    if stop_requested():
        return False
    if not _wait_panel_or_open(eng):
        return False

    # 1. 照料子界面
    if not _click_left_nav(eng, "照料"):
        return False
    got = _wait_care_tabs(eng, 6.0)
    if got is None:
        _save_shot(eng, "harvest_care_failed")
        return False
    x, y, _ = got

    # 2. x=0: 跳过并关面板
    if x == 0:
        print("    [收获] 可收获=0, 跳过收花")
        _save_shot(eng, "harvest_zero")
        _close_plant_panel(eng)
        return True

    # 3. 授粉子界面
    if not _click_left_nav(eng, "授粉"):
        return False
    if not _wait_pollinate_page(eng, 6.0):
        _save_shot(eng, "harvest_pollinate_timeout")
        return False
    _read_pollinate_page(eng)
    _save_shot(eng, "harvest_pollinate")

    # 4-5. 有待授粉 -> 不收花（用户规则：无待授粉才收花）
    if y is None:
        print("    [收获] 可授粉计数未读到 -> 保守判定有待授粉, 跳过收花")
        _close_plant_panel(eng)
        return True
    if y > 0:
        print(f"    [收获] 可授粉={y} > 0, 跳过收花")
        _close_plant_panel(eng)
        return True

    # 收花
    if not eng.click_text(["一键收花", "收花"], region_rel=HARVEST_BTN_REGION,
                          min_score=0.4, no_fallback=True):
        print("    [收获] 未找到「一键收花」")
        _save_shot(eng, "harvest_btn_missing")
        _close_plant_panel(eng)
        return False
    time.sleep(1.2)
    _save_shot(eng, "harvest_reward")
    result = _wait_harvest_result(eng, 8.0)
    if result is None:
        _save_shot(eng, "harvest_no_reward")
        print("    [收获] 收花后无奖励/失败弹窗, 结果不明")
        return False
    kind, blocks = result
    if kind == "no_harvest":
        _save_shot(eng, "harvest_no_harvest_popup")
        _close_no_harvest_popup(eng)
        print("[收获] ===== 无可收花, 已关闭提示; 本轮结束 =====")
        return True
    if kind == "unknown":
        _save_shot(eng, "harvest_unknown_popup")
        print("    [收获] 未知提示弹窗, 不盲点; 本轮结束")
        return False

    _close_reward_popup(eng)

    # 诊断: 回照料页读 x 是否减少
    if _click_left_nav(eng, "照料"):
        after = _wait_care_tabs(eng, 4.0)
        if after:
            x2, _, _ = after
            print(f"    [收获] 收花后诊断: 可收获 {x}->{x2}")
    print("[收获] ===== 花朵收获完成 =====")
    return True
