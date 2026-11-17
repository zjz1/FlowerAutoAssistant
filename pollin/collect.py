# -*- coding: utf-8 -*-
"""pollin 单个好友采集：进好友花园 -> 快捷操作 -> 一键采粉 -> 收菜单/关弹窗。

Stage 5（2026-11-17）自单文件 pollin.py 拆出，函数体与注释原样保留。
依赖方向：navigation + popups + primitives → 本模块；runner 依赖本模块。
"""
from __future__ import annotations

import os
import time

from core.ports import EnginePort
from ocr_engine import stop_requested

from .constants import BASE, BOTTOM_BAR_REGION, HOUSE_DX_REL, HOUSE_DY_REL
from .navigation import ensure_home, in_garden, in_list, wait_enter_garden
from .popups import (dismiss_no_pollen_popup, dismiss_reward_popup,
                     escape_overlay, no_pollen_popup)
from .primitives import click_btn_fine, frame_diff, has, wait_stable, wait_until


def collect_one(eng: EnginePort, x, y):
    """进好友家园 -> 快捷操作 -> 采粉。返回 ok / empty / fail。

    ⚠ 绿花是浮在家园图标**右上**的气泡角标(纯图形, 模板命中其中心), 本身不可点;
    真正可点的是它左下的「家园」图标, 故按固定相对偏移换算后再点。
    ⚠ **采完不离场**: 直接从好友花园开好友列表去下一个目标,
    只有整个类别收敛(无可采粉)时才由外层回自己家园。这样也避开了「离开→等回主界面」
    这条超时高发路径(实测 14 次采集里 12 次卡在这里)。
    """
    if not eng.screen_w or not eng.screen_h:      # 屏幕尺寸未知时偏移会算成 0
        eng.screenshot()
    hx = x + int(HOUSE_DX_REL * eng.screen_w)
    hy = y + int(HOUSE_DY_REL * eng.screen_h)
    print(f"  [采集] 点家园图标 ({hx},{hy}) (绿花角标 {x},{y})")

    # ⚠ 模拟器输入延迟/积压可达数十秒, 单次点击常被吞(实测真实流程多次 75s 超时,
    #   而 probe 脚本同判据 +19s 即成功) -> 进园判定改「点-等-重试」而非一次定生死。
    entered = False
    for i in range(1, 4):
        if stop_requested():
            return "fail"
        if in_garden(eng):                 # 上一轮点击可能此刻才落地
            entered = True
            break
        print(f"  [采集] 第{i}次点击家园图标")
        wait_stable(eng, 1.5)              # C3: 画面未稳定时点击易被系统丢弃
        eng.click_abs(hx, hy)
        # C1b: 点击被吞时(仍在好友列表)提前失败, 不再干等满 15s
        if wait_enter_garden(eng, 15, desc=f"进入好友花园(第{i}次)"):
            entered = True
            break
        time.sleep(2)                      # 输入队列延迟宽限: 点击可能刚落地
        if in_garden(eng):
            entered = True
            break
        img = eng.screenshot()
        if in_list(eng, img):
            print(f"    [采集] 第{i}次点击后仍在好友列表(点击被吞/未落地), 重试")
            continue
        # 未进园也未在列表 -> 点偏或误触: 存诊断画面并退出, 由外层重开列表
        import cv2
        diag = os.path.join(str(BASE / "debug"), "_enter_garden_fail.png")
        cv2.imwrite(diag, img)
        texts = [b["text"] for b in sorted(eng.ocr_direct(img, src="diag"),
                                           key=lambda b: b["score"], reverse=True)][:12]
        print(f"    [采集] 第{i}次点击后未进园也未在列表(可能点偏), 画面存 {diag}")
        print(f"    [采集] 画面文本: {texts}")
        ensure_home(eng)
        break
    if not entered:
        return "fail"
    # 已站到好友花园: 声明场景 —— 这里与「自己家园主界面」的「快捷操作/社交/离开」同名同位置,
    # 不区分场景的话均值复核会拿主界面的历史坐标来比, 无法发现点偏。
    eng.set_scene("好友花园")

    # 模拟器输入延迟/积压可达数十秒, 单次点击常被吞, 故「点-等-重试」而非一次定生死
    opened = False
    for i in range(1, 4):
        click_btn_fine(eng, ["快捷操作"])
        if wait_until(eng, lambda: has(eng, "采粉"), 5, desc=f"快捷操作菜单(第{i}次)"):
            opened = True
            break
    if not opened:
        return "fail"

    click_btn_fine(eng, ["采粉"])
    # 有粉: 静默成功(菜单收起); 无粉: 弹「很抱歉, 这人花园里没有花粉可以采哦」+确定。
    # ⚠ 不能用裸「花粉」判定 —— 世界频道聊天常含「花粉」会误判,
    #   故要求「抱歉」与「确定」同时出现才算无花粉弹窗。
    # ⚠ 性能(2026-10-02): 原固定轮询等 45s; 改为「首帧比对、变化即返回」+ 上限 20s ——
    #   菜单收起/弹窗弹出都会让画面显著变化, 变化后只做一次确认 OCR 即可判定。
    base = eng.screenshot()
    changed = wait_until(eng, lambda: frame_diff(base, eng.screenshot()) >= 0.02, 5,
                         desc="点采粉后画面变化", interval=0.5)
    if not changed:
        print("    [采集] 点采粉后 5s 画面无变化(点击可能被吞/被气泡遮挡), 本槽位跳过")
        return "fail"
    img = eng.screenshot()
    empty = no_pollen_popup(eng, img)
    if empty:
        dismiss_no_pollen_popup(eng, img)
    elif has(eng, "采粉", img=img):
        # 画面已变化但「一键采粉」菜单仍在(2026-10-04, 协作区 zcode-20261004):
        # 旧判据把它当"未确认失败"→ 当晚 7 槽位全 fail、采粉 0 收获。实机观察:
        # 「一键采粉」点击后菜单**不会自动关闭**, 菜单残留属正常态; 点采粉后画面已变化
        # 即采集生效(花粉动画/数值变化)。菜单残留≠失败 —— 判定放宽为成功,
        # 下方统一收菜单。(是否真采到以游戏内花粉数为准, 待实机确认)
        print("    [采集] 采集生效(画面已变化; 快捷菜单未自动关闭属正常), 继续收菜单")
    else:
        print("    [采集] 静默成功(有花粉)")

    # 收「快捷操作」菜单(否则挡住底栏「社交」): 改「底栏区域限定 + exact」定位 ——
    # 旧 click_text(["快捷操作"]) 会命中 OCR 合并块(如「快捷操作种植箱」)并取其中心, 该点可能
    # **越出屏幕**(2026-10-14 日志实测 (883,773), 屏高仅 720) -> 菜单没真正收起。
    img = eng.screenshot()
    if has(eng, "采粉", img=img):
        pt = eng.locate(["快捷操作"], img=img, exact=True,
                        region_rel=BOTTOM_BAR_REGION, min_score=0.5)
        if pt is not None:
            print(f"    [采集] 收「快捷操作」菜单 ({pt.x},{pt.y})")
            eng.click_abs(pt.x, pt.y)
            time.sleep(1.5)
    # 2026-10-14 修复: 采粉后会弹「点击任意处关闭」型半透明奖励弹窗, 必须在此关掉 ——
    # 该弹层半透明, 底层按钮仍可见 -> in_garden() 仍 HIT; 随后开列表走花园分支时
    # 「社交」被弹层遮挡, OCR 整词 MISS -> 归类中止(本轮日志: 采 1 次即中止)。
    dismiss_reward_popup(eng)
    if not has(eng, "社交", img=eng.screenshot(), min_score=0.5):
        escape_overlay(eng)
    return "empty" if empty else "ok"
