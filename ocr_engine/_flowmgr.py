"""流程管理与引擎 CLI(原 ocr_engine.py __main__ 用法面)。

E01(batch-03, 2026-11-14) 自单文件 ocr_engine.py 机械拆包: 本文件各段为原文件对应
行段的**逐行原文**(唯 __file__ 锚点因包层级 +1 机械重锚定, 见 ast_hash_compare.py
allowlist)。行为等价口径: 帧集回归 0 退化 + 闸门全绿 + import 面零改动。
原行段映射: evidence/batch-03/tiles_manifest.json。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ._constants import FLOW_DIR
from .engine._core import OCREngine
from ocr_ui import ocr_image, ocr_find

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
