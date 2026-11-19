"""关闭按钮注册表 + close_dialog 关闭链 + 顶部菜单自愈。

E01(batch-03, 2026-11-14) 自单文件 ocr_engine.py 机械拆包: 本文件各段为原文件对应
行段的**逐行原文**(唯 __file__ 锚点因包层级 +1 机械重锚定, 见 ast_hash_compare.py
allowlist)。行为等价口径: 帧集回归 0 退化 + 闸门全绿 + import 面零改动。
原行段映射: evidence/batch-03/tiles_manifest.json。
"""
from __future__ import annotations

import json
import time

import numpy as np

from .._constants import CLOSE_BUTTONS_PATH

class _CloseButtonMixin:
    # ---- 关闭按钮特殊逻辑注册表 ----
    def _load_close_buttons(self) -> list:
        """加载『关闭按钮-特殊逻辑』注册表 (data/close_buttons.json)。
        每个条目是一种关闭按钮的定位逻辑; 找关闭按钮时会依次遍历。
        """
        try:
            if CLOSE_BUTTONS_PATH.exists():
                with open(CLOSE_BUTTONS_PATH, encoding="utf-8") as fp:
                    data = json.load(fp)
                    if isinstance(data, list):
                        return data
        except Exception as e:
            print(f"[关闭按钮注册表加载失败] {e}")
        return []

    def _save_close_buttons(self) -> None:
        CLOSE_BUTTONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CLOSE_BUTTONS_PATH, "w", encoding="utf-8") as fp:
            json.dump(self.close_buttons, fp, ensure_ascii=False, indent=2)

    def register_close_button(self, new_entry: dict) -> None:
        """新增/更新一种关闭按钮特殊逻辑到注册表 (按 name 去重) 并持久化。"""
        for i, e in enumerate(self.close_buttons):
            if e.get("name") == new_entry.get("name"):
                self.close_buttons[i] = new_entry
                break
        else:
            self.close_buttons.append(new_entry)
        self._save_close_buttons()
        print(f"[注册表] 已保存关闭按钮特殊逻辑: {new_entry.get('name')}")

    def pink_ratio_at(self, pt, img, color_cfg: dict, tol: int) -> float:
        """统计命中点附近小窗口内「粉色」像素占比。

        2026-10-24: 用于『粉色关闭钮』的二次校验。右上角的「收起菜单」是**纯白箭头**(无文字),
        与 close_corner_pink.png(白圆+粉花) 的背景/白色轮廓相近, 实测能以 0.865 骗过 0.85 阈值,
        点下去会收起右侧功能菜单 → 手账/在线礼包等按钮消失, 后续模块整段失效。
        真关闭钮必然带粉色(粉花或粉圆钮), 模板本体实测粉色占比 5.6%;
        白色箭头窗口内为 0.0%。用该占比做「纯白图标」否决项。

        F02(batch-05, 2026-11-14): 提为公有 API —— 采集层 pollin.click_top_right_close 经
        此做粉色校验(原私有跨界 `eng._pink_ratio_at`, 协议化后走公有面, 引擎可被假引擎
        mock 替换单测)。私有名 `_pink_ratio_at` 以类体内别名保活一个版本(引擎内部 2 处
        调用点照旧, 回退/revert 无外部可见影响)。
        """
        import cv2
        import numpy as np
        h, w = img.shape[:2]
        x1, y1 = max(0, pt.x - tol), max(0, pt.y - tol)
        x2, y2 = min(w, pt.x + tol), min(h, pt.y + tol)
        patch = img[y1:y2, x1:x2]
        if patch.size == 0:
            return 0.0
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array(color_cfg["hsv_lower"]),
                           np.array(color_cfg["hsv_upper"]))
        return float(cv2.countNonZero(mask)) / float(mask.size)

    # F02(batch-05): 私有名保活别名 —— 旧调用点(self._pink_ratio_at, 本文件 2 处)语义零变化;
    # 一个版本后(约 batch-12 实机窗口)可连同调用点一并收编为公有名。
    _pink_ratio_at = pink_ratio_at

    def _locate_close_by_entry(self, entry: dict, img, w, h, quiet: bool = False):
        """按单条『关闭按钮-特殊逻辑』注册项尝试定位。
        返回 `(Point, channel, score)` 或 None；channel ∈ `anchor` / `template` / `color`。
        score 仅模板通道有值(1−sqdiff)，供 P1-2 批2 在同通道内排序；
        锚点(靠标题文字自证)与色块(无相似度概念)不参与跨通道比分数。
        quiet=True: 不打印（点后复检用，避免常态 MISS 刷屏）。
        """
        t = entry.get("type")
        color = entry.get("color", {})
        if t == "anchor_color":
            pt = self.locate_anchor_color(
                entry.get("anchor", "提示"), color,
                dx_range=entry.get("dx_range", (150, 400)),
                dy_tol=entry.get("dy_tol", 60),
                img=img, min_score=entry.get("min_score", 0.4), quiet=quiet)
            return (pt, "anchor", None) if pt is not None else None
        if t in ("corner", "corner_white", "corner_pink_small"):
            # region_rel: [x1,y1,x2,y2] 相对坐标(0~1) → 转绝对坐标
            rx = entry.get("region_rel", [0.82, 0.0, 1.0, 0.18])
            region_abs = [max(0, int(rx[0] * w)), max(0, int(rx[1] * h)),
                          min(w, int(rx[2] * w)), min(h, int(rx[3] * h))]
            # 支持模板优先: 注册项带 template 字段时, 先在该区内做模板匹配(纯图形关闭钮更稳);
            # 未命中再回退原颜色特征定位。
            tpl = entry.get("template")
            if tpl:
                rr = [rx[0], rx[1], rx[2], rx[3]]
                got = self.locate_template(tpl, img=img,
                                           region_rel=rr,
                                           threshold=entry.get("template_threshold", 0.8),
                                           return_score=True, quiet=quiet)
                pt, score = got if got is not None else (None, None)
                # 2026-10-24: 粉色一致性否决 —— 纯白图标(右上角「收起菜单」箭头)会以中等分
                # 误命中粉色关闭模板; 模板命中点附近没有粉色块时弃用, 交回下面的颜色兜底。
                if pt is not None and entry.get("verify_pink") and color:
                    tol = max(20, int(0.05 * h))
                    ratio = self._pink_ratio_at(pt, img, color, tol)
                    need = float(entry.get("verify_pink_ratio", 0.02))
                    if ratio < need:
                        if not quiet:
                            print(f"[关闭按钮] '{entry.get('name', '?')}' 模板命中({pt.x},{pt.y})"
                                  f" 但附近粉色占比 {ratio:.1%} < {need:.0%}, 判为纯白图标, 弃用")
                        pt = None
                # V01-b(batch-11): 条目级 verify_color 颜色校验注册 —— 机制=verify_pink 同款
                # (pink_ratio_at 的 HSV 窗口占比校验, 由「粉色专用」推广为任意颜色窗口;
                # 方案锚点 07 笔记 V01-b, 应对 TM_SQDIFF 低对比塌缩下「分数不可信 → 颜色自证」路线)。
                # ⚠ 本批**只挂观测**: 逐钮 HSV 窗口实测定值属 batch-12 采样执行项, 定值回填前
                # 不参与判定(不否决候选, 天然可回退); 条目未配 verify_color 时零动作零输出。
                # batch-12 回填定值后再接否决分支(同 verify_pink 的 ratio<need 弃用路径)。
                vcfg = entry.get("verify_color")
                if isinstance(vcfg, dict) and vcfg.get("hsv_lower") is not None \
                        and pt is not None and not quiet:
                    vtol = max(20, int(0.05 * h))
                    vratio = self._pink_ratio_at(pt, img, vcfg, vtol)
                    vneed_s = (f"观测阈值 {float(vcfg['ratio_min']):.0%}"
                               if vcfg.get("ratio_min") is not None
                               else "阈值未定(待 batch-12 采样)")
                    print(f"[关闭按钮] '{entry.get('name', '?')}' verify_color 观测: "
                          f"({pt.x},{pt.y}) HSV 窗口占比 {vratio:.1%} / {vneed_s}"
                          f" —— 本批仅观测不否决(HSV 定值回填后才参与判定)")
                if pt is not None:
                    return (pt, "template", score)
            cfg = dict(color)
            cfg["region"] = region_abs
            pt = self.locate_color(cfg, img=img)
            return (pt, "color", None) if pt is not None else None
        return None

    def find_all_close_buttons(self, img=None, only_types=None) -> list:
        """遍历『关闭按钮-特殊逻辑』注册表, 返回**所有**可定位到的关闭按钮候选。
        每个已注册类型一个条目 `{"name":..., "type":..., "pt": Point}`, 未命中/异常类型不入列。
        支持的特殊逻辑 type:
          - "anchor_color": 以锚点文字(如「提示」)为锚, 在其右侧 dx_range 内按颜色找关闭按钮
          - "corner": 在画面固定相对区域(如右上角)按颜色找关闭按钮

        2026-10-24(P1-1): 新增 only_types —— **遍历前**跳过不在白名单里的条目。
        原先 close_dialog 是「先全表定位、后按类型过滤」, 指定 only_types 时仍会白跑其它类型的
        OCR 锚点(实测每个 close_dialog 多打 3 次 `[锚点定位] 未找到…` + 2~4 次无关模板匹配),
        一轮 31 分钟日志里 `['跳转页签']` 这类无效锚点探测共 30 次。
        """
        img = img if img is not None else self.screenshot()
        w, h = self.screen_w, self.screen_h
        allowed = None
        if only_types is not None:
            allowed = {only_types} if isinstance(only_types, str) else set(only_types)
        hits = []
        for entry in self.close_buttons:
            name = entry.get("name", "?")
            if allowed is not None and entry.get("type") not in allowed:
                continue
            try:
                res = self._locate_close_by_entry(entry, img, w, h)
            except Exception as e:
                print(f"[关闭按钮] 逻辑 '{name}' 执行异常: {e}")
                res = None
            if res is not None:
                pt, channel, score = res
                hits.append({"name": name, "type": entry.get("type"), "pt": pt,
                             "channel": channel, "score": score,
                             "score_base": entry.get("score_base"),
                             "rank_last": bool(entry.get("rank_last")), "entry": entry})
        return hits

    def find_close_button(self, img=None) -> "Point | None":
        """遍历注册表返回**第一个**命中的关闭按钮; 全未命中返回 None。
        （兼容调用方/--close-test; 需要"逐个试所有类型"请用 find_all_close_buttons() 或 close_dialog()）
        """
        hits = self.find_all_close_buttons(img=img)
        if hits:
            h = hits[0]
            print(f"[关闭按钮] 特殊逻辑 '{h['name']}' 命中 -> {h['pt'].x},{h['pt'].y}")
            return h["pt"]
        return None

    def _verify_close_candidate(self, hit: dict, wait: float) -> bool:
        """点后复检: 该候选的“存在证据”是否已消失（P1-2 批2）。

        比全屏帧差更准：只复核**该候选自身**，不受无关动画/滚动干扰。
          · 锚点 → 标题文字/锚点侧按钮不再命中
          · 模板 → 同模板在同一区域已低于阈值
          · 色块 → 该区域不再有匹配色块
        复检走 `quiet=True`，不刷常态 MISS 日志。
        """
        time.sleep(max(0.2, float(wait)))
        img = self.screenshot()
        if img is None:
            return False
        entry = hit.get("entry")
        if not entry:
            return False
        try:
            res = self._locate_close_by_entry(entry, img, self.screen_w, self.screen_h, quiet=True)
        except Exception:
            res = None
        return res is None

    def close_dialog(self, img=None, anchor_kw="提示", dx_range=(150, 400),
                     dy_tol=60, min_score=0.4, only_types=None,
                     verify_wait: float = 1.2, max_tries: int = 2) -> bool:
        """关闭通用弹窗（P1-2 批2 起：语义优先 → 同通道分数 → 点后复检 → 至多 2 次）。

        选择顺序：
          1) **Tier 1 锚点**（anchor_color）：靠面板标题文字自证，按注册表顺序先试；
          2) **Tier 2 其余候选**：模板通道内按模板分降序；纯色块用 `score_base`（默认 0.60，
             `corner_white` 在 JSON 里配 0.70）——**不做跨通道分数比较**；
          3) 每次点击后用 `_verify_close_candidate` 复核；未关闭才试下一个，最多 `max_tries` 次。

        共享小✕门控（2026-10-24 用户裁定）：`corner_pink_small` 在通用链里仍参与（大多数面板关闭
        就是这枚 ✕），但当前帧若命中**户外主界面 / 家园界面 / 好友列表**（这些画面有右上角「收起菜单」
        且没有面板可关）则跳过；调用方**显式 `only_types`** 点名时不受门控。

        only_types: 可选, 字符串或类型列表; 仅在注册表中挑选指定类型, **遍历前**过滤（P1-1）。
        （anchor_kw/dx_range/dy_tol 参数仅为兼容旧调用保留, 实际以注册表为准。）
        返回语义保持旧版：**True=至少点击了一次**（不表示“已验证关闭”），False=没有可用候选。
        """
        img = img if img is not None else self.screenshot()
        hits = self.find_all_close_buttons(img=img, only_types=only_types)
        if not hits:
            # 2026-11-19: 「等级提升 / 已全部解锁 + 点击任意处关闭」全屏覆盖层没有右上角✕。
            # 旧链在 claim/daily 的 ensure_home 里连续空转直至模块软失败; 交给 reward 原语:
            # 标题优先点击(弹窗内部, 无穿透), 页脚仅兜底。
            if self.has_reward_popup(img=img):
                print("[关闭弹窗] 无常规关闭按钮, 检测到「点击任意处关闭」覆盖层 -> 按奖励弹窗关闭")
                if self.reward_dialog({"wait": 0.0, "tries": 2, "required": False,
                                       "quiet": True, "name": "全屏覆盖层"}):
                    return True
            print("[关闭弹窗(only_types)] 未定位到匹配类型的关闭按钮")
            return False

        def _fmt(x):
            s = x.get("channel") or "?"
            if x.get("score") is not None:
                s += f" {x['score']:.3f}"
            elif x.get("score_base") is not None:
                s += f" base {float(x['score_base']):.2f}"
            return f"'{x['name']}' ({x['type']}, {s})"

        # 主界面门控（2026-10-24 用户裁定「这些画面有右上角关闭菜单按键」）：
        # 共享小✕ 与纯白圆都可能在 户外/家园/好友列表 命中「收起菜单」白箭头/空白，
        # 通用链整体跳过它们；显式 only_types 视为调用方已确知面板开着，不受门控。
        # corner(粉色花钮) 不受门控 —— 它已有 verify_pink 保护，且花园上的家族面板需要它。
        GATE_TYPES = ("corner_pink_small", "corner_white")
        gated = False
        if only_types is None and any(x["type"] in GATE_TYPES for x in hits):
            on_main = any(self.judge_scene(n, img=img, quiet=True)
                          for n in ("户外主界面", "家园界面", "好友列表"))
            if on_main:
                gated = True
                dropped = [x for x in hits if x["type"] in GATE_TYPES]
                # 2026-11-07: 把「被排除的是谁、什么分、在哪」一并打印, 便于下次排查
                # (好友列表的真出口是左缘 » 钮, 这里的小✕本就是误命中, 门控正确; 不改点击逻辑)。
                print("[关闭弹窗] 当前为主界面(户外/家园/好友列表): 共享小✕/纯白圆不参与(防收起菜单/空白误点); "
                      "排除候选: " + " | ".join(_fmt(x) for x in dropped))
                hits = [x for x in hits if x["type"] not in GATE_TYPES]
                if not hits:
                    print("[关闭弹窗] 门控后无候选")
                    return False

        def _eff(x):
            if x.get("score") is not None:
                return float(x["score"])
            return float(x.get("score_base") or 0.60)

        anchors = [x for x in hits if x.get("channel") == "anchor"]
        # rank_last 条目(共享小✕)永久排在 Tier 2 末尾：它在任意画面都能 0.9x 命中，
        # 拿原始分与独立关闭钮比较会反客为主（推荐活动页实测 0.911 > corner 色块 0.60）；
        # 但“大多数面板关闭就是这枚 ✕”仍然成立 —— 它是唯一候选时照常点击。
        rest = [x for x in hits if x.get("channel") != "anchor"]
        rest.sort(key=lambda x: (bool(x.get("rank_last")), -_eff(x)))
        ordered = anchors + rest
        # 同点去重：不同条目可能定位到同一颗按钮（corner 色块 / corner_white 白圆 / family 色块），
        # 重复点同一坐标 = 多余点击 + 双击风险 → 只保留排名最高的一个。
        tol = max(8, int(0.01 * (self.screen_w or 1280)))
        uniq = []
        for h in ordered:
            if any(abs(h["pt"].x - u["pt"].x) <= tol and abs(h["pt"].y - u["pt"].y) <= tol
                   for u in uniq):
                continue
            uniq.append(h)
        if len(uniq) < len(ordered):
            print(f"[关闭弹窗] 合并同点候选 {len(ordered) - len(uniq)} 个(防重复点击同一按钮)")
        ordered = uniq
        print("[关闭弹窗] 候选: " + " | ".join(_fmt(x) for x in ordered)
              + ("  (小✕已门控)" if gated else ""))

        tries = max(1, int(max_tries))
        clicked = 0
        for i, h in enumerate(ordered[:tries], 1):
            pt = h["pt"]
            print(f"[关闭弹窗] 第{i}次选中 {_fmt(h)} -> {pt.x},{pt.y}")
            self.click_abs(pt.x, pt.y)
            self._log_click("弹窗关闭", [anchor_kw], pt, "color")
            clicked += 1
            if self._verify_close_candidate(h, verify_wait):
                print(f"[关闭弹窗] 已确认关闭(复检: {h.get('channel')}证据消失, 等待{verify_wait:g}s)")
                return True
            if i < min(tries, len(ordered)):
                print("[关闭弹窗] 未确认关闭 -> 尝试下一候选")
        print(f"[关闭弹窗] {clicked} 次点击后仍未确认关闭(如实报出; 返回 True=已点击, 交调用方复核)")
        return True

    def ensure_menu_expanded(self, step: dict | None = None) -> bool:
        """顶部活动菜单被「收起菜单」折叠时, 点右上角白色箭头展开(2026-10-24 P1-3)。

        背景: 2026-10-24 实机日志里 close_dialog 误点右上角「收起菜单」纯白箭头 → 顶部菜单整排
        收起, `手账`/`在线礼包` 入口消失 → claim 在线礼包静默跳过、daily 手账整模块失败。
        误点本身已由 close_buttons.json 的 `verify_pink` 拦住; 本方法负责**已处于收起态**时的自愈
        (人工误点 / 上一轮遗留 / 其它路径收起)。

        判据(全部满足才动作):
          ① 常驻入口「推荐活动」在屏 → 确认当前有顶部菜单带;
          ② 「手账」与「在线礼包」都读不到 → 收起态特征(展开态二者必有其一);
          ③ 右上角 collapse_menu.png 命中(默认阈值 0.95) 且命中点附近**没有粉色**
             (占比 < 2%) —— 收起态白箭头实测 0.0%; 推荐活动页右上角的粉色✕实测 8.9%/9.1%,
             会被粉色否决; 且该✕在区域内的模板分更低, 双保险。
        动作: 点一次箭头 → 等 1.5s → 复检; 仍未展开只告警(返回 False), 不抛错、不登记失败。
        返回 True=已展开 / 无需动作(含「疑似收起但箭头未确认」——宁可不动);
        False=点击箭头后仍未能确认展开(只告警)。
        """
        step = step or {}
        region = step.get("region_rel") or [0.94, 0.035, 1.0, 0.10]
        threshold = float(step.get("threshold", 0.95))
        pink_max = float(step.get("pink_max", 0.02))
        wait = float(step.get("wait", 1.5))
        img = self.screenshot()
        if img is None:
            return True
        hit = self._kw_hits(self._scene_blocks(img, 0.4), ["推荐活动", "手账", "在线礼包"])
        if "手账" in hit or "在线礼包" in hit:
            return True                      # 展开态: 入口可见, 不动
        if "推荐活动" not in hit:
            return True                      # 不在有顶部菜单的画面, 不动
        pink_cfg = {"hsv_lower": [150, 80, 90], "hsv_upper": [175, 255, 255]}
        got = self.locate_template("collapse_menu.png", img=img,
                                   region_rel=region, threshold=threshold, return_score=True)
        pt, tpl_score = got if got is not None else (None, None)
        if pt is None:
            print("[菜单] 疑似收起(推荐活动在屏/手账与在线礼包均不可见), 但右上角箭头未命中 -> 不动作")
            return True
        # 2026-10-26(codex-20261025-7 实机反馈): 收起态的箭头模板分可达 0.982, 但同窗口内的
        # 邻近粉色装饰会把粉色占比推到 14.9% -> 旧逻辑错误否决、菜单无法自愈。
        # 高分(≥0.96)已足以确认是 arrow 本体, 跳过粉色否决; 低分候选仍保留否决
        # (推荐活动页右上角粉色✕的模板分低于箭头, 由阈值+粉色双保险拦住)。
        if tpl_score is not None and tpl_score >= 0.96:
            print(f"[菜单] 箭头模板分 {tpl_score:.3f} ≥ 0.96, 跳过粉色否决(高置信白箭头)")
        else:
            ratio = self._pink_ratio_at(pt, img, pink_cfg, max(20, int(0.05 * self.screen_h)))
            if ratio >= pink_max:
                print(f"[菜单] 右上角候选({pt.x},{pt.y})粉色占比 {ratio:.1%} ≥ {pink_max:.0%}, "
                      f"判为粉色关闭钮/其它图标(非收起箭头), 不动作")
                return True
        print(f"[菜单] 顶部菜单已收起(手账/在线礼包均不可见) -> 点右上角箭头 ({pt.x},{pt.y}) 展开")
        self.click_abs(pt.x, pt.y)
        time.sleep(wait)
        img2 = self.screenshot()
        if img2 is None:
            return False
        hit2 = self._kw_hits(self._scene_blocks(img2, 0.4), ["手账", "在线礼包"])
        if hit2:
            print(f"[菜单] 展开成功: {sorted(hit2)} 已可见")
            return True
        print("[菜单] 箭头已点击, 但仍未读到手账/在线礼包 -> 如实告警(不判失败, 交后续步骤)")
        return False
