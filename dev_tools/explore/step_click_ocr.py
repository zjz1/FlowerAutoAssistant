"""实机界面交互探索脚本: 依次执行若干个 (点rel坐标 -> 打印OCR) 步骤, 用于手动分步定位子界面入口.

归档于 dev_tools/explore/ —— 定位「家族活动」下各活动子界面(闪耀委托挑战/矿洞等)入口的分步勘探。需连模拟器。
用法(项目根下): .venv\\Scripts\\python.exe -u dev_tools\\explore\\step_click_ocr.py
STEPS 里每步: {"rel":[x,y],"name":"说明"} -> 点击后打印画面 OCR; 或 {"sleep":秒}.
"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 项目根, 保证 import ocr_engine

from ocr_engine import OCREngine
from ocr_ui import ocr_image

eng = OCREngine()
assert eng.connect(), "连接失败"

def dump(tag):
    img = eng.screenshot()
    h, w = img.shape[:2]
    blocks = ocr_image(img)
    print(f"\n===== [{tag}] 画面 {w}x{h} 共{len(blocks)}块 =====")
    for b in sorted(blocks, key=lambda x: (x["center"][1], x["center"][0])):
        t = b["text"].strip()
        rx, ry = round(b["center"][0] / w, 4), round(b["center"][1] / h, 4)
        print(f"  {t:<16} rel({rx},{ry})  abs({int(b['center'][0])},{int(b['center'][1])})  s{b.get('score',0):.2f}")

# ---- 分步步骤(按需修改) ----
STEPS = [
    {"rel": [0.2664, 0.9181], "name": "点「我换好了」(已点推荐搭配后)"},
]
row = 0
for i, st in enumerate(STEPS):
    if "sleep" in st:
        time.sleep(st["sleep"]); continue
    rx, ry = st["rel"]
    ax, ay = int(rx * 1280), int(ry * 720)
    print(f"\n>>> [{i}] {st.get('name','')} 点击 rel({rx},{ry}) abs({ax},{ay})")
    eng.click_abs(ax, ay)
    time.sleep(1.6)
    dump(st.get('name', f'step{i}'))