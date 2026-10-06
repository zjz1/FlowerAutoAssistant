# -*- coding: utf-8 -*-
"""好友采粉闭环（主体模块）。

逻辑（用户给定）：
    打开好友列表 -> 找到可采粉好友 -> 进入其家园 -> 快捷操作 -> 一键采粉
    -> 采完不离开好友花园，就地在好友花园重开好友列表去下一个目标
    -> 密友与好友两类均翻到最后一页仍无可采粉 -> 回到自己家园 -> 结束

硬性约束：
    纯图标形按钮 -> 模板匹配（locate_template，模板在 resource/template/）
    含文字按钮   -> 本体 OCR   （locate / click_text）
  所有定位/点击一律走本体函数，不另起一套。

入口：`run_friend_pollin(eng)`（由引擎 `friend_pollin` 步骤类型调用）。
独立调试：`python pollin.py state|all`（需连模拟器）。
"""
from __future__ import annotations

import subprocess
import sys
import time

from ocr_engine import OCREngine, ADB_ADDRESS, ADB_PATH, stop_requested
from ocr_ui import ocr_image

# ---------------- 常量（全部相对坐标/相对区域，分辨率无关） ----------------
TPL_GREEN = "friend_pollin"                      # 可采粉绿花角标(纯图形)
TPL_JUMP = "friend_page_jump"                    # 列表底部金色圆形「跳」按钮(纯图形)
GREEN_TH = 0.97
GREEN_REGION = [0.74, 0.0, 0.83, 1.0]
HOUSE_DX_REL = -0.0172                           # 绿花角标 -> 家园图标中心 的相对偏移
HOUSE_DY_REL = 0.0417
JUMP_TH = 0.80
JUMP_REGION = [0.38, 0.86, 0.52, 1.0]
# ---- 纯图形出口/控件: 全部模板化(2026-10-04 合规改造 zcode-20261004-4, 规则6: 禁直坐标) ----
# 模板均按 1280 基准尺寸入库(resource/template/), 引擎按 screen_w/1280 尺度自适应;
# 阈值=各模板离线实测(源图命中 vs 异图假阳性)的分离值。
TPL_DELEGATE_CLOSE = "delegate_close.png"        # 委托子页内容区右上角白圆粉花✕(源图0.999/异图0.742)
DELEGATE_CLOSE_REGION = [0.82, 0.0, 1.0, 0.20]
DELEGATE_CLOSE_TH = 0.90
TPL_SHELL_CLOSE = "shell_close.png"              # 家族外壳右上角花形✕(源图0.995/异图0.766)
SHELL_CLOSE_REGION = [0.93, 0.0, 1.0, 0.12]
SHELL_CLOSE_TH = 0.90
TPL_FRIENDLIST_EXIT = "friendlist_exit.png"      # 好友列表左缘中央 » 抽屉钮(源图0.999/异图0.939→阈值取中)
FRIENDLIST_EXIT_REGION = [0.37, 0.35, 0.52, 0.60]
FRIENDLIST_EXIT_TH = 0.95
TPL_NUM_BAR = "num_bar.png"                      # 跳转页签对话框数字条(源图0.999/异图0.987→仅对话框上下文使用)
NUM_BAR_REGION = [0.35, 0.38, 0.72, 0.55]
NUM_BAR_TH = 0.90
TPL_DLG_CLOSE = "dlg_close.png"                  # 跳转页签对话框右上✕(源图0.999/异图0.955→阈值0.97)
DLG_CLOSE_REGION = [0.62, 0.24, 0.80, 0.42]
DLG_CLOSE_TH = 0.97
DLG_CONFIRM_REGION = [0.35, 0.60, 0.65, 0.72]    # 对话框「确认」按钮所在区域(有文字, OCR)
IME_OK_REGION = [0.85, 0.88, 1.0, 1.0]           # 系统数字键盘右下「确定」(有文字, OCR)
TAB_REGION = [0.90, 0.0, 1.0, 0.30]              # 右侧竖排页签(密友/好友)
SOCIAL_FRIEND_REGION = [0.25, 0.65, 0.55, 0.80]  # 家园「社交」面板内的「好友」按钮
PAGE_REGION = [0.5125, 0.9333]                   # 列表底部页码 "x/N"(中心)
PAGE_CROP = [0.44, 0.90, 0.60, 0.97]             # 页码胶囊裁剪框(2026-10-03 加宽: 旧 0.484~0.547 会截断
                                                 # 多位数页码, 实测 1080p「1/105」被裁成「1/1」→ 采粉误判单页)
ROW_TOP_REL, ROW_STEP_REL = 0.1375, 0.1347        # 好友行结构(实测 1280×720; 相对值随分辨率自适应,
                                                  # 实机验证时重新测定后只需改这两个数)
MERGE_Y_REL = 0.0764                              # 同一标记的 y 聚类去重阈值
SAFE_SLOT_MAX = 4                                 # 可点安全区最大槽位(0-4); 槽位5=底行视口裁切死区
                                                  # (16:35 实锤: 底行标记 2/2 失败, 3次×15s 点击全吞)
SWIPE_MAX_PER_PAGE = 3                            # 底行补救每页滑动上限(2026-10-06 方案一, 用户定)
SWIPE_Y_REL = 0.72                                # 补救滑动手势起点 y(列表中下部; 终点=起点-ROW_STEP_REL,
                                                  # 上滑一行=相对行高, 随实机分辨率自适应)
SWIPE_MS = 300                                    # 手势时长(ms): 温和拖动, 避免触发惯性 fling
SWIPE_SETTLE_S = 1.5                              # 滑动后等列表停稳再扫描(动画 ~0.3s, 留裕量防运动模糊帧)

LIST_MARKS = ("删除好友", "好友设置")             # 好友列表存在性判据(2026-10-05 已迁至 scenes.json「好友列表」, 常量保留供参考)
CATEGORIES = ("密友", "好友")


# ---------------- 基础工具 ----------------

def has(eng, kws, img=None, min_score=0.4, **kw):
    return eng.locate(kws, img=img, min_score=min_score, **kw) is not None


def wait_until(eng, cond, timeout, desc="", interval=1.0):
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
BTN_EXPAND = (0.06, 0.08)     # 命中点向外扩展比例 (宽, 高)


def click_btn_fine(eng, kws, img=None, min_score=0.4):
    """带「区域缓存 + 滤色精识」兜底的按钮点击: 常规 OCR 命中即点(并学习缓存区域);
    未命中且有缓存 → 对缓存小区域滤色放大精识, 命中即点。返回 Point 或 None(未命中)。"""
    kws = kws if isinstance(kws, list) else [kws]
    pt = eng.locate(kws, img=img, min_score=min_score)
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


# 脱困点击的「画面真的变了」复核参数(2026-10-03, 协作区 zcode-20261003-2):
# 阈值 0.05 明显高于倒计时/动画的帧间抖动(委托子页倒计时跳动实测 <<0.01), 低于整屏面板切换(>0.1),
# 用于区分「退出成功」与「点在无效控件上画面纹丝不动」。待实机校准: 若出现漏判先怀疑这里。
ESCAPE_CHANGE_TH = 0.05
ESCAPE_WAIT_S = 6.0

# ---- 纯图形出口控件: 模板化改造记录 (2026-10-04, zcode-20261004-4) ----
# ① 委托挑战全屏子页退出 = 内容区右上角「白色圆形粉花✕」→ delegate_close.png
#    (旧直坐标 (0.9010,0.1065) 为 2026-10-03 实测过渡态; 该✕与外壳装饰花不同, 必须先点它)。
# ② 家族界面外壳关闭 = 右上角「花形✕」→ shell_close.png
#    (旧 FAMILY_SHELL_EXIT_REL (0.9833,0.0509); close_family 旧模板带背景有假阳性史, 已裁新鲜模板)。
# ③ 好友列表退出 = 左缘中央「粉色凸出抽屉钮 + 白色向右双箭头»」→ friendlist_exit.png
#    (旧 FRIENDLIST_EXIT_REL (0.4313,0.4694); 右上角是页签列没有✕, 该钮是整个列表唯一出口)。
# 模板素材与离线验证证据: _collab/inbox/zcode-20261004-4/{files/resource/template,evidence}/


def wait_screen_change(eng, base, desc="画面变化", timeout=None, threshold=None, interval=1.0):
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


def save_escape_evidence(eng, tag):
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
        import os
        img = eng.screenshot()
        if img is None:
            return
        d = os.path.join(os.path.dirname(__file__), "debug")
        os.makedirs(d, exist_ok=True)
        fn = os.path.join(d, f"escape_fail_{tag}_{time.strftime('%H%M%S')}.png")
        if not cv2.imwrite(fn, img):
            print("  [存证] 失败画面写盘失败(路径/权限):", fn)
            return
        print(f"  [存证] 脱困失败画面已保存 -> {os.path.basename(fn)}"
              " (请用 WebUI /tpltool 载入该图采集真实出口控件)")
    except Exception as e:
        print(f"  [存证] 保存失败画面异常: {e}")


def adb_text(s):
    subprocess.run([ADB_PATH, "-s", ADB_ADDRESS, "shell", "input", "text", s],
                   capture_output=True, timeout=15)


def adb_key(code):
    """发按键(同本体 back() 的 subprocess 机制): 123=移到行尾, 67=退格。"""
    subprocess.run([ADB_PATH, "-s", ADB_ADDRESS, "shell", "input", "keyevent", str(code)],
                   capture_output=True, timeout=15)


def in_list(eng, img=None):
    """好友列表判据(2026-10-05 迁移至场景注册表): scenes.json「好友列表」=「删除好友」「好友设置」
    任一命中即算(原 LIST_MARKS 常量判据原样迁入, 本函数保留为兼容入口)。"""
    return eng.judge_scene("好友列表", img=img)


def in_home(eng, img=None):
    """自己家园主界面判据: 「户外主界面」场景(底部导航「社交」可见) **且不在好友列表**。

    ⚠ 旧版只判「社交」二字 → 好友列表页也含该字样, 于是被误判成"已在主界面";
      2026-10-02 日志: social 结束停在好友列表, ensure_home 直接收工,
      claim 整段(5 分钟)在好友列表上空跑, 三个功能几乎全未触发。
    ⚠ 2026-10-05 起底层走 scenes.json「户外主界面」(社交/家园/仙境花园, 锚点=社交)。
    """
    img = img if img is not None else eng.screenshot()
    if in_list(eng, img):
        return False
    return eng.judge_scene("户外主界面", img=img)


def in_garden(eng, img=None):
    """好友花园判据(2026-10-05 场景注册表版): 「家园界面」场景命中 **且没有**「勇气国花园」。

    ⚠ 判据来源(2026-10-05 用户口述): 家园界面 = 右下角 快捷操作/种植箱/一键种植/离开/地图
      + 左上角 菜单/奇妙花宝/园艺店, 「一键种植」或「菜单」其一命中再任意两钮即算 ——
      已录入 flows/common/scenes.json「家园界面」条目。
    ⚠ 好友家园与自己家园无可辨差异(用户 2026-10-05), 业务上不区分谁的家;
      本函数保留「排除自己家园」语义, 仅供回家链(ensure_home/leave_garden)决定是否点「离开」。
      排除法仍靠左下角地图名「勇气国花园」(自己家园恒显示, 好友花园永不显示,
      2026-09-22 多次实测; 不能写死任一好友花园名作判据)。
    ⚠ 性能: judge_scene 一次全图 OCR 判完全部锚点; 「勇气国花园」复核走引擎帧缓存,
      不再产生第二次整图识别。
    """
    img = img if img is not None else eng.screenshot()
    if not eng.judge_scene("家园界面", img=img):
        return False
    return not has(eng, "勇气国花园", img=img)


def in_family_panel(eng, img=None):
    """家族面板判据: 左侧导航「家族首页/家族活动/家族排行」任一命中。

    摇钱树/闪耀等家族活动结束后若关闭按钮没点准, 画面会残留在家族面板;
    该面板是整屏 UI, 按返回键(back)关不掉, ensure_home 需识别并点右上角关闭钮。
    """
    img = img if img is not None else eng.screenshot()
    return eng.locate(["家族首页", "家族排行"], img=img, min_score=0.4) is not None


def in_delegate_subpage(eng, img=None):
    """委托挑战全屏子页判据: 「委托排行」/「距离结束」任一命中。

    该子页(点家族活动网格「闪耀委托挑战」进入)是整屏 UI, 右上角**没有**关闭 X,
    家庭网格的 close_family 模板不会命中(实测恒 0.683); 真实出口是**左上角返回箭头**。
    家族活动 2x2 网格不显示「委托排行/距离结束」, 故可用来区分子页与网格。
    """
    img = img if img is not None else eng.screenshot()
    return eng.locate(["委托排行", "距离结束"], img=img, min_score=0.4) is not None


def _panel_friend_pt(eng, img=None):
    """「社交」面板内「好友」按钮位置; 面板未开则 None。
    region 限定 + exact, 避免误命中「添加好友」「删除好友」「好友设置」。
    2026-10-06: 常规未命中时对该固定 region 做滤色精识兜底(面板底色个别情况下压置信度)。"""
    pt = eng.locate(["好友"], img=img, exact=True,
                    region_rel=SOCIAL_FRIEND_REGION, min_score=0.4)
    if pt is None:
        pt = eng.locate_fine(["好友"], SOCIAL_FRIEND_REGION,
                             min_score=0.3, img=img, exact=True)
    return pt


# 右上角关闭区(通用整屏面板关闭钮位置, 用点击兜底; 小花仙里返回键无效, 不得再用 back)
# 阈值按模板分别校准: close_family 原统一取 0.65, 结果在**非家族面板**的任意画面上以
# 0.72~0.84 分误命中右上角并空点(escape_probe2.log: 0.823@(1229,32) / 0.839@(1183,119);
# escape_probe.log: 0.726@(1174,110)), 而真命中为 0.946 → 对齐 data/close_buttons.json。
# 2026-09-30 再提到 0.92: 社区页(like_exp_before)曾以 **0.896**@(1245,27) 命中(真命中 0.946)。
# ⚠ 风险: 真命中目前只有 1 个样本(0.946), 余量仅 0.026; 若后续在家族面板上出现漏关, 先怀疑这里。
# 另两个已剔除(2026-09-30):
#   close_online_small.png —— 仅 17×21 的「粉底白✕」, 是游戏里**所有面板共用的关闭字形**;
#     实测在本区([0.90,0,1.0,0.16])内到处命中 0.94~0.98(cur_state 0.953@(1232,36)、家园 0.941@(1170,72)),
#     纯属"随机误点生成器" → 从兜底链移除。在线礼包面板的关闭改走注册表「在线礼包」anchor_color 条目;
#     摇钱树子面板由 flow_social.json 自己的 click_template 步骤显式关(带 tight region + 「今日浇水次数」守卫), 不依赖本兜底。
#   close_signin.png —— 资源文件根本不存在(每次只会打印"模板不存在"), 属死条目 → 移除。
CORNER_CLOSE_TEMPLATES = {
    "close_family": 0.92,
    "close_corner_pink.png": 0.65,
}
CORNER_CLOSE_REGION = [0.90, 0.0, 1.0, 0.16]


def click_top_right_close(eng):
    """点右上角关闭钮。整屏面板(家族面板/邮件对话框等)在返回键无效的情况下,
    只能靠点右上角 X 关闭: 依次试模板(各自阈值见 CORNER_CLOSE_TEMPLATES), 都没命中则点右上角区域中心为止步操作。"""
    img = eng.screenshot()
    if img is None:
        return False
    for tpl, th in CORNER_CLOSE_TEMPLATES.items():
        pt = eng.locate_template(tpl, threshold=th, region_rel=CORNER_CLOSE_REGION, img=img)
        if pt is not None:
            print(f"  [关闭] 右上角模板 {tpl} 命中 ({pt.x},{pt.y})")
            eng.click_abs(pt.x, pt.y)
            return True
    import os
    x2 = int(CORNER_CLOSE_REGION[2] * img.shape[1])
    y2 = int(CORNER_CLOSE_REGION[3] * img.shape[0])
    x1 = int(CORNER_CLOSE_REGION[0] * img.shape[1])
    y1 = int(CORNER_CLOSE_REGION[1] * img.shape[0])
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    print(f"  [关闭] 无模板命中, 点右上角区域中心 ({cx},{cy})")
    eng.click_abs(cx, cy)
    return True


# ---------------- 环节: 回主界面 / 开列表 / 切页签 ----------------

def ensure_home(eng):
    """确保回到自己家园主界面: 关提示框 -> 离开好友花园 -> 委托子页点左上角返回 -> 关家族面板 -> 兜底点右上角关闭。

    ⚠ 2026-10-03 加固(协作区 zcode-20261003-2): 每个退出动作后用 wait_screen_change 复核画面真的变了;
      无效则升级第二策略; **连续 2 个退出动作画面均无变化即如实放弃归位**。
      背景: 本次日志里委托子页出口 rel(0.035,0.038) 点在「家族」文字标签上, 画面不变却被当成功,
      4 轮 × 各模块(采粉开列表 3 次 × ensure_home 4 轮 + claim 首步)反复空转数分钟。
      出口控件真实位置仍待实机重采(B1); 本函数只保证「无效出口被快速、如实地暴露」, 不再空转陪跑。
    """
    stale = 0  # 连续「点击后画面无变化」的退出动作计数(任一动作确认画面变化即清零)
    for _ in range(4):
        if stop_requested():
            return False
        img = eng.screenshot()
        if in_home(eng, img) and not in_garden(eng, img):
            print("  [主界面] 已在自己家园主界面")
            eng.set_scene("家园主界面")
            return True
        if in_list(eng, img):
            # 整屏好友列表面板: 返回键无效, 也不能当"已在主界面"(in_home 已排除),
            # 必须先关掉列表再往家园走 (2026-10-02 根因: 停在这里导致 claim 全程空跑)
            print("  [主界面] 停在好友列表, 先关闭列表")
            leave_friend_list(eng)
            continue
        if has(eng, "确定", img=img) and has(eng, "抱歉", img=img):
            print(f"  [主界面] 关提示框 click_text(['确定']) -> {eng.click_text(['确定'])}")
            wait_until(eng, lambda: not has(eng, "抱歉"), 5, desc="提示框关闭")
            continue
        if in_garden(eng, img):
            leave_garden(eng)
            continue
        if in_delegate_subpage(eng, img):
            # 委托挑战全屏子页: 出口=内容区右上角白圆粉花✕ → 模板定位(合规改造 2026-10-04;
            # 该✕与外壳装饰花不同形, 在子页上外壳花被内容层压住点不动, 必须先点本钮)
            pt = eng.locate_template(TPL_DELEGATE_CLOSE, img=img,
                                     threshold=DELEGATE_CLOSE_TH, region_rel=DELEGATE_CLOSE_REGION)
            if pt is not None:
                print(f"  [主界面] 停在委托挑战子页, 模板命中✕ ({pt.x},{pt.y})")
                eng.click_abs(pt.x, pt.y)
                if wait_screen_change(eng, img, desc="委托子页✕"):
                    stale = 0
                    continue
                print("  [主界面] ✕点击后画面无变化, 换右上角关闭区兜底")
            else:
                print("  [主界面] 委托子页✕模板未命中(delegate_close), 换右上角关闭区兜底")
            click_top_right_close(eng)
            if wait_screen_change(eng, img, desc="委托子页右上角兜底"):
                stale = 0
                continue
            stale += 1
            if stale >= 2:
                print("  [主界面] 连续 2 个退出动作画面均无变化, 如实放弃归位"
                      "(委托子页出口待实机重采, 不再空转)")
                save_escape_evidence(eng, "delegate_subpage")
                return False
            continue
        if in_family_panel(eng, img):
            # 主路径: 外壳右上角花形✕ → 模板定位(合规改造 2026-10-04; 新鲜裁切模板,
            # 弃用 close_family 旧模板——自带背景, 有在其它画面误命中右上角空点的历史)
            pt = eng.locate_template(TPL_SHELL_CLOSE, img=img,
                                     threshold=SHELL_CLOSE_TH, region_rel=SHELL_CLOSE_REGION)
            if pt is not None:
                print(f"  [主界面] 关家族外壳 模板命中花形✕ ({pt.x},{pt.y})")
                eng.click_abs(pt.x, pt.y)
                if wait_screen_change(eng, img, desc="关家族面板"):
                    stale = 0
                    continue
                print("  [主界面] 花形✕点击后画面无变化, 换右上角关闭区兜底")
            else:
                print("  [主界面] 外壳✕模板未命中(shell_close), 换右上角关闭区兜底")
            click_top_right_close(eng)
            if wait_screen_change(eng, img, desc="关家族面板(兜底)"):
                stale = 0
                continue
            stale += 1
            if stale >= 2:
                print("  [主界面] 家族面板关闭后画面无变化, 如实放弃归位"
                      "(不再空转)")
                save_escape_evidence(eng, "family_panel")
                return False
            continue
        print("  [主界面] 未识别场景, 点右上角关闭区")
        click_top_right_close(eng)
        if wait_screen_change(eng, img, desc="右上角兜底"):
            stale = 0
            continue
        stale += 1
        if stale >= 2:
            print("  [主界面] 连续 2 个退出动作画面均无变化, 如实放弃归位")
            save_escape_evidence(eng, "unknown_scene")
            return False
    ok = in_home(eng)
    if ok:
        eng.set_scene("家园主界面")
    return ok


def leave_garden(eng):
    """离开好友花园回到自己家园。失败路径与 ensure_home 共用。

    ⚠ 不用裸 click_text(['离开']) 作为主路径: 引擎 click_text 带「场景均值复核」,
      会按 self._scene 取 click_log 场景分组缓存比对; 若 _scene 仍是上一步遗留的
      「家族活动界面」等场景, 且该场景误录过离开坐标(实测 2026-09-22 误录到左上角),
      会把正确的 OCR 命中(底部右下角)判为误命中并点错位置。
    → 主路径改为**底部栏区域限定**直接定位点击(家园/好友花园的「离开」恒在右下角),
      复核按区域裁掉无关干扰, 不依赖场景缓存; click_text 仅作兜底。

    ⚠ 2026-10-03 实机日志(协作区 zcode-20261004): 「离开」点击常被吞 —— 75s 窗口内
      连续 2 次点击画面纹丝不动, 3×75s 超时 ≈4 分钟才回家。改为**点-验-重试**:
      每次点击后用 wait_screen_change 验证画面真的变了, 无变化立即重点(至多 3 次);
      离开成功后回家等待 75s→30s(点击已验证落地, 30s 足够过场动画; 未到主界面由
      调用方 ensure_home 循环继续处理, 不再干等)。
    """
    for i in range(1, 4):
        if stop_requested():
            return False
        img = eng.screenshot()
        if not in_garden(eng):
            # 已不在花园(可能上一轮点击此刻才落地), 直接进入回家等待
            break
        pt = eng.locate(["离开"], img=img, region_rel=[0.70, 0.88, 1.0, 1.0], min_score=0.5)
        if pt is not None:
            print(f"  [离开] 底部栏定位「离开」({pt.x},{pt.y})")
            eng.click_abs(pt.x, pt.y)
        else:
            print(f"  [离开] 底部栏未OCR到「离开」, 回退 click_text -> {eng.click_text(['离开'])}")
        if wait_screen_change(eng, img, desc=f"点离开(第{i}次)"):
            break
        print(f"  [离开] 第{i}次点击后画面无变化(吞点击), 重试")
    ok = wait_until(eng, lambda: in_home(eng) and not in_garden(eng), 10, desc="回到自己家园")
    if ok:
        eng.set_scene("家园主界面")
    return ok


def leave_friend_list(eng):
    """关闭整屏好友列表面板, 回到自己家园。

    ⚠ 2026-10-02 根因: 采粉完成后画面停在好友列表 → 引擎 close_dialog 反复点 (1216,106) 无效,
      而旧 `in_home` 只判「社交」把列表误判成主界面 → `ensure_home` 直接收工 →
      claim 三个功能整段在列表上空跑 5 分钟。故归位链必须先认出列表并关掉它。
    出口优先「列表右上角 ✕」(与其它整屏面板一致), 未确认离开再试底部栏「离开」。
    ⚠ 待实机校准: 好友列表真实关闭钮尚未定向采集; 若两轮都未确认离开, 按
      `docs/PROJECT_GUIDE.md` §8.3 对「好友列表关闭钮」做一次定向采集后修正本函数。
    ⚠ 2026-10-03 离线排查+用户指认+实机验证: 好友列表**没有任何可见关闭✕** —— 右上角被
      「密友/好友/黑名单/附近/最近/申请」页签列占据(模板在该区最高仅 0.67), 底栏只有
      删除好友/好友设置/添加好友(无「离开」), 旧主路径 click_top_right_close 的区域中心兜底
      恰好点在「密友」页签(1216,57)上, 等于切页签而非关闭。
      真实出口 = 列表面板**左缘中央**的「粉色凸出小抽屉钮 + 白色向右双箭头»」(纯图形, OCR 不可达):
      实测点击 → 列表收起回社交面板视图(frame_diff 0.31)。2026-10-04 合规改造: 该钮已模板化
      (friendlist_exit.png), 不再使用直坐标; 次路径保留底部栏「离开」;
      两轮都失败仍如实报出并存证 escape_fail_friendlist_*.png。
    """
    for i in range(1, 3):
        if stop_requested():
            return False
        img = eng.screenshot()
        if not in_list(eng, img):
            return True
        pt = eng.locate_template(TPL_FRIENDLIST_EXIT, img=img,
                                 threshold=FRIENDLIST_EXIT_TH, region_rel=FRIENDLIST_EXIT_REGION)
        if pt is not None:
            print(f"  [列表] 第{i}次关闭好友列表: 模板命中»钮 ({pt.x},{pt.y})")
            eng.click_abs(pt.x, pt.y)
        else:
            print(f"  [列表] 第{i}次: »钮模板未命中(friendlist_exit), 直接试底部栏「离开」")
        if wait_until(eng, lambda: not in_list(eng), 5, desc=f"关闭好友列表(第{i}次)"):
            return True
        img = eng.screenshot()
        pt = eng.locate(["离开"], img=img, region_rel=[0.70, 0.88, 1.0, 1.0], min_score=0.5)
        if pt is not None:
            print(f"  [列表] 底部栏定位「离开」({pt.x},{pt.y})")
            eng.click_abs(pt.x, pt.y)
            if wait_until(eng, lambda: not in_list(eng), 5, desc=f"离开好友列表(第{i}次)"):
                return True
    ok = not in_list(eng)
    if not ok:
        print("  [列表] 如实报出: 两轮均未确认离开好友列表")
        save_escape_evidence(eng, "friendlist")
    return ok


def open_friend_list(eng):
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
    for attempt in range(1, 4):
        if stop_requested():
            return False
        img = eng.screenshot()
        if in_list(eng, img):
            print("  [列表] 已在好友列表")
            eng.set_scene("好友列表")
            return True
        pt = _panel_friend_pt(eng, img)
        if pt is None:
            if in_home(eng, img) or in_garden(eng, img):
                # 自己家园/好友花园按钮一致(用户 2026-10-05), 统一处理:
                # 点-验-重试(2026-10-04 引入): 「社交」点击常被吞/被气泡遮挡 —— 点击后画面
                # 5s 内必须变化, 无变化立即重点(至多 3 次); 面板等待 15s→5s(定值规则)。
                where = "好友花园" if in_garden(eng, img) else "自己家园"
                print(f"  [列表] 第{attempt}次 在{where} 点「社交」")
                for i in range(1, 4):
                    if stop_requested():
                        return False
                    pre = eng.screenshot()
                    pt_btn = click_btn_fine(eng, ["社交"], img=pre)
                    if pt_btn is not None and wait_screen_change(eng, pre, desc=f"点「社交」(第{i}次)", timeout=5):
                        break
                    if pt_btn is None:
                        print("  [列表] 「社交」常规+滤色精识均未命中, 未产生点击, 重试")
                    else:
                        print("  [列表] 点「社交」后画面无变化(点击被吞), 重试")
                wait_until(eng, lambda: _panel_friend_pt(eng) is not None, 5, desc="社交面板")
                pt = _panel_friend_pt(eng)
            else:
                print(f"  [列表] 第{attempt}次: 场景未知, 先回自己家园")
                ensure_home(eng)
                continue
        if pt is not None:
            print(f"  [列表] 点社交面板内「好友」({pt.x},{pt.y})")
            eng.click_abs(pt.x, pt.y)
            if wait_until(eng, lambda: in_list(eng), 5, desc="好友列表出现"):
                eng.set_scene("好友列表")
                return True
        # 兜底: 列表已在(只是标记未识别)时, 点右侧竖排页签「好友」
        pt = eng.locate(["好友"], exact=True, region_rel=TAB_REGION, min_score=0.4)
        if pt is not None:
            print(f"  [列表] 点右侧页签「好友」({pt.x},{pt.y})")
            eng.click_abs(pt.x, pt.y)
            if wait_until(eng, lambda: in_list(eng), 5, desc="好友列表出现"):
                eng.set_scene("好友列表")
                return True
    print("  [列表] 打开好友列表失败")
    return False


def switch_tab(eng, name):
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


# ---------------- 环节: 翻页 ----------------

def read_page(eng, img=None):
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
                for b in ocr_image(cv2.cvtColor(bin_, cv2.COLOR_GRAY2BGR)):
                    m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", b["text"].strip())
                    if m:
                        return (int(m[1]), int(m[2]))
    return eng.parse_fraction_at(PAGE_REGION, img=img, tol=80)


def read_total(eng):
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


def open_jump_dialog(eng):
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


def _jump_once(eng, n):
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
    adb_key(123)                             # 光标移到行尾
    for _ in range(5):
        adb_key(67)                          # 退格清空(最大两位数, 5 次足够)
    adb_text(str(n))
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


def goto_page(eng, n, tries=3):
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


# ---------------- 环节: 扫描可采粉标记 ----------------

def scan_marks(eng, img=None):
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


def slot_of(eng, y):
    """按当前屏高把 abs y 换算为好友行槽位(分辨率无关)。"""
    return int(round((y / eng.screen_h - ROW_TOP_REL) / ROW_STEP_REL))


def _rescan_skip_failed(eng, failed_y):
    """底行补救段重扫: 跳过已失败标记附近(按 MERGE_Y_REL 聚类)的候选, 防假标记重试风暴。"""
    thr = MERGE_Y_REL * eng.screen_h
    return [m for m in scan_marks(eng)
            if not any(abs(fy - m[1]) <= thr for fy in failed_y)]


# ---------------- 环节: 采集一个好友 ----------------

def collect_one(eng, x, y):
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
        eng.click_abs(hx, hy)
        if wait_until(eng, lambda: in_garden(eng), 15, desc=f"进入好友花园(第{i}次)"):
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
        import os
        import cv2
        diag = os.path.join(os.path.dirname(__file__), "debug", "_enter_garden_fail.png")
        cv2.imwrite(diag, img)
        texts = [b["text"] for b in sorted(ocr_image(img),
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
    empty = has(eng, "抱歉", img=img, min_score=0.3) and has(eng, "确定", img=img, min_score=0.3)
    if empty:
        print(f"    [采集] 无花粉提示 -> click_text(['确定']) {eng.click_text(['确定'])}")
        time.sleep(1.0)
    elif has(eng, "采粉", img=img):
        # 画面已变化但「一键采粉」菜单仍在(2026-10-04, 协作区 zcode-20261004):
        # 旧判据把它当"未确认失败"→ 当晚 7 槽位全 fail、采粉 0 收获。实机观察:
        # 「一键采粉」点击后菜单**不会自动关闭**, 菜单残留属正常态; 点采粉后画面已变化
        # 即采集生效(花粉动画/数值变化)。菜单残留≠失败 —— 判定放宽为成功,
        # 下方统一收菜单。(是否真采到以游戏内花粉数为准, 待实机确认)
        print("    [采集] 采集生效(画面已变化; 快捷菜单未自动关闭属正常), 继续收菜单")
    else:
        print("    [采集] 静默成功(有花粉)")

    img = eng.screenshot()
    if has(eng, "采粉", img=img):            # 菜单必须收起, 否则挡住底部的「社交」
        eng.click_text(["快捷操作"])
        time.sleep(1.5)
    return "empty" if empty else "ok"


# ---------------- 编排: 单类别 ----------------

def run_category(eng, cat, max_pages=30):
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


def run_friend_pollin(eng) -> dict:
    """好友采粉闭环入口。返回 {'密友': n, '好友': m}（打开列表失败该类别记 None）。"""
    print("[好友采粉] 开始闭环: 密友 + 好友 两类逐页采集, 无可采粉则回自己家园")
    ensure_home(eng)
    summary = {}
    for cat in CATEGORIES:
        summary[cat] = run_category(eng, cat)
        if stop_requested():
            break
    print(f"[好友采粉] 闭环结束: {summary}")
    print(f"[好友采粉] 回自己家园 -> {ensure_home(eng)}")
    return summary


# ---------------- 独立调试入口 ----------------

def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "state"
    eng = OCREngine()
    assert eng.connect(), "连接失败"
    if stage == "state":
        img = eng.screenshot()
        print(f"  在列表={in_list(eng, img)} 在主界面={in_home(eng, img)} 在花园={in_garden(eng, img)}")
        print(f"  页码={read_page(eng, img)} 标记={scan_marks(eng, img)}")
        return
    if stage == "all":
        run_friend_pollin(eng)
        return
    raise SystemExit(f"未知 stage {stage}（可用: state / all）")


if __name__ == "__main__":
    main()