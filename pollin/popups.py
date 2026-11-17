# -*- coding: utf-8 -*-
"""pollin 弹窗处理：无花粉提示框 / 半透明奖励弹窗 / 弹层遮挡脱困。

Stage 5（2026-11-17）自单文件 pollin.py 拆出，函数体与注释原样保留。
依赖方向：primitives → 本模块；navigation/list_panel/collect 可依赖本模块。
"""
from __future__ import annotations

import time

from core.ports import EnginePort
from ocr_engine import stop_requested

from .constants import NO_POLLEN_CONFIRM_REGION, NO_POLLEN_KWS
from .primitives import has, has_social


def no_pollen_popup(eng: EnginePort, img=None) -> bool:
    """当前画面是否为「没有花粉」提示框(带「确定」)。

    2026-11-16 实机: 好友花园点「采粉」后弹出「提示 / 很抱款, 这人花园里没有花粉可以采哦 / 确定」。
    旧判据只认「抱歉」, 而 OCR 实测读成「很抱款」→ 漏判；改用「没有花粉」作为主判据。
    必须同时有「确定」，避免把聊天/活动横幅里的「花粉」误当弹窗。
    """
    img = img if img is not None else eng.screenshot()
    if img is None:
        return False
    if not has(eng, "确定", img=img, min_score=0.3, region_rel=NO_POLLEN_CONFIRM_REGION):
        return False
    return any(has(eng, k, img=img, min_score=0.3) for k in NO_POLLEN_KWS)


def dismiss_no_pollen_popup(eng: EnginePort, img=None, tries=2) -> bool:
    """点「确定」关闭「没有花粉」提示框。True=确认已不在屏/本就无此弹窗。"""
    for i in range(max(1, int(tries))):
        img = img if i == 0 and img is not None else eng.screenshot()
        if not no_pollen_popup(eng, img):
            return True
        print(f"    [采集] 无花粉提示 -> 点「确定」(第{i + 1}次)")
        eng.click_text(["确定"], exact=True, region_rel=NO_POLLEN_CONFIRM_REGION,
                       min_score=0.4, no_fallback=True)
        time.sleep(1.0)
    return not no_pollen_popup(eng)


def dismiss_reward_popup(eng: EnginePort, img=None, tries=2):
    """关闭半透明奖励弹窗(点弹窗 = 点任意处关闭)。True=确认已不在屏 / 本就无弹窗。

    2026-10-20 D13(主 agent): 判定/关闭/上报统一走引擎 `reward_dialog` —— 原先这里有一份独立实现,
      全项目因此存在 5 套不同写法。现保留本函数只为不动既有调用点(escape_overlay / 采粉收尾)。
    ! 语义差异: 旧版"本就无弹窗"直接 True。本函数是**守卫**不是"领取成功判定", 故未见弹窗也算成功
      (quiet=True 抑制"未见到"日志), 最终以"弹窗是否仍在屏"为准 —— 与旧返回值一致。
    ! 关闭优先级: 引擎原语**先点标题「恭喜获得」**(落在弹窗内, 无穿透风险), 标题读不到才点页脚
      「点击任意处关闭」; 页脚贴近底栏, 弹窗若已消失会**点击穿透**到底层 UI(flow_social 2026-10-05 实测
      曾误开「我的背包」)。
    """
    eng.reward_dialog({"wait": 0.0, "tries": tries, "required": False,
                       "quiet": True, "name": "奖励弹窗(采粉守卫)"})
    return not eng.has_reward_popup()


def escape_overlay(eng: EnginePort, tries=2):
    """兜底: 花园判据 HIT 但底栏「社交」不可读 -> 判为有**半透明弹层**遮挡, 清掉弹层后重试。

    返回 True=底栏「社交」已可读。

    ⚠ 主 agent 修订(里程碑 91): 原实现为 `eng.click_abs(0.5*w, 0.22*h)` —— 即**写死相对坐标盲点
      画面空白处**, 违反用户 2026-10-04 硬规则 6(任何点击必须先经 OCR/模板匹配取得**实时**坐标;
      该规则原文明确涵盖相对坐标), 且与原 REPORT §8「未硬编码任何游戏坐标」的自我声明不符。
      现改为**合规原语链**(全部为既有机制, 本函数不再自带任何坐标):
        ① `dismiss_reward_popup` —— OCR 定位弹窗文字(标题优先/页脚兜底)后点**该文字自身**的实时坐标;
        ② 仍不可读时退 `eng.close_dialog()` —— 引擎既有机制(模板/锚点/corner 定位), 非本函数写死。
      语义与原意一致(清掉遮挡再重试), 但不再有盲点击。

    ⚠ 主 agent 修复 Bug②(里程碑 93): 第②步原为**全类型** `eng.close_dialog()`, 会遍历整个注册表,
      其中条目 7 `corner_pink_small`(专为「在线礼包界面」设计, 模板 `close_online_small.png` 仅 17×21)
      在**好友花园画面**上误命中 (1097,111)(2026-10-16 日志 L1184/L1196 `选中 …(corner_pink_small)`),
      该点落在花园横幅上 -> **把「在线礼包」面板误打开**, 进而触发 ensure_home 未识别场景分支 12 次空转
      ≈4.5min 直至采粉类别中止(Bug③)。改为 `only_types=["anchor_color"]`:
      **锚点档必须 OCR 读到面板标题才动作** —— 花园画面无「跳转页签/提示/在线礼包」标题时**零动作**
      (注册表条目 3 的 `_note` 有 2026-09-30 实测: 该锚点在 家园/户外主界面/好友列表 全部 miss),
      有面板时则能真关(同轮 energy 一次锚点关闭即关掉 (1105,97), 实证有效)。
      读不到标题 -> 不做任何点击, **如实返回 False** 交上层(诚实失败, 不伪装成功)。
    """
    for i in range(1, tries + 1):
        if stop_requested():
            return False
        if has_social(eng) is not None:
            return True
        print(f"  [弹窗] 花园底栏「社交」不可读, 判为半透明弹层遮挡 -> 清弹层(第{i}次)")
        dismiss_reward_popup(eng)          # ① OCR 定位弹窗文字后点其自身坐标(合规)
        if i < tries:
            # ② 仅锚点档(须读到面板标题才动作) —— 防跨场景误点。
            # P1-B(2026-10-27): 末轮不再做锚点探测+复查 —— 其结果只能被紧随的终判消费, 无 settle 时间的
            # 探测纯属白花; 非末轮保留(决定是否需要锚点清面板)。
            if has_social(eng) is None:
                eng.close_dialog(only_types=["anchor_color"])
            # P1-A(2026-10-27): 非末轮等待 1.0->3.0s —— 10-24 轮 17 次清弹层的实际生效机制是
            # 「等遮挡物消散」(codex-20261025 分析 §4.2); 1s 不够, 3s 与既有重试节奏一致; 末轮不空等直接交回上层。
            time.sleep(3.0)
    ok = has_social(eng) is not None
    if not ok:
        print("  [弹窗] 底栏「社交」仍不可读, 如实报出(交上层 leave_friend_list/ensure_home 兜底)")
    return ok
