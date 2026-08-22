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
import os
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
        """记录一次成功点击: 按钮名 + 文本 + 相对坐标 + 绝对坐标。同名按钮只保留一次。"""
        kws = keywords if isinstance(keywords, list) else [keywords]
        self.click_log[name] = {
            "name": name,
            "text": kws,
            "rel": [round(pt.rel[0], 4), round(pt.rel[1], 4)],
            "abs": [pt.x, pt.y],
            "screen": [self.screen_w, self.screen_h],
            "method": method,  # ocr / fallback
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
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
        self._ctrl.post_click(int(x), int(y)).wait()
        print(f"[点击] 绝对({x},{y})")

    def click_rel(self, rx: float, ry: float) -> None:
        """按相对坐标点击 (自适应屏幕尺寸)。"""
        x = int(rx * self.screen_w)
        y = int(ry * self.screen_h)
        print(f"[点击] 相对({rx:.3f},{ry:.3f}) -> 绝对({x},{y})")
        self.click_abs(x, y)

    # ---- OCR 定位 ----
    def find_text(self, keywords, img=None, top_k=3):
        """在截图(或给定图)中按关键字找文字块。返回 OCR 块列表 (含坐标)。
        若整图识别出的文字块过宽(可能合并了相邻按钮), 会自动对该区域放大 2x 重识别拆开。
        """
        img = img if img is not None else self.screenshot()
        if img is None:
            return []
        blocks = ocr_image(img)
        # 对命中关键字但块过宽(可能合并多按钮)的, 做放大重识别
        refined = []
        for b in blocks:
            x1, y1, x2, y2 = b["box"]
            w = x2 - x1
            hit = any(k in b["text"] for k in (keywords if isinstance(keywords, list) else [keywords]))
            if hit and w > 90:  # 过宽, 疑似合并
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
                        refined.append(nb2)
                    continue
            refined.append(b)
        return ocr_find(refined, keywords)

    def locate(self, keywords, img=None, min_score=0.5):
        """返回第一个命中块的中心绝对坐标 Point; 未命中返回 None。
        命中后更新 last_rel 缓存。
        """
        blocks = self.find_text(keywords, img=img)
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

    def click_text(self, keywords, img=None, fallback_rel=None, min_score=0.5) -> bool:
        """OCR 定位关键字并点击。命中返回 True。
        回退链: OCR → 颜色特征(若知识库有 color 配置) → 进程缓存 → 知识库坐标 → 失败
        """
        pt = self.locate(keywords, img=img, min_score=min_score)
        if pt is not None:
            print(f"[OCR命中] {keywords} -> {pt.x},{pt.y}")
            self.click_abs(pt.x, pt.y)
            self._log_click(keywords[0] if isinstance(keywords, list) else keywords,
                            keywords, pt, "ocr")
            return True
        # 颜色特征检测 (针对无文字的图形按钮)
        kws = keywords if isinstance(keywords, list) else [keywords]
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

    def run_step(self, step: dict):
        """执行单个步骤。step 为流程 JSON 中的一个节点。"""
        s_type = step.get("type")
        kws = step.get("text", step.get("keywords"))
        if s_type == "wait_text":
            self.wait_text(kws, timeout=step.get("timeout", 30), interval=step.get("interval", 1.0))
        elif s_type == "click_text":
            ok = self.click_text(kws, fallback_rel=step.get("fallback_rel"))
            time.sleep(step.get("delay", 0.5))
        elif s_type == "sleep":
            time.sleep(step.get("seconds", 1.0))
        elif s_type == "click_rel":
            rx, ry = step["rel"]
            self.click_rel(rx, ry)
            time.sleep(step.get("delay", 0.5))
        else:
            print(f"[未知步骤] {s_type}")

    def run_flow(self, flow: dict):
        """执行整个流程。flow 含 steps 列表。"""
        name = flow.get("name", "未命名流程")
        print(f"\n===== 流程: {name} =====")
        for step in flow.get("steps", []):
            self.run_step(step)
        print(f"===== 流程完成: {name} =====")

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


def main():
    args = sys.argv[1:]
    if not args or args[0] == "--list":
        for fl in load_flows():
            print(f"- {fl.get('name')}  [{fl.get('_file')}]")
        return

    if args[0] == "--flow":
        key = args[1] if len(args) > 1 else ""
        flows = load_flows()
        target = next((f for f in flows if key in f.get("name", "")), None)
        if target is None:
            print(f"未找到流程包含关键字 '{key}'. 可用: {[f.get('name') for f in flows]}")
            return
        eng = OCREngine()
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

    print("用法: python ocr_engine.py --list | --flow <关键字> | --collect")


if __name__ == "__main__":
    main()
