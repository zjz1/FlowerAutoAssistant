"""实机截图保存脚本: 连接后截取当前画面存为指定 PNG, 供人工/视觉查看图形按钮布局.

归档于 dev_tools/explore/ —— 采集无文字图形按钮(如推荐套装/一键搭配)位置时用。需连模拟器。
用法(项目根下): .venv\\Scripts\\python.exe -u dev_tools\\explore\\snap.py debug\\recommend.png
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 项目根

import cv2
from ocr_engine import OCREngine

out = sys.argv[1] if len(sys.argv) > 1 else "debug/snap.png"
eng = OCREngine()
assert eng.connect(), "连接失败"
img = eng.screenshot()
Path(out).parent.mkdir(parents=True, exist_ok=True)
cv2.imwrite(out, img)
print(f"已保存 {len(img) if hasattr(img,'__len__') else img.shape} -> {out}")