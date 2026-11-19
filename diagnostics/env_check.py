# -*- coding: utf-8 -*-
"""环境自检（1.0 #14）：`webui.py --check-env [--json]`。

只读检查，不启动服务、不连游戏、不写用户数据（写权限检查用临时文件并立即删除）。
退出码: 0 = 无 FAIL（WARN 不阻断）/ 1 = 至少一项 FAIL。
"""
from __future__ import annotations

import json
import os
import platform
import socket
import sys
import tempfile
from pathlib import Path

from .errors import ERRORS

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORT = 8765


def _entry(code: str, status: str, detail: str) -> dict:
    meta = ERRORS.get(code, {})
    return {
        "code": code,
        "status": status,
        "title": meta.get("title", code),
        "detail": detail,
        "cause": meta.get("cause", "") if status != "ok" else "",
        "action": meta.get("action", "") if status != "ok" else "",
    }


def _tcp_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _port_state(port: int) -> str:
    """free / faa / other（与 ProbeService 三态语义一致）。"""
    if not _tcp_open("127.0.0.1", port, timeout=1.0):
        return "free"
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2.0) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        return "faa" if data.get("service") == "faa" else "other"
    except Exception:  # noqa: BLE001
        return "other"


def run_checks(deep: bool = False) -> list[dict]:
    """执行全部检查，返回结果列表（ok / warn / fail）。"""
    out: list[dict] = []

    # 1) 操作系统
    os_ok = platform.system() == "Windows"
    out.append(_entry("ENV-OS", "ok" if os_ok else "fail",
                      f"{platform.system()} {platform.release()} ({platform.machine()})"))

    # 2) Python 运行时
    frozen = bool(getattr(sys, "frozen", False))
    py_ok = frozen or sys.version_info >= (3, 11)
    out.append(_entry("ENV-PY", "ok" if py_ok else "fail",
                      "打包后端(frozen)" if frozen else sys.version.split()[0]))

    # 3) 资源目录
    missing = [str(p.relative_to(ROOT)) for p in
               (ROOT / "flows", ROOT / "resource" / "template", ROOT / "data") if not p.is_dir()]
    out.append(_entry("ENV-PATH", "fail" if missing else "ok",
                      f"缺失: {missing}" if missing else f"程序根目录 {ROOT}"))

    # 4) 流程文件
    daily = ROOT / "flows" / "daily.json"
    try:
        data = json.loads(daily.read_text(encoding="utf-8"))
        mods = data.get("modules") or []
        bad = [m.get("flow") for m in mods
               if not (ROOT / "flows" / str(m.get("flow"))).is_file()]
        flow_files = len(list((ROOT / "flows").glob("*.json")))
        if not mods or bad:
            out.append(_entry("ENV-FLOW", "fail",
                              f"modules={len(mods)}, 引用缺失={bad}"))
        else:
            out.append(_entry("ENV-FLOW", "ok",
                              f"{flow_files} 个流程文件, daily.json {len(mods)} 个模块引用全部存在"))
    except Exception as e:  # noqa: BLE001
        out.append(_entry("ENV-FLOW", "fail", f"读取失败: {type(e).__name__}: {e}"))

    # 5) 模板
    try:
        n_tpl = len(list((ROOT / "resource" / "template").glob("*.png")))
        out.append(_entry("ENV-TEMPLATE", "ok" if n_tpl >= 30 else "warn", f"{n_tpl} 个模板"))
    except Exception as e:  # noqa: BLE001
        out.append(_entry("ENV-TEMPLATE", "fail", str(e)))

    # 6) 用户配置（不存在=首启自动生成, 不算错）
    cfg_path = ROOT / "data" / "config.json"
    try:
        if not cfg_path.exists():
            out.append(_entry("ENV-CONFIG", "ok", "尚无 config.json（首次启动会从示例生成）"))
        else:
            from config.schema import migrate_config, validate_config
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
            errs = validate_config(raw)
            _, notes = migrate_config(raw)
            if errs:
                out.append(_entry("ENV-CONFIG", "fail", "; ".join(errs[:5])))
            else:
                out.append(_entry("ENV-CONFIG", "ok",
                                  "类型校验通过" + (f"; 待升级: {'; '.join(notes)}" if notes else "")))
    except Exception as e:  # noqa: BLE001
        out.append(_entry("ENV-CONFIG", "fail", f"解析失败: {type(e).__name__}: {e}"))

    # 7) 数据目录可写
    try:
        ROOT.joinpath("data").mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=str(ROOT / "data"), prefix=".envcheck_", delete=True):
            pass
        out.append(_entry("ENV-DATA-WRITE", "ok", "data/ 可写"))
    except Exception as e:  # noqa: BLE001
        out.append(_entry("ENV-DATA-WRITE", "fail", f"{type(e).__name__}: {e}"))

    # 8) ADB 路径与模拟器连接（默认 MuMu；不阻止先启动程序后开模拟器 → WARN）
    adb_path, adb_addr = None, "127.0.0.1:16384"
    try:
        from ocr_engine._constants import ADB_ADDRESS, ADB_PATH
        adb_path, adb_addr = ADB_PATH, ADB_ADDRESS
    except Exception as e:  # noqa: BLE001
        out.append(_entry("ENV-OCR", "fail", f"引擎导入失败: {type(e).__name__}: {e}"))
    if adb_path is not None:
        if Path(adb_path).is_file():
            out.append(_entry("ENV-ADB-PATH", "ok", adb_path))
        else:
            out.append(_entry("ENV-ADB-PATH", "warn",
                              f"未找到 {adb_path}（MuMu 装在别处时用 --adb 指定）"))
    host, _, port_s = adb_addr.partition(":")
    try:
        port = int(port_s)
    except ValueError:
        port = 16384
    if _tcp_open(host, port):
        out.append(_entry("ENV-ADB-CONN", "ok", f"{adb_addr} 可连接"))
    else:
        out.append(_entry("ENV-ADB-CONN", "warn", f"{adb_addr} 连不上（MuMu 未启动属正常）"))

    # 9) 服务端口
    state = _port_state(DEFAULT_PORT)
    if state == "faa":
        out.append(_entry("ENV-PORT", "ok", f"{DEFAULT_PORT} 已有 FAA 实例（可复用连接）"))
    elif state == "other":
        out.append(_entry("ENV-PORT", "warn", f"{DEFAULT_PORT} 被其他程序占用"))
    else:
        out.append(_entry("ENV-PORT", "ok", f"{DEFAULT_PORT} 空闲"))

    # 10) OCR 运行库（deep 时额外加载模型）
    try:
        import onnxruntime  # noqa: F401
        import rapidocr_onnxruntime  # noqa: F401
        detail = f"onnxruntime {getattr(onnxruntime, '__version__', '?')}"
        if deep:
            import numpy as np
            from ocr_ui import ocr_image
            img = np.full((64, 256, 3), 255, dtype=np.uint8)
            import cv2
            cv2.putText(img, "FAA", (10, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
            ocr_image(img)
            detail += "; 模型加载/推理通过"
        out.append(_entry("ENV-OCR", "ok", detail))
    except Exception as e:  # noqa: BLE001
        out.append(_entry("ENV-OCR", "fail", f"{type(e).__name__}: {e}"))

    return out


def format_text(results: list[dict]) -> str:
    lines = [f"FAA 环境检查（{ROOT}）", "-" * 52]
    for r in results:
        lines.append(f"[{r['status'].upper():<4}] {r['code']:<16} {r['detail']}")
        if r["status"] != "ok" and r.get("action"):
            lines.append(f"       → {r['action']}")
    ok = sum(1 for r in results if r["status"] == "ok")
    warn = sum(1 for r in results if r["status"] == "warn")
    fail = sum(1 for r in results if r["status"] == "fail")
    lines.append("-" * 52)
    lines.append(f"结果: OK {ok} / WARN {warn} / FAIL {fail}")
    if warn:
        lines.append("WARN 不阻断启动（如模拟器尚未打开）；FAIL 需要先按建议修复。")
    return "\n".join(lines)


def main(json_out: bool = False, deep: bool = False) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    results = run_checks(deep=deep)
    if json_out:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(format_text(results))
    return 1 if any(r["status"] == "fail" for r in results) else 0
