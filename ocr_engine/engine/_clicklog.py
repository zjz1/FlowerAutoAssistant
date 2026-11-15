"""点击日志知识库 + 立体化分级复核。

E01(batch-03, 2026-11-14) 自单文件 ocr_engine.py 机械拆包: 本文件各段为原文件对应
行段的**逐行原文**(唯 __file__ 锚点因包层级 +1 机械重锚定, 见 ast_hash_compare.py
allowlist)。行为等价口径: 帧集回归 0 退化 + 闸门全绿 + import 面零改动。
原行段映射: evidence/batch-03/tiles_manifest.json。
"""
from __future__ import annotations

import json
import time

from .._constants import CLICK_LOG_PATH
from ocr_ui import ocr_image

class _ClickLogMixin:
    # ---- 点击日志 (持久化知识库) ----
    # 磁盘格式(version 2, 两层嵌套): {"version":2, "scenes": {场景名: {按钮名: {记录, "category":类别}}}}
    # 兼容: 旧扁平格式 {"按钮名": {记录}} 加载时自动收敛到 "未分类" 场景。
    @staticmethod
    def _build_flat_index(scenes: dict) -> dict[str, dict]:
        """把场景嵌套结构收敛为 按钮名->记录 扁平索引(跨场景同名取最后一个)。"""
        flat: dict[str, dict] = {}
        for scene, buttons in scenes.items():
            for name, entry in buttons.items():
                flat[name] = entry
        return flat

    def _load_click_log(self) -> dict[str, dict[str, dict]]:
        """加载知识库并转为 场景->按钮->记录 两级嵌套。旧扁平格式自动归入「未分类」。"""
        try:
            if CLICK_LOG_PATH.exists():
                with open(CLICK_LOG_PATH, encoding="utf-8") as fp:
                    data = json.load(fp)
                if isinstance(data, dict):
                    if "scenes" in data and isinstance(data["scenes"], dict):
                        return data["scenes"]
                    # 旧扁平格式: 每条记录若有 scene 字段则按其归组, 否则归「未分类」
                    scenes: dict[str, dict[str, dict]] = {}
                    for name, entry in data.items():
                        sc = (entry or {}).get("scene") or "未分类"
                        scenes.setdefault(sc, {})[name] = entry
                    return scenes
        except Exception as e:
            print(f"[点击日志加载失败] {e}")
        return {}

    def _save_click_log(self) -> None:
        CLICK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CLICK_LOG_PATH, "w", encoding="utf-8") as fp:
            json.dump({"version": 2, "scenes": self.click_log_scenes}, fp,
                      ensure_ascii=False, indent=2)

    def _log_click(self, name: str, keywords, pt: "Point", method: str,
                   scene: str | None = None, category: str | None = None) -> None:
        """记录一次成功点击: 按钮名 + 文本 + 相对坐标 + 绝对坐标, 按场景分组存储。
        scene 缺省用 self._scene; 同场景同名按钮只保留一次(跨场景互不覆盖)。
        旧条目中人工标注的扩展字段(anchor/color/scene/note/category)会被保留, 不被自动日志覆盖。
        全局开关 `log_click_pos`(data/config.json, **默认 false**) 关闭时本方法直接返回, 不做任何记录:
        历史坐标一旦写错会被回退链放大成系统性误点(2026-10-03「切换账号」误登录), 故默认不记。
        注意: 只 gate「引擎运行时的自动记录」; 人工标注(`/tpltool` 提交后写库)或直接编辑
        `data/click_log.json` 是显式动作, 不受此开关影响。
        """
        if not self.config.get("log_click_pos", False):
            # 全局开关「记录按钮位置」(log_click_pos) 默认关闭: 运行时不再把点到的坐标写入知识库
            # data/click_log.json。历史坐标一旦写错, 会被回退链反复放大成系统性误点
            # (2026-10-03「切换账号」误登录即此链路), 故默认不记 —— 由用户显式开启后再积累样本。
            # 注意: 只 gate「运行时自动记录」; 人工标注/直接编辑 click_log.json 是用户显式动作, 不受此开关影响。
            # 提示只打印一次: 每次点击都刷一行会把日志淹掉(性能/可读性)。
            if not getattr(self, "_logpos_notice_done", False):
                self._logpos_notice_done = True
                print("[记录] 记录按钮位置已关闭(log_click_pos=false), 运行时点击坐标不写入知识库(本提示只打一次)")
            return
        kws = keywords if isinstance(keywords, list) else [keywords]
        sc = scene or self._scene or "未分类"
        old = (self.click_log_scenes.get(sc) or {}).get(name) or {}
        # 缓存回退(fallback)不产生新位置证据 → 一律不落库。
        # 曾只挡「已有 ocr/color/anchor 条目」的情形；旧条目本身就是 fallback 时会再次写入, 错坐标被固化并
        # 自我强化：2026-10-03 日志里「切换账号」正是被历史 fallback 坐标(0.7727,0.3944) 盲点到「登录」,
        # 误登录后公告/进入游戏/收尾守卫全部空转。回退坐标永远不是位置证据, 不得据以续传。
        if method == "fallback":
            kept = f"(已有 {old['method']} 条目, 其位置证据保留不变)" if old else "(本场景无既有条目, 不新建)"
            print(f"[记录] 按钮[{name}] 本次为缓存回退, 不产生新位置证据, 不落库 {kept}")
            return
        entry = {
            "name": name,
            "text": kws,
            "rel": [round(pt.rel[0], 4), round(pt.rel[1], 4)],
            "method": method,  # ocr / color / anchor / fallback
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        for k in ("anchor", "color", "scene", "note", "category"):
            if k in old:
                entry[k] = old[k]
        if scene is not None:
            entry["scene"] = scene
        elif "scene" not in entry and self._scene != "未分类":
            entry["scene"] = self._scene
        # 方案②: 立体化分级 + 均值累积。仅「整体相对坐标」定位(ocr/color)的命中纳入均值样本
        # (锚点-像素偏移属固定尺寸界面, 整体相对坐标不可比; fallback 是缓存回退, 不产生新位置证据)。
        if method in ("ocr", "color"):
            old_n = int(old.get("sample_n", 0) or 0)
            old_mean = old.get("mean_rel")
            rel = entry["rel"]
            if old_n > 0 and old_mean:
                m = old_n + 1
                entry["mean_rel"] = [round((old_mean[0] * old_n + rel[0]) / m, 4),
                                     round((old_mean[1] * old_n + rel[1]) / m, 4)]
                entry["sample_n"] = m
            else:
                entry["mean_rel"] = list(rel)
                entry["sample_n"] = 1
        entry.setdefault("category", category or self.auto_category(name))
        self.click_log_scenes.setdefault(sc, {})[name] = entry
        self.click_log[name] = entry  # 同步扁平索引, 兼容既有查找回退链
        self._save_click_log()
        tail = f" 均值{entry['mean_rel']}(样本{entry.get('sample_n',1)})" if "mean_rel" in entry else ""
        print(f"[记录] [{sc}] 按钮[{name}] 相对{entry['rel']}{tail} 已存入 {CLICK_LOG_PATH.name}")

    def set_scene(self, name: str, quiet: bool = False) -> None:
        """**显式声明**当前所处界面场景, 之后的点击记录/均值复核都归到这个场景。

        为什么需要这个 public 接口: `self._scene` 原本只在三处被改写 —— flow 的 "scene" 字段、
        单步骤的 "scene" 字段、以及 navigate 命中进入时置为目标场景。**没有任何地方会在界面
        真的切换后复位**, 于是 `navigate(家族活动)` 把场景钉死在「家族活动界面」, 之后同模块里
        跑的好友采粉/社区点赞等操作全被误记进「家族活动界面」(实测 63 次误归)。
        → 由 pollin/community_like 这类"自己会换界面"的子模块在切换点调用本方法声明场景。
        """
        if name and name != self._scene:
            self._scene = name
            if not quiet:
                print(f"[场景] -> {name}")

    # ---- 方案②: 立体化分级 + 均值 + 偏差复核 ----
    def _entry_for(self, name: str) -> dict | None:
        """按当前场景优先取知识库条目(场景分组), 场景未收录时回退扁平索引(跨场景同名取最新)。"""
        sc = self._scene
        if sc:
            e = (self.click_log_scenes.get(sc) or {}).get(name)
            if e is not None:
                return e
        return self.click_log.get(name)

    @staticmethod
    def _bias_px(pt: "Point", mean_rel, w: int, h: int) -> float | None:
        """计算命中点与历史均值点的欧氏像素偏差; 无均值返回 None。"""
        if not mean_rel:
            return None
        dx = pt.x - int(mean_rel[0] * w)
        dy = pt.y - int(mean_rel[1] * h)
        return (dx * dx + dy * dy) ** 0.5

    def _refine_hit(self, keywords, pt: "Point", img) -> "Point | None":
        """二次更精细处理: 以命中点为中心局部截图, 放大 2x 重识别关键字(近似 find_text 的过宽块拆分),
        返回与均值更吻合的精确子块中心; 无结果返回 None。用于 OCR 命中点偏差过大时校准, 避免点整块中心误触邻钮。
        """
        try:
            import cv2
            x1 = max(0, pt.x - 60); y1 = max(0, pt.y - 40)
            x2 = min(self.screen_w, pt.x + 60); y2 = min(self.screen_h, pt.y + 40)
            crop = img[y1:y2, x1:x2]
            if crop.size == 0:
                return None
            big = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            kws = keywords if isinstance(keywords, list) else [keywords]
            for b in ocr_image(big):
                text = b.get("text", "")
                if any(kw in text for kw in kws):
                    ox = int(b["center"][0] / 2) + x1
                    oy = int(b["center"][1] / 2) + y1
                    return Point(ox, oy, self.screen_w, self.screen_h)
        except Exception as e:
            print(f"[复核] 局部重识别失败: {e}")
        return None

    @staticmethod
    def auto_category(name: str) -> str:
        """按按钮名语义自动推断功能类别(导航/作业/活动/账号/弹窗/关闭按钮/状态/其他)。"""
        if "关闭" in name:
            return "关闭按钮"
        if name in ("家园", "菜单", "社交", "世界", "家族", "离开"):
            return "导航"
        if name in ("在线礼包", "花灵派对", "家族活动", "摇钱树", "签到", "点击签到",
                    "矿洞探险", "闪耀委托挑战", "守望兔子", "花香垂钓", "花仙乐园"):
            return "活动"
        if name in ("切换账号", "登录", "点击进入游戏"):
            return "账号"
        if name in ("恭喜获得", "点击任意处关闭", "确定", "确认", "弹窗关闭", "提示"):
            return "弹窗"
        if any(k in name for k in ("领取", "抽奖", "投喂", "采集")):
            return "作业"
        if name in ("浇水", "施肥", "收花", "授粉", "开花", "清理", "照料",
                    "一键种植", "种植箱", "快捷操作", "造型种植", "随机种植",
                    "速通", "光偶像"):
            return "作业"
        if any(k in name for k in ("/", "：")):
            return "状态"
        return "其他"
