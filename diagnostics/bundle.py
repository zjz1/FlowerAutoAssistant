# -*- coding: utf-8 -*-
"""脱敏诊断包导出（1.0 #16）：`webui.py --export-diag <zip>`。

包内容（**默认不含截图**）:
    manifest.json          版本/平台/生成时间/说明
    env.json               环境检查结果（与 --check-env --json 同源）
    config.json            脱敏后的用户配置（无 target_tail、无绝对路径）
    logs/runtime_tail.txt  运行日志尾部（脱敏）
    logs/http_tail.txt      HTTP 日志尾部（脱敏）
    flows/summary.json     流程文件与模块概览
导出内容可供用户自行检查后再上传；不含账号、绝对路径、ADB 路径与截图。
"""
from __future__ import annotations

import json
import platform
import sys
import time
import zipfile
from pathlib import Path

from .env_check import ROOT, run_checks
from .redact import redact_config, redact_text


def _tail(path: Path, max_lines: int) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-max_lines:])
    except Exception:  # noqa: BLE001
        return ""


def _adb_path() -> str | None:
    try:
        from ocr_engine._constants import ADB_PATH
        return ADB_PATH
    except Exception:  # noqa: BLE001
        return None


def export_bundle(out_path: Path, *, log_lines: int = 400) -> Path:
    """生成脱敏诊断 zip，返回最终路径（自动补 .zip 后缀）。"""
    out_path = Path(out_path)
    if out_path.suffix.lower() != ".zip":
        out_path = out_path.with_suffix(".zip")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    adb = _adb_path()
    frozen = bool(getattr(sys, "frozen", False))

    manifest = {
        "app": "FlowerAutoAssistant",
        "profile": "frozen" if frozen else "source",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "python": sys.version.split()[0] if not frozen else "frozen",
        "note": "脱敏诊断包：不含截图、账号尾号、ADB 路径与本机绝对路径。",
        "schema_version": 1,
    }

    env = run_checks()
    cfg_raw = None
    cfg_file = ROOT / "data" / "config.json"
    if cfg_file.exists():
        try:
            cfg_raw = json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            cfg_raw = None
    cfg = redact_config(cfg_raw or {})

    runtime = redact_text(_tail(ROOT / "data" / "webui_runtime_log.txt", log_lines), adb)
    http = redact_text(_tail(ROOT / "data" / "webui_http_log.txt", log_lines), adb)

    flows: dict = {"files": [], "daily_modules": []}
    try:
        flows["files"] = sorted(p.name for p in (ROOT / "flows").glob("*.json"))
        daily = json.loads((ROOT / "flows" / "daily.json").read_text(encoding="utf-8"))
        flows["daily_modules"] = [m.get("id") for m in (daily.get("modules") or [])]
    except Exception as e:  # noqa: BLE001
        flows["error"] = f"{type(e).__name__}: {e}"

    readme = (
        "FAA 诊断包（脱敏）\n"
        "=================\n"
        "本包用于排查启动/连接/流程问题，内容：\n"
        "  manifest.json  版本与平台\n"
        "  env.json       环境检查结果\n"
        "  config.json    脱敏后的配置（target_tail 已隐藏）\n"
        "  logs/          最近日志尾部\n"
        "  flows/         流程文件清单\n"
        "默认不包含游戏截图；上传前可自行解压检查。\n"
    )

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        def _w(name: str, text: str) -> None:
            z.writestr(name, text)

        _w("README.txt", readme)
        _w("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        _w("env.json", json.dumps(env, ensure_ascii=False, indent=2))
        _w("config.json", json.dumps(cfg, ensure_ascii=False, indent=2))
        _w("logs/runtime_tail.txt", runtime)
        _w("logs/http_tail.txt", http)
        _w("flows/summary.json", json.dumps(flows, ensure_ascii=False, indent=2))
    return out_path


def main(out_arg: str, log_lines: int = 400) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    try:
        path = export_bundle(Path(out_arg), log_lines=log_lines)
    except Exception as e:  # noqa: BLE001
        print(f"诊断包导出失败: {type(e).__name__}: {e}")
        return 1
    print(f"已导出脱敏诊断包: {path}")
    print("内容: manifest / env / config(脱敏) / 日志尾部 / 流程清单；不含截图。")
    return 0
