"""实机「确认+采集」工具: 按序点击进入目标界面→用颜色特征 find(关闭钮)或指定 rel 定位按钮→标注截图→(可选)采集模板。

归档于 dev_tools/explore/ —— 开发确认各个图形按钮的采集对象与真实点位(不依赖不稳定的图片视觉描述, 而是程序化定位)。
需连模拟器。用法(项目根下):
  .venv\\Scripts\\python.exe -u dev_tools\\explore\\confirm_capture.py \\
      --nav "x,y,w|x,y,w"      按序点击相对坐标进入目标界面(每组 x,y,等待秒)
      --find <type>            用 find_all_close_buttons 定位该类型关闭钮(corner/corner_white/corner_pink_small…)
      --loc "cx,cy"            或直接指定按钮相对坐标点
      --tpl <名称>             采集模板存 resource/template/<名称>.png(需 --hw --hh)
      --hw 0.026 --hh 0.045    采集半宽/半高(相对)
      --out debug\\x.png       标注图输出(可选)
输出打印被定位按钮的 abs/rel 坐标。
"""
import sys, argparse, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import cv2
from ocr_engine import OCREngine, TEMPLATE_DIR


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nav", help="| 分隔 x,y,wait 相对坐标点击序列")
    ap.add_argument("--find", help="关闭按钮类型(用颜色特征定位)")
    ap.add_argument("--loc", help="直接指定相对坐标 cx,cy")
    ap.add_argument("--tpl", help="采集模板名(存 resource/template/)")
    ap.add_argument("--hw", type=float, default=0.026)
    ap.add_argument("--hh", type=float, default=0.045)
    ap.add_argument("--out", help="标注图输出路径")
    a = ap.parse_args()
    assert a.find or a.loc, "需提供 --find 或 --loc"

    eng = OCREngine()
    assert eng.connect(), "连接失败"

    if a.nav:
        for seg in a.nav.strip().split("|"):
            seg = seg.strip()
            if not seg:
                continue
            p = [float(t.strip()) for t in seg.split(",")]
            x, y, w = p[0], p[1], p[2] if len(p) >= 3 else 1.6
            ax, ay = int(x * 1280), int(y * 720)
            print(f"[nav] rel({x},{y}) abs({ax},{ay}) wait {w}")
            eng.click_abs(ax, ay); time.sleep(w)

    img = eng.screenshot()
    assert img is not None, "截图失败"
    h, w = img.shape[:2]

    pt = None
    if a.loc:
        cx, cy = (float(t) for t in a.loc.split(","))
        pt = type("P", (), {"x": int(cx * w), "y": int(cy * h)})()
        print(f"[loc] rel({cx},{cy}) abs({pt.x},{pt.y})")
    elif a.find:
        for hh in eng.find_all_close_buttons(img=img):
            if hh["type"] == a.find:
                pt = hh["pt"]
                print(f"[find/{a.find}] {hh['name']} abs({pt.x},{pt.y}) rel({pt.x/w:.4f},{pt.y/h:.4f})")
                break
        if pt is None:
            print(f"未找到 {a.find} 类型关闭钮")
            sys.exit(1)

    if a.out:
        hw2, hh2 = 0.03 * w, 0.04 * h
        x1, y1 = int(pt.x - hw2), int(pt.y - hh2)
        x2, y2 = int(pt.x + hw2), int(pt.y + hh2)
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
        cv2.putText(img, f"rel({pt.x/w:.3f},{pt.y/h:.3f})", (x1, max(14, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(a.out, img)
        print(f"标注图 -> {a.out}")

    if a.tpl:
        hw3, hh3 = a.hw * w, a.hh * h
        x1, y1 = int(pt.x - hw3), int(pt.y - hh3)
        x2, y2 = int(pt.x + hw3), int(pt.y + hh3)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        crop = img[y1:y2, x1:x2]
        fname = a.tpl if a.tpl.lower().endswith(".png") else a.tpl + ".png"
        TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(TEMPLATE_DIR / fname), crop)
        print(f"采集模板 -> resource/template/{fname} ({x2-x1}x{y2-y1}px)")


if __name__ == "__main__":
    main()