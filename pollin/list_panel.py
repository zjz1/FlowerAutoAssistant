# -*- coding: utf-8 -*-
"""pollin 好友列表面板：开/关列表、切页签、翻页、可采粉标记扫描。

Stage 5（2026-11-17）自单文件 pollin.py 拆出，函数体与注释原样保留。
依赖方向：navigation + popups + primitives → 本模块；collect/runner 依赖本模块。
"""
from __future__ import annotations

import time

from core.ports import EnginePort
from ocr_engine import stop_requested

from .constants import (DLG_CLOSE_REGION, DLG_CLOSE_TH, DLG_CONFIRM_REGION,
                        GREEN_REGION, GREEN_TH, IME_OK_REGION, JUMP_REGION,
                        JUMP_TH, MERGE_Y_REL, NUM_BAR_REGION, NUM_BAR_TH,
                        PAGE_CROP, PAGE_REGION, ROW_STEP_REL, ROW_TOP_REL,
                        SOCIAL_BTN_BAND, SOCIAL_FRIEND_REGION, TAB_REGION,
                        TPL_DLG_CLOSE, TPL_GREEN, TPL_JUMP, TPL_NUM_BAR)
from .navigation import ensure_home, in_garden, in_list, social_usable
from .popups import (dismiss_no_pollen_popup, dismiss_reward_popup,
                     escape_overlay, no_pollen_popup)
from .primitives import (adb_key, adb_text, click_btn_fine, has, has_social,
                         wait_screen_change, wait_until)


def _panel_friend_pt(eng: EnginePort, img=None):
    """「社交」面板内「好友」按钮位置; 面板未开则 None。
    region 限定 + exact, 避免误命中「添加好友」「删除好友」「好友设置」。
    2026-10-24(P2-5③): 只加**成功率统计**(粗识 / 精识兜底), 日志逐条保留 ——
      用户裁定: 粗 OCR 频繁 MISS 是「粗 OCR 技术待改进」的提醒, 不得静默; 先量化再谈优化。
    2026-10-25(codex-20261025-2): **调用时机收窄** —— 仅保留「点『社交』之后」的面板确认路径。
      20261024 日志实测精识兜底 0/16, 且 16 次粗识 MISS 全部发生在「点『社交』前」的入口探测
      (面板必然未开, 结构性不可能命中, 每次白跑一次区域 OCR + 一次滤色精识)。
      「面板是否已开」由调用方改用 in_list 同帧判定(帧缓存复用, 零额外 OCR)。
    F02(batch-05, 2026-11-14): 统计读写走公有面 eng.get_ocr_stat()(原为引擎下划线私有属性
      跨界直读, 现走公有读法; 返回引擎活引用, 本函数的纯观测自增语义不变)。
    """
    st = eng.get_ocr_stat()
    st["friend_coarse_n"] = st.get("friend_coarse_n", 0) + 1
    pt = eng.locate(["好友"], img=img, exact=True,
                    region_rel=SOCIAL_FRIEND_REGION, min_score=0.4)
    if pt is not None:
        st["friend_coarse_hit"] = st.get("friend_coarse_hit", 0) + 1
        return pt
    st["friend_fine_n"] = st.get("friend_fine_n", 0) + 1
    pt = eng.locate_fine(["好友"], SOCIAL_FRIEND_REGION,
                         min_score=0.3, img=img, exact=True)
    if pt is not None:
        st["friend_fine_hit"] = st.get("friend_fine_hit", 0) + 1
    return pt


def open_friend_list(eng: EnginePort):
    """开好友列表。起点可以是**自己家园主界面**, 也可以是**好友花园** —— 两处底部都有「社交」
    (用户 2026-10-05 确认: 好友家园与自己家园**按钮一致**, 无需回自己家园再开列表),
    采完粉不必先回自己家园, 直接在好友花园里开列表去下一个目标。

    ⚠ 点「社交」只弹出**面板**(不是列表), 必须再点面板内的「好友」才进列表;
      早期版本点完「社交」直接等列表出现, 每次都白等 60s。
    ⚠ 2026-10-05 日志「社交面板 超时」×26 的根因 = 好友花园内「社交」被**临时遮挡**
      (底部 NPC 对话气泡@(602,679) / 中央活动横幅), OCR 暂时读不到 —— 靠点-验-重试自然恢复
      (气泡会轮走), 不做「先回家再开」绕路(用户裁定: 按钮一致, 绕路不合理)。
      面板等待已按定值规则 15s→5s, 空转代价同步压缩。
    """
    # 2026-10-25(codex-20261025-2): 面板「可能还开着」标志 —— 仅当上一轮明确见到面板/确认过
    # 点击生效/点过「好友」而列表未开(常见: 列表内完成动作后弹层残留)时为 True, 供入口
    # _panel_friend_pt 恢复探测; 全新进入(采粉/回家后)为 False, 跳过结构性必然 MISS 的探测。
    panel_may_open = False
    for attempt in range(1, 4):
        if stop_requested():
            return False
        img = eng.screenshot()
        # 2026-11-16: 「没有花粉」提示框带「确定」但没有右上角✕，会吞掉后续「社交」点击；
        # 在花园/列表判定前先清掉，避免 open_friend_list 重试 3 次全被弹窗吞掉。
        if no_pollen_popup(eng, img):
            print("  [列表] 存在「没有花粉」提示框 -> 先点「确定」")
            dismiss_no_pollen_popup(eng, img)
            img = eng.screenshot()
        # 2026-10-14 防御(2026-10-21 修正判据): 上一环节(采粉/浇水/矿洞…)可能残留半透明奖励弹窗。
        # ⚠ 原判据 `not has(社交)` 是**反的**: 弹窗半透明时「社交」仍然可读, 但点击会被弹窗吞掉
        #   (用户 2026-10-20 指出)。于是最需要清弹窗的场景反而永远不进 escape —— 日志里大量
        #   「点「社交」后未见社交面板(点击被吞)」而 `[弹窗] 社交不可读` 只有寥寥几次, 即此。
        # 现改为**先判是否存在弹窗**: 有 -> 关掉再继续; 没有再走旧「不可读」兜底(面板/其它遮挡)。
        if in_garden(eng, img, quiet=True):
            if eng.has_reward_popup(img):
                print("  [列表] 花园画面存在半透明奖励弹窗(社交可读但点击会被吞) -> 先关闭")
                dismiss_reward_popup(eng, img)
                img = eng.screenshot()
            elif has_social(eng, img=img) is None:
                # 兜底: 底栏小裁片确实读不到「社交」(彩底压分/横幅类遮挡) -> 清弹层链
                escape_overlay(eng)
                img = eng.screenshot()
        if in_list(eng, img, quiet=True):
            print("  [列表] 已在好友列表")
            eng.set_scene("好友列表")
            return True
        # 2026-10-25(codex-20261025-2): 入口探测按 panel_may_open 门控 —— 只有上一轮
        # 确认「社交面板可能还开着」才调 _panel_friend_pt; 20261024 日志的 16 次粗识 MISS
        # 全部发生在「从采粉/回家后首次进入」(面板必然未开, L173~L1005), 每次白跑
        # 一次区域 OCR + 滤色精识。列表真开着已由上方 in_list 覆盖, 不受影响。
        pt = _panel_friend_pt(eng, img) if panel_may_open else None
        if pt is None:
            # 2026-10-24(P2-5④): 重试循环内场景判定静默, 由下面的「在XX点社交 / 场景未知」行保留结论
            in_g = in_garden(eng, img, quiet=True)
            if social_usable(eng, img, quiet=True) or in_g:
                # 自己家园/好友花园按钮一致(用户 2026-10-05), 统一处理:
                # 点-验-重试(2026-10-04 引入): 「社交」点击常被吞/被气泡遮挡 —— 点击后必须在
                # 5s 内确认**社交面板出现**, 未出现立即重点(至多 3 次); 面板等待 15s→5s(定值规则)。
                # ⚠ 2026-10-10 判据修正(officeAce, 依据 codeart 10-10 18:10 运行日志):
                #   原判据只有 `wait_screen_change` = **整屏**帧差(96×54 灰度, 阈值 0.05); 而「社交」
                #   弹出的是**小面板**, 整屏帧差天然测不到它 —— 日志实证: 连报 3 次「点击被吞」之后
                #   `[等待] 社交面板 命中 (3s)` 面板其实早已弹出, 随后成功点「好友」(422,518) 进列表。
                #   危害: ①每次误报都让 wait_screen_change 空等满 5s; ②多余的再点击可能把刚弹出的
                #   面板又关掉。故在帧差之外**追加一次正向复核**(面板内「好友」按钮出现即视为生效),
                #   并把循环末尾那次 5s 面板等待去掉(每轮点击已自带确认, 避免重复空等)。
                where = "花园(自己/好友)" if in_g else "户外主界面"
                print(f"  [列表] 第{attempt}次 在{where} 点「社交」")
                for i in range(1, 4):
                    if stop_requested():
                        return False
                    pre = eng.screenshot()
                    # D18①: 社交钮实测恒在 rel(0.331,0.949)(10-22/10-24/10-27 三份日志同位),
                    # 常住带过滤聊天气泡同字文本(10-27 实锤气泡 (0.441,0.906) 被误点开聊天面板)。
                    pt_btn = click_btn_fine(eng, ["社交"], img=pre, expect_region=SOCIAL_BTN_BAND)
                    if pt_btn is None:
                        print("  [列表] 「社交」常规+滤色精识均未命中, 未产生点击, 重试")
                        continue
                    if wait_screen_change(eng, pre, desc=f"点「社交」(第{i}次)", timeout=5):
                        panel_may_open = True
                        break
                    # 2026-10-25 时机收窄后唯一调用点: 点「社交」之后的面板确认(面板此时才可能存在)。
                    if _panel_friend_pt(eng) is not None:
                        panel_may_open = True
                        print("  [列表] 点「社交」后整屏帧差未达阈值, 但社交面板(「好友」钮)已出现 -> 视为点击生效")
                        break
                    print("  [列表] 点「社交」后未见社交面板(点击被吞), 重试")
                pt = _panel_friend_pt(eng)
                if pt is not None:
                    panel_may_open = True
            else:
                print(f"  [列表] 第{attempt}次: 场景未知, 先回自己家园")
                ensure_home(eng)
                continue
        if pt is not None:
            print(f"  [列表] 点社交面板内「好友」({pt.x},{pt.y})")
            eng.click_abs(pt.x, pt.y)
            if wait_until(eng, lambda: in_list(eng, quiet=True), 5, desc="好友列表出现"):
                eng.set_scene("好友列表")
                return True
            # 2026-10-25(codex-20261025-2): 点过「好友」而列表未确认, 下一轮入口可能需要
            # 经面板恢复(而非再点「社交」把面板关掉), 保持 panel_may_open=True。
        # 兜底: 列表已在(只是标记未识别)时, 点右侧竖排页签「好友」
        pt = eng.locate(["好友"], exact=True, region_rel=TAB_REGION, min_score=0.4)
        if pt is not None:
            print(f"  [列表] 点右侧页签「好友」({pt.x},{pt.y})")
            eng.click_abs(pt.x, pt.y)
            if wait_until(eng, lambda: in_list(eng, quiet=True), 5, desc="好友列表出现"):
                eng.set_scene("好友列表")
                return True
    print("  [列表] 打开好友列表失败")
    return False


def switch_tab(eng: EnginePort, name):
    """切换右侧竖排页签(密友/好友)。含文字按钮 -> 走本体 OCR 定位。"""
    img = eng.screenshot()
    pt = eng.locate([name], img=img, exact=True, region_rel=TAB_REGION, min_score=0.4)
    if pt is None:
        print(f"  [页签] 未找到「{name}」")
        return False
    print(f"  [页签] 点「{name}」({pt.x},{pt.y})")
    eng.click_abs(pt.x, pt.y)
    time.sleep(1.5)
    return True


def read_page(eng: EnginePort, img=None):
    """读列表底部页码 "x/N"。

    ⚠ 本体 OCR 在「粉底白字」页码胶囊上会把 9 误读成 6(实测 9/9 -> 6/6), 故裁剪胶囊后
    用二值化重识别。2026-10-03 加固(协作区 zcode-20261003-4, 真样本实测):
    ① 固定阈值 200 在变暗画面(模态框压暗整屏, 实测 crop 灰度仅 60~119)下整片全黑、OCR 必空
      → 改 **Otsu 自适应阈值**, 二值/反相两种极性都试(白字黑底/黑字白底);
    ② 裁剪框放宽(见 PAGE_CROP), 修复多位数页码被截断;
    ③ 仍失败才回退本体 `parse_fraction_at`。
    实测: 变暗 720p「2/9」(旧逻辑 OCR 必空)与干净 1080p「1/1」均直接命中。
    """
    import re
    import cv2
    img = img if img is not None else eng.screenshot()
    if img is not None:
        h, w = img.shape[:2]
        x1, y1, x2, y2 = (int(PAGE_CROP[0] * w), int(PAGE_CROP[1] * h),
                          int(PAGE_CROP[2] * w), int(PAGE_CROP[3] * h))
        crop = img[y1:y2, x1:x2]
        if crop.size:
            big = cv2.resize(crop, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
            _, binimg = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            _, bininv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            for bin_ in (binimg, bininv, gray):  # 二值 → 反相 → 纯灰度, 首个解析成功即返回
                # O0(2026-10-21): 走引擎直调统计 —— 原 `ocr_image` 完全不计时, 导致 OCR 总账被低估
                for b in eng.ocr_direct(cv2.cvtColor(bin_, cv2.COLOR_GRAY2BGR), src="read_page"):
                    m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", b["text"].strip())
                    if m:
                        return (int(m[1]), int(m[2]))
    return eng.parse_fraction_at(PAGE_REGION, img=img, tol=80)


def read_total(eng: EnginePort):
    img = eng.screenshot()
    fr = read_page(eng, img)
    if fr:
        return fr[1]
    if not open_jump_dialog(eng):
        return None
    n = eng.parse_count_at([0.5, 0.52], tol=150)
    pt = eng.locate_template(TPL_DLG_CLOSE, img=eng.screenshot(),
                             threshold=DLG_CLOSE_TH, region_rel=DLG_CLOSE_REGION)
    if pt is not None:
        print(f"  [翻页] 点对话框✕ ({pt.x},{pt.y}) 关掉对话框, 不改页码")
        eng.click_abs(pt.x, pt.y)
    else:
        print("  [翻页] 对话框✕模板未命中(dlg_close), 不盲点")
    time.sleep(1.5)
    return n


def open_jump_dialog(eng: EnginePort):
    img = eng.screenshot()
    if has(eng, "跳转页签", img=img):
        return True
    pt = eng.locate_template(TPL_JUMP, img=img, threshold=JUMP_TH, region_rel=JUMP_REGION)
    if pt is None:
        print("  [翻页] 「跳」按钮模板未命中")
        return False
    print(f"  [翻页] 点「跳」按钮 ({pt.x},{pt.y})")
    eng.click_abs(pt.x, pt.y)
    return wait_until(eng, lambda: has(eng, "跳转页签"), 5, desc="跳转页签对话框")


def _jump_once(eng: EnginePort, n):
    """一次翻页尝试: 点「跳」-> 点数字条弹数字键盘 -> 清空 -> 输入 n -> 确认。"""
    if not open_jump_dialog(eng):
        return False
    pt = eng.locate_template(TPL_NUM_BAR, img=eng.screenshot(),
                             threshold=NUM_BAR_TH, region_rel=NUM_BAR_REGION)
    if pt is None:
        print("  [翻页] 数字条模板未命中(num_bar)")
        return False
    print(f"  [翻页] 模板命中数字条 ({pt.x},{pt.y}) 唤起数字键盘")
    eng.click_abs(pt.x, pt.y)
    time.sleep(2.5)
    adb_key(123, eng)                        # 光标移到行尾
    for _ in range(5):
        adb_key(67, eng)                     # 退格清空(最大两位数, 5 次足够)
    adb_text(str(n), eng)
    time.sleep(1.5)
    print("  [翻页] 点键盘「确定」(OCR, 系统键盘有该文字)")
    eng.click_text(["确定"], region_rel=IME_OK_REGION, min_score=0.4)
    time.sleep(1.5)
    pt = eng.locate(["确认"], region_rel=DLG_CONFIRM_REGION, min_score=0.4)
    if pt is None:
        print("  [翻页] 对话框内未见「确认」")
        return False
    print(f"  [翻页] 点对话框「确认」({pt.x},{pt.y})")
    eng.click_abs(pt.x, pt.y)
    return True


def goto_page(eng: EnginePort, n, tries=3):
    """翻到第 n 页。

    实测对话框「前往 第 [N] 页」的数字条**不是**文本框, 点它才弹数字键盘;
    输入走 adb keyevent/input text(本体暂无文本输入步骤, 机制同本体 back())。
    模拟器输入延迟/积压严重(可达数十秒), 故翻完必须**校验页码并重试**。
    """
    for i in range(1, tries + 1):
        if stop_requested():
            return False
        if (read_page(eng) or (0, 0))[0] == n:
            print(f"  [翻页] 已在第 {n} 页")
            return True
        print(f"  [翻页] 第{i}次尝试 -> 第{n}页")
        if not _jump_once(eng, n):
            continue
        if wait_until(eng, lambda: (read_page(eng) or (0, 0))[0] == n, 5, desc=f"第{n}页"):
            return True
    print(f"  [翻页] 重试 {tries} 次仍未到第 {n} 页")
    return False


def scan_marks(eng: EnginePort, img=None):
    """一次模板匹配取**全部**可采粉绿花标记, 返回 [(abs_x, abs_y)]。

    早期版本在此逐带(y 步进 0.03, 共约 30 次)调用 locate_template,
    而引擎每次调用都要做 4 尺度全图 matchTemplate, 一次扫描=120 次全图匹配;
    改用新增的 locate_template_all(一次匹配+跨尺度 NMS)后约 30 倍提速。
    返回结果仍按 y 聚类去重(相邻行同标记)。
    """
    img = img if img is not None else eng.screenshot()
    pts = eng.locate_template_all(TPL_GREEN, img=img, threshold=GREEN_TH,
                                  region_rel=GREEN_REGION, nms_gap_rel=0.05)
    hits = [(p.x, p.y) for p in pts]
    hits.sort(key=lambda p: p[1])
    thr = MERGE_Y_REL * img.shape[0]         # 去重阈值随当前屏高换算, 不写死像素
    merged = []
    for x, yy in hits:                       # 多尺度/NMS 后仍可能残留重复, 按 y 聚类去重
        if merged and abs(yy - merged[-1][1]) <= thr:
            continue
        merged.append((x, yy))
    return merged


def slot_of(eng: EnginePort, y):
    """按当前屏高把 abs y 换算为好友行槽位(分辨率无关)。"""
    return int(round((y / eng.screen_h - ROW_TOP_REL) / ROW_STEP_REL))


def _rescan_skip_failed(eng: EnginePort, failed_y):
    """底行补救段重扫: 跳过已失败标记附近(按 MERGE_Y_REL 聚类)的候选, 防假标记重试风暴。"""
    thr = MERGE_Y_REL * eng.screen_h
    return [m for m in scan_marks(eng)
            if not any(abs(fy - m[1]) <= thr for fy in failed_y)]
