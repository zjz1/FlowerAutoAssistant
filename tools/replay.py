# -*- coding: utf-8 -*-
"""离线回放/回归基座（1.0 #9）。

用途: 拿真机存的故障帧（data/fail_cache，不入库）在**不连 ADB** 的情况下跑真实 OCR，
把「识别文本 / 定位结果 / 阻断层 / 场景判据」与 case 里的期望逐条比对，输出可复核证据。
回归面 = OCR 与判定逻辑本身；点击动作不执行（回放只报“会点哪”）。

用法（仓库根执行）:
    python tools/replay.py --list
    python tools/replay.py --all
    python tools/replay.py --case upgrade_overlay -v
    python tools/replay.py --all --strict     # 缺帧也算失败（默认缺帧=SKIP）

case 格式(tools/replay/cases/*.json):
    {
      "name": "...", "description": "...",
      "frame": "data/fail_cache/<会话>/<文件>.jpg",   # 相对仓库根; 不存在则 SKIP
      "expect": {
        "blocker": "level_up" | null,                 # 阻断层 id（null=不应有阻断层）
        "text_any": ["..."], "text_none": ["..."],    # OCR 文本必须/不得出现
        "locate": [{"keywords": ["..."], "rel": [x,y], "tol": 0.02}],
        "scene":  [{"name": "家园界面", "value": true}]
      }
    }

退出码: 0=全通过(含 SKIP) / 1=有 FAIL 或 --strict 下缺帧。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = Path(__file__).resolve().parent / "replay" / "cases"
if str(ROOT) not in sys.path:      # 以脚本方式运行时, 让仓库根可 import ocr_engine
    sys.path.insert(0, str(ROOT))


def _load_cases() -> list[dict]:
    cases = []
    for f in sorted(CASES_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"[case] 解析失败 {f.name}: {e}")
            continue
        data["_file"] = f.name
        cases.append(data)
    return cases


def _evidence(eng, img) -> None:
    """打印本帧 OCR 全量文本 + 相对坐标（可复核证据）。"""
    blocks = eng._ocr_frame(img, need_split=False)[0]
    print(f"    OCR {len(blocks)} 块:")
    for b in sorted(blocks, key=lambda x: (x["center"][1], x["center"][0])):
        cx, cy = b["center"]
        rel = (cx / eng.screen_w if eng.screen_w else 0.0,
               cy / eng.screen_h if eng.screen_h else 0.0)
        print(f"      {b.get('text', ''):<20} score={float(b.get('score', 0)):.2f} "
              f"rel=({rel[0]:.3f},{rel[1]:.3f})")


def _run_case(eng, case: dict, verbose: bool) -> tuple[bool, str]:
    import cv2

    frame = ROOT / case["frame"]
    if not frame.exists():
        return False, f"SKIP 缺帧 {case['frame']}（真机故障帧不入库；在本机跑过一次后可回放）"
    img = cv2.imread(str(frame))
    if img is None:
        return False, f"FAIL 帧读取失败 {frame}"
    eng.screen_w, eng.screen_h = img.shape[1], img.shape[0]
    expect = case.get("expect") or {}
    problems: list[str] = []
    if verbose:
        _evidence(eng, img)

    # ---- 文本必须出现 / 不得出现 ----
    any_kws = expect.get("text_any") or []
    if any_kws:
        hits = eng.find_text(any_kws, img=img, need_refine=False, log_miss=False)
        found = {b["text"].strip() for b in hits}
        missing = [k for k in any_kws
                   if not any(k in t for t in found)]
        if missing:
            problems.append(f"text_any 未命中 {missing}（实读: {sorted(found)[:8]}）")
    none_kws = expect.get("text_none") or []
    if none_kws:
        hits = eng.find_text(none_kws, img=img, need_refine=False, log_miss=False)
        bad = sorted({b["text"].strip() for b in hits})
        if bad:
            problems.append(f"text_none 出现 {bad}")

    # ---- 定位点与相对坐标 ----
    for item in expect.get("locate") or []:
        kws = item["keywords"]
        pt = eng.locate(kws, img=img, min_score=item.get("min_score", 0.4),
                        need_refine=False, log_miss=False)
        if pt is None:
            problems.append(f"locate {kws} 未命中")
            continue
        rel = pt.rel
        exp = item["rel"]
        tol = float(item.get("tol", 0.02))
        ok = abs(rel[0] - exp[0]) <= tol and abs(rel[1] - exp[1]) <= tol
        print(f"    locate {kws} -> ({pt.x},{pt.y}) rel=({rel[0]:.3f},{rel[1]:.3f}) "
              f"期望({exp[0]:.3f},{exp[1]:.3f})±{tol} -> {'OK' if ok else 'MISMATCH'}")
        if not ok:
            problems.append(f"locate {kws} 偏差过大")

    # ---- 阻断层 ----
    if "blocker" in expect:
        info = eng.detect_blocker(img=img)
        got = info["id"] if info else None
        ok = got == expect["blocker"]
        print(f"    blocker -> {got!r}（期望 {expect['blocker']!r}）-> {'OK' if ok else 'MISMATCH'}")
        if not ok:
            problems.append(f"blocker {got!r} != {expect['blocker']!r}")

    # ---- 场景判据 ----
    for item in expect.get("scene") or []:
        got = eng.judge_scene(item["name"], img=img, quiet=True)
        if got != item["value"]:
            problems.append(f"scene {item['name']} = {got}, 期望 {item['value']}")
        else:
            print(f"    scene {item['name']} = {got} -> OK")

    if problems:
        return False, "FAIL " + "; ".join(problems)
    return True, "PASS"


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="FAA 离线回放（不连 ADB）")
    ap.add_argument("--list", action="store_true", help="列出所有 case")
    ap.add_argument("--case", action="append", default=[], help="只跑指定 case（可重复）")
    ap.add_argument("--all", action="store_true", help="跑全部 case")
    ap.add_argument("--strict", action="store_true", help="缺帧也算失败")
    ap.add_argument("-v", "--verbose", action="store_true", help="打印每帧全量 OCR 证据")
    args = ap.parse_args(argv)

    cases = _load_cases()
    if args.list or not (args.all or args.case):
        print(f"可用 case（{CASES_DIR}）:")
        for c in cases:
            has = "有帧" if (ROOT / c.get("frame", "")).exists() else "缺帧"
            print(f"  {c['name']:<28} [{has}] {c.get('description', '')}")
        return 0

    selected = [c for c in cases if not args.case or c["name"] in args.case]
    unknown = set(args.case) - {c["name"] for c in cases}
    if unknown:
        print(f"未知 case: {sorted(unknown)}")
        return 1

    from ocr_engine import OCREngine
    import cv2  # noqa: F401 —— 与 OCREngine 同环境, 早失败早提示

    eng = OCREngine()
    passed = failed = skipped = 0
    print(f"FAA 离线回放: {len(selected)} 个 case")
    for c in selected:
        print(f"\n[{c['name']}] {c.get('description', '')}")
        ok, msg = _run_case(eng, c, args.verbose)
        if msg.startswith("SKIP"):
            skipped += 1
            if args.strict:
                failed += 1
                print(f"  {msg}")
            else:
                print(f"  {msg}")
        elif ok:
            passed += 1
            print(f"  {msg}")
        else:
            failed += 1
            print(f"  {msg}")

    print(f"\n结果: PASS {passed} / FAIL {failed} / SKIP {skipped}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
