"""社区点赞闭环（社交任务 4.3 段）。

逻辑（用户给定）：
    回主界面 -> 点「种草社区」入口 -> 进页面后点「向右」随机次数(n ∈ [1, min(总页数,25)])
    -> 随机点 2 个点赞按钮 -> 若不足 2 个则随机前后翻一页并把剩余次数点完
    -> 退出回主界面。

业务背景（决定了"只点 2 次、不多点"）：
    每日任务要求点赞 2 次；同时每期(约 7 天)点赞次数有上限(20 次)。
    多点了会挤占后续天数的额度，故本模块**只为完成每日 2 次任务**，绝不贪点。
    理想触发判据是「每日任务面板里识别到『点赞』任务且未完成」，但每日任务模块尚未开发，
    因此当前用 config.enable_like 开关挂在社交模块下（默认 false，避免误消耗额度）。

============================ 2026-09-29 实机实测结论（决定实现方式） ============================
① 点赞按钮的两种形态（实测：点一次后 79945+胶囊 -> 79946+灰拇指，本期点赞数 6->7）：
     未点赞 = 数字**右侧**一枚**亮紫色胶囊**内含白拇指 + 星点，尺寸 81x40
     已点赞 = 数字**左侧**一枚**灰拇指**，胶囊消失
   → 位置、颜色、大小三者同时变化，故**"胶囊是否还在"就是点赞是否成功的判据**。
② 模板匹配在本场景**不可用**（实测证据，勿再改回模板）：
     全胶囊模板 -> 本页 31 处误命中（地板光滑渐变与胶囊同色，真点 1.000 / 假点 0.94+）
     白拇指小模板 -> 本页 33 处误命中
     右箭头模板   -> 本页 11 处误命中
   三者分数都无法与真点拉开差距，TM_SQDIFF_NORMED 对低纹理模板天然失效。
   → 点赞按钮/翻页箭头改用 **HSV 颜色 + 形状** 检测（见 find_likes / find_arrow）。
     关闭按钮的粉色花模板反而唯一（th=0.95 只 1 处命中），故关闭仍走模板。
③ 实测坐标（1280x720）：
     入口「种草社区」 主界面右侧竖排导航 @abs(1230,328) rel(0.9609,0.4556)，score 0.80
     点赞胶囊         3 张卡固定 @abs(426,555)/(751,555)/(1075,555)，均 81~82 x 40
     右箭头           @abs(1204,345)  47~49 x 57~59，面积 ~1830
     左箭头           @abs(187,345)   同样尺寸（第 1 页时不存在）
     页码 "N/1950"    @abs(694,613) rel(0.5430,0.8514)
     本期点赞数        @abs(1157,660) rel(0.9039,0.9167)，实测文本为「本周点赞数：0/20」
     关闭 X           @abs(1246,26)  rel(0.9734,0.0361)，点击后回主界面
  ⚠ 实测坑：进入社区页会**记住上次浏览的页码**（实测再进入时直接从 4/1950 开始），
    故不能假定"进页面 = 第 1 页"，随机翻页一律按用户要求"从当前页向右 n 次"。
  ⚠ 实测坑：左侧 x<140 的两个紫色块是**左导航图标**（服装/家园，93x78 与 93x29），
    不是左箭头；左箭头在 x=187。曾误点左导航导致跳到「1/565」的另一份榜单。
=========================================================================================

硬性约束（沿用 pollin.py 的项目约定）：
    含文字按钮 -> 本体 OCR（locate / click_text）
    纯图形按钮 -> 优先模板匹配（locate_template）；经实测模板失效时才用颜色/形状检测，并写明实测证据
    所有定位/点击一律走本体函数（screenshot / click_abs / locate / click_text），不另起一套。

入口：`run_community_like(eng)`，由引擎 `community_like` 步骤类型调用
      （ocr_engine.py 的 run_step 中紧跟 friend_pollin 分支）。
开关：`config.enable_like`（默认 false）—— 每日任务模块未就绪前，用开关兜住误耗额度的风险。
独立调试：`python community_like.py run|enter|flip|state [--address ...]`（需连模拟器）。
"""
from __future__ import annotations

import random
import sys
import time

import cv2
import numpy as np

from ocr_engine import OCREngine, ADB_ADDRESS, ADB_PATH, stop_requested
from ocr_ui import ocr_image

# ---------------- 常量（一律相对坐标/相对区域，分辨率无关） ----------------

# ---- 入口（主界面文字按钮 -> OCR）----
ENTRY_TEXT = "种草社区"
ENTRY_REGION = [0.88, 0.38, 1.00, 0.53]          # 主界面右侧竖排导航带(防命中其他页面的同名标题)
TITLE_REGION = [0.00, 0.00, 0.20, 0.10]          # 社区页左上角标题「种草社区」
# 合规改造(2026-10-04, zcode-20261004-4, 规则6: 禁直坐标): 删除 ENTRY_FALLBACK_REL /
# MENU_FALLBACK_REL / HOME_FALLBACK_REL 三个直坐标兜底 —— OCR 未命中时不再盲点,
# 由各自的轮询重试链处理(入口 3 轮 / ensure_home 循环)。

# ---- 点赞按钮（纯图形 -> HSV 颜色 + 形状检测; 模板匹配实测失效, 见文件头②）----
LIKE_BAND = [0.735, 0.815]                       # 卡片底部条纵带(实测胶囊恒在 abs y 535~575)
LIKE_HSV_LO = (125, 70, 150)                     # 亮紫胶囊
LIKE_HSV_HI = (175, 255, 255)
LIKE_MIN_AREA = 600
LIKE_W_RANGE = (60, 130)                         # 实测 81~82
LIKE_H_RANGE = (30, 52)                          # 实测 40
LIKE_HIT_GAP_FRAC = 0.06                         # 判定"同一枚按钮"的最大位移(相对屏宽), 远大于点赞后的形变

# ---- 翻页箭头（纯图形 -> HSV 颜色 + 形状检测）----
ARROW_Y_RANGE = (280, 430)
ARROW_X_RANGE = {"prev": (140, 250), "next": (1140, 1280)}   # ⚠ 左箭头 x=187, 不得含左导航(x<140)
ARROW_HSV_LO = (120, 40, 100)
ARROW_HSV_HI = (179, 255, 255)
ARROW_AREA_RANGE = (1200, 2800)                  # 实测 1825 / 1763
ARROW_W_RANGE = (40, 70)                         # 实测 49 / 47
ARROW_H_RANGE = (45, 75)                         # 实测 58 / 57

# ---- 页码 x/N ----
PAGE_NUM_REGION = [0.5430, 0.8514]               # 2026-09-29 实测 abs(694,613)
PAGE_TOL = 60

# ---- 本期点赞数 N/20（额度守卫用）----
QUOTA_REGION = [0.80, 0.86, 1.00, 0.97]          # 实测 abs(1157,660), 文本为「本周点赞数：0/20」
QUOTA_RE = r"(?:本期|本周)点赞数\s*[：:]\s*(\d+)\s*/\s*(\d+)"

# ---- 退出 ----
CLOSE_TEMPLATE = "community_close"               # 已采集: 右上角粉色花 X
CLOSE_TH = 0.95                                  # 实测 th=0.95 唯一命中(0.90 起出现误命中)
CLOSE_REGION = [0.93, 0.0, 1.00, 0.14]
# 合规改造(2026-10-04, zcode-20261004-4): 删除 CLOSE_FALLBACK_REL 直坐标兜底 ——
# 关闭✕本就已模板化(仅剩 else 分支在模板未命中时盲点), 现改为不点, 由上方退出判据如实报出。

# ---- 行为参数 ----
CAP = 25            # 单次随机翻页次数硬上限（用户要求不超过 25）
LIKE_TARGET = 2     # 每日任务要求点赞次数
MAX_TURNS = 8       # 补足点赞的最大翻页轮数，防无限空转
FLIP_WAIT = 1.6     # 翻页后等待加载
CLICK_WAIT = 1.5    # 点赞后等待
ENTER_WAIT = 5      # 进入页面等待(2026-10-05 用户定值规则 15s→5s; 单次点击后等页面进入, 超时落回归位重试链)


# ---------------- 基础工具 ----------------

def has(eng, kws, img=None, min_score=0.4, **kw):
    return eng.locate(kws, img=img, min_score=min_score, **kw) is not None


def wait_until(eng, cond, timeout, desc="", interval=1.0):
    """轮询等待条件成立。模拟器输入延迟可达数十秒, 故一律轮询而非固定 sleep（沿用 pollin.py）。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if stop_requested():
            print(f"    [等待] {desc} 收到停止请求, 中断")
            return False
        if cond():
            return True
        time.sleep(interval)
    print(f"    [等待] {desc} 超时({timeout}s)")
    return False


def _violet_blobs(img, hsv_lo, hsv_hi, y_range, x_range, min_area):
    """在给定矩形带内找紫色连通域, 返回 [(cx, cy, area, w, h), ...]。"""
    h = img.shape[0]
    y1, y2 = max(0, int(y_range[0])), min(h, int(y_range[1]))
    x1, x2 = max(0, int(x_range[0])), min(img.shape[1], int(x_range[1]))
    if y2 <= y1 or x2 <= x1:
        return []
    hsv = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(hsv_lo), np.array(hsv_hi))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        a = cv2.contourArea(c)
        if a < min_area:
            continue
        bx, by, bw, bh = cv2.boundingRect(c)
        out.append((x1 + bx + bw // 2, y1 + by + bh // 2, int(a), bw, bh))
    return out


# ---------------- 读页面状态 ----------------

def read_page(eng, img=None):
    """读页码 "x/N" -> (cur, total); 未读到返回 None。

    复用引擎 parse_fraction_at（OCR 整图找 'a/b' 数字块, 取离目标点最近的一个）。
    不自己写一套 OCR 解析 —— 与 pollin.py 保持一致。
    """
    return eng.parse_fraction_at(PAGE_NUM_REGION, img=img, tol=PAGE_TOL)


def read_quota(eng, img=None):
    """读「本期(本周)点赞数：used/cap」-> (used, cap); 未读到返回 None。

    ⚠ 不能复用 parse_fraction_at: 它要求 OCR 块**整块**就是 'a/b',
      而这里整块是「本周点赞数：0/20」, 故须在模块内用正则从块文本里抠。
    """
    import re
    img = img if img is not None else eng.screenshot()
    if img is None:
        return None
    pat = re.compile(QUOTA_RE)
    for b in ocr_image(img):
        m = pat.search(b.get("text", ""))
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def find_likes(eng, img=None):
    """找当前页**未点赞**的按钮(亮紫胶囊), 返回中心点列表 [(x,y), ...]。"""
    img = img if img is not None else eng.screenshot()
    if img is None:
        return []
    h = img.shape[0]
    ys = (LIKE_BAND[0] * h, LIKE_BAND[1] * h)
    blobs = _violet_blobs(img, LIKE_HSV_LO, LIKE_HSV_HI, ys, (0, img.shape[1]), LIKE_MIN_AREA)
    out = []
    for cx, cy, _a, w, hh in blobs:
        if LIKE_W_RANGE[0] <= w <= LIKE_W_RANGE[1] and LIKE_H_RANGE[0] <= hh <= LIKE_H_RANGE[1]:
            out.append((cx, cy))
    return sorted(out)


def find_arrow(eng, direction, img=None):
    """找翻页箭头 -> (x, y); 未找到返回 None。

    direction: "next"(向右) / "prev"(向左)。
    第 1 页时左箭头不存在, 返回 None 是正常情况。
    """
    img = img if img is not None else eng.screenshot()
    if img is None:
        return None
    blobs = _violet_blobs(img, ARROW_HSV_LO, ARROW_HSV_HI,
                          ARROW_Y_RANGE, ARROW_X_RANGE[direction], 300)
    cand = [b for b in blobs
            if ARROW_AREA_RANGE[0] <= b[2] <= ARROW_AREA_RANGE[1]
            and ARROW_W_RANGE[0] <= b[3] <= ARROW_W_RANGE[1]
            and ARROW_H_RANGE[0] <= b[4] <= ARROW_H_RANGE[1]]
    if not cand:
        return None
    cand.sort(key=lambda b: -b[2])
    return cand[0][0], cand[0][1]


def _entered(eng, img=None):
    """进入「种草社区」的判据: 能读到页码, 或左上角有社区页标题。

    ⚠ 不得用**不带区域**的「种草社区」做判据: 主界面右侧导航也有这四个字,
      否则"点了入口但还没进页面"会被误判为已进入。
    """
    img = img if img is not None else eng.screenshot()
    if read_page(eng, img) is not None:
        return True
    return has(eng, [ENTRY_TEXT], img=img, region_rel=TITLE_REGION)


# ---------------- 环节: 进入 / 退出 ----------------

def escape_to_main(eng):
    """脱困回主界面（enter_community 每次重试前调用）。

    实测踩坑（2026-09-29 里程碑 56）：pollin 翻页用的「跳转页签」是**模态对话框**，会吞掉一切点击 ——
    此时点右上角、点底部导航、点关闭模板**全都无效**（实测 4 条路径全空转，画面一字未变）。
    故脱困必须**先关模态框**，顺序为：
      ① `close_dialog()` —— 注册表已含「跳转页签」锚点（关闭钮实测 @abs(889,232)）与通用「提示」锚点弹窗；
      ② `pollin.ensure_home()` —— 关提示框/离开好友花园/关家族面板/右上角兜底，既有实战链路**直接复用不重造**；
      ③ 仍不到位才用「菜单 → 家园」OCR 点击兜底（ensure_home 未成功时才做，避免在主界面上空点菜单；
        合规改造 2026-10-04: 已删这两个按钮的直坐标 fallback，OCR 未命中就不点）。
    """
    try:
        eng.close_dialog()                      # ① 先关模态框(否则后面全部点击都会被吞)
    except Exception as e:
        print(f"  [社区点赞] close_dialog 异常: {e}")
    time.sleep(1.0)
    ok = False
    try:
        from pollin import ensure_home          # ② 复用既有归位链(避免重复造轮子)
        ok = ensure_home(eng)
    except Exception as e:
        print(f"  [社区点赞] ensure_home 异常: {e}")
    time.sleep(0.8)
    if not ok:                                  # ③ 兜底: 菜单 -> 家园(OCR; 未命中不盲点, 如实留痕)
        print("  [社区点赞] ensure_home 未归位, 走「菜单→家园」OCR 兜底")
        eng.click_text(["菜单"])
        time.sleep(1.2)
        eng.click_text(["家园"])
        time.sleep(1.5)


def enter_community(eng, tries=3):
    """进「种草社区」: 主界面右侧导航文字按钮 -> OCR 定位点击。

    不在主界面时走 `escape_to_main()` 归位再试。
    进入成功以 `_entered()` 为准, 不把「点了入口」当成「已进入」（缓存/误点不得作为命中判据）。
    """
    for i in range(1, tries + 1):
        if stop_requested():
            return False
        img = eng.screenshot()
        if _entered(eng, img):
            print(f"  [社区点赞] 已在种草社区（第 {i} 轮）")
            eng.set_scene("种草社区")
            return True
        pt = eng.locate([ENTRY_TEXT], img=img, region_rel=ENTRY_REGION, min_score=0.4)
        if pt is not None:
            print(f"  [社区点赞] 主界面右侧导航命中「{ENTRY_TEXT}」({pt.x},{pt.y})")
            eng.click_abs(pt.x, pt.y)
        else:
            print(f"  [社区点赞] 第 {i}/{tries} 轮: 未命中「{ENTRY_TEXT}」入口(OCR), 不盲点, 走归位重试")
        if wait_until(eng, lambda: _entered(eng), ENTER_WAIT, desc="进入种草社区"):
            eng.set_scene("种草社区")
            return True
        print("  [社区点赞] 点了入口但未确认进入, 继续重试")
        if i < tries:
            escape_to_main(eng)
    print("  [社区点赞] 入口重试耗尽, 未能进入种草社区")
    return False


def leave(eng):
    """退出种草社区回主界面。

    ⚠ 每个子功能结束**必须归位** —— BUG2 教训: 花灵派对结束后不回家园,
      导致 7.3 奇妙花宝整条入口链在错误界面上空转。
    实测: 社区页右上角 X @abs(1246,26) 点掉即回主界面, 主界面右侧能重新看到入口。
    """
    img = eng.screenshot()
    pt = eng.locate_template(CLOSE_TEMPLATE, img=img, threshold=CLOSE_TH, region_rel=CLOSE_REGION) \
        if img is not None else None
    if pt is not None:
        print(f"  [社区点赞] 点社区页关闭 X ({pt.x},{pt.y})")
        eng.click_abs(pt.x, pt.y)
    else:
        print("  [社区点赞] 关闭模板未命中(community_close), 不盲点; 由下方退出判据如实处理")
    time.sleep(1.5)

    # ⚠ 不能用「重新看到入口」做成功判据: 主界面右侧导航是**活动主题位**, 实测有时显示
    #   「星盐冰沙套装」等主题名而非「种草社区」, 会把"已到家"误报成"没关闭"。
    #   故判据改为「社区页特征消失」= 读不到页码 且 左上角没有社区页标题。
    if not _entered(eng):
        print("  [社区点赞] 社区页特征已消失, 视为已退出")
        if has(eng, [ENTRY_TEXT], region_rel=ENTRY_REGION):
            print("  [社区点赞] 且重新看到主界面右侧导航入口, 归位确认")
        eng.set_scene("家园主界面")          # 归位后复位场景, 否则后续点击仍记在「种草社区」
        return True

    # 仍在社区页才动关闭注册表兜底 ——
    # ⚠ BUG2 教训 + 实测: close_dialog 的模板在非目标界面会假命中
    #   (实测离页后 close_online_small 以 0.929 误命中 (1145,100) 并点了 (1170,52)),
    #   所以这一步**必须**加"仍在社区页"的守卫, 不能无条件调用。
    print("  [社区点赞] 仍在社区页, 走关闭注册表兜底")
    eng.close_dialog()          # 注意: close_dialog 无 delay 参数(签名 img/anchor_kw/dx_range/dy_tol/min_score/only_types)
    time.sleep(1.0)
    if _entered(eng):
        print("  [社区点赞] ⚠ 兜底关闭后仍在社区页, 请检查关闭按钮/模板")
        return False
    print("  [社区点赞] 兜底关闭生效")
    eng.set_scene("家园主界面")
    return True


# ---------------- 环节: 翻页 / 点赞 ----------------

def flip(eng, direction=None):
    """翻一页。direction: "next" / "prev" / None(=随机, 且尊重页码边界)。

    边界规则（用户要求）: 已在第 1 页只能向右, 已在最后一页只能向左。
    返回 True=已点翻页按钮, False=按钮未命中（首页无左箭头属正常）。
    """
    if direction is None:
        fr = read_page(eng)
        if fr:
            cur, total = fr
            if cur <= 1:
                direction = "next"
                print(f"  [社区点赞] 当前 {cur}/{total} 页(首页), 只能向右")
            elif cur >= total:
                direction = "prev"
                print(f"  [社区点赞] 当前 {cur}/{total} 页(末页), 只能向左")
        if direction is None:
            direction = random.choice(["next", "prev"])
            print(f"  [社区点赞] 随机翻页方向: {'向右' if direction == 'next' else '向左'}")

    pt = find_arrow(eng, direction)
    if pt is None:
        print(f"  [社区点赞] {'向右' if direction == 'next' else '向左'}箭头未检测到"
              f"（第 1 页无左箭头属正常）")
        return False
    print(f"  [社区点赞] {'向右' if direction == 'next' else '向左'}翻页 -> ({pt[0]},{pt[1]})")
    eng.click_abs(pt[0], pt[1])
    return True


def like_at(eng, x, y):
    """点一个「未点赞」按钮, 用**点赞后按钮形态变化**做校验。

    实测: 未点赞 = 数字右侧亮紫胶囊; 已点赞 = 胶囊消失 + 数字左侧灰拇指。
    故校验 = 点击后该位置附近不再检出胶囊 ⇒ 确实点上了。
    返回 True=确认点中, False=点了但胶囊仍在(如实报出, 不谎报成功)。
    """
    img0 = eng.screenshot()
    if img0 is None:
        return False
    before = find_likes(eng, img0)
    eng.click_abs(x, y)
    time.sleep(CLICK_WAIT)
    img1 = eng.screenshot()
    if img1 is None:
        return False
    after = find_likes(eng, img1)
    gap = LIKE_HIT_GAP_FRAC * img1.shape[1]
    still = [p for p in after
             if abs(p[0] - x) <= gap and abs(p[1] - y) <= gap]
    if still:
        print(f"    [点赞] ({x},{y}) 点击后胶囊仍在 {still}, 判定**未点上**")
        return False
    print(f"    [点赞] ({x},{y}) 胶囊已消失, 确认点中（本页剩余可点 {len(before)} -> {len(after)}）")
    return True


def like_some(eng, k, clicked):
    """在当前页**随机**挑 k 个「未点赞」按钮点击, 返回实际确认点中数。

    不是点前 k 个, 而是全页候选里随机抽 k 个（用户明确要求"随机点击"）。
    clicked: 已点过的坐标 —— 防止形变后又被当成新候选重复点。
    """
    cand = find_likes(eng)
    if not cand:
        print("  [社区点赞] 本页无可点赞按钮")
        return 0
    gap = LIKE_HIT_GAP_FRAC * (eng.screen_w or 1280)   # 按实际屏宽换算(原硬编码 1280 在非 1280 宽分辨率下与 like_at 判定不一致)
    cand = [p for p in cand
            if not any(abs(p[0] - c[0]) <= gap and abs(p[1] - c[1]) <= gap for c in clicked)]
    if not cand:
        print("  [社区点赞] 本页候选均已点过")
        return 0

    pick = random.sample(cand, min(k, len(cand)))
    print(f"  [社区点赞] 本页候选 {len(cand)} 个, 随机取 {len(pick)} 个")
    ok = 0
    for x, y in pick:
        if stop_requested():
            break
        clicked.append((x, y))
        if like_at(eng, x, y):
            ok += 1
    return ok


# ---------------- 今日是否已点（待接入每日任务模块） ----------------

def already_liked_today(eng):
    """「今日已点过 2 次则跳过」的**主体逻辑占位**。

    ⚠ 识别方法（用户指定）: 该功能应只在「每日任务」面板里识别到"点赞"任务时触发。
      但每日任务模块尚未开发, 故这里暂返回 False（即不跳过）, 由 config.enable_like 开关兜住风险。
    TODO(待每日任务模块就绪): 改为读取每日任务面板中"点赞"任务状态 ——
      任务存在且未完成 -> 需要点 2 次; 任务不存在/已完成 -> 返回 True 跳过 2~4 步。
    """
    return False


# ---------------- 主流程 ----------------

def run_community_like(eng):
    """社区点赞主流程（4.3 段）。返回结果字典, 供引擎日志打印。"""
    print("  [社区点赞] ===== 开始 =====")
    res = {"ok": False, "entered": False, "liked": 0, "reason": ""}

    # --- 第 0 步: 今日已点则跳过（主体逻辑占位）---
    if already_liked_today(eng):
        res["ok"] = True
        res["reason"] = "今日已点过, 跳过"
        print("  [社区点赞] 今日已点过 2 次, 跳过 2~4 步")
        return res

    # --- 第 1 步: 回主界面 -> 点「种草社区」入口 ---
    if not enter_community(eng):
        res["reason"] = "未能进入种草社区"
        print(f"  [社区点赞] {res['reason']}, 整段跳过")
        return res
    res["entered"] = True

    # --- 额度守卫: 本期点赞数已满则一次都不点（宁可漏做, 不可超额）---
    quota = read_quota(eng)
    if quota:
        used, cap = quota
        print(f"  [社区点赞] 本期点赞数 {used}/{cap}")
        if used >= cap:
            res["reason"] = f"本期点赞额度已满({used}/{cap})"
            print(f"  [社区点赞] {res['reason']}, 不点赞, 直接退出")
            leave(eng)
            return res
    else:
        print("  [社区点赞] ⚠ 未读到本期点赞数, 无法做额度守卫（继续, 但只点 2 次风险可控）")

    # --- 第 2 步: 随机落页: 点「向右」n 次, n ∈ [1, min(总页数, CAP)] ---
    fr = read_page(eng)
    total = fr[1] if fr else None
    upper = min(total, CAP) if total else CAP
    if not total:
        print(f"  [社区点赞] ⚠ 总页数未读到, 随机上界降级为硬上限 {CAP}（点过头无害）")
    n = random.randint(1, upper)
    print(f"  [社区点赞] 随机向右 {n} 次（总页数={total}, 上界={upper}）")
    for i in range(n):
        if stop_requested():
            break
        if not flip(eng, "next"):
            print(f"  [社区点赞] 向右箭头未命中, 随机翻页在第 {i + 1} 次中止")
            break
        time.sleep(FLIP_WAIT)

    # --- 第 3~4 步: 点赞 2 次; 不足则随机翻页补足 ---
    clicked = []
    need = LIKE_TARGET
    for turn in range(1, MAX_TURNS + 1):
        if stop_requested():
            break
        need -= like_some(eng, need, clicked)
        print(f"  [社区点赞] 第 {turn} 轮结束, 还差 {need} 次")
        if need <= 0:
            break
        if not flip(eng, None):
            print("  [社区点赞] 翻页箭头未检测到, 无法继续补足")
            break
        time.sleep(FLIP_WAIT)

    res["liked"] = LIKE_TARGET - need
    if need > 0:
        # 如实报告: 不把"放弃"说成"完成"（否则日志里看不出任务其实没做完）
        print(f"  [社区点赞] ⚠ 还差 {need} 次未点完, 未完成（未确认真点满）")
        res["reason"] = f"还差 {need} 次"
    else:
        res["ok"] = True

    # --- 第 5 步: 退出回主界面 ---
    leave(eng)
    print(f"  [社区点赞] ===== 结束 {res} =====")
    return res


# ---------------- 独立调试入口 ----------------

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("run", "enter", "flip", "state"):
        print("用法: python community_like.py run|enter|flip|state  [--address 127.0.0.1:16384]")
        return
    addr = ADB_ADDRESS
    if "--address" in sys.argv:
        addr = sys.argv[sys.argv.index("--address") + 1]
    eng = OCREngine(adb_path=ADB_PATH, address=addr)
    if not eng.connect():
        print("[错误] 连接模拟器失败")
        return
    cmd = sys.argv[1]
    if cmd == "enter":
        print(enter_community(eng))
    elif cmd == "flip":
        print(flip(eng, None))
    elif cmd == "state":
        img = eng.screenshot()
        print("页码:", read_page(eng, img))
        print("配额:", read_quota(eng, img))
        print("可点赞按钮:", find_likes(eng, img))
        print("左箭头:", find_arrow(eng, "prev", img), " 右箭头:", find_arrow(eng, "next", img))
    else:
        print(run_community_like(eng))


if __name__ == "__main__":
    main()