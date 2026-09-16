"""实机界面探索脚本: navigate 进入家族活动 -> 打印该面板全部 OCR 文本与相对坐标.

归档于 dev_tools/explore/ —— 采集家族活动页等子界面的文字块分布, 供设计流程步骤 / 定位入口用。需连模拟器。
用法(项目根下): .venv\\Scripts\\python.exe -u dev_tools\\explore\\screen_family_activity.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 项目根, 保证 import ocr_engine

from ocr_engine import OCREngine

eng = OCREngine()
assert eng.connect(), "连接失败"

r = eng.run_navigate({"type": "navigate", "target": "家族活动", "max_rounds": 4})
print(f"[结果] navigate 家族活动 = {r}, scene={eng._scene}")

img = eng.screenshot()
h, w = img.shape[:2]
print(f"画面尺寸 W={w} H={h}")
from ocr_ui import ocr_image
blocks = ocr_image(img)
print(f"共识别 {len(blocks)} 块:")
for b in sorted(blocks, key=lambda x: (x["center"][1], x["center"][0])):
    t = b["text"].strip()
    rx, ry = round(b["center"][0] / w, 4), round(b["center"][1] / h, 4)
    print(f"  {t:<16} rel({rx},{ry})  abs({int(b['center'][0])},{int(b['center'][1])})  score{b.get('score',0):.2f}")