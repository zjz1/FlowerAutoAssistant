"""
FlowerAutoAssistant - OCR 数据驱动引擎核心（替代 MAA 模板匹配路线）

核心循环: 截图 -> OCR识别文字 -> 按关键字定位按钮 -> 计算相对坐标(归一化) -> 点击

与 MAA 模板匹配的区别:
- 不依赖模板图片, 每次运行通过 OCR 直接识别文字/按钮位置
- 使用「相对坐标」: 记录 (x/宽, y/高) 归一化坐标, 屏幕尺寸变化时相对位置不变
- 数据驱动: 流程由 JSON 描述(flow), 无需改代码即可适配新流程
- 回退缓存: 记录「最后已知相对坐标」, 当 OCR 瞬时失败时可用缓存补点击, 提高鲁棒性

用法:
    python ocr_engine.py --list            # 列出可用流程
    python ocr_engine.py --flow 每日      # 运行指定流程(按关键字匹配)
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# 复用 OCR 单例模块
from ocr_ui import ocr_image, ocr_find

ADB_ADDRESS = "127.0.0.1:16384"
ADB_PATH = r"D:\Program Files\Netease\MuMu\nx_main\adb.exe"
FLOW_DIR = Path(__file__).parent / "flows"
CLICK_LOG_PATH = Path(__file__).parent / "data" / "click_log.json"
CLOSE_BUTTONS_PATH = Path(__file__).parent / "data" / "close_buttons.json"
CONFIG_PATH = Path(__file__).parent / "data" / "config.json"


# ---------- 坐标 ----------
@dataclass
class Point:
    """绝对坐标 (px) 与相对坐标 (0~1 归一化)。"""
    x: int
    y: int
    w: int  # 屏幕宽
    h: int  # 屏幕高

    @property
    def rel(self) -> tuple[float, float]:
        return (self.x / self.w if self.w else 0.0,
                self.y / self.h if self.h else 0.0)

    @staticmethod
    def from_rel(rx: float, ry: float, w: int, h: int) -> "Point":
        return Point(int(rx * w), int(ry * h), w, h)


# ---------- 核心引擎 ----------
class OCREngine:
    """OCR 自动化引擎: 管理设备连接、截图、OCR、定位、点击。"""

    def __init__(self, adb_path: str = ADB_PATH, address: str = ADB_ADDRESS):
        self.adb_path = adb_path
        self.address = address
        self._ctrl = None
        self.last_rel: dict[str, tuple[float, float]] = {}  # 文字关键字 -> 相对坐标缓存
        self.screen_w = 0
        self.screen_h = 0
        self.click_log: dict[str, dict] = self._load_click_log()  # 按钮名 -> 记录
        self.close_buttons: list[dict] = self._load_close_buttons()  # 关闭按钮特殊逻辑注册表
        self.config: dict = self._load_config()  # 用户配置 (data/config.json), 支持 CLI 覆盖
        self._rr_hit = False  # retry_loop 本轮命中标记

    # ---- 用户配置 (data/config.json) ----
    def _load_config(self) -> dict:
        """加载用户配置 (data/config.json)。流程 JSON 中可用 ${key} 占位符引用配置值,
        例如 ${target_tail} -> config["target_tail"]。缺失字段返回空字符串。"""
        cfg = {}
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, encoding="utf-8") as fp:
                    data = json.load(fp)
                    if isinstance(data, dict):
                        cfg = {k: v for k, v in data.items() if not k.startswith("_")}
        except Exception as e:
            print(f"[配置加载失败] {e}")
        return cfg

    def _save_config(self) -> None:
        """把 self.config 写回 data/config.json (合并注释字段除外)。"""
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, encoding="utf-8") as fp:
                    data = json.load(fp)
        except Exception:
            data = {}
        for k, v in self.config.items():
            data[k] = v
        with open(CONFIG_PATH, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=4)

    def update_config(self, **kwargs) -> None:
        """更新配置项并持久化。例如 update_config(enable_switch=True, target_tail="61")。"""
        self.config.update(kwargs)
        self._save_config()

    def resolve(self, val):
        """把字符串中的 ${key} 占位符替换为配置值; 非字符串或未含占位符则原样返回。"""
        if isinstance(val, str) and "${" in val:
            def _repl(m):
                key = m.group(1)
                if key not in self.config:
                    print(f"[配置] 提示: 配置键 '{key}' 未定义, 使用空值")
                return str(self.config.get(key, ""))
            return re.sub(r"\$\{(\w+)\}", _repl, val)
        return val

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

    # ---- 点击日志 (持久化知识库) ----
    def _load_click_log(self) -> dict:
        try:
            if CLICK_LOG_PATH.exists():
                with open(CLICK_LOG_PATH, encoding="utf-8") as fp:
                    data = json.load(fp)
                    if isinstance(data, dict):
                        return data
        except Exception as e:
            print(f"[点击日志加载失败] {e}")
        return {}

    def _save_click_log(self) -> None:
        CLICK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CLICK_LOG_PATH, "w", encoding="utf-8") as fp:
            json.dump(self.click_log, fp, ensure_ascii=False, indent=2)

    def _log_click(self, name: str, keywords, pt: "Point", method: str) -> None:
        """记录一次成功点击: 按钮名 + 文本 + 相对坐标 + 绝对坐标。同名按钮只保留一次。
        旧条目中人工标注的扩展字段(anchor/color/scene/note)会被保留, 不被自动日志覆盖。
        """
        kws = keywords if isinstance(keywords, list) else [keywords]
        old = self.click_log.get(name) or {}
        entry = {
            "name": name,
            "text": kws,
            "rel": [round(pt.rel[0], 4), round(pt.rel[1], 4)],
            "abs": [pt.x, pt.y],
            "screen": [self.screen_w, self.screen_h],
            "method": method,  # ocr / color / anchor / fallback
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        for k in ("anchor", "color", "scene", "note"):
            if k in old:
                entry[k] = old[k]
        self.click_log[name] = entry
        self._save_click_log()
        print(f"[记录] 按钮[{name}] 相对{self.click_log[name]['rel']} 已存入 {CLICK_LOG_PATH.name}")


    # ---- 设备 ----
    def connect(self) -> bool:
        from maa.controller import AdbController
        from maa.toolkit import Toolkit

        Toolkit.init_option("./")
        ctrl = AdbController(adb_path=self.adb_path, address=self.address)
        ctrl.post_connection().wait()
        if not ctrl.connected:
            print("[错误] 连接失败")
            return False
        self._ctrl = ctrl
        self.debug_click = bool(os.environ.get("FAA_DEBUG_CLICK", ""))
        self._click_seq = 0
        if self.debug_click:
            self.debug_dir = Path(__file__).parent / "data" / "click_debug"
            self.debug_dir.mkdir(parents=True, exist_ok=True)
        return True

    def screenshot(self) -> np.ndarray | None:
        """截图, 并记录当前屏幕尺寸。返回 BGR ndarray。"""
        img = self._ctrl.post_screencap().wait().get()
        if img is None:
            return None
        # img shape = (H, W, 3)
        self.screen_h, self.screen_w = img.shape[:2]
        return img

    def click_abs(self, x: int, y: int) -> None:
        if getattr(self, "debug_click", False):
            self._snapshot_click(int(x), int(y))
        self._ctrl.post_click(int(x), int(y)).wait()
        print(f"[点击] 绝对({x},{y})")

    def _snapshot_click(self, x: int, y: int) -> None:
        """调试: 点击前截图, 用红框标注点击点并保存, 便于逐帧核对点击区域。"""
        try:
            img = self.screenshot()
            if img is None:
                return
            import cv2
            img = img.copy()
            cv2.rectangle(img, (x - 25, y - 25), (x + 25, y + 25), (0, 0, 255), 2)
            cv2.circle(img, (x, y), 5, (0, 0, 255), -1)
            self._click_seq += 1
            fp = self.debug_dir / f"click_{self._click_seq:03d}_({x}_{y}).png"
            cv2.imwrite(str(fp), img)
            self._last_snapshot = fp
            print(f"[截图] 点击区域已保存 -> {fp.name}")
        except Exception as e:
            print(f"[截图调试] 失败: {e}")

    def click_rel(self, rx: float, ry: float) -> None:
        """按相对坐标点击 (自适应屏幕尺寸)。
        若屏幕尺寸未知(尚未截图)则先截图获取; 避免相对坐标算成 (0,0)。
        """
        if not self.screen_w or not self.screen_h:
            self.screenshot()
        if not self.screen_w or not self.screen_h:
            print("[点击] 相对坐标失败: 屏幕尺寸未知")
            return
        x = int(rx * self.screen_w)
        y = int(ry * self.screen_h)
        print(f"[点击] 相对({rx:.3f},{ry:.3f}) -> 绝对({x},{y})")
        self.click_abs(x, y)

    def back(self) -> bool:
        """发送 Android 返回键 (adb shell input keyevent 4)。用于关闭弹窗/返回上一级。
        返回 True/False。失败时回退点击屏幕左上角。
        """
        import subprocess
        try:
            # 尝试用 adb 命令行发 keyevent (返回键 code=4)
            subprocess.run(
                [self.adb_path, "-s", self.address, "shell", "input", "keyevent", "4"],
                capture_output=True, timeout=5, check=True,
            )
            print("[back] 已发送返回键 keyevent=4")
            return True
        except Exception as e:
            print(f"[back] adb keyevent 失败({e}), 回退点击左上角")
            self.click_abs(20, 20)
            return False

    # ---- OCR 定位 ----
    def find_text(self, keywords, img=None, top_k=3, exact=False, region_rel=None):
        """在截图(或给定图)中按关键字找文字块。返回 OCR 块列表 (含坐标)。
        exact=True 要求块文本与关键字完全相等, 避免『家园』误命中『勇气国花园』等。
        region_rel=[x1,y1,x2,y2] (0~1) 时只保留中心落在该区域内的块 (用于区域限定文本判断)。
        对过宽的合并块(宽>90, 如「种植箱一键种植」)尝试放大 2x 重识别拆出子按钮以提升
        定位精度, 但始终保留原合并块(且置于拆分块之前优先匹配), 避免重识别丢失命中。
        """
        img = img if img is not None else self.screenshot()
        if img is None:
            return []
        blocks = ocr_image(img)
        refined = []
        sub_blocks = []  # 过宽块 2x 重识别拆出的精确子块, 点击定位时优先(点击点落到目标文字自身中心)
        for b in blocks:
            x1, y1, x2, y2 = b["box"]
            # 原块始终保留作为兜底: 即使拆分失败/丢字, 也能整体命中, 中心已落在目标按钮上
            refined.append(b)
            w = x2 - x1
            if w > 90:  # 过宽, 疑似合并(如「菜单/奇妙花宝」挤在一起): 放大重识别尝试拆出更精确的子按钮
                crop = img[max(0, y1 - 10):y2 + 10, max(0, x1 - 10):x2 + 10]
                if crop.size:
                    import cv2
                    big = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                    for nb in ocr_image(big):
                        ox = int(nb["center"][0] / 2) + max(0, x1 - 10)
                        oy = int(nb["center"][1] / 2) + max(0, y1 - 10)
                        nb2 = dict(nb)
                        nb2["center"] = [ox, oy]
                        nb2["box"] = [int(nb["box"][0] / 2) + max(0, x1 - 10),
                                      int(nb["box"][1] / 2) + max(0, y1 - 10),
                                      int(nb["box"][2] / 2) + max(0, x1 - 10),
                                      int(nb["box"][3] / 2) + max(0, y1 - 10)]
                        sub_blocks.append(nb2)
        # 精确子块优先(点击点优先落到「菜单」二字自身中心), 原合并块兜底保证整体命中
        refined = sub_blocks + refined
        if region_rel:
            w, h = self.screen_w, self.screen_h
            rx1, ry1 = int(region_rel[0] * w), int(region_rel[1] * h)
            rx2, ry2 = int(region_rel[2] * w), int(region_rel[3] * h)
            refined = [b for b in refined
                       if rx1 <= b["center"][0] <= rx2 and ry1 <= b["center"][1] <= ry2]
        return ocr_find(refined, keywords, exact=exact)

    def locate(self, keywords, img=None, min_score=0.5, exact=False, region_rel=None):
        """返回第一个命中块的中心绝对坐标 Point; 未命中返回 None。
        命中后更新 last_rel 缓存。
        """
        blocks = self.find_text(keywords, img=img, exact=exact, region_rel=region_rel)
        for b in blocks:
            if b.get("score", 1.0) < min_score:
                continue
            cx, cy = b["center"]
            pt = Point(cx, cy, self.screen_w, self.screen_h)
            for kw in (keywords if isinstance(keywords, list) else [keywords]):
                self.last_rel[kw] = pt.rel
            return pt
        return None

    def locate_color(self, color_cfg: dict, img=None) -> "Point | None":
        """颜色特征定位: HSV 过滤 + 连通区域分析, 返回中心 Point。
        color_cfg: {"hsv_lower": [h,s,v], "hsv_upper": [h,s,v],
                    "area_min": int, "area_max": int, "region": [x1,y1,x2,y2]}
        """
        import cv2
        import numpy as np
        img = img if img is not None else self.screenshot()
        if img is None:
            return None
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        lower = np.array(color_cfg["hsv_lower"])
        upper = np.array(color_cfg["hsv_upper"])
        mask = cv2.inRange(hsv, lower, upper)
        # 可选: 限定搜索区域
        region = color_cfg.get("region")
        if region:
            x1, y1, x2, y2 = region
            sub_mask = np.zeros_like(mask)
            sub_mask[y1:y2, x1:x2] = mask[y1:y2, x1:x2]
            mask = sub_mask
        num_labels, _, stats, centroids = cv2.connectedComponentsWithStats(mask)
        area_min = color_cfg.get("area_min", 50)
        area_max = color_cfg.get("area_max", 999999)
        candidates = []
        for i in range(1, num_labels):
            area = stats[i, cv2.CC_STAT_AREA]
            if area_min < area < area_max:
                cx, cy = centroids[i]
                candidates.append((cx, cy, area))
        if not candidates:
            return None
        # 取面积最大的
        candidates.sort(key=lambda c: c[2], reverse=True)
        cx, cy = int(candidates[0][0]), int(candidates[0][1])
        return Point(cx, cy, self.screen_w, self.screen_h)

    def locate_anchor_offset(self, anchor_cfg: dict, img=None, min_score=0.4) -> "Point | None":
        """锚点 + 像素偏移定位: 适用于「固定尺寸界面」(如小花仙登录界面不随设备分辨率缩放),
        整体画面相对坐标(0~1)会失效, 但「界面内元素相对锚点的像素偏移」恒定不变。

        anchor_cfg: {"anchors": [
            {"text_contains": "****", "offset": [dx, dy]},   # 按子串找锚点块(如账号 abc****de)
            {"text": ["登录"], "offset": [dx, dy]},           # 按关键字找锚点块
        ]}
        依次尝试各锚点, 首个命中即返回 锚点中心+offset 的 Point; 全部失败返回 None。
        """
        img = img if img is not None else self.screenshot()
        if img is None:
            return None
        for a in anchor_cfg.get("anchors", []):
            dx, dy = a.get("offset", [0, 0])
            pat = a.get("text_contains")
            if pat:
                hit = next((b for b in ocr_image(img) if pat in b.get("text", "")), None)
                if hit is None:
                    print(f"[锚点偏移] 未找到含 '{pat}' 的文本块")
                    continue
                cx, cy = hit["center"]
            else:
                pt = self.locate(a.get("text", []), img=img, min_score=min_score)
                if pt is None:
                    continue
                cx, cy = pt.x, pt.y
            tx = max(0, min(self.screen_w - 1, int(cx + dx)))
            ty = max(0, min(self.screen_h - 1, int(cy + dy)))
            return Point(tx, ty, self.screen_w, self.screen_h)
        return None

    def click_account_tail(self, tail: str, region_rel=None, min_score=0.4) -> bool:
        """在账号选择界面点击「账号文本尾部数字」匹配的账号条目并返回坐标缓存。

        账号条目文本形如 `abc****de`(如 138****00)。登录界面固定尺寸, 用 OCR 识别各账号块,
        locale 匹配文本尾部数字==tail 的块(可能合并块需取尾部), 点击其中心。
        region_rel=[x1,y1,x2,y2] 限定时只在账号列表区域匹配, 避免误点其它数字文本。
        """
        img = self.screenshot()
        if img is None:
            return False
        blocks = [b for b in ocr_image(img) if b.get("score", 1) >= min_score]
        # 区域限定
        if region_rel:
            w, h = self.screen_w, self.screen_h
            rx1, ry1 = int(region_rel[0] * w), int(region_rel[1] * h)
            rx2, ry2 = int(region_rel[2] * w), int(region_rel[3] * h)
            blocks = [b for b in blocks if rx1 <= b["center"][0] <= rx2 and ry1 <= b["center"][1] <= ry2]
        tail = str(tail).strip()
        best = None
        for b in blocks:
            txt = b.get("text", "").strip()
            # 匹配账号格式: 尾部数字 == tail (可含 **** 脱敏)
            m = re.search(r"(\d+)\s*$", txt)
            if not m or m.group(1) != tail:
                continue
            if "****" in txt:  # 确认是脱敏账号块
                best = b
                break
        if best is None:
            print(f"[账号尾部] 未找到尾部={tail} 的账号条目")
            return False
        cx, cy = best["center"]
        pt = Point(cx, cy, self.screen_w, self.screen_h)
        print(f"[账号尾部] {best['text']} 尾部={tail} -> {cx},{cy}")
        self.click_abs(cx, cy)
        self._log_click(f"账号:{best['text']}", [], pt, "account_tail")
        for kw in (best["text"], f"账号尾{tail}"):
            self.last_rel[kw] = pt.rel
        return True

    def locate_anchor_color(self, anchor_kw, color_cfg: dict, dx_range=(150, 400), dy_tol=60,
                            img=None, min_score=0.4) -> "Point | None":
        """锚点 + 颜色复合定位: 先 OCR 找锚点文字(如「提示」), 在锚点右侧/某偏移区域按颜色找目标按钮。
        用于弹窗关闭按钮等「有文字作锚点 + 按钮自身无文字」的场景, 比固定绝对坐标更健壮。
        color_cfg 的 region 若未提供, 则由锚点动态计算。
        """
        img = img if img is not None else self.screenshot()
        if img is None:
            return None
        anchor = self.locate([anchor_kw], img=img, min_score=min_score)
        if anchor is None:
            print(f"[锚点定位] 未找到锚点文字 '{anchor_kw}'")
            return None
        import cv2
        import numpy as np
        ax, ay = anchor.x, anchor.y
        # 若颜色配置未给定 region, 用锚点动态生成右侧搜索区
        cfg = dict(color_cfg)
        if not cfg.get("region"):
            x1, x2 = ax + dx_range[0], ax + dx_range[1]
            y1, y2 = ay - dy_tol, ay + dy_tol
            cfg["region"] = [max(0, x1), max(0, y1), x2, y2]
        return self.locate_color(cfg, img=img)

    def parse_fraction_at(self, region_rel, img=None, tol=60) -> "tuple[int,int] | None":
        """OCR 整图, 找形如 'a/b' 的数字块, 取中心离 region_rel*屏 最近且距离<=tol 的, 返回 (a,b)。
        未找到返回 None。
        """
        img = img if img is not None else self.screenshot()
        if img is None:
            return None
        w, h = self.screen_w, self.screen_h
        tx, ty = int(region_rel[0] * w), int(region_rel[1] * h)
        best, best_d = None, float("inf")
        for b in ocr_image(img):
            m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", b.get("text", "").strip())
            if not m:
                continue
            cx, cy = b["center"]
            d = (cx - tx) ** 2 + (cy - ty) ** 2
            if d < best_d:
                best_d, best = d, (int(m[1]), int(m[2]))
        if best is not None and best_d ** 0.5 <= tol:
            return best
        return None

    def parse_count_at(self, region_rel, img=None, tol=120) -> "int | None":
        """OCR 整图, 找形如 '关键字:N' 或纯数字('N') 的数字块, 取中心离 region_rel*屏 最近且距离<=tol 的, 返回 N。
        用于解析『剩余抽奖次数:3』这类带关键字的单值数字。未找到返回 None。
        """
        img = img if img is not None else self.screenshot()
        if img is None:
            return None
        w, h = self.screen_w, self.screen_h
        tx, ty = int(region_rel[0] * w), int(region_rel[1] * h)
        best, best_d = None, float("inf")
        for b in ocr_image(img):
            m = re.search(r"[:：]?\s*(\d+)\s*$", b.get("text", "").strip())
            if not m:
                continue
            cx, cy = b["center"]
            d = (cx - tx) ** 2 + (cy - ty) ** 2
            if d < best_d:
                best_d, best = d, int(m[1])
        if best is not None and best_d ** 0.5 <= tol:
            return best
        return None

    def eval_count(self, step, img=None) -> bool:
        """判断指定相对位置处 '关键字:N' 的数字 N 是否满足 condition (变量 N)。如 N>0。"""
        reg = step.get("region_rel")
        if not reg:
            print("[if_greater] 缺少 region_rel")
            return False
        n = self.parse_count_at(reg, img=img)
        if n is None:
            print(f"[if_greater] 区域{reg} 未识别到 '关键字:N' 数字")
            return False
        cond = step.get("condition", "N>0")
        if not re.fullmatch(r"[N0-9+\-*/<>!= ().,]+", cond):
            print(f"[if_greater] 非法条件 '{cond}'")
            return False
        try:
            ok = bool(eval(cond, {"__builtins__": {}}, {"N": n}))
        except Exception as e:
            print(f"[if_greater] 条件求值异常 '{cond}': {e}")
            return False
        print(f"[if_greater] 区域{reg} N={n} 条件'{cond}' -> {'TRUE' if ok else 'FALSE'}")
        return ok

    def count_text(self, kws, region_rel=None, img=None) -> int:
        """统计文本关键字在(限定时)区域内出现的总次数。跨 OCR 块去重: 挡块文本本身可能含多个关键字时按出现次数计。"""
        img = img if img is not None else self.screenshot()
        if img is None:
            return 0
        w, h = self.screen_w, self.screen_h
        hits = 0
        for b in ocr_image(img):
            x1, y1, x2, y2 = b["box"]
            if region_rel:
                rx1, ry1, rx2, ry2 = region_rel
                if not (rx1 * w <= x1 and x2 <= rx2 * w and ry1 * h <= y1 and y2 <= ry2 * h):
                    continue
            text = b.get("text", "")
            for kw in (kws if isinstance(kws, list) else [kws]):
                hits += text.count(kw)
        print(f"[count_text] {kws} 区域{region_rel or '全屏'} 命中 {hits} 次")
        return hits

    def eval_fraction(self, step, img=None) -> bool:
        """判断某个相对位置处 'a/b' 数字是否满足 condition。
        condition 使用变量 a(分子)/b(分母) 的表达式, 如 'a<b'、'a>=20'。返回 True/False。
        """
        reg = step.get("region_rel")
        if not reg:
            print("[if_fraction] 缺少 region_rel")
            return False
        res = self.parse_fraction_at(reg, img=img)
        if res is None:
            print(f"[if_fraction] 区域{reg} 未识别到 'a/b' 数字块")
            return False
        a, b = res
        cond = step.get("condition", "a<b")
        # 配置可信, 但仅放行数字/变量/运算符, 避免任意代码
        if not re.fullmatch(r"[ab0-9+\-*/<>!= ().,]+", cond):
            print(f"[if_fraction] 非法条件 '{cond}'")
            return False
        try:
            ok = bool(eval(cond, {"__builtins__": {}}, {"a": a, "b": b}))
        except Exception as e:
            print(f"[if_fraction] 条件求值异常 '{cond}': {e}")
            return False
        print(f"[if_fraction] 区域{reg} a={a}/b={b} 条件'{cond}' -> {'TRUE' if ok else 'FALSE'}")
        return ok

    def store_fraction(self, step: dict, img=None) -> bool:
        """读取指定相对位置处 'a/b' 数字的分子(a), 存入 config 并持久化。
        用于记录『已浇水次数』等带冷却/每日上限的行为, 便于流程判断当天是否已满。
        键名规则: config[step.key]=a, config[step.key+"_date"]=YYYYMMDD。
        读取不到 a/b 时返回 False (不写入)。
        """
        reg = step.get("region_rel")
        key = step.get("key")
        if not reg or not key:
            print("[store_fraction] 缺少 region_rel/key")
            return False
        res = self.parse_fraction_at(reg, img=img)
        if res is None:
            print(f"[store_fraction] 区域{reg} 未识别到 'a/b', 不写入")
            return False
        a, _b = res
        self.update_config(**{key: a, key + "_date": time.strftime("%Y%m%d")})
        print(f"[store_fraction] 区域{reg} a/b={a}/{_b} -> 已存 {key}={a}")
        return True

    def eval_config(self, step: dict) -> bool:
        """判断 config 中键值是否满足条件, 用于流程内做配置开关。返回 True/False。
        step: {key, value, op} op ∈ {==,!=,>=,<=,>,<}, 默认 ==。
        value 支持 ${key} 占位符解析与 bool/int/str 自动转换。
        """
        key = step.get("key")
        if not key:
            print("[if_config] 缺少 key")
            return False
        raw = self.config.get(key)
        want_raw = self.resolve(str(step.get("value", "")))
        if want_raw in ("True", "true"):
            want = True
        elif want_raw in ("False", "false"):
            want = False
        else:
            try:
                want = int(want_raw)
            except (TypeError, ValueError):
                want = want_raw
        op = step.get("op", "==")
        try:
            ok = {
                "==": lambda: raw == want,
                "!=": lambda: raw != want,
                ">=": lambda: raw >= want,
                "<=": lambda: raw <= want,
                ">": lambda: raw > want,
                "<": lambda: raw < want,
            }[op]()
        except Exception as e:
            print(f"[if_config] 比较失败 {key}={raw} {op} {want}: {e}")
            return False
        print(f"[if_config] config[{key}]={raw} {op} {want} -> {'TRUE' if ok else 'FALSE'}")
        return ok

    def _calc_int(self, formula, a, b) -> int:
        """受信配置内安全求值整数公式。可用变量 a=分子, b=分母, 函数 ceil()/floor(), 四则运算。
        非法字符/求值异常抛 ValueError / 返回 0。
        """
        if not re.fullmatch(r"[a-zA-Z0-9+\-*/<>!= ().,]+", formula):
            raise ValueError(f"非法公式 '{formula}'")
        ns = {"a": a, "b": b, "ceil": math.ceil, "floor": math.floor}
        try:
            return int(eval(formula, {"__builtins__": {}}, ns))
        except Exception as e:
            raise ValueError(f"公式求值异常 '{formula}': {e}")

    def run_loop_fraction(self, step, indent=0):
        """按『分数区域算出的循环次数』重复执行 do 子流程。
        iterations: [{region_rel, formula}] 各自从相对位置读取 a/b 并按公式算一个整数值;
        combine: 取 min(默认) 或 max 合并; 结果再夹到 max_loop; 为 0 则不循环。
        典型用法: n=ceil((b-a)/57) 与 m=floor(a/20), combine=min → 每次消耗 20 体力直到结束或所需满足。
        """
        pad = "  " * indent
        img = self.screenshot()
        vals = []
        for spec in step.get("iterations", []):
            res = self.parse_fraction_at(spec["region_rel"], img=img)
            if res is None:
                print(f"{pad}[loop_fraction] 区域{spec['region_rel']} 未识别到 a/b, 循环次数=0")
                return
            v = self._calc_int(spec["formula"], res[0], res[1])
            print(f"{pad}[loop_fraction] 区域{spec['region_rel']} a={res[0]} b={res[1]} 公式'{spec['formula']}' -> {v}")
            vals.append(v)
        combine = step.get("combine", "min")
        m = min(vals) if combine != "max" else max(vals)
        if m < 0:
            m = 0
        m = min(m, step.get("max_loop", 100))
        print(f"{pad}[loop_fraction] 合并({combine})={vals} -> 循环 {m} 次")
        # 一次性步骤(如读完顶栏后点「光偶像」进入新界面), 在循环前执行一次
        if step.get("once"):
            print(f"{pad}[loop_fraction] 执行入场步骤 once")
            self.run_steps(step["once"], indent=indent + 1)
        for i in range(m):
            print(f"{pad} --- 逻辑 {i + 1}/{m} ---")
            self.run_steps(step.get("do", []), indent=indent + 1)

    def _locate_close_by_entry(self, entry: dict, img, w, h) -> "Point | None":
        """按单条『关闭按钮-特殊逻辑』注册项尝试定位, 返回命中 Point 或 None。"""
        t = entry.get("type")
        color = entry.get("color", {})
        if t == "anchor_color":
            return self.locate_anchor_color(
                entry.get("anchor", "提示"), color,
                dx_range=entry.get("dx_range", (150, 400)),
                dy_tol=entry.get("dy_tol", 60),
                img=img, min_score=entry.get("min_score", 0.4))
        if t in ("corner", "corner_white", "corner_pink_small"):
            # region_rel: [x1,y1,x2,y2] 相对坐标(0~1) → 转绝对坐标
            rx = entry.get("region_rel", [0.82, 0.0, 1.0, 0.18])
            cfg = dict(color)
            cfg["region"] = [max(0, int(rx[0] * w)), max(0, int(rx[1] * h)),
                             min(w, int(rx[2] * w)), min(h, int(rx[3] * h))]
            return self.locate_color(cfg, img=img)
        return None

    def find_all_close_buttons(self, img=None) -> list:
        """遍历『关闭按钮-特殊逻辑』注册表, 返回**所有**可定位到的关闭按钮候选。
        每个已注册类型一个条目 `{"name":..., "type":..., "pt": Point}`, 未命中/异常类型不入列。
        支持的特殊逻辑 type:
          - "anchor_color": 以锚点文字(如「提示」)为锚, 在其右侧 dx_range 内按颜色找关闭按钮
          - "corner": 在画面固定相对区域(如右上角)按颜色找关闭按钮
        """
        img = img if img is not None else self.screenshot()
        w, h = self.screen_w, self.screen_h
        hits = []
        for entry in self.close_buttons:
            name = entry.get("name", "?")
            try:
                pt = self._locate_close_by_entry(entry, img, w, h)
            except Exception as e:
                print(f"[关闭按钮] 逻辑 '{name}' 执行异常: {e}")
                pt = None
            if pt is not None:
                hits.append({"name": name, "type": entry.get("type"), "pt": pt})
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

    def close_dialog(self, img=None, anchor_kw="提示", dx_range=(150, 400),
                     dy_tol=60, min_score=0.4, only_types=None) -> bool:
        """关闭通用弹窗: 遍历『关闭按钮-特殊逻辑』注册表, **逐个尝试满足类型的关闭按钮并点击**。
        含义: 当前画面上能识别的多种关闭按钮(弹窗式/右上角式等)都会被各点一次, 直到试完。
        only_types: 可选, 字符串或类型列表; 仅在注册表中挑选指定类型(如 ["corner","corner_white"])定位,
                   用于退出整屏面板(右上角关闭)时避免误点「提示」锚点弹窗。None 表示全部类型。
        （anchor_kw/dx_range/dy_tol 参数仅为兼容旧调用保留, 实际以注册表为准。）
        成功点击任一写入知识库。返回是否至少点击了一次。
        """
        img = img if img is not None else self.screenshot()
        hits = self.find_all_close_buttons(img=img)
        # 按 only_types 过滤
        if only_types:
            allowed = [only_types] if isinstance(only_types, str) else list(only_types)
            hits = [h for h in hits if h["type"] in allowed]
        if not hits:
            print("[关闭弹窗(only_types)] 未定位到匹配类型的关闭按钮")
            return False
        clicked = False
        for h in hits:
            pt = h["pt"]
            print(f"[关闭弹窗] 点击 '{h['name']}' ({h['type']}) -> {pt.x},{pt.y}")
            self.click_abs(pt.x, pt.y)
            self._log_click("弹窗关闭", [anchor_kw], pt, "color")
            clicked = True
        return clicked

    def click_text(self, keywords, img=None, fallback_rel=None, min_score=0.5, exact=False) -> bool:
        """OCR 定位关键字并点击。命中返回 True。
        回退链: OCR → 颜色特征(若知识库有 color 配置) → 进程缓存 → 知识库坐标 → 失败
        exact=True 时用精确匹配(要求块文本完全等于关键字)。
        """
        pt = self.locate(keywords, img=img, min_score=min_score, exact=exact)
        if pt is not None:
            print(f"[OCR命中] {keywords} -> {pt.x},{pt.y}")
            self.click_abs(pt.x, pt.y)
            self._log_click(keywords[0] if isinstance(keywords, list) else keywords,
                            keywords, pt, "ocr")
            return True
        # 锚点偏移定位 (固定尺寸界面, 如登录界面无文字图形按钮)
        kws = keywords if isinstance(keywords, list) else [keywords]
        for kw in kws:
            entry = self.click_log.get(kw)
            if entry and "anchor" in entry:
                pt_a = self.locate_anchor_offset(entry["anchor"], img=img)
                if pt_a is not None:
                    print(f"[锚点偏移命中] {kw} -> {pt_a.x},{pt_a.y}")
                    self.click_abs(pt_a.x, pt_a.y)
                    self._log_click(kw, [kw], pt_a, "anchor")
                    return True
        # 颜色特征检测 (针对无文字的图形按钮)
        for kw in kws:
            entry = self.click_log.get(kw)
            if entry and entry.get("method") == "color" and "color" in entry:
                pt_c = self.locate_color(entry["color"], img=img)
                if pt_c is not None:
                    print(f"[颜色命中] {kw} -> {pt_c.x},{pt_c.y}")
                    self.click_abs(pt_c.x, pt_c.y)
                    self._log_click(kw, [kw], pt_c, "color")
                    return True
        # OCR+颜色均未命中: 尝试回退缓存 (进程内 last_rel, 再查持久化 click_log 知识库)
        if fallback_rel is None:
            for kw in kws:
                if kw in self.last_rel:
                    fallback_rel = self.last_rel[kw]
                    break
            if fallback_rel is None:
                for kw in kws:
                    if kw in self.click_log:
                        fallback_rel = tuple(self.click_log[kw]["rel"])
                        break
        if fallback_rel is not None:
            print(f"[回退缓存] {keywords} 未OCR到, 用缓存 {fallback_rel}")
            pt_fb = Point.from_rel(fallback_rel[0], fallback_rel[1], self.screen_w, self.screen_h)
            self.click_rel(*fallback_rel)
            self._log_click(keywords[0] if isinstance(keywords, list) else keywords,
                            keywords, pt_fb, "fallback")
            return True
        print(f"[未命中] {keywords}")
        return False

    # ---- 流程执行 ----
    def wait_text(self, keywords, timeout=30, interval=1.0):
        """轮询等待某文字出现, 返回 Point; 超时返回 None。"""
        kws = keywords if isinstance(keywords, list) else [keywords]
        deadline = time.time() + timeout
        while time.time() < deadline:
            img = self.screenshot()
            pt = self.locate(kws, img=img)
            if pt is not None:
                print(f"[等待成功] {kws} @ {pt.x},{pt.y}")
                return pt
            time.sleep(interval)
        print(f"[等待超时] {kws} ({timeout}s)")
        return None

    def wait_text_gone(self, keywords, timeout=30, interval=1.0):
        """轮询等待某文字消失, 返回 True; 超时返回 False。"""
        kws = keywords if isinstance(keywords, list) else [keywords]
        deadline = time.time() + timeout
        while time.time() < deadline:
            img = self.screenshot()
            if self.locate(kws, img=img, min_score=0.3) is None:
                print(f"[消失成功] {kws}")
                return True
            time.sleep(interval)
        print(f"[消失超时] {kws} ({timeout}s)")
        return False

    def detect_scene(self, timeouts: dict) -> str:
        """判断当前所处界面。timeouts: {场景标识文字: 超时秒}。
        依次 OCR 检查每个标识文字是否存在, 返回命中的场景 key; 全未命中返回 'unknown'。
        """
        img = self.screenshot()
        hits = []
        for label, kws in timeouts.items():
            kws_list = kws if isinstance(kws, list) else [kws]
            for kw in kws_list:
                if self.locate([kw], img=img, min_score=0.4) is not None:
                    hits.append(label)
                    break
        return hits[0] if hits else "unknown"

    def run_steps(self, steps: list, indent=1):
        """顺序执行一组 steps, 支持 list 形式的嵌套(用于 loop 子块)。返回达到的最大步骤索引。"""
        for step in steps:
            if isinstance(step, list):
                # 嵌套块列表
                self.run_steps(step, indent=indent + 1)
                continue
            self.run_step(step, indent=indent)
        return 0

    def run_step(self, step: dict, indent=1):
        """执行单个步骤。step 为流程 JSON 中的一个节点。
        支持: wait_text / click_text / click_rel / sleep / close_dialog /
        if_text / if_fraction / loop_fraction / loop_times
        """
        pad = "  " * indent
        s_type = step.get("type")
        kws = step.get("text", step.get("keywords"))
        if s_type == "wait_text":
            self.wait_text(kws, timeout=step.get("timeout", 30), interval=step.get("interval", 1.0))
        elif s_type == "click_text":
            ok = self.click_text(kws, fallback_rel=step.get("fallback_rel"),
                                 exact=step.get("exact", False))
            print(f"{pad}[click_text] {kws} -> {'ok' if ok else 'fail'}")
            if ok and step.get("mark"):
                self._rr_hit = True  # 命中目标步骤, 记为本轮 retry_loop 成功
            time.sleep(step.get("delay", 0.5))
        elif s_type == "click_account_tail":
            # 点击「账号文本尾部数字」匹配的账号条目(账号选择界面)。
            # 登录界面固定尺寸, 账号条目以 `abc****de` 出现, 用尾部数字识别目标账号。
            tail = self.resolve(step.get("tail"))
            if tail in (None, ""):
                tail = self.resolve(self.config.get("target_tail", ""))
            ok = self.click_account_tail(str(tail), region_rel=step.get("region_rel"),
                                         min_score=step.get("min_score", 0.4))
            print(f"{pad}[click_account_tail] tail={tail} -> {'ok' if ok else 'fail'}")
            time.sleep(step.get("delay", 0.5))
        elif s_type == "sleep":
            time.sleep(step.get("seconds", 1.0))
        elif s_type == "click_rel":
            rx, ry = step["rel"]
            self.click_rel(rx, ry)
            time.sleep(step.get("delay", 0.5))
        elif s_type == "close_dialog":
            self.close_dialog(
                anchor_kw=step.get("anchor", "提示"),
                dx_range=step.get("dx_range", (150, 400)),
                dy_tol=step.get("dy_tol", 60),
                only_types=step.get("only_types"),
            )
            time.sleep(step.get("delay", 1.0))
        elif s_type == "if_text":
            # 条件分支: 检测到任意关键字才执行 then, 否则执行 else(可选)
            # 支持 region_rel=[x1,y1,x2,y2] (0~1) 限定时只在指定区域做文本判断
            hit = self.locate(kws, min_score=step.get("min_score", 0.5),
                              region_rel=step.get("region_rel")) is not None
            branch = step.get("then") if hit else step.get("else")
            print(f"{pad}[if_text] {kws} {'区域'+str(step.get('region_rel'))+' ' if step.get('region_rel') else ''}-> {'HIT' if hit else 'MISS'}")
            if branch:
                self.run_steps(branch, indent=indent + 1)
        elif s_type == "if_fraction":
            # 条件分支: 读取指定相对位置处 'a/b' 数字, 满足 condition(变量 a=分子,b=分母) 则执行 then, 否则 else
            hit = self.eval_fraction(step)
            branch = step.get("then") if hit else step.get("else")
            if branch:
                self.run_steps(branch, indent=indent + 1)
        elif s_type == "store_fraction":
            # 读取区域 'a/b' 的分子存入 config(带日期), 用于记录浇水/每日上限等状态
            self.store_fraction(step)
        elif s_type == "if_greater":
            # 条件分支: 读取指定相对位置处 '关键字:N' 数字(如 剩余抽奖次数:3), 满足 condition(变量 N) 则执行 then, 否则 else
            hit = self.eval_count(step)
            branch = step.get("then") if hit else step.get("else")
            if branch:
                self.run_steps(branch, indent=indent + 1)
        elif s_type == "count_text":
            # 统计数据文本出现次数; 若 >= threshold 执行 then(默认空), 否则执行 else (若有)
            n = self.count_text(step.get("text"), region_rel=step.get("region_rel"))
            ok = n >= step.get("threshold", 1)
            branch = step.get("then") if ok else step.get("else")
            print(f"{pad}[count_text] {step.get('text')} 计数={n} threshold={step.get('threshold',1)} -> {'TRUE' if ok else 'FALSE'}")
            if branch:
                self.run_steps(branch, indent=indent + 1)
        elif s_type == "if_config":
            # 配置开关分支: config[key] 满足 op/value 则执行 then, 否则 else(可选)
            hit = self.eval_config(step)
            branch = step.get("then") if hit else step.get("else")
            if branch:
                self.run_steps(branch, indent=indent + 1)
        elif s_type == "loop_text":
            # 循环直到找不到某文本: 只要还能识别到 text(领取等动态按钮)就重复执行 do,
            # 识别不到则退出。用于"有'领取'就点, 领完按钮消失即自然停止"的领取循环。
            kws = step.get("text", step.get("keywords"))
            body = step.get("do", [])
            guard = step.get("max_loop", 20)
            n = 0
            while n < guard and \
                    self.locate(kws, min_score=step.get("min_score", 0.4),
                                region_rel=step.get("region_rel")) is not None:
                n += 1
                print(f"{pad}[loop_text] {kws} 存在, 执行第 {n} 次领取/操作")
                self.run_steps(body, indent=indent + 1)
            print(f"{pad}[loop_text] {kws} 不存在, 领取/操作完成, 退出")
        elif s_type == "loop_fraction":
            # 按分数区域算出的次数重复执行 do (n=ceil((b-a)/57), m=floor(a/20), 取 min)
            self.run_loop_fraction(step, indent)
        elif s_type == "loop_times":
            # 循环执行子块 N 次
            times = step.get("times", 1)
            body = step.get("do", [])
            for i in range(times):
                print(f"{pad}[loop_times] 第 {i+1}/{times} 次")
                self.run_steps(body, indent=indent + 1)
        elif s_type == "retry_loop":
            # 脱困重试循环: 最多 max_rounds 轮。
            # 每轮执行 do; 只要 do 内任一带 mark 的正常点击真实命中(本轮回成),
            # 本轮即成功, 退出循环。若整轮无命中(被弹窗/无关界面挡住), 执行
            # fail_do 脱困(未提供则自动 close_dialog 尝试全部关闭类型)再进入下一轮。
            # 跑满 max_rounds 仍无命中 → 放弃, 继续流程后续步骤(不抛错)。
            rounds = step.get("max_rounds", 3)
            body = step.get("do", [])
            fail_do = step.get("fail_do")
            for i in range(rounds):
                print(f"{pad}[retry_loop] 第 {i+1}/{rounds} 轮")
                self._rr_hit = False
                self.run_steps(body, indent=indent + 1)
                if self._rr_hit:
                    print(f"{pad}[retry_loop] 第 {i+1} 轮命中目标, 退出")
                    break
                print(f"{pad}[retry_loop] 第 {i+1} 轮未命中, 脱困重试")
                if fail_do:
                    self.run_steps(fail_do, indent=indent + 1)
                else:
                    self.close_dialog()
                    time.sleep(step.get("delay", 1.0))
        else:
            print(f"[未知步骤] {s_type}")

    def run_flow(self, flow: dict):
        """执行整个流程。flow 含 steps 列表。返回值: 接口回调事件列表。"""
        name = flow.get("name", "未命名流程")
        print(f"\n===== 流程: {name} =====")
        for step in flow.get("steps", []):
            self.run_step(step)
        print(f"===== 流程完成: {name} =====")

    def run_module(self, module: dict, registry: dict) -> str:
        """执行单个模块(module), 返回结果: 'ok' | 'skip' | 'fail'。
        module: {"id","flow","flow_data","required","on_fail"}
        registry: {文件名: 已加载的 flow dict}, 避免重复读盘。
        """
        mid = module.get("id", "?")
        fname = module.get("flow")
        flow = module.get("flow_data") or registry.get(fname)
        if flow is None:
            print(f"[模块:{mid}] 未找到流程文件 {fname}")
        on_fail = module.get("on_fail", "stop_round")
        required = module.get("required", False)
        desc = flow.get("description", "") if isinstance(flow, dict) else ""
        print(f"\n>>> 模块执行: {mid} [{fname}] {'[必选]' if required else '[可选]'}  {desc}".strip())
        try:
            if isinstance(flow, dict):
                self.run_steps(flow.get("steps", []))
            print(f"<<< 模块完成: {mid}")
            return "ok"
        except Exception as e:
            print(f"<<< 模块异常: {mid} -> {e} (on_fail={on_fail})")
            return "fail"

    def run_daily(self, plan: dict) -> dict:
        """按编排 plan 调度各模块。plan: {"name","modules":[{"id","flow",...}]}。
        返回统计: {"ok":[],"skip":[],"fail":[]}。容错规则由每个 module.on_fail 决定:
          skip        -> 失败继续下一个
          stop_round  -> 失败终止本轮后续模块
        """
        name = plan.get("name", "每日编排")
        # 预加载所有引用到的流程
        registry = {}
        for m in plan.get("modules", []):
            fname = m.get("flow")
            if fname and fname not in registry:
                fp = FLOW_DIR / fname
                if fp.exists():
                    with open(str(fp), encoding="utf-8") as f:
                        registry[fname] = json.load(f)
        result = {"ok": [], "skip": [], "fail": []}
        print(f"\n########## 编排: {name} ##########")
        for m in plan.get("modules", []):
            mid = m.get("id")
            res = self.run_module(m, registry)
            result[res if res in result else "fail"].append(mid)
            if res == "fail" and m.get("on_fail", "stop_round") == "stop_round":
                print(f"[编排] 模块 {m.get('id')} 失败且 on_fail=stop_round, 终止本轮")
                break
        print(f"########## 编排结束: ok={len(result['ok'])} skip={len(result['skip'])} fail={len(result['fail'])} ##########")
        return result

    # ---- 界面采集 ----
    def collect_ui(self, min_score=0.5) -> dict:
        """采集当前界面所有文字块, 写入 click_log 知识库。
        返回: {文字: 记录} 字典。
        """
        img = self.screenshot()
        blocks = ocr_image(img)
        new_entries = {}
        for b in blocks:
            if b.get("score", 1.0) < min_score:
                continue
            text = b["text"].strip()
            if not text or len(text) < 2:
                continue
            cx, cy = b["center"]
            pt = Point(cx, cy, self.screen_w, self.screen_h)
            entry = {
                "name": text,
                "text": [text],
                "rel": [round(pt.rel[0], 4), round(pt.rel[1], 4)],
                "abs": [pt.x, pt.y],
                "screen": [self.screen_w, self.screen_h],
                "method": "ocr",
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            # 同名按钮只保留最新
            self.click_log[text] = entry
            new_entries[text] = entry
        self._save_click_log()
        print(f"[采集] 当前界面: {len(new_entries)} 个按钮已写入知识库")
        for name, e in sorted(new_entries.items()):
            print(f"  {name:<16} 相对{e['rel']} 绝对{e['abs']}")
        return new_entries


# ---------- 流程管理 ----------
def load_flows(flow_dir: Path = FLOW_DIR) -> list[dict]:
    flows = []
    if not flow_dir.exists():
        return flows
    for f in sorted(flow_dir.glob("*.json")):
        try:
            with open(f, encoding="utf-8") as fp:
                data = json.load(fp)
                data.setdefault("_file", str(f))
                flows.append(data)
        except Exception as e:
            print(f"[流程加载失败] {f}: {e}")
    return flows


def select_flow(flows, key):
    """按关键字选择流程: 先精确名匹配('name' == key), 再关键字子串匹配。
    避免『种植』误选先载入的「进入种植界面」而非「种植任务」。
    返回命中的 flow dict; 未命中返回 None。
    """
    if not key:
        return None
    for f in flows:
        if f.get("name") == key:
            return f
    for f in flows:
        if f.get("name") and key in f["name"]:
            return f
    return None


def main():
    args = sys.argv[1:]
    if not args or args[0] == "--list":
        for fl in load_flows():
            print(f"- {fl.get('name')}  [{fl.get('_file')}]")
        return

    if args[0] == "--flow":
        key = args[1] if len(args) > 1 else ""
        flows = load_flows()
        target = select_flow(flows, key)
        if target is None:
            print(f"未找到流程包含关键字 '{key}'. 可用: {[f.get('name') for f in flows]}")
            return
        eng = OCREngine()
        # 支持 --tail <数字> 覆盖配置(切换账号目标账户尾部)
        if "--tail" in args:
            i = args.index("--tail")
            if i + 1 < len(args):
                eng.config["target_tail"] = args[i + 1]
        if not eng.connect():
            return
        eng.run_flow(target)
        return

    if args[0] == "--collect":
        eng = OCREngine()
        if not eng.connect():
            return
        eng.collect_ui()
        return

    if args[0] == "--close-test":
        eng = OCREngine()
        if not eng.connect():
            return
        pt = eng.find_close_button()
        if pt is not None:
            print(f"[close-test] 命中关闭按钮 绝对{pt.x},{pt.y} 相对{tuple(round(v,4) for v in pt.rel)}")
        else:
            print("[close-test] 未命中任何关闭按钮")
        return

    if args[0] == "--add-close":
        if len(args) < 3:
            print("用法: python ocr_engine.py --add-close <名称> <corner|anchor_color>")
            return
        name, t = args[1], args[2]
        pink = {"hsv_lower": [150, 80, 90], "hsv_upper": [175, 255, 255],
                "area_min": 300, "area_max": 5000}
        if t == "corner":
            entry = {"name": name, "type": "corner",
                     "region_rel": [0.82, 0.0, 1.0, 0.18], "color": pink}
        elif t == "anchor_color":
            entry = {"name": name, "type": "anchor_color", "anchor": "提示",
                     "dx_range": [150, 400], "dy_tol": 60, "min_score": 0.4,
                     "color": dict(pink, area_max=3000)}
        else:
            print(f"未知类型 '{t}'. 可选: corner | anchor_color")
            return
        OCREngine().register_close_button(entry)
        print(f"[add-close] 已新增关闭按钮特殊逻辑: {name} ({t})")
        return

    if args[0] == "--ocr-screen":
        """开发工具: 连接->截图->一次OCR->打印当前画面所有字符及相对坐标(不写入知识库)。"""
        eng = OCREngine()
        if not eng.connect():
            return
        img = eng.screenshot()
        if img is None:
            print("[失败] 截图失败")
            return
        h, w = img.shape[:2]
        print(f"画面尺寸 W={w} H={h}")
        blocks = [b for b in ocr_image(img) if b.get("score", 1) >= 0.4]
        blocks.sort(key=lambda b: (b["center"][1], b["center"][0]))
        print(f"共识别 {len(blocks)} 块:")
        for b in blocks:
            rx, ry = round(b["center"][0] / w, 4), round(b["center"][1] / h, 4)
            print(f"  {b['text']:<16} rel({rx},{ry})  abs({b['center'][0]},{b['center'][1]})  score{b.get('score',0):.2f}")
        return

    if args[0] == "--ocr-anchor":
        """开发工具: 以指定文字(如「登录」)为锚点, 打印其它各文字块相对锚点的像素偏移。

        适用于「固定尺寸界面」(如小花仙登录界面尺寸不随设备分辨率改变):
        整体画面相对坐标(0~1)会失效, 改用「锚点 + 像素偏移」定位, 偏移不随分辨率变化。
        用法: python ocr_engine.py --ocr-anchor <锚点关键字> [--exact]
        """
        exact = "--exact" in args
        anchor_kw = args[1] if len(args) > 1 and not args[1].startswith("-") else "登录"
        eng = OCREngine()
        if not eng.connect():
            return
        img = eng.screenshot()
        if img is None:
            print("[失败] 截图失败")
            return
        h, w = img.shape[:2]
        print(f"画面尺寸 W={w} H={h} | 锚点='{anchor_kw}' (exact={exact})")
        blocks = [b for b in ocr_image(img) if b.get("score", 1) >= 0.4]
        # 找锚点块(取第一个非空、按文本命中)
        anchors = ocr_find(blocks, [anchor_kw], exact=exact)
        if not anchors:
            print(f"[失败] 未找到锚点文字 '{anchor_kw}'")
            return
        ax, ay = anchors[0]["center"]
        print(f"锚点中心 abs({ax},{ay})")
        blocks.sort(key=lambda b: (b["center"][1], b["center"][0]))
        print(f"共 {len(blocks)} 块, 相对锚点的像素偏移 (dx=center_x-ax, dy=center_y-ay):")
        for b in blocks:
            dx = int(b["center"][0] - ax)
            dy = int(b["center"][1] - ay)
            print(f"  {b['text']:<16} d({dx},{dy})  anchor_abs({b['center'][0]},{b['center'][1]})  score{b.get('score',0):.2f}")
        return

    print("用法: python ocr_engine.py --list | --flow <关键字> | --collect | --close-test | --add-close <名称> <corner|anchor_color> | --ocr-screen | --ocr-anchor <锚点关键字> [--exact]")


if __name__ == "__main__":
    main()
