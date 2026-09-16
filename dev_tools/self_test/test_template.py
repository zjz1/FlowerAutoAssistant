"""模板匹配识别离线自测: 验证 locate_template 在内存合成图上能命中「纯图形按钮」中心点。无需连设备。

归档于 dev_tools/self_test/ —— 回归 click_template/locate_template 的多尺度匹配正确性。
用法(项目根下): .venv\\Scripts\\python.exe -u dev_tools\\self_test\\test_template.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 项目根

import cv2
import numpy as np
import ocr_engine as E


def test_locate_template_center():
    """在 500x300 带细小噪声的灰(200)背景上放一个「深蓝按钮(空白点)」, 以周边 60x60 作模板。
    背景加噪声模拟真实游戏界面的纹理, 使模板自匹配位置在多个匹配尺度下唯一最高(≈(325,205)),
    避免「大片纯色背景」在多尺度限缩下与模板背景部分误匹配。
    """
    img = np.full((300, 500, 3), 200, np.uint8).astype(np.int16)
    img += np.random.default_rng(1).integers(-12, 13, img.shape)
    img = np.clip(img, 0, 255).astype(np.uint8)
    cv2.rectangle(img, (300, 180), (350, 230), (30, 30, 160), -1)  # 深蓝按钮
    cv2.circle(img, (325, 205), 12, (255, 255, 255), -1)           # 内部白点(对比)
    tpl = img[175:235, 295:355].copy()  # 60x60, 含按钮+噪声灰边

    tp = E.TEMPLATE_DIR / "test_red.png"
    E.TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(tp), tpl)
    try:
        eng = E.OCREngine(adb_path=E.ADB_PATH, address="127.0.0.1:1")  # 不连接设备
        pt = eng.locate_template("test_red.png", img=img, threshold=0.8)
        assert pt is not None, "应命中模板位置"
        assert abs(pt.x - 325) < 8 and abs(pt.y - 205) < 8, f"中心偏差: ({pt.x},{pt.y}) 期望≈(325,205)"
        print(f"OK  locate_template 命中中心 ({pt.x},{pt.y}) 期望≈(325,205)  score>0.8")
    finally:
        if tp.exists():
            tp.unlink()


def test_missing_template_returns_none():
    """不存在的模板应返回 None, 不抛异常。"""
    eng = E.OCREngine(adb_path=E.ADB_PATH, address="127.0.0.1:1")
    assert eng.locate_template("no_such_tpl_xyz", img=np.zeros((100, 100, 3), np.uint8)) is None
    print("OK  不存在模板返回 None")


if __name__ == "__main__":
    test_locate_template_center()
    test_missing_template_returns_none()
    print("\n全部模板匹配自测通过 ✅")