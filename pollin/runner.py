# -*- coding: utf-8 -*-
"""pollin 编排与调试入口：单类别逐页采集 / 好友采粉闭环 / state|all CLI。

Stage 5（2026-11-17）自单文件 pollin.py 拆出，函数体与注释原样保留。
依赖方向：底层各模块 → 本模块（本模块不被其它子模块依赖）。
"""
from __future__ import annotations

import sys
import time

from core.ports import EnginePort
from ocr_engine import OCREngine, report_failure, stop_requested

from .collect import collect_one
from .constants import (CATEGORIES, ROW_STEP_REL, SAFE_SLOT_MAX,
                        SWIPE_MAX_PER_PAGE, SWIPE_MS, SWIPE_SETTLE_S, SWIPE_Y_REL)
from .list_panel import (_rescan_skip_failed, goto_page, open_friend_list,
                         read_page, read_total, scan_marks, slot_of, switch_tab)
from .navigation import ensure_home, in_garden, in_list, social_usable


def run_category(eng: EnginePort, cat, max_pages=30):
    """跑完一个类别(密友/好友): 逐页扫标记 -> 逐个采集 -> 收敛到本页无标记 -> 下一页。

    ⚠ 性能(2026-10-02): 旧版内层 `while True` 每采一个好友就重扫一次**全页模板**
      (第3页扫5次 / 第6页4次 / 第8页3次 … 单轮共 24 次页扫描, 相邻两次常隔 130~295s)。
      现改为**每页只扫一次**(`scan_marks`), 标记坐标在页内复用;
      进园失败/无粉/未确认的槽位记入 failed 跳过, 不整页重采。
    ⚠ 每轮动作前先确认「人在好友列表」: 采集失败时人可能还站在好友花园,
      此时翻页必然失败(花园里没有「跳」按钮), 必须先兜底回列表再继续。
    返回采到的次数; 打开列表失败返回 None。
    """
    print(f"\n=== 类别「{cat}」===")
    if not open_friend_list(eng):
        return None
    if not switch_tab(eng, cat):
        return None
    total = read_total(eng)
    if not total:
        print(f"  [{cat}] 读不到总页数, 按 1 页处理")
        total = 1
    print(f"  [{cat}] 总页数 {total}")

    collected, empty_cnt = 0, 0

    def back_to_list_page(page):
        """采集后回到好友列表并翻回第 page 页(采完人在好友花园)。返回 False=本页剩余标记放弃。"""
        if not in_list(eng):
            if not open_friend_list(eng):
                print(f"  [{cat}] 第{page}页 无法回到好友列表, 放弃本页剩余标记")
                return False
        switch_tab(eng, cat)
        if not goto_page(eng, page):
            print(f"  [{cat}] 第{page}页 翻页未确认, 放弃本页剩余标记")
            return False
        return True

    page_fails = 0   # 连续「无法回到好友列表」页数(2026-10-06: 上限 3, 防整类别空转 ——
                     # 10-06 日志 10 页 × 每页 3 尝试 ≈ 25 分钟颗粒无收)
    for page in range(1, min(total, max_pages) + 1):
        if stop_requested():
            print(f"  [{cat}] 收到停止请求, 中断")
            break
        if not in_list(eng):                  # 兜底: 不在列表就重开(含从好友花园回来)
            if not open_friend_list(eng):
                page_fails += 1
                print(f"  [{cat}] 第{page}页 无法回到好友列表, 跳过(连续第{page_fails}次)")
                if page_fails >= 3:
                    print(f"  [{cat}] 连续 3 页无法回到好友列表, 如实中止本类别"
                          f"(防整类别空转, 已采 {collected} 次)")
                    break
                continue
            page_fails = 0
            switch_tab(eng, cat)
        if not goto_page(eng, page):
            break
        marks = scan_marks(eng)               # 页顶扫描(补救段另有重扫, locate_template_all 单次匹配成本低)
        print(f"  [{cat}] 第{page}页 可采粉标记 {len(marks)} 个 {marks}")
        # 同一槽位可能有多个残留标记(跨尺度/NMS 去重后仍可能重复), 每槽位只取一个;
        # 底行(槽位5)是视口裁切死区, 不进常规采集(点 3 次×15s 必然全吞), 交页尾补救段
        cand, seen, n_bottom = [], set(), 0
        for x, y in sorted(marks, key=lambda p: p[1]):
            slot = slot_of(eng, y)
            if slot in seen:
                continue
            seen.add(slot)
            if slot > SAFE_SLOT_MAX:
                n_bottom += 1
                continue
            cand.append((x, y, slot))
        if n_bottom:
            print(f"  [{cat}] 第{page}页 底行死区标记 {n_bottom} 个, 常规采集跳过, 交页尾补救")
        failed = set()                        # 本页「进园失败/无粉/未确认」的槽位, 避免死循环
        for i, (x, y, slot) in enumerate(cand):
            if stop_requested():
                break
            if slot in failed:
                continue
            res = collect_one(eng, x, y)
            print(f"    [{cat}] 第{page}页 标记({x},{y}) 槽位{slot} 结果={res}")
            if res == "fail":
                # 进园失败(多为假标记: 绿花模板会误匹配底部好友的「绿色家园图标」本身)
                # 或点采粉未确认: 该槽位本页不再重采, 只跳过它继续看其它标记
                failed.add(slot)
            elif res == "empty":
                failed.add(slot)
                empty_cnt += 1
            else:
                collected += 1
            # 采完**不离开好友花园**: 若本页后面还有候选标记, 就地重开列表并翻回本页;
            # 没有后续候选就不做多余的一次「开列表+翻页」(旧版每轮都做, 白跑一趟)
            if any(s not in failed for _, _, s in cand[i + 1:]):
                if not back_to_list_page(page):
                    break
        # ---- 底行补救(2026-10-06 用户方案一): 常规候选采完后执行 ----
        # 底行好友在页码跳转视图里被列表视口裁切(角标可见、图标点击落空), 页码跳转无法
        # 改变其窗口内位置; 上滑一行把它带入安全区后重扫采集。采集后角标消失(已实证),
        # 重扫天然不重复; 位置一律以「最近一次重扫」为准, 不依赖页码视图模型。
        if not in_list(eng) and not back_to_list_page(page):
            continue                          # 回不了列表: 交给下一页顶部的兜底链(计 page_fails)
        page_swipes = 0
        remedy_failed_y = []                  # 补救段失败标记的 y(防假标记重试风暴)
        while not stop_requested() and page_swipes < SWIPE_MAX_PER_PAGE:
            fresh = _rescan_skip_failed(eng, remedy_failed_y)
            if not any(slot_of(eng, y) > SAFE_SLOT_MAX for _, y in fresh):
                break                         # 视口内无底行标记(或已采完/已失败) → 本页收尾
            page_swipes += 1
            print(f"  [{cat}] 第{page}页 底行补救 {page_swipes}/{SWIPE_MAX_PER_PAGE}: "
                  f"上滑一行(相对行高 {ROW_STEP_REL}; 手势参数非点击坐标, 规则6边界见 swipe_rel)")
            eng.swipe_rel(0.5, SWIPE_Y_REL, 0.5, SWIPE_Y_REL - ROW_STEP_REL, SWIPE_MS)
            time.sleep(SWIPE_SETTLE_S)
            fresh = _rescan_skip_failed(eng, remedy_failed_y)
            for x, y in sorted(fresh, key=lambda p: p[1]):
                if stop_requested():
                    break
                if slot_of(eng, y) > SAFE_SLOT_MAX:
                    continue                  # 仍在底行的留给下一轮滑动
                res = collect_one(eng, x, y)
                print(f"    [{cat}] 第{page}页 补救标记({x},{y}) 结果={res}")
                if res == "fail":
                    remedy_failed_y.append(y)
                elif res == "empty":
                    remedy_failed_y.append(y)
                    empty_cnt += 1
                else:
                    collected += 1
                if not back_to_list_page(page):
                    break
    print(f"  [{cat}] 完成: 采到 {collected} 次, 空花粉 {empty_cnt} 次")
    return collected


def run_friend_pollin(eng: EnginePort) -> dict:
    """好友采粉闭环入口。返回 {'密友': n, '好友': m, '_home_ok': bool}
    （打开列表失败该类别记 None）。"""
    print("[好友采粉] 开始闭环: 密友 + 好友 两类逐页采集, 无可采粉则回自己家园")
    ensure_home(eng)
    summary = {}
    for cat in CATEGORIES:
        summary[cat] = run_category(eng, cat)
        if stop_requested():
            break
    print(f"[好友采粉] 闭环结束: {summary}")
    # 2026-11-07: 收尾归位结果必须如实登记 —— 旧版把 ensure_home 的 False 直接丢弃, 模块仍记
    # 「完成」, 于是 energy/claim/daily 三个模块被同一个卡死画面连累空跑(日志 1180 行起)。
    home_ok = ensure_home(eng)
    print(f"[好友采粉] 回自己家园 -> {home_ok}")
    summary["_home_ok"] = home_ok
    if not home_ok:
        report_failure(getattr(eng, "_module", None) or "社交任务",
                       "好友采粉收尾未确认回到自己家园(后续模块可能被同一画面连累)")
    return summary


# ---------------- 独立调试入口 ----------------

def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "state"
    eng = OCREngine()
    assert eng.connect(), "连接失败"
    if stage == "state":
        img = eng.screenshot()
        print(f"  在列表={in_list(eng, img)} 社交可用={social_usable(eng, img)} 在花园={in_garden(eng, img)}")
        print(f"  页码={read_page(eng, img)} 标记={scan_marks(eng, img)}")
        return
    if stage == "all":
        run_friend_pollin(eng)
        return
    raise SystemExit(f"未知 stage {stage}（可用: state / all）")
