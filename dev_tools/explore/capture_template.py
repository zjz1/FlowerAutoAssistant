"""实机模板采集工具: 连接模拟器→截图→按「相对中心 + 相对半宽高」裁剪按钮区域→存 resource/template/<名称>.png。

归档于 dev_tools/explore/ —— 为 click_template 步骤采集「纯图形/无文字按钮」模板图
(借鉴 MAA TemplateMatch)。需连模拟器。
用法(项目根下): .venv\\Scripts\\python.exe -u dev_tools\\explore\\capture_template.py <名称> <rel_cx> <rel_cy> <half_w> <half_h> [--debug]
  <名称>     存为 resource/template/<名称>.png(建议英文/语义名, 如 close_pink / switch_arrow)
  rel_cx,cy  按钮中心相对坐标(0~1)
  half_w,h   按钮半宽/半高(相对, 0~1); 裁剪范围 = 中心 ± 半宽高
示例(裁剪整体右上角 (0.988,0.149) 约 40x40px, 1280x720 下 half_w=0.031, half_h=0.056):
  .venv\\Scripts\\python.exe -u dev_tools\\explore\\capture_template.py close_pink 0.988 0.149 0.031 0.056
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 项目根

import cv2
from ocr_engine import OCREngine, TEMPLATE_DIR


def main():
    if len(sys.argv) < 6:
        print(__doc__)
        sys.exit(1)
    name, rel_cx, rel_cy, half_w, half_h = (
        sys.argv[1], float(sys.argv[2]), float(sys.argv[3]),
        float(sys.argv[4]), float(sys.argv[5]),
    )
    debug = "--debug" in sys.argv

    eng = OCREngine()
    assert eng.connect(), "连接失败"

    img = eng.screenshot()
    assert img is not None, "截图失败"
    h, w = img.shape[:2]
    cx, cy = int(rel_cx * w), int(rel_cy * h)
    hw, hh = int(half_w * w), int(half_h * h)
    x1, y1 = max(0, cx - hw), max(0, cy - hh)
    x2, y2 = min(w, cx + hw), min(h, cy + hh)
    crop = img[y1:y2, x1:x2]
    if crop.size == 0:
        print(f"裁剪为空, 检查 half 参数: 区域 ({x1},{y1})-({x2},{y2})")
        sys.exit(1)

    fname = name if name.lower().endswith(".png") else name + ".png"
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    out = TEMPLATE_DIR / fname
    cv2.imwrite(str(out), crop)
    print(f"[采集] 按钮中心 abs({cx},{cy}) rel({rel_cx},{rel_cy})")
    print(f"[采集] 裁剪区域 abs ({x1},{y1})-({x2},{y2}) = {x2-x1}x{y2-y1}px")
    print(f"[采集] 已保存模板 -> {out}")
    if debug:
        cv2.imwrite(str(TEMPLATE_DIR / ("_dbg_" + fname)), crop)


if __name__ == "__main__":
    main()