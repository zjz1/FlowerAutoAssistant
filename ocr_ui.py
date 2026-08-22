"""OCR 识别服务（单例复用版）。

设计目标：
- 模型只加载一次（模块级单例），避免每次调用重复初始化、重复触发权限。
- 提供函数式 API：`ocr_image(path_or_ndarray) -> list[OCRResult]`
- 提供 CLI 模式：`python ocr_ui.py <截图.png>` 打印文字+坐标（兼容旧用法）
- 提供常驻服务模式：`python ocr_ui.py --serve`，从 stdin 逐行读图片路径，返回 JSON，
  引擎只初始化一次，适合被主程序以子进程方式反复调用。

OCRResult 结构: {"text": str, "center": [cx, cy], "box": [x1,y1,x2,y2], "score": float}
坐标基准: 输入图片像素坐标（默认 1280x720 横屏）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

# ---------- 单例引擎 ----------
_engine = None


def get_engine():
    """获取全局唯一 OCR 引擎实例（首次调用时初始化）。"""
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _engine = RapidOCR()
    return _engine


def ocr_image(image) -> list[dict]:
    """对图片执行 OCR。image 可为路径字符串 / Path / numpy 数组 (BGR)。
    返回按 上->下、左->右 排序的文字块列表。
    """
    engine = get_engine()
    res, _ = engine(image)
    if not res:
        return []
    out = []
    for box, text, score in res:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        out.append(
            {
                "text": text,
                "center": [int(sum(xs) / 4), int(sum(ys) / 4)],
                "box": [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))],
                "score": float(score),
            }
        )
    # 按 y 优先（上->下）、x 次之（左->右）排序
    out.sort(key=lambda r: (r["box"][1], r["box"][0]))
    return out


def ocr_find(blocks, keyword: str) -> list[dict]:
    """在 OCR 结果中筛选包含 keyword 的文字块。keyword 可为 str 或 str 列表（任一命中）。
    返回命中块列表。
    """
    if isinstance(keyword, str):
        keyword = [keyword]
    return [b for b in blocks if any(k in b["text"] for k in keyword)]


# ---------- CLI ----------
def _print_human(blocks):
    if not blocks:
        print("未识别到文字")
        return
    print(f"{len(blocks)} 个文字块:\n")
    print(f"{'文字':<16}{'中心X':<8}{'中心Y':<8}  框x1 y1 x2 y2")
    print("-" * 60)
    for b in blocks:
        cx, cy = b["center"]
        x1, y1, x2, y2 = b["box"]
        print(f"{b['text']:<16}{cx:<8}{cy:<8}  {x1} {y1} {x2} {y2}")


def _serve_loop():
    """常驻服务：逐行读图片路径，每行输出一条 JSON 结果。引擎只初始化一次。"""
    engine = get_engine()  # 提前初始化，权限只需一次
    print("[OCR-Server] ready", flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            blocks = ocr_image(line)
            print(json.dumps(blocks, ensure_ascii=False), flush=True)
        except Exception as e:
            print(json.dumps({"error": str(e)}), flush=True)


def main():
    args = sys.argv[1:]
    if args and args[0] == "--serve":
        _serve_loop()
        return
    if not args:
        print("用法: python ocr_ui.py <截图.png> | --serve")
        sys.exit(1)
    blocks = ocr_image(args[0])
    _print_human(blocks)


if __name__ == "__main__":
    main()
