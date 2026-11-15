"""
FlowerAutoAssistant - 回归帧集采集钩子（度量批 2026-11-13）
================================================
为回归帧集补 1080p 与动画中间帧两类样本的**采集入口**。只加入口, 不自动产帧:

- 引擎/编排/WebUI/CLI 全部正常路径**零调用**本工具（全仓无自动触发点）, 一切采集都由人
  在实机前显式执行; 本批不产生任何帧数据（禁 adb/实机 —— 立项红线, 采集留待实机排期批）。
- 依据: 评估报告 OCR2/OCR4/OCR5 验收线均要求「回归帧集 0 退化门」, V03(iii) 要求
  「须先采帧核验锚点」—— 现语料门 G0 自报 FAIL（DECISION.md §8: negative 20<30、popup 2/40、
  在线礼包 0/20、主界面 5/20）, 1080p 与动画中间帧两类样本缺采集通道, 本工具即该通道。

用法（需实机; 用项目 .venv）:
    python tools/collect_frames.py --kind 1080p                       # 原生分辨率静态帧(默认 1 张)
    python tools/collect_frames.py --kind 1080p --count 5 --note 家园主界面
    python tools/collect_frames.py --kind anim --count 8 --interval-ms 250
                                                                      # 动画中间帧连拍(不点击不干预画面)
    python tools/collect_frames.py --kind anim --address 127.0.0.1:5555 --adb <adb路径>

采集管线: adb exec-out screencap -p **原生直读**（不经 MAA 长边 1280 缩放 —— 见
ocr_engine.connect() ②的既有口径; 引擎工作区帧经 MAA 缩放后拿不到真 1080p 像素）。
kind 只是采集意图标签, 实际分辨率如实记录; 1080p 档实得高度 <1080 时 WARN 不 FAIL（如实不假装）。

落盘形态（仿 ocr_engine.dump_full_frame 里程碑 94 存证契约）:
    data/frame_corpus/<kind>/<会话戳>/fr_<日期>_<时刻>_<序号>_<kind>.jpg   (JPEG q85, 纯 ASCII 文件名)
    data/frame_corpus/index.jsonl                                          (元数据墓碑, 追加一行/张)
墓碑字段: ts/session/kind/file/bytes/width/height/sig(帧指纹 blake2b 前 16 hex, 与 _lab
回归帧集 fr_<指纹> 命名同源对账)/note(场景说明)/evicted。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))   # tools/ 子目录 → 仓库根, 复用引擎常量与连接逻辑

from ocr_engine import OCREngine, ADB_ADDRESS, ADB_PATH   # noqa: E402  (sys.path 注入后导入)

# 回归帧集落盘根(data/ 已被 .gitignore 整体出仓, 与 fail_cache/metrics 同区不同目录)
CORPUS_DIR = ROOT / "data" / "frame_corpus"
INDEX_FILE = CORPUS_DIR / "index.jsonl"

_KINDS = ("1080p", "anim")          # 1080p=原生分辨率静态帧; anim=动画中间帧连拍
_ANIM_DEFAULT_COUNT = 8             # 动画中间帧默认连拍张数(~2s @250ms 覆盖常见弹窗/转场动画)


def _adb_screencap(eng: OCREngine) -> "bytes | None":
    """adb exec-out screencap -p 原生直读 PNG 字节(与 ocr_engine.connect() ②实机分辨率读取同管线)。
    失败返回 None(不抛出, 调用方如实报错跳过)。"""
    try:
        import subprocess
        raw = subprocess.run(
            [eng.adb_path, "-s", eng.address, "exec-out", "screencap", "-p"],
            capture_output=True, timeout=15).stdout
        return raw or None
    except Exception as e:
        print(f"[采帧] 原生截图失败(跳过): {e}")
        return None


def _decode(raw: bytes):
    """PNG 字节 → BGR ndarray; 解码失败返回 None。"""
    import cv2
    import numpy as np
    return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)


def _save_frame(eng: OCREngine, session: str, kind: str, seq: int, note: str) -> bool:
    """截一帧 → 落盘 JPEG + 追加元数据墓碑。成功返回 True。"""
    raw = _adb_screencap(eng)
    if raw is None:
        return False
    img = _decode(raw)
    if img is None:
        print("[采帧] 帧解码失败(跳过)")
        return False
    try:
        import cv2
        h, w = img.shape[:2]
        sig = hashlib.blake2b(img.tobytes(), digest_size=16).hexdigest()[:16]  # 帧指纹, 同 _frame_hash 口径
        out = CORPUS_DIR / kind / session
        out.mkdir(parents=True, exist_ok=True)
        fn = f"fr_{time.strftime('%Y%m%d')}_{time.strftime('%H%M%S')}_{seq:03d}_{kind}.jpg"
        fp = out / fn
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            print("[采帧] JPEG 编码失败(跳过)")
            return False
        buf.tofile(str(fp))   # tofile 而非 imwrite: 绕开 OpenCV 对非 ASCII 路径的处理差异(同 dump_full_frame)
        nbytes = fp.stat().st_size
        rel = f"{kind}/{session}/{fn}"
        print(f"[采帧] {kind} #{seq:03d}: {w}x{h} -> data/frame_corpus/{rel} ({nbytes / 1024:.0f} KB, sig={sig})")
        if kind == "1080p" and h < 1080:
            print(f"[采帧] WARN: kind=1080p 但实得高度 {h}<1080 —— 设备非 1080p 或管线降级, 已如实记录分辨率")
        try:
            entry = {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "session": session,
                "kind": kind, "file": rel, "bytes": nbytes,
                "width": int(w), "height": int(h), "sig": sig,
                "note": str(note or ""), "evicted": False,
            }
            with open(INDEX_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e2:
            print(f"[采帧] 索引写入失败(不影响已落盘像素): {e2}")
        return True
    except Exception as e:
        print(f"[采帧] 落盘异常(跳过): {e}")
        return False


def main() -> int:
    p = argparse.ArgumentParser(description="回归帧集采集钩子(1080p 静态帧 / 动画中间帧连拍; 显式执行, 无自动触发)")
    p.add_argument("--kind", required=True, choices=_KINDS,
                   help="1080p=原生分辨率静态帧; anim=动画中间帧连拍(采集意图标签, 实际分辨率如实记录)")
    p.add_argument("--count", type=int, default=None, help="采集张数(默认: 1080p=1, anim=8)")
    p.add_argument("--interval-ms", type=int, default=250, help="连拍间隔毫秒(默认 250, 动画中间帧时序密度)")
    p.add_argument("--address", default=ADB_ADDRESS, help=f"ADB 地址 (默认: {ADB_ADDRESS})")
    p.add_argument("--adb", default=ADB_PATH, help="adb 可执行文件路径")
    p.add_argument("--note", default="", help="场景说明(写入 index.jsonl 墓碑, 如「好友列表翻页中」)")
    args = p.parse_args()

    count = args.count if args.count and args.count > 0 else (1 if args.kind == "1080p" else _ANIM_DEFAULT_COUNT)
    session = time.strftime("%Y%m%d_%H%M%S")

    eng = OCREngine(adb_path=args.adb, address=args.address)
    if not eng.connect():
        print("[采帧] 连接模拟器失败, 请确认模拟器已启动且 ADB 可用")
        return 1
    print(f"[采帧] 开始: kind={args.kind} count={count} interval={args.interval_ms}ms "
          f"note={args.note!r} session={session}(只截图, 不点击不干预画面)")

    ok_n = 0
    for i in range(1, count + 1):
        if _save_frame(eng, session, args.kind, i, args.note):
            ok_n += 1
        if i < count and args.interval_ms > 0:
            time.sleep(args.interval_ms / 1000.0)
    print(f"[采帧] 完成: {ok_n}/{count} 帧已落盘 -> data/frame_corpus/ (元数据: index.jsonl)")
    return 0 if ok_n else 1


if __name__ == "__main__":
    sys.exit(main())
