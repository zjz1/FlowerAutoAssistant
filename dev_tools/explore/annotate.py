"""实机图标点位标注工具: 连接模拟器→(可选)依次点击进入界面→截图→在待采按钮相对坐标画框+编号→存 PNG。

归档于 dev_tools/explore/ —— 开发时给「拟采集/拟点击」的图形按钮做点位标注，供人工确认采集对象。
需连模拟器。用法(项目根下):
  .venv\\Scripts\\python.exe -u dev_tools\\explore\\annotate.py <out.png> \
      --click "x,y,wait|x,y,wait"  按序点击若干相对坐标(可进入目标界面), 每组 3 值(相对坐标+等待秒)
      --box "cx,cy,name,hw,hh|cx,cy,name,hw,hh"  在相对坐标中心画框+框内半数宽高(名称不含逗号)
示例(点「家园」进入后标注 A1 关闭钮, 标签用 ASCII 避免乱码):
  .venv\\Scripts\\python.exe -u dev_tools\\explore\\annotate.py debug\\plant.png \\
      --click "0.8719,0.9514,2.5" --box "0.988,0.149,A1-close_corner_pink,0.025,0.035"
"""
import sys, argparse, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 项目根

import cv2
from ocr_engine import OCREngine


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", help="输出 PNG 路径")
    ap.add_argument("--click", help="点相对坐标, | 分隔每组 x,y,wait_sec")
    ap.add_argument("--box", help="标注框, | 分隔每组 cx,cy,名称,hw,hh(名称内勿含逗号)")
    a = ap.parse_args()

    clicks = []
    if a.click:
        for seg in a.click.strip().split("|"):
            seg = seg.strip()
            if not seg:
                continue
            p = [float(t.strip()) for t in seg.split(",")]
            clicks.append((p[0], p[1], p[2] if len(p) >= 3 else 1.6))
    boxes = []
    if a.box:
        for seg in a.box.strip().split("|"):
            seg = seg.strip()
            if not seg:
                continue
            p = seg.split(",")
            cx, cy, name = float(p[0]), float(p[1]), p[2]
            hw = float(p[3]) if len(p) >= 4 else 0.04
            hh = float(p[4]) if len(p) >= 5 else 0.045
            boxes.append((cx, cy, name, hw, hh))

    eng = OCREngine()
    assert eng.connect(), "连接失败"

    for (x, y, w) in clicks:
        ax, ay = int(x * 1280), int(y * 720)
        print(f"[点] rel({x},{y}) abs({ax},{ay}) wait {w}s")
        eng.click_abs(ax, ay); time.sleep(w)

    img = eng.screenshot()
    assert img is not None, "截图失败"
    h, w = img.shape[:2]
    for n, (cx, cy, name, hw, hh) in enumerate(boxes, 1):
        x1, y1 = int((cx - hw) * w), int((cy - hh) * h)
        x2, y2 = int((cx + hw) * w), int((cy + hh) * h)
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
        cv2.putText(img, f"{n} {name}", (x1, max(14, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(a.out, img)
    print(f"[标注] 共 {len(boxes)} 个框 -> {a.out} ({w}x{h})")


if __name__ == "__main__":
    main()