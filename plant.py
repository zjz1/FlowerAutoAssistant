# -*- coding: utf-8 -*-
"""种植模块：种植花朵（桃花系）+ 花朵收获。

阶段0「确保在自己家园」在 flow_plant.json；本模块负责：
  种植：一键种植 → 采集天气/肥力/已选 → 按 plant_flower_type 搜索基础花名
        → 精确点选目标颜色变体 → 数量1 → 随机种植 → 详情确认 → 回读 → 关面板归位；
  收获：照料页可收获/可授粉判定 → 无待授粉才一键收花 → 关奖励弹窗 → 关面板归位。

区域常量均为相对坐标（0~1），只限定 OCR/点击判据，点击仍取实时命中坐标。
通用截图/精识原语在 ui_ops.py（2026-11-17 P0 重构）。
"""
from __future__ import annotations
from core.ports import EnginePort

import re
import json
import subprocess
import time
from dataclasses import dataclass

from ocr_engine import ADB_ADDRESS, ADB_PATH, stop_requested
from ocr_engine._constants import PLANT_PRESETS_PATH
from ui_ops import (IME_OK_REGION, close_reward_popup,
                    click_text_fine as _click_text_fine,
                    fine_blocks as _fine_blocks, save_shot as _save_shot,
                    texts as _texts)

# ---- 区域（相对坐标；实机标定后收紧） ----
PLANT_ENTRY_REGION = [0.70, 0.88, 1.0, 1.0]       # 自己家园底栏「一键种植」带
PLANT_PANEL_REGION = [0.02, 0.02, 0.98, 0.98]     # 种植页整体（点击判据范围）
PLANT_STATUS_REGION = [0.35, 0.10, 0.75, 0.15]    # 天气 / 肥力值 a/b（实机标定 2026-11-16）
PLANT_SELECTED_REGION = [0.16, 0.82, 0.35, 0.91]  # 当前已选 c/d（实机标定 2026-11-16）
PLANT_SEARCH_DIALOG_REGION = [0.30, 0.30, 0.75, 0.70]  # 关键字输入框/确定
PLANT_SEED_RESULT_REGION = [0.27, 0.15, 0.95, 0.82]    # 筛选后的种子列表（实机标定 2026-11-16）

PANEL_READY_KWS = ("请输入关键字", "肥力值", "当前已选")
WEATHER_KWS = ("晴", "雨", "阴", "雪")
NUM_PAIR_RE = re.compile(r"(\d+)\s*[/／]\s*(\d+)")
NUM_RE = re.compile(r"^\s*(\d+)\s*$")

# 花种名称 -> 数量 的固定相对偏移（2026-11-16 实机标定: 白色桃花 名称(464,244) 数量(483,215)）
SEED_COUNT_DX_REL = 0.015
SEED_COUNT_DY_REL = -0.040
SEED_COUNT_RADIUS_REL = 0.02

# ---- 阶段2: 种植花朵（2026-11-17 用户确认；2026-11-20 数量/预设/缺种购买） ----
MAX_PLANT_COUNT = 360          # 单次种植数量上限（用户 2026-11-20 定值）
MAX_BUY_BATCH = 99             # 园艺店单次购买上限（超出分批）
DEFAULT_SEED = "白色桃花"
COLOR_PREFIX_RE = re.compile(r"^(白色|粉色|绿色|黄色|紫色|蓝色|红色|黑色|橙色|彩色)")

_PRESETS_CACHE: dict | None = None


def load_presets() -> dict:
    """读取 data/plant_presets.json（花名→颜色→种子）。

    缺失/损坏/字段非法一律抛 ValueError（带可操作说明），由调用方如实失败，
    不做“猜一个种子”的回退。缓存一次；`reload_presets()` 供测试/热更新。
    """
    global _PRESETS_CACHE
    if _PRESETS_CACHE is not None:
        return _PRESETS_CACHE
    try:
        data = json.loads(PLANT_PRESETS_PATH.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"种子数据库读取失败({PLANT_PRESETS_PATH}): {e}") from e
    flowers = data.get("flowers") if isinstance(data, dict) else None
    if not isinstance(flowers, list) or not flowers:
        raise ValueError("种子数据库缺少 flowers 列表")
    lib: dict[str, dict] = {}
    for fl in flowers:
        if not isinstance(fl, dict):
            raise ValueError(f"种子数据库花名项非法: {fl!r}")
        fname = str(fl.get("name") or "").strip()
        colors = fl.get("colors")
        if not fname or not isinstance(colors, list) or not colors:
            raise ValueError(f"种子数据库花名/颜色不完整: {fl!r}")
        for c in colors:
            if not isinstance(c, dict):
                raise ValueError(f"种子数据库颜色项非法: {fname}/{c!r}")
            cname = str(c.get("name") or "").strip()
            seed = str(c.get("seed") or "").strip()
            if not cname or not seed:
                raise ValueError(f"种子数据库颜色项缺少 name/seed: {fname}/{c!r}")
            cost = c.get("cost", 2)
            if isinstance(cost, bool) or not isinstance(cost, int) or not 0 <= cost <= 2:
                raise ValueError(f"{seed} 的 cost 须为 0~2 整数, 实为 {cost!r}")
            if seed in lib:
                raise ValueError(f"种子重复: {seed}")
            lib[seed] = {
                "flower": fname, "color": cname, "seed": seed,
                "detail": str(c.get("detail") or (seed + "花种")),
                "buy_name": str(c.get("buy_name") or (seed + "种子")),
                "rare": bool(c.get("rare", False)),
                "cost": cost,
                "cost_source": c.get("cost_source", "default"),
            }
    _PRESETS_CACHE = {"raw": data, "seeds": lib, "flowers": flowers}
    return _PRESETS_CACHE


def reload_presets() -> None:
    """清缓存（测试用）。"""
    global _PRESETS_CACHE
    _PRESETS_CACHE = None


def seed_library() -> dict[str, dict]:
    return dict(load_presets()["seeds"])


def supported_seeds() -> str:
    return "、".join(load_presets()["seeds"])


def _normalize_seed_input(raw: str) -> str:
    """去掉「种子/花种」后缀；空值按默认桃花处理。"""
    s = str(raw or "").strip()
    for suffix in ("种子", "花种"):
        if s.endswith(suffix) and len(s) > len(suffix):
            s = s[:-len(suffix)]
    return s


def resolve_seed_name(raw: str) -> tuple[bool, str, "str | None"]:
    """校验种子名是否在库（set_config / UI / 引擎共用）。

    返回 (ok, 错误文案, 规范化种子名)。接受「桃花」别名与「…种子/花种」后缀；
    未带颜色的其它花名按「白色+花名」查找（与旧行为一致）；查不到不猜。
    """
    try:
        lib = load_presets()["seeds"]
    except ValueError as e:  # noqa: BLE001
        return False, str(e), None
    name = _normalize_seed_input(raw)
    if not name:
        name = "桃花"
    if name == "桃花":
        if DEFAULT_SEED in lib:
            return True, "", DEFAULT_SEED
        return False, f"种子库缺少默认种子 {DEFAULT_SEED}", None
    if name in lib:
        return True, "", name
    if COLOR_PREFIX_RE.match(name):
        return False, f"「{raw}」不在种子库；可选：{supported_seeds()}", None
    candidate = "白色" + name
    if candidate in lib:
        return True, "", candidate
    return False, f"「{raw}」不在种子库；可选：{supported_seeds()}", None


@dataclass(frozen=True)
class PlantTarget:
    """一次种植的目标花种（解析结果，供阶段函数共享）。"""
    seed: str                 # 网格块精确名称，如「粉色桃花」
    detail: str               # 详情窗口名称，如「粉色桃花花种」
    search_kw: str            # 搜索框输入的基础花名，如「桃花」
    cost: int | None          # 肥力消耗（0~2；数据库未标注时为 None）
    rare: bool = False        # 稀有种子（不可购买）
    buy_name: str = ""        # 园艺店搜索/详情名（缺省 seed+种子）


@dataclass(frozen=True)
class PlantOptions:
    """一次种植的用户选项（由配置/步骤传入）。"""
    count_mode: str = "fixed"     # fixed / auto
    count: int = 1                # fixed 模式数量（1~360）
    buy_missing: bool = False     # fixed 模式缺种购买
    auto_buy: bool = False        # auto 模式也自动购买


def compute_target_count(count_mode: str, count: int, *, n: int, plantable: int,
                         fertility: int, cost: "int | None", auto_buy: bool = False,
                         rare: bool = False, max_count: int = MAX_PLANT_COUNT) -> int:
    """计算本次种植数量 Q（纯函数，供单测）。

    fixed: Q = clamp(count, 1, max_count)
    auto : Q = min(plantable, max_count, fertility//cost)；cost=0/None 不设肥力上限；
           未开自动购买（或稀有种子）时再加 n 上限。
    返回 0 表示当前无法种植（无槽位/无肥力/无种子）。
    """
    if str(count_mode) != "auto":
        try:
            return max(1, min(int(max_count), int(count)))
        except (TypeError, ValueError):
            return 1
    q = max(0, min(int(plantable or 0), int(max_count)))
    if cost is not None and int(cost) > 0:
        q = min(q, max(0, int(fertility or 0) // int(cost)))
    if not auto_buy or rare:
        q = min(q, max(0, int(n or 0)))
    return max(0, int(q))



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


# ---------------- 基础（通用截图/精识在 ui_ops.py） ----------------

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


def read_panel_info(eng: EnginePort, img=None) -> dict:
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


def _wait_panel_ready(eng: EnginePort, timeout=10.0) -> bool:
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


def _wait_dialog(eng: EnginePort, timeout=12.0) -> bool:
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


def _adb_input_text(eng: EnginePort, text: str) -> bool:
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


def _input_flower(eng: EnginePort, flower: str) -> bool:
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


def _confirm_search(eng: EnginePort) -> bool:
    for reg in (IME_OK_REGION, PLANT_SEARCH_DIALOG_REGION):
        if _click_text_fine(eng, "确定", reg):
            time.sleep(1.5)
            return True
    print("    [种植] 未找到「确定」(键盘/对话框区域)")
    return False


def _wait_search_result(eng: EnginePort, flower: str, timeout=10.0) -> bool:
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


def read_search_result(eng: EnginePort, flower: str) -> dict:
    """读取筛选后的全部花种名称/是否搜出/数量；数量按固定相对偏移取最近数字块。"""
    img = eng.screenshot()
    blocks = eng.ocr_blocks(img, PLANT_SEED_RESULT_REGION)
    names = [b for b in blocks if flower in str(b.get("text", ""))]
    w, h = eng.screen_w or 1, eng.screen_h or 1

    results = []
    for name in names:
        nx, ny = name["center"]
        best = _badge_for(eng, name, blocks)
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


# ---------------- 阶段2: 种植目标花种 ----------------

def _resolve_seed(flower: str) -> PlantTarget | None:
    """配置值 -> PlantTarget（数据库校验；不支持/库损坏返回 None 并打印原因）。"""
    ok, msg, seed = resolve_seed_name(flower)
    if not ok or not seed:
        print(f"    [种植] {msg or '种子名无法解析'}")
        return None
    info = load_presets()["seeds"][seed]
    return PlantTarget(seed=seed, detail=info["detail"], search_kw=info["flower"],
                       cost=info["cost"], rare=info["rare"], buy_name=info["buy_name"])


def resolve_target(flower: str) -> PlantTarget | None:
    """公开解析入口（步骤处理器 / 测试用）。"""
    return _resolve_seed(flower)


def _nearest_badge(blocks, nx, ny, w, h, radius_rel=SEED_COUNT_RADIUS_REL):
    """按名称->数量固定偏移找最近的纯数字角标块。返回 (count, block) 或 None。"""
    expected = (nx + SEED_COUNT_DX_REL * w, ny + SEED_COUNT_DY_REL * h)
    best = None
    best_d = 1e9
    for b in blocks:
        m = NUM_RE.match(str(b.get("text", "")))
        if not m:
            continue
        cx, cy = b["center"]
        d = abs(cx - expected[0]) + abs(cy - expected[1])
        if d > radius_rel * (w + h):
            continue
        if d < best_d:
            best_d = d
            best = (int(m.group(1)), b)
    return best


def _badge_for(eng: EnginePort, name_block, blocks):
    """取名称块对应的数量角标；全图 OCR 读不到时对该块邻近区域做 2x 精识重试。

    实机 2026-11-16: 绿色桃花角标为小字号, 全图 OCR 常漏读; 2x 裁片可读。
    """
    w, h = eng.screen_w or 1, eng.screen_h or 1
    nx, ny = name_block["center"]
    best = _nearest_badge(blocks, nx, ny, w, h)
    if best:
        return best
    x1 = max(0.0, (nx - 0.06 * w) / w)
    y1 = max(0.0, (ny - 0.065 * h) / h)
    x2 = min(1.0, (nx + 0.09 * w) / w)
    y2 = min(1.0, (ny + 0.035 * h) / h)
    fine = _fine_blocks(eng, [x1, y1, x2, y2], 2)
    return _nearest_badge(fine, nx, ny, w, h, radius_rel=0.03)


def _find_grid_seed(eng: EnginePort, seed_exact: str):
    """在种子结果区找精确同名的网格块（带数量角标），返回 (name_block, count) 或 None。

    用户要求: 页面至少两个「种子名称」文字, 必须精准 OCR; 选“带数量角标的种子网格块”。
    其余同名块(如选中列表/提示)因找不到固定偏移的数量角标而被排除。
    """
    blocks = eng.ocr_blocks(None, PLANT_SEED_RESULT_REGION)
    cands = [b for b in blocks if str(b.get("text", "")).strip() == seed_exact]
    print(f"    [种植] 精确匹配「{seed_exact}」: {len(cands)} 块 "
          f"{[b['center'] for b in cands]}")
    for name in cands:
        best = _badge_for(eng, name, blocks)
        if best:
            print(f"    [种植] 选中网格块 center={name['center']} 角标={best[0]} "
                  f"(角标块 {best[1]['center']})")
            return name, best[0]
    return None


def _read_quantity_pair(eng: EnginePort, timeout=8.0):
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


def _quantity_button(eng: EnginePort, pair, sign: int):
    """定位 +/- 图标；OCR 不到时按 m/n 块左右下角相对推算（不写死屏幕坐标）。"""
    kws = ["-", "－", "−"] if sign < 0 else ["+", "＋", "﹢"]
    pt = eng.locate(kws, region_rel=QUANTITY_DIALOG_REGION, min_score=0.2,
                    need_refine=False, log_miss=False)
    if pt is not None:
        return int(pt.x), int(pt.y)
    _, _, block = pair
    w, h = eng.screen_w or 1, eng.screen_h or 1
    x = int(block["center"][0] + (-0.13 if sign < 0 else 0.13) * w)
    y = int(block["center"][1] + 0.06 * h)
    print(f"    [种植] 「{'+' if sign > 0 else '-'}」图标未识别, 按 m/n 块相对点击 ({x},{y})")
    return x, y


def _adjust_quantity(eng: EnginePort, pair, target: int) -> bool:
    """把将种个数调到 target（1~n）。± 图标点击 + 每轮复读校验，最多 3 轮。"""
    m, n, block = pair
    if n < 1:
        print(f"    [种植] 该种子数量为 {n}, 不能种植")
        return False
    target = max(1, min(int(target), int(n)))
    if m == target:
        print(f"    [种植] 数量已为 {target}, 无需调整")
        return True
    for round_no in range(1, 4):
        m, n, block = pair
        delta = target - m
        if delta == 0:
            print(f"    [种植] 数量已调到 {target}")
            return True
        sign = 1 if delta > 0 else -1
        clicks = min(abs(delta), MAX_PLANT_COUNT)
        x, y = _quantity_button(eng, pair, sign)
        print(f"    [种植] 数量 {m} -> {target}: 点击「{'+' if sign > 0 else '-'}」x{clicks} "
              f"(第{round_no}轮)")
        for i in range(clicks):
            if stop_requested():
                return False
            eng.click_abs(x, y)
            time.sleep(0.12)
            if (i + 1) % 25 == 0:
                time.sleep(0.2)          # 每 25 次给 UI 一点消化时间
        time.sleep(0.4)
        pair = _read_quantity_pair(eng, 3.0)
        if pair is None:
            print("    [种植] 调整数量后 m/n 丢失")
            return False
        if pair[0] == target:
            print(f"    [种植] 数量已调到 {target}")
            return True
        print(f"    [种植] 本轮后 m={pair[0]}（目标 {target}），继续校准")
    print(f"    [种植] 数量调整失败, 仍为 {pair[0]}")
    return False


def _confirm_quantity(eng: EnginePort) -> bool:
    for reg in (QUANTITY_DIALOG_REGION,):
        if eng.click_text(["确认"], region_rel=reg, no_fallback=True):
            time.sleep(1.2)
            return True
        if _click_text_fine(eng, "确认", reg):
            time.sleep(1.2)
            return True
    print("    [种植] 数量窗口未找到「确认」")
    return False


def _wait_after_quantity(eng: EnginePort, base: dict, q: int, cost=None, timeout=8.0):
    """数量确认后的状态。返回 (info, mode): mode='selected'=已选 q 待随机;
    mode='planted'=确认后已直接完成种植(实机可能出现)。

    cost=None（该花种肥力消耗未标定）时跳过肥力数值判据, 只按已选/可种判断。
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        if stop_requested():
            return None
        info = read_panel_info(eng)
        a_ok = (cost is None
                or (info["fertility_remaining"] is not None
                    and base["fertility_remaining"] is not None
                    and info["fertility_remaining"] == base["fertility_remaining"] - cost * q))
        if a_ok and info["selected_count"] == q:
            print(f"    [种植] 数量确认后: 已选={q}, 待随机种植")
            return info, "selected"
        if (a_ok and info["selected_count"] == 0
                and info["plantable_total"] is not None
                and base["plantable_total"] is not None
                and info["plantable_total"] == base["plantable_total"] - q):
            print(f"    [种植] 数量确认后: 已直接完成种植(可种-{q})")
            return info, "planted"
        time.sleep(1.0)
    print("    [种植] 数量确认后状态不符(已选/肥力/可种), 不继续")
    return None


def _wait_detail_window(eng: EnginePort, detail_name: str, timeout=10.0):
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


def _verify_detail(eng: EnginePort, blocks, detail_name: str, q: int) -> bool:
    """详情窗口: 目标行「白色桃花花种」+ 数量=q；出现计划外花种行则拒绝确认。

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
        print(f"    [种植] 详情核对: {detail_name} 已选择={got}/{total} (计划 {q})")
        return got == q and total >= q

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
    print(f"    [种植] 详情核对(同行): {detail_name} = {got} (计划 {q})")
    return got == q


def _close_detail_window(eng: EnginePort, blocks, detail_name: str) -> bool:
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


def _confirm_detail(eng: EnginePort) -> bool:
    for text in ("确认种植", "确认"):
        if eng.click_text([text], region_rel=DETAIL_DIALOG_REGION, no_fallback=True):
            time.sleep(1.5)
            return True
        if _click_text_fine(eng, text, DETAIL_DIALOG_REGION):
            time.sleep(1.5)
            return True
    print("    [种植] 详情窗口未找到「确认种植/确认」")
    return False


def _wait_detail_closed(eng: EnginePort, detail_name: str, timeout=8.0) -> bool:
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


def _verify_after_plant(eng: EnginePort, base: dict, cost, q: int) -> bool:
    """回读校验: 可种 q、已选归零；肥力消耗已标定时另校验 a/b 同步 -cost*q。

    cost=None（未标定）时只校验可种/已选, 肥力变化如实打印不参与判定。
    """
    after = read_panel_info(eng)
    eng.plant_panel_after = after
    d_ok = (after["plantable_total"] is not None
            and base["plantable_total"] is not None
            and after["plantable_total"] == base["plantable_total"] - q)
    if cost is not None:
        a_ok = (after["fertility_remaining"] is not None
                and base["fertility_remaining"] is not None
                and after["fertility_remaining"] == base["fertility_remaining"] - cost * q)
        b_ok = (after["fertility_total"] is not None
                and base["fertility_total"] is not None
                and after["fertility_total"] == base["fertility_total"] - cost * q)
    else:
        a_ok = b_ok = True
    c_ok = after["selected_count"] == 0
    print(f"    [种植] 种植前后: 可种 {base['plantable_total']}->{after['plantable_total']} "
          f"(期望-{q}) 肥力 {base['fertility_remaining']}/{base['fertility_total']}"
          f"->{after['fertility_remaining']}/{after['fertility_total']} "
          f"({'期望各-' + str(cost * q) if cost is not None else '消耗未标定, 仅记录'}) "
          f"已选={after['selected_count']}")
    ok = d_ok and a_ok and b_ok and c_ok
    print(f"    [种植] 种植判据: 可种{'OK' if d_ok else 'FAIL'} "
          f"肥力a{'OK' if a_ok else 'FAIL'} 肥力b{'OK' if b_ok else 'FAIL'} "
          f"已选{'OK' if c_ok else 'FAIL'}")
    return ok


# ---------------- 主入口 ----------------

def run_plant_flower(eng: EnginePort, flower: str = "桃花",
                     options: PlantOptions | None = None) -> bool:
    """种植花朵: 解析目标 -> 阶段1搜索 -> 阶段2选种/数量/缺种购买/随机种植/回读校验。

    options 由配置/步骤传入（数量模式、数量、缺种购买、auto 自动购买）。
    结束（无论成功/失败）若种植面板仍打开, 统一关闭面板归位, 便于模块串联。
    """
    opts = options or PlantOptions()
    state = {"opened": False}
    try:
        return _run_plant_flower(eng, flower, state, opts)
    finally:
        if state["opened"]:
            _close_plant_panel(eng)


def _plan_header(target: PlantTarget, opts: PlantOptions) -> None:
    """运行日志头部：目标/数量模式/购买开关（稀有种子强制关闭购买）。"""
    if target.rare:
        print(f"[种植] 目标={target.seed}（稀有）| 数量={opts.count_mode} | "
              f"自动购买=强制关闭（稀有种子不可购买）")
        return
    if opts.count_mode == "auto":
        print(f"[种植] 目标={target.seed} | 数量=auto | "
              f"自动购买={'开' if opts.auto_buy else '关'} | 上限=肥力/槽位/库存")
        return
    print(f"[种植] 目标={target.seed} | 数量=fixed({opts.count}) | "
          f"缺种购买={'开' if opts.buy_missing else '关'}")


def _run_plant_flower(eng: EnginePort, flower: str, state: dict, options: PlantOptions) -> bool:
    target = _resolve_seed(flower)
    if target is None:
        return False
    print(f"\n[种植] ===== 种植花朵: {target.seed} (搜索词={target.search_kw}) =====")
    _plan_header(target, options)
    if stop_requested():
        return False
    if not _open_plant_panel(eng, state):
        return False
    if not _search_target(eng, target):
        return False
    return _plant_target(eng, target, options, state)


def _open_plant_panel(eng: EnginePort, state: dict) -> bool:
    """点「一键种植」并等待种植页就绪；点击一发出即标记 opened，便于 finally 收尾。"""
    if not eng.click_text(["一键种植"], region_rel=PLANT_ENTRY_REGION,
                          min_score=0.4, no_fallback=True):
        print("    [种植] 未找到「一键种植」, 中止")
        _save_shot(eng, "no_entry")
        return False
    state["opened"] = True
    _save_shot(eng, "entry_clicked")
    if not _wait_panel_ready(eng, 10.0):
        _save_shot(eng, "panel_timeout")
        return False
    return True


def _search_target(eng: EnginePort, target: PlantTarget) -> bool:
    """阶段1：采集页面信息 → 搜索基础花名 → 确认 → 读取筛选结果。"""
    img = _save_shot(eng, "panel")
    info = read_panel_info(eng, img)
    eng.plant_panel_info = info

    if not eng.click_text(["请输入关键字"], region_rel=PLANT_PANEL_REGION,
                          min_score=0.35, no_fallback=True):
        print("    [种植] 未找到「请输入关键字」, 中止")
        _save_shot(eng, "no_search_box")
        return False
    if not _wait_dialog(eng, 12.0):
        _save_shot(eng, "dialog_timeout")
        return False
    _save_shot(eng, "dialog")
    if not _input_flower(eng, target.search_kw):
        _save_shot(eng, "input_failed")
        return False
    if not _confirm_search(eng):
        _save_shot(eng, "confirm_failed")
        return False
    if not _wait_search_result(eng, target.search_kw, 10.0):
        _save_shot(eng, "result_timeout")
        return False

    res = read_search_result(eng, target.search_kw)
    eng.plant_search_result = res
    _save_shot(eng, "result")
    print(f"[种植] ===== 阶段1完成: found={res['found']} 结果数={len(res['results'])} =====")
    return res["found"]


def _buy_shortfall(eng: EnginePort, target: PlantTarget, need: int) -> int:
    """按批购买缺少的种子（单批 ≤ MAX_BUY_BATCH），返回已买到的数量。"""
    from buy_seed import run_buy_seed

    name = target.buy_name or (target.seed + "种子")
    bought = 0
    remaining = max(0, int(need))
    print(f"    [种植] 园艺店购买「{name}」x{remaining}（单批≤{MAX_BUY_BATCH}）")
    while remaining > 0 and not stop_requested():
        batch = min(MAX_BUY_BATCH, remaining)
        if not run_buy_seed(eng, name, count=batch):
            print(f"    [种植] 购买失败（本批 {batch} 颗）")
            break
        bought += batch
        remaining -= batch
    return bought


def _back_to_garden(eng: EnginePort) -> bool:
    """购买后从园艺店回到任意家园；失败如实返回 False。"""
    from navigation import ensure_any_garden

    for _ in range(2):
        if ensure_any_garden(eng):
            return True
        print("    [种植] 尝试关闭园艺店面板后回家园")
        try:
            eng.close_dialog()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.2)
    return ensure_any_garden(eng)


def _plant_target(eng: EnginePort, target: PlantTarget, options: PlantOptions,
                  state: dict) -> bool:
    """阶段2：基线 → 计算数量 Q → 缺种购买 → 选种/数量 → 随机种植/回读。"""
    base = read_panel_info(eng)
    eng.plant_panel_baseline = base
    if base["plantable_total"] is None or base["fertility_remaining"] is None:
        print("    [种植] 基线 a/d 未读到, 中止(不点种子)")
        return False

    grid = _find_grid_seed(eng, target.seed)
    if grid is None:
        print(f"    [种植] 未找到带数量角标的精确块「{target.seed}」, 中止; 不点其它变体")
        _save_shot(eng, "seed_not_found")
        return False
    n = int(grid[1])

    q = compute_target_count(options.count_mode, options.count,
                             n=n, plantable=base["plantable_total"],
                             fertility=base["fertility_remaining"], cost=target.cost,
                             auto_buy=options.auto_buy, rare=target.rare)
    buy_wanted = ((options.count_mode == "fixed" and options.buy_missing)
                  or (options.count_mode == "auto" and options.auto_buy))
    if target.rare:
        buy_wanted = False
    print(f"    [种植] 库存={n} 可种={base['plantable_total']} "
          f"肥力={base['fertility_remaining']} cost={target.cost} → 计划={q}"
          + ("（缺种购买已开启）" if buy_wanted and q > n else ""))

    if q < 1:
        if options.count_mode == "auto":
            print("    [种植] auto 计划为 0（无种子/无槽位/无肥力），跳过本次种植")
            return True
        print("    [种植] 固定数量计划为 0, 无法种植")
        return False

    if q > n and buy_wanted:
        need = q - n
        print(f"    [种植] 缺 {need} 颗 → 关闭种植面板, 前往园艺店")
        state["opened"] = False
        _close_plant_panel(eng)
        bought = _buy_shortfall(eng, target, need)
        print(f"    [种植] 购买结束: {bought}/{need} 颗")
        if not _back_to_garden(eng):
            print("    [种植] 购买后未回到家园, 中止")
            return False
        if not _open_plant_panel(eng, state):
            return False
        base = read_panel_info(eng)
        eng.plant_panel_baseline = base
        if base["plantable_total"] is None or base["fertility_remaining"] is None:
            print("    [种植] 购买后基线 a/d 未读到, 中止")
            return False
        grid = _find_grid_seed(eng, target.seed)
        if grid is None:
            print(f"    [种植] 购买后未找到「{target.seed}」, 中止")
            return False
        n2 = int(grid[1])
        print(f"    [种植] 购买后库存={n2}（计划 {q}）")
        q = min(q, n2)
        if q < 1:
            print("    [种植] 购买后仍无种子, 中止")
            return False
    elif q > n:
        print(f"    [种植] 种子不足（计划 {q} / 现有 {n}），按现有 {n} 种植")
        q = n

    mode = _choose_quantity(eng, target, base, q)
    if mode is None:
        return False
    if mode == "planted":
        ok = _verify_after_plant(eng, base, target.cost, q)
        _save_shot(eng, "after_plant")
        print(f"[种植] ===== 阶段2{'完成' if ok else '失败'}: {target.seed} x{q} "
              f"(数量确认即完成种植) =====")
        return ok

    if not _random_plant_and_confirm(eng, target, q):
        return False

    ok = _verify_after_plant(eng, base, target.cost, q)
    _save_shot(eng, "after_plant")
    cost_desc = f"消耗 {target.cost * q} 肥力" if target.cost is not None else "肥力消耗未标定"
    print(f"[种植] ===== 阶段2{'完成' if ok else '失败'}: {target.seed} x{q} {cost_desc} =====")
    return ok


def _choose_quantity(eng: EnginePort, target: PlantTarget, base: dict, q: int) -> str | None:
    """精确点选网格块 → 数量窗口调到 q → 确认；返回 selected/planted 或 None。"""
    grid = _find_grid_seed(eng, target.seed)
    if grid is None:
        print(f"    [种植] 未找到带数量角标的精确块「{target.seed}」, 中止; 不点其它变体")
        _save_shot(eng, "seed_not_found")
        return None
    name_block, badge = grid
    _save_shot(eng, "before_seed_click")
    eng.click_abs(int(name_block["center"][0]), int(name_block["center"][1]))
    time.sleep(1.2)
    _save_shot(eng, "quantity_dialog")

    pair = _read_quantity_pair(eng, 8.0)
    if pair is None:
        print("    [种植] 数量窗口未就绪, 中止")
        return None
    if pair[1] < q:
        print(f"    [种植] 数量窗口库存 {pair[1]} < 计划 {q}, 按现有库存种植")
        q = int(pair[1])
    if q < 1:
        print("    [种植] 数量窗口库存为 0, 中止")
        return None
    if not _adjust_quantity(eng, pair, q):
        _save_shot(eng, "quantity_failed")
        return None
    if not _confirm_quantity(eng):
        _save_shot(eng, "quantity_confirm_failed")
        return None

    state_mid = _wait_after_quantity(eng, base, q, target.cost, 8.0)
    if state_mid is None:
        _save_shot(eng, "selected_state_failed")
        return None
    return state_mid[1]


def _random_plant_and_confirm(eng: EnginePort, target: PlantTarget, q: int) -> bool:
    """点随机种植 → 等详情窗口 → 核对名称/数量 → 确认种植 → 等窗口关闭。"""
    if not eng.click_text(["随机种植"], region_rel=PLANT_PANEL_REGION,
                          min_score=0.4, no_fallback=True):
        print("    [种植] 未找到「随机种植」, 中止")
        _save_shot(eng, "no_random_plant")
        return False
    time.sleep(1.2)
    _save_shot(eng, "detail_dialog")

    blocks = _wait_detail_window(eng, target.detail, 10.0)
    if blocks is None:
        _save_shot(eng, "detail_timeout")
        return False
    if not _verify_detail(eng, blocks, target.detail, q):
        print("    [种植] 详情核对不符 -> 关闭窗口(右上角X), 不确认")
        _save_shot(eng, "detail_mismatch")
        _close_detail_window(eng, blocks, target.detail)
        return False
    if not _confirm_detail(eng):
        _save_shot(eng, "detail_confirm_failed")
        return False
    if not _wait_detail_closed(eng, target.detail, 8.0):
        _save_shot(eng, "detail_not_closed")
        return False
    return True


# ---------------- 花朵收获 ----------------

def _wait_panel_or_open(eng: EnginePort) -> bool:
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


def _click_left_nav(eng: EnginePort, text: str) -> bool:
    if not eng.click_text([text], region_rel=HARVEST_LEFT_NAV_REGION,
                          min_score=0.4, no_fallback=True):
        print(f"    [收获] 左侧未找到「{text}」")
        return False
    time.sleep(1.5)
    return True


def _read_harvest_tabs(eng: EnginePort):
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


def _wait_care_tabs(eng: EnginePort, timeout=6.0):
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


def _wait_pollinate_page(eng: EnginePort, timeout=6.0) -> bool:
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


def _read_pollinate_page(eng: EnginePort):
    blocks = _fine_blocks(eng, HARVEST_POLLEN_REGION, 2)
    print(f"    [收获] 授粉页左侧实读: {_texts(blocks)[:20]}")
    return blocks


def _close_plant_panel(eng: EnginePort) -> bool:
    """关闭种植面板（走 close_dialog 通用出口, 点后复核面板特征是否消失）。

    面板未打开时直接返回 True, 避免在其它界面误操作。
    """
    blocks = eng.ocr_blocks(None)
    still = any(("照料" in str(b.get("text", ""))
                 or "可收获" in str(b.get("text", ""))
                 or "当前已选" in str(b.get("text", ""))) for b in blocks)
    if not still:
        print("    [种植面板] 面板未打开, 无需关闭")
        return True
    print("    [种植面板] 关闭种植面板")
    eng.close_dialog()
    time.sleep(1.5)
    blocks = eng.ocr_blocks(None)
    still = any(("照料" in str(b.get("text", ""))
                 or "可收获" in str(b.get("text", ""))
                 or "当前已选" in str(b.get("text", ""))) for b in blocks)
    if still:
        print("    [种植面板] 面板关闭未确认, 仍见 照料/可收获/当前已选")
        return False
    print("    [种植面板] 面板已关闭")
    return True


def _wait_harvest_result(eng: EnginePort, timeout=8.0):
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


def _close_no_harvest_popup(eng: EnginePort) -> bool:
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


def _close_reward_popup(eng: EnginePort) -> bool:
    return close_reward_popup(eng, ("确定", "点击任意处关闭"),
                              REWARD_REGION, tag="收获", fine_fallback=True)


def run_plant_harvest(eng: EnginePort) -> bool:
    """花朵收获：照料页读可收获(x) → x=0 关面板；x>0 查可授粉(y) → y=0 收花并关弹窗。

    结束（无论成功/失败）若种植面板仍打开, 统一关闭面板归位。
    """
    state = {"opened": False}
    try:
        return _run_plant_harvest(eng, state)
    finally:
        if state["opened"]:
            _close_plant_panel(eng)


def _run_plant_harvest(eng: EnginePort, state) -> bool:
    print("\n[收获] ===== 花朵收获 =====")
    if stop_requested():
        return False
    if not _wait_panel_or_open(eng):
        return False
    state["opened"] = True

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
