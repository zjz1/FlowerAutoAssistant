# -*- coding: utf-8 -*-
"""pollin 基础原语：存在性判断 / 轮询 / 帧差 / 按钮精识 / ADB 输入 / 证据落盘。

Stage 5（2026-11-17）自单文件 pollin.py 拆出，函数体与注释原样保留。
依赖方向：constants → 本模块；本模块不依赖导航/弹窗/采集层。
"""
from __future__ import annotations

import os
import subprocess
import time

from core.ports import EnginePort
from ocr_engine import ADB_ADDRESS, ADB_PATH, stop_requested

from .constants import (BASE, BTN_EXPAND, BOTTOM_BAR_REGION, ESCAPE_CHANGE_TH,
                        ESCAPE_WAIT_S)


def has(eng: EnginePort, kws, img=None, min_score=0.4, **kw):
    """存在性判断(只返回布尔)。
    O2(2026-10-21): 默认 need_refine=False —— 拆分的唯一用途是给**点击**提供精确子块坐标,
    纯判断不需要; 省下 social 大量等待探测里的过宽块 2× 重识别。需要坐标的调用一律走 locate/click。
    exact=True 时仍保留拆分(合并块会让 exact 失配, 拆分可能是唯一命中途径)。"""
    if "need_refine" not in kw:
        kw["need_refine"] = bool(kw.get("exact", False))
    return eng.locate(kws, img=img, min_score=min_score, **kw) is not None


def has_social(eng: EnginePort, img=None, min_score=0.4, cache=None):
    """codex-20261025-3(用户裁定「背景色遮挡」): 底栏「社交」统一判读入口。

    现象与判读(20261024 日志): escape_overlay 的 has() 用 0.5 闸门判 MISS,
    紧随其后的 click_btn_fine 用 0.4 闸门 OCR 命中同一按钮 —— 分数落在 [0.4,0.5) 灰带,
    即「字在屏上、背景色把置信度压低」(与 locate_fine 的 2026-10-06 立项事实同源:
    不同好友花园的紫/蓝彩底压白字置信度; 聊天气泡在屏顶 (640,78) 一带、位置固定,
    不遮挡底栏 —— 2026-10-25 用户纠正)。

    区域化读法: 「社交」恒在底栏左段(2026-10-22 用户澄清 + 10-24 全部命中 x∈[423,424]),
    固定 region + min_score 0.40(主 agent 修订: 去掉 0.35 二次放宽 —— 日志证据只到 0.4 灰带,
    0.35 无实测支撑, 按 R3 不擅自放宽阈值; 裁片 MISS 时由上层点-验-重试与 escape 链兜底)。
    cache: 调用方可传 dict 收集 {命中方式: 次数} 供日志/观测(可选)。
    """
    img = img if img is not None else eng.screenshot()
    pt = eng.locate(["社交"], img=img, region_rel=BOTTOM_BAR_REGION, min_score=min_score)
    if pt is not None and cache is not None:
        cache["region"] = cache.get("region", 0) + 1
    return pt


def wait_until(eng: EnginePort, cond, timeout, desc="", interval=1.0):
    """轮询等待条件成立。模拟器输入延迟可达数十秒, 故一律轮询而非固定 sleep。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if stop_requested():
            print(f"    [等待] {desc} 收到停止请求, 中断")
            return False
        if cond():
            print(f"    [等待] {desc} 命中 ({time.time() - t0:.0f}s)")
            return True
        time.sleep(interval)
    print(f"    [等待] {desc} 超时 {timeout}s")
    return False


# ---------------- 运行期按钮区域缓存 + 滤色精识 (2026-10-06, 用户方案) ----------------
# 背景: 好友花园底栏「社交」按钮存在, 但不同好友花园的紫/蓝等彩底会把常规 OCR 置信度
# 压到阈值以下造成整词 MISS(10-06 日志: 110 次尝试 0 命中, 10 页采粉全部放弃, 仅采 1 次)。
# 方案: 首次真实命中时缓存按钮相对区域(命中点外扩), 之后未命中时对该小区域做
# 「放大 + 白字滤色」精识(eng.locate_fine)。
# 合规性(规则 6): 区域来自**本次运行的真实识别命中**动态推导, 非写死坐标; 最终点击仍来自
# 精识 OCR 的实时命中 —— 不是盲点历史坐标。
# 开销(用户约束): 命中路径零额外开销; 未命中才做一次小裁片推理(毫秒级);
# 缓存为内存字典(每键 4 个 float), 仅本次运行有效, 不落盘、不跨运行、不占额外内存。
BTN_REGION_CACHE: dict = {}   # {按钮关键字: [x1,y1,x2,y2] 相对坐标}


def click_btn_fine(eng: EnginePort, kws, img=None, min_score=0.4, expect_region=None):
    """带「区域缓存 + 滤色精识」兜底的按钮点击: 常规 OCR 命中即点(并学习缓存区域);
    未命中且有缓存 → 对缓存小区域滤色放大精识, 命中即点。返回 Point 或 None(未命中)。

    D18①(2026-10-27, zcode-20261028-8): `expect_region` —— 该按钮在屏上的**实测常住带**
    (判据, 非点击坐标, 与 region_rel 同性质)。传入后: 主定位先按该带 region_rel 过滤;
    精识兜底得到的命中也须落在带内, 出界一律弃用并如实返回 None。
    背景(10-27 22:45 实锤): 聊天气泡文本含「社交」@rel(0.441,0.906) 在底栏区域内被当按钮
    点击 -> 打开聊天面板 -> ensure_home 无出口空转至关服。社交钮实测恒在 (0.331,0.949)。
    """
    kws = kws if isinstance(kws, list) else [kws]
    pt = eng.locate(kws, img=img, min_score=min_score,
                    region_rel=expect_region) if expect_region else eng.locate(kws, img=img, min_score=min_score)
    how = "ocr"
    if pt is None:
        for kw in kws:
            reg = BTN_REGION_CACHE.get(kw)
            if not reg:
                continue
            pt = eng.locate_fine(kws, reg, min_score=max(0.30, min_score - 0.10), img=img)
            if pt is not None:
                how = "滤色精识"
                break
    if pt is None:
        return None
    if expect_region:
        w0, h0 = eng.screen_w or 1280, eng.screen_h or 720
        rx1, ry1, rx2, ry2 = expect_region
        if not (rx1 * w0 <= pt.x <= rx2 * w0 and ry1 * h0 <= pt.y <= ry2 * h0):
            print(f"  [按钮] {'/'.join(kws)} 命中 ({pt.x},{pt.y}) 在常住带外 {expect_region}, "
                  f"判为同字气泡/遮挡文本, 弃用不点击(D18①)")
            return None
    w, h = eng.screen_w or 1280, eng.screen_h or 720
    ex, ey = BTN_EXPAND
    BTN_REGION_CACHE[kws[0]] = [max(0.0, pt.x / w - ex), max(0.0, pt.y / h - ey),
                                min(1.0, pt.x / w + ex), min(1.0, pt.y / h + ey)]
    print(f"  [按钮] {'/'.join(kws)} {how}命中 ({pt.x},{pt.y})")
    eng.click_abs(pt.x, pt.y)
    return pt


def frame_diff(a, b):
    """两张同尺寸 BGR 帧的粗略差异(0~1, 越大差别越大)。

    用于「点完等画面变化, 变了就往下走」—— 缩到 96×54 灰度再比, 单次成本远低于一次全屏 OCR,
    避免为等一个大概率已落地的动作空转满超时(2026-10-02 采粉提速)。
    """
    import cv2
    if a is None or b is None or a.shape != b.shape:
        return 1.0
    ga = cv2.cvtColor(cv2.resize(a, (96, 54)), cv2.COLOR_BGR2GRAY)
    gb = cv2.cvtColor(cv2.resize(b, (96, 54)), cv2.COLOR_BGR2GRAY)
    return float(cv2.absdiff(ga, gb).mean()) / 255.0


def wait_screen_change(eng: EnginePort, base, desc="画面变化", timeout=None, threshold=None, interval=1.0):
    """等待画面相对 base 发生**大幅**变化(整屏面板切换), 变了即返回 True。

    用于脱困/归位链「点击退出控件后确认真的退出去了」—— 本次日志(2026-10-03 19:15)里
    委托子页出口 rel(0.035,0.038) 点在「家族」文字标签上, 画面纹丝不动却被当成功,
    ensure_home 4 轮 × 各模块反复空转数分钟, energy/claim 全程陪跑。
    轮询截图无 OCR, 成本可忽略; 有 timeout + 变化即返回, 尊重停止请求。
    """
    if timeout is None:
        timeout = ESCAPE_WAIT_S
    if threshold is None:
        threshold = ESCAPE_CHANGE_TH
    t0 = time.time()
    while time.time() - t0 < timeout:
        if stop_requested():
            print(f"    [画面复核] {desc} 收到停止请求, 中断")
            return False
        if frame_diff(base, eng.screenshot()) >= threshold:
            return True
        time.sleep(interval)
    return False


def wait_stable(eng: EnginePort, timeout=1.5, interval=0.3, threshold=None):
    """C3(2026-10-22): 点击前等画面稳定(连续两帧帧差 < 阈值)。**纯帧差, 无 OCR**。

    背景: 10-22 日志 L466-510 点击家园图标后画面纹丝不动、重试 3 次全被吞; 很多点击发生在
    翻页/滑行/过场动画刚结束的瞬间 —— 画面还在动时, 点击容易被系统丢弃, 标记坐标也可能来自
    未稳定的旧帧。等连续两帧几乎一致再点, 可显著降低「点了没反应」。
    超时也放行: 宁可直接点, 不能因等稳定阻塞业务。返回 True=已稳定 / False=超时或停止。
    """
    if threshold is None:
        threshold = ESCAPE_CHANGE_TH
    prev = eng.screenshot()
    if prev is None:
        return False
    t0 = time.time()
    while time.time() - t0 < timeout:
        if stop_requested():
            return False
        time.sleep(interval)
        cur = eng.screenshot()
        if cur is not None and frame_diff(prev, cur) < threshold:
            return True
        prev = cur
    return False


def save_escape_evidence(eng: EnginePort, tag):
    """脱困/归位失败时把当前画面存到 debug/, 作为出口控件的定向采集素材。

    背景(2026-10-03): 委托子页/好友列表的真实出口控件位置失准且仓库内**没有**这些界面的
    干净截图(历史素材已被清理), 导致无法离线重采。本钩子在失败现场自动落盘
    debug/escape_fail_<tag>_<时刻>.png, 下次实机再卡死即产出校准素材 ——
    用户可直接在 WebUI /tpltool「载入 debug 图片」框选真实出口, 据此修订对应模板
    (delegate_close/shell_close/friendlist_exit 等)与阈值/region。
    与既有 debug/_enter_garden_fail.png 同类机制; debug/ 为测试区出仓目录, 不入 git。
    """
    try:
        import cv2
        img = eng.screenshot()
        if img is None:
            return
        d = str(BASE / "debug")
        os.makedirs(d, exist_ok=True)
        fn = os.path.join(d, f"escape_fail_{tag}_{time.strftime('%H%M%S')}.png")
        if not cv2.imwrite(fn, img):
            print("  [存证] 失败画面写盘失败(路径/权限):", fn)
            return
        print(f"  [存证] 脱困失败画面已保存 -> {os.path.basename(fn)}"
              " (请用 WebUI /tpltool 载入该图采集真实出口控件)")
    except Exception as e:
        print(f"  [存证] 保存失败画面异常: {e}")


def adb_text(s, eng=None):
    adb = getattr(eng, "adb_path", ADB_PATH) if eng is not None else ADB_PATH
    addr = getattr(eng, "address", ADB_ADDRESS) if eng is not None else ADB_ADDRESS
    subprocess.run([adb, "-s", addr, "shell", "input", "text", s],
                   capture_output=True, timeout=15)


def adb_key(code, eng=None):
    """发按键(同本体 back() 的 subprocess 机制): 123=移到行尾, 67=退格。"""
    adb = getattr(eng, "adb_path", ADB_PATH) if eng is not None else ADB_PATH
    addr = getattr(eng, "address", ADB_ADDRESS) if eng is not None else ADB_ADDRESS
    subprocess.run([adb, "-s", addr, "shell", "input", "keyevent", str(code)],
                   capture_output=True, timeout=15)
