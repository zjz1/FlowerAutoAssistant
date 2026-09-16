"""实机坐标校准脚本: 点速通 -> 抓「确定」弹窗坐标(真实点击驱动).

归档于 dev_tools/calibrate/ —— 采集速通/确定 等按钮相对坐标用, 需连接模拟器实机。
原为临时脚本 _tmp_cal_qd.py。
用法(项目根下): .venv\\Scripts\\python.exe -u dev_tools\\calibrate\\cal_quick_dialog_qd.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 项目根, 保证 import ocr_engine

import time
from ocr_engine import OCREngine
from ocr_ui import ocr_image

eng = OCREngine()
assert eng.connect(), "连接失败"

def screen_rel_blocks(min_score=0.4):
    img = eng.screenshot()
    h, w = img.shape[:2]
    out = []
    for b in ocr_image(img):
        if b.get("score", 1) >= min_score:
            rx, ry = round(b["center"][0] / w, 4), round(b["center"][1] / h, 4)
            out.append((b["text"].strip(), rx, ry, b["center"][0], b["center"][1]))
    return out

def find_dialog_qd(tag):
    """找含「确定」的块, 打印坐标; 命中则点击返回 True."""
    blocks = screen_rel_blocks()
    qd = [b for b in blocks if "确定" in b[0]]
    print(f"[{tag}] 画面含'确定'的块:")
    for t, rx, ry, ax, ay in qd:
        print(f"   文本'{t}' rel({rx},{ry}) abs({ax},{ay})")
    if not qd:
        print(f"[{tag}] 未找到「确定」")
        return False
    # 点击首个「确定」
    t, rx, ry, ax, ay = qd[0]
    print(f"[{tag}] 点击「确定」 rel({rx},{ry})")
    eng.click_abs(ax, ay)
    return True

# 1) 若当前画面有「速通」则点击进入
print("== 当前画面字符(节选含'速通'/'确定') ==")
blk = screen_rel_blocks()
for t, rx, ry, ax, ay in blk:
    if "速通" in t or "确定" in t or "挑战" in t:
        print(f"   {t:<12} rel({rx},{ry}) abs({ax},{ay})")

if any("速通" in b[0] for b in blk):
    st = [b for b in blk if "速通" in b[0]][0]
    print(f"点击「速通」 rel({st[1]},{st[2]})")
    eng.click_abs(st[3], st[4])
    time.sleep(1.8)

# 2) 抓第一个「确定」弹窗
find_dialog_qd("弹窗1")
time.sleep(1.2)
# 3) 抓第二个「确定」弹窗
find_dialog_qd("弹窗2")
time.sleep(1.2)
# 4) 可能还有第三个
find_dialog_qd("弹窗3")
print("校准抓取完成.")