# -*- coding: utf-8 -*-
"""pollin 导航与归位：场景判据 / 进园等待 / 右上角关闭 / 回家链 / 离园·关列表。

Stage 5（2026-11-17）自单文件 pollin.py 拆出，函数体与注释原样保留。
依赖方向：primitives + popups → 本模块；list_panel/collect/runner 依赖本模块。
"""
from __future__ import annotations

import time

from core.ports import EnginePort
from ocr_engine import stop_requested

from .constants import (CHAT_COLLAPSE_REGION, CHAT_COLLAPSE_TH, CHAT_COLLAPSE_TPL,
                        CORNER_CLOSE_REGION, CORNER_CLOSE_TEMPLATES,
                        DELEGATE_CLOSE_REGION, DELEGATE_CLOSE_TH,
                        FRIENDLIST_EXIT_REGION, FRIENDLIST_EXIT_TH,
                        SHELL_CLOSE_REGION, SHELL_CLOSE_TH, TPL_DELEGATE_CLOSE,
                        TPL_FRIENDLIST_EXIT, TPL_SHELL_CLOSE, _PINK_CFG, _PINK_MIN)
from .popups import dismiss_no_pollen_popup, no_pollen_popup
from .primitives import (frame_diff, has_social, save_escape_evidence,
                         wait_screen_change, wait_until)


def in_list(eng: EnginePort, img=None, quiet=False):
    """好友列表判据(2026-10-05 迁移至场景注册表): scenes.json「好友列表」=「删除好友」「好友设置」
    任一命中即算(原 LIST_MARKS 常量判据原样迁入, 本函数保留为兼容入口)。
    quiet=True: 轮询内用, 不打印逐次判定(2026-10-24 P2-5, 由调用方汇总)。"""
    return eng.judge_scene("好友列表", img=img, quiet=quiet)


def social_usable(eng: EnginePort, img=None, quiet=False):
    """「底栏可用」判据: 底部导航「社交」可见 **且不在好友列表**。

    ⚠ 这不是场景分类器 —— 只有「社交」命中无法判断任意一个场景; 它的真实用途是判断
      **能不能点底栏的「社交」**: 自己家园主界面、户外主界面、好友花园三种画面都可点
      (用户 2026-10-22 澄清), 所以好友花园上返回 True 是**正确**的。
    ⚠ 若调用方需要的是「已回到自己家园(而不是好友花园)」, 必须用 `at_home_main`
      (ensure_home / 回家链), 不能单独用本函数 —— 好友花园底栏同样有「社交」。
    ⚠ 旧版只判「社交」二字 → 好友列表页也含该字样, 于是被误判成"已在主界面";
      2026-10-02 日志: social 结束停在好友列表, ensure_home 直接收工,
      claim 整段(5 分钟)在好友列表上空跑, 三个功能几乎全未触发。
    ⚠ 2026-10-05 起底层走 scenes.json「户外主界面」(锚点=社交)。
    quiet=True: 重试循环内用, 不打印逐次判定(2026-10-24 P2-5)。
    """
    img = img if img is not None else eng.screenshot()
    if in_list(eng, img, quiet=quiet):
        return False
    return eng.judge_scene("户外主界面", img=img, quiet=quiet)


def at_home_main(eng: EnginePort, img=None):
    """「已回到主线(户外主界面)」判据 = 底栏可用 **且不在任何花园内**(用户 2026-10-22 命名拆分)。

    花园(自己/好友)底栏「社交/家园/离开」与户外同名同位, 只能靠「家园界面」场景区分;
    本函数把这一约束内置, 供 ensure_home / 回家链使用。同帧两次场景判断走帧缓存, 无额外 OCR。
    """
    img = img if img is not None else eng.screenshot()
    return social_usable(eng, img) and not in_garden(eng, img)


def in_garden(eng: EnginePort, img=None, quiet=False):
    """花园判据(自己家园与好友花园**都算**): 「家园界面」场景命中。

    2026-10-24(用户裁定, P2-5): 删除早期「勇气国花园」地点名排除 ——
      ① 当前版本日志中该地名 **89 次探测 0 次命中**(全是 MISS), 纯噪声;
      ② 违反「判据锚定按钮/UI, 不用地点名」原则(地点名会随版本/改名失效)。
    去掉后语义 = 「人在花园里(自己或好友)」, 正是 ensure_home / leave_garden 需要的粒度:
    两处花园的「离开/社交/家园」同名同位(用户 2026-10-05 确认), 业务上不需要区分谁的家。
    quiet=True: 等待循环内用, 不打印逐次判定(2026-10-24 P2-5)。
    """
    img = img if img is not None else eng.screenshot()
    return eng.judge_scene("家园界面", img=img, quiet=quiet)


def in_family_panel(eng: EnginePort, img=None):
    """家族面板判据: 左侧导航「家族首页/家族活动/家族排行」任一命中。

    摇钱树/闪耀等家族活动结束后若关闭按钮没点准, 画面会残留在家族面板;
    该面板是整屏 UI, 按返回键(back)关不掉, ensure_home 需识别并点右上角关闭钮。
    """
    img = img if img is not None else eng.screenshot()
    return eng.locate(["家族首页", "家族排行"], img=img, min_score=0.4) is not None


def in_delegate_subpage(eng: EnginePort, img=None):
    """委托挑战全屏子页判据: 「委托排行」/「距离结束」任一命中。

    该子页(点家族活动网格「闪耀委托挑战」进入)是整屏 UI, 右上角**没有**关闭 X,
    家庭网格的 close_family 模板不会命中(实测恒 0.683); 真实出口是**左上角返回箭头**。
    家族活动 2x2 网格不显示「委托排行/距离结束」, 故可用来区分子页与网格。
    """
    img = img if img is not None else eng.screenshot()
    return eng.locate(["委托排行", "距离结束"], img=img, min_score=0.4) is not None


def wait_enter_garden(eng: EnginePort, timeout=15, desc="进入好友花园", swallowed_hits=2, interval=1.0):
    """C1b(2026-10-22): 等待进入好友花园; 连续 N 次探测仍在**好友列表** -> 判定点击被吞并提前失败。

    原实现只等 `in_garden` 成立, 点击被吞时会把 15s 预算白白耗满(10-22 日志 L466-510:
    8 次探测全部 `好友列表 HIT`, 3 次尝试 × 15s = 45s/标记)。这里加一条“仍在列表”的旁路判据:
    连续 2 次(≥2s)仍 HIT 就立即返回 False, 由调用方重新点击 —— 失败标记从 45s 压到 ~6-10s。
    每次探测只截一张图, `in_garden` 与 `in_list` 共用同一帧(第二次判定走帧缓存, 零额外 OCR)。
    """
    # C49(codex-20261025-2): 先等过场动画停稳再起算 15s —— 20261024 日志 L864:
    # 15s 窗口 3 次探测全「其它」判超时, 超时后下一帧即「家园界面 HIT」(点击已生效,
    # 窗口首段被过场动画吃掉)。等画面停稳可让探测全部落在可判定帧上。
    wait_garden_frame_settled(eng)
    t0 = time.time()
    stuck = 0
    probes = list_n = 0
    while time.time() - t0 < timeout:
        if stop_requested():
            print(f"    [等待] {desc} 收到停止请求, 中断")
            return False
        img = eng.screenshot()
        probes += 1
        # 2026-10-24(P2-5②): 轮询内场景判定静默, 由本函数在出口打一行分布汇总 ——
        # 信息不丢(探测次数/仍在列表次数), 但不再每秒刷一行「好友列表 MISS」。
        if in_garden(eng, img, quiet=True):
            print(f"    [等待] {desc} 命中 ({time.time() - t0:.0f}s, 探测{probes}次: "
                  f"好友列表{list_n}/其它{probes - list_n})")
            return True
        if in_list(eng, img, quiet=True):
            stuck += 1
            list_n += 1
            if stuck >= swallowed_hits:
                print(f"    [等待] {desc} 提前失败: 连续{stuck}次探测仍在好友列表(点击被吞) "
                      f"({time.time() - t0:.0f}s, 不等满{timeout}s, 探测{probes}次)")
                return False
        else:
            stuck = 0
        time.sleep(interval)
    # C49(codex-20261025-2): 窗口末次终末探测 —— 窗口在最后 0~1s 内动画完成时不再误报超时。
    img = eng.screenshot()
    probes += 1
    if in_garden(eng, img, quiet=True):
        print(f"    [等待] {desc} 终末探测命中 "
              f"({time.time() - t0:.0f}s, 探测{probes}次: 好友列表{list_n}/其它{probes - list_n})")
        return True
    print(f"    [等待] {desc} 超时 {timeout}s (探测{probes}次: 好友列表{list_n}/其它{probes - list_n})")
    return False


def wait_garden_frame_settled(eng: EnginePort, timeout=1.5):
    """C49(codex-20261025-2): 点「家园图标」后等画面停稳, 再交给 wait_enter_garden。

    纯帧差判定(零 OCR, 复用 frame_diff, 与 M100 wait_stable 同力学):
    连续两帧差异 < 0.01 视为稳定即返回; 上限 1.5s、采样间隔 0.3s(最坏 5 张截图)。
    收到停止请求立即返回, 交上层如实处理。
    """
    prev = eng.screenshot()
    t0 = time.time()
    while time.time() - t0 < timeout:
        if stop_requested():
            return
        time.sleep(0.3)
        cur = eng.screenshot()
        if frame_diff(prev, cur) < 0.01:
            return
        prev = cur


def click_top_right_close(eng: EnginePort):
    """点右上角关闭钮。整屏面板(家族面板/邮件对话框等)在返回键无效的情况下,
    只能靠点右上角 X 关闭: 依次试模板(各自阈值见 CORNER_CLOSE_TEMPLATES), 命中后须过「粉色一致性」校验。

    E3(2026-10-27, zcode-20261028-4, D12 收窄实施):
    ①**粉色校验**: 复用引擎 pink_ratio_at(F02 公有名, 原 _pink_ratio_at; 与 close_dialog
      verify_pink 同 HSV/同阈值)——
      10-26 双日志实锤: 资料页上 close_corner_pink 0.748-0.753@(1195,99)/(1196,73) 以 0.65 低阈值
      通过并点击, 画面无变化(真 ✕ ≈(1240,30) 形状不同) -> 连续 2 个退出动作无变化 -> 归位放弃,
      ④段被跳过。校验后纯白/非粉候选被弃用, 交回下一模板。
    ②**去掉「无模板命中则盲点区域中心」的为止步操作**: 该盲点属规则 6 禁止的写死坐标点击
      (中心=(0.95w,0.08h) 随分辨率漂移), 且在「什么都不该点」的画面(户外/家园/伙伴页)必然点空或误点;
      无可用候选时如实返回 False, 交 ensure_home 的 stale 计数如实放弃 —— 与 M103 方案C
      「门控后无候选 -> 返回 False」的口径一致。
    """
    img = eng.screenshot()
    if img is None:
        return False
    tol = max(20, int(0.05 * eng.screen_h)) if eng.screen_h else 36
    for tpl, th in CORNER_CLOSE_TEMPLATES.items():
        pt = eng.locate_template(tpl, threshold=th, region_rel=CORNER_CLOSE_REGION, img=img)
        if pt is None:
            continue
        ratio = eng.pink_ratio_at(pt, img, _PINK_CFG, tol)
        if ratio < _PINK_MIN:
            print(f"  [关闭] 右上角候选 {tpl} ({pt.x},{pt.y}) 粉色占比 {ratio:.1%} < {_PINK_MIN:.0%}, "
                  f"判为纯白图标/装饰, 弃用(不点击)")
            continue
        print(f"  [关闭] 右上角模板 {tpl} 命中 ({pt.x},{pt.y}) 粉色 {ratio:.1%} 校验通过")
        eng.click_abs(pt.x, pt.y)
        return True
    print("  [关闭] 右上角无可用关闭候选(模板未命中或纯白否决), 不盲点, 如实返回 False")
    return False


def ensure_home(eng: EnginePort):
    """确保回到自己家园主界面(入口; 实现在 _ensure_home_walk, 判定行为原样)。

    V03(ii)(batch-11): 归位失败(任一退出档连续 2 轮无变化如实放弃 / 收尾仍未确认)时,
    经引擎公有口 note_home_recover_failed 登记「本轮归位已失败」状态, 供 run_module 入口
    对后续模块做**一次** at_home_main 轻验短路(不再每模块重复烧 4 轮归位 —— 2026-11-07
    日志 1180 行起同一卡死画面连累 energy/claim/daily 各跑 4 轮); 本函数自身的失败上报
    口径不变(run_friend_pollin 收尾失败如实上报口径保持, report_failure 无漏发)。
    收到停止请求的返回 False 不登记(用户主动停止, 非归位失败)。
    """
    ok = _ensure_home_walk(eng)
    if not ok and not stop_requested():
        _note_home_recover_failed(eng)
    return ok


def _note_home_recover_failed(eng: EnginePort):
    """V03(ii)(batch-11): 「本轮归位已失败」登记进编排层 —— 走引擎公有口
    note_home_recover_failed(F02 公有面口径, 采集层不触引擎私有成员; 假引擎/桩引擎缺
    该方法时静默跳过, batch-05 mock 单测链不受影响)。纯状态位, 不改任何判定语义。"""
    fn = getattr(eng, "note_home_recover_failed", None)
    if callable(fn):
        fn()


def _ensure_home_walk(eng: EnginePort):
    """确保回到自己家园主界面: 关提示框 -> 离开好友花园 -> 委托子页点左上角返回 -> 关家族面板 -> 兜底点右上角关闭。

    ⚠ 2026-10-03 加固(协作区 zcode-20261003-2): 每个退出动作后用 wait_screen_change 复核画面真的变了;
      无效则升级第二策略; **连续 2 个退出动作画面均无变化即如实放弃归位**。
      背景: 本次日志里委托子页出口 rel(0.035,0.038) 点在「家族」文字标签上, 画面不变却被当成功,
      4 轮 × 各模块(采粉开列表 3 次 × ensure_home 4 轮 + claim 首步)反复空转数分钟。
      出口控件真实位置仍待实机重采(B1); 本函数只保证「无效出口被快速、如实地暴露」, 不再空转陪跑。
    V03(i)(batch-11): 好友列表档/提示框档/花园档原先 `continue` 不递增 stale —— 「列表关不掉」
      类卡死每模块白烧满 4 轮(每轮 30-40s, 花园档最坏 ~2min/轮)。现三档结果全部纳入 stale
      计数(成功清零/失败 +1, 阈值 2 与其它档一致, 对冲「动画慢」漏判风险)。
    """
    stale = 0  # 连续「点击后画面无变化」的退出动作计数(任一动作确认画面变化即清零)
    for _ in range(4):
        if stop_requested():
            return False
        img = eng.screenshot()
        if at_home_main(eng, img):
            print("  [主界面] 已回到主界面(户外)")
            eng.set_scene("家园主界面")
            return True
        if in_list(eng, img):
            # 整屏好友列表面板: 返回键无效, 也不能当"已在主界面"(social_usable 已排除列表),
            # 必须先关掉列表再往家园走 (2026-10-02 根因: 停在这里导致 claim 全程空跑)
            print("  [主界面] 停在好友列表, 先关闭列表")
            # V03(i)(batch-11): 关列表结果纳入 stale 计数(旧版 continue 不计数 —— 列表
            # 关不掉类卡死每模块白烧 4 轮; 阈值 2 与其它档一致)。失败存证已由
            # leave_friend_list 内部如实落盘(tag=friendlist), 此处不重复存证。
            if leave_friend_list(eng):
                stale = 0
            else:
                stale += 1
                if stale >= 2:
                    print("  [主界面] 好友列表连续 2 轮关闭未确认, 如实放弃归位(不再空转)")
                    return False
            continue
        if no_pollen_popup(eng, img):
            print("  [主界面] 关「没有花粉」提示框 -> 点「确定」")
            if dismiss_no_pollen_popup(eng, img):
                stale = 0
            else:
                stale += 1
                if stale >= 2:
                    print("  [主界面] 「没有花粉」提示框连续 2 轮关闭未确认, 如实放弃归位(不再空转)")
                    save_escape_evidence(eng, "prompt_box")
                    return False
            continue
        if in_garden(eng, img):
            # V03(i)(batch-11): 离园结果纳入 stale 计数(旧版 continue 不计数 —— 花园档最坏
            # ~2min/轮 × 4; leave_garden 内部点-验-重试 3 次仍失败才计 1 档, 阈值 2 不变)。
            if leave_garden(eng):
                stale = 0
            else:
                stale += 1
                if stale >= 2:
                    print("  [主界面] 离开花园连续 2 轮未确认回家, 如实放弃归位(不再空转)")
                    save_escape_evidence(eng, "garden")
                    return False
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
        pt_chat = eng.locate_template(CHAT_COLLAPSE_TPL, img=img,
                                      threshold=CHAT_COLLAPSE_TH, region_rel=CHAT_COLLAPSE_REGION)
        if pt_chat is not None:
            print(f"  [主界面] 侧栏面板塌陷舌台(≪)命中 ({pt_chat.x},{pt_chat.y}) -> 点其收起(聊天面板唯一出口)")
            eng.click_abs(pt_chat.x, pt_chat.y)
            if wait_screen_change(eng, img, desc="侧栏面板收起"):
                stale = 0
                continue
            print("  [主界面] ≪ 点击后画面无变化, 落入后续分支")
            stale += 1
            if stale >= 2:
                print("  [主界面] 连续 2 个退出动作画面均无变化, 如实放弃归位")
                save_escape_evidence(eng, "chat_panel")
                return False
            continue
        pt_fashion = eng.locate(["服装"], img=img, min_score=0.5,
                                region_rel=[0.0, 0.0, 0.12, 0.10])
        if pt_fashion is not None:
            # E3(2026-10-27, zcode-20261028-4): 服装圣殿系页面出口 —— 左上「服装」页签=整页返回。
            # 2026-10-27 实采实锤: 伙伴页(我的花宝)覆盖在服装圣殿上, 右上角粉 ✕(1245,27) 属底层
            # 服装圣殿且被模态层吃点击(模板 0.96-0.98 命中、点击无效), 引擎 close_dialog/ensure_home
            # 角区档全部无效; 实测点左上「服装」即整页回主界面。region 限定左上角, 主界面右栏
            # 「服装」(x≈0.96) 与「服装圣殿」(x≈0.95) 均被排除。
            print(f"  [主界面] 服装圣殿系页面(左上「服装」在屏) -> 点其返回 ({pt_fashion.x},{pt_fashion.y})")
            eng.click_abs(pt_fashion.x, pt_fashion.y)
            if wait_screen_change(eng, img, desc="服装圣殿返回"):
                stale = 0
                continue
            print("  [主界面] 「服装」点击后画面无变化, 落入角区档")
            stale += 1
            if stale >= 2:
                print("  [主界面] 连续 2 个退出动作画面均无变化, 如实放弃归位")
                save_escape_evidence(eng, "fashion_page")
                return False
            continue
        # ⚠ 主 agent 修复 Bug③(里程碑 93): 未识别场景分支原先**只有角区档**(click_top_right_close:
        #   角区模板 — 本事故里 close_family 0.705<0.92 / close_corner_pink 0.647<0.65 全 MISS —
        #   然后盲点角区中心 (1216,57)), 对「真钮在角区外且需标题锚点」的面板(如 在线礼包 真钮 (1105,97),
        #   注册表条目 3 anchor_color dx_range=[700,1100])**完全无能** -> 12 次空转 ≈4.5min 直至类别中止。
        #   同轮 energy 用一次锚点关闭即关掉该面板 => 是**选型**缺口, 非引擎能力缺失。
        #   修法: 在角区档**之前**插入锚点档(only_types=["anchor_color"], 须 OCR 读到面板标题才动作
        #   —— 花园/横幅画面无标题, 天然零动作; 注册表条目 3 的 _note 有 2026-09-30 实测佐证)。
        #   锚点档只有**画面真的变了**才算成功; 不动作/无变化则落回存量角区档(放弃阈值「连续 2 次」不变)。
        print("  [主界面] 未识别场景, 先试锚点关闭档(须读到面板标题才动作)")
        if eng.close_dialog(only_types=["anchor_color"]):
            if wait_screen_change(eng, img, desc="锚点关闭未识别面板"):
                stale = 0
                continue
            print("  [主界面] 锚点关闭已动作但画面无变化, 落回右上角角区档")
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
    ok = at_home_main(eng)
    if ok:
        eng.set_scene("家园主界面")
    return ok


def leave_garden(eng: EnginePort):
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
    ok = wait_until(eng, lambda: at_home_main(eng), 10, desc="回到自己家园")
    if ok:
        eng.set_scene("家园主界面")
    return ok


def leave_friend_list(eng: EnginePort):
    """关闭整屏好友列表面板, 回到自己家园。

    ⚠ 2026-10-02 根因: 采粉完成后画面停在好友列表 → 引擎 close_dialog 反复点 (1216,106) 无效,
      而旧版 `in_home`(现 `social_usable`) 只判「社交」把列表误判成主界面 → `ensure_home` 直接收工 →
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
      (friendlist_exit.png), 不再使用直坐标。
    ⚠ 2026-11-07 删除旧的次路径「OCR ['离开'] @[0.7,0.88,1.0,1.0]」: 该区域在好友列表里只有
      「删除好友 / 好友设置 / 添加好友」, 全项目从无「离开」二字 —— 这条兜底结构上永不可能命中,
      留着只会每次白等 5s 再空搜一次(日志 48 次 leave_miss 全由此产生)。现改为: 模板未命中即
      如实说明并按新帧重试一轮, 两轮都不中则报失败并存证, 不留假路径。
    """
    for i in range(1, 3):
        if stop_requested():
            return False
        img = eng.screenshot()
        if not in_list(eng, img):
            return True
        pt = eng.locate_template(TPL_FRIENDLIST_EXIT, img=img,
                                 threshold=FRIENDLIST_EXIT_TH, region_rel=FRIENDLIST_EXIT_REGION)
        if pt is None:
            print(f"  [列表] 第{i}次: »钮模板未命中(friendlist_exit, 阈值{FRIENDLIST_EXIT_TH}), 不盲点, 重截一帧重试")
            continue
        print(f"  [列表] 第{i}次关闭好友列表: 模板命中»钮 ({pt.x},{pt.y})")
        eng.click_abs(pt.x, pt.y)
        if wait_until(eng, lambda: not in_list(eng, quiet=True), 5, desc=f"关闭好友列表(第{i}次)"):
            return True
    ok = not in_list(eng)
    if not ok:
        print(f"  [列表] 如实报出: 两轮均未确认离开好友列表(模板阈值 {FRIENDLIST_EXIT_TH})")
        save_escape_evidence(eng, "friendlist")
    return ok
