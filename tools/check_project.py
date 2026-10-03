"""FAA 项目校验 / 合并闸门
================================
任何 agent 的开发成果「合并进本项目」之前，先跑本脚本并全绿。

不做任何联网 / 连模拟器 / 依赖 maafw 的动作，秒级完成，只做静态校验：

  1. JSON 校验      : flows/**/*.json 与 data/*.json 全部可解析
  2. 步骤类型白名单 : 递归比对 flow 里所有 "type"，是否都在引擎 run_step 支持的类型集合内
                      （类型集合从 ocr_engine.py 实时提取，不硬编码，避免与引擎漂移）
  3. 语法校验       : 代码区全部 .py 做语法校验（内置 compile，不落 .pyc）
  4. 文档同步提醒   : 提示同步 PROGRESS.md / docs/FLOWS.md，并给出各 flow 与 FLOWS.md 的对应关系
  5. 协作开发区预检 : <工作区根>/_collab/inbox/** 的 JSON 可解析（硬判）
                      + 步骤类型软提示 + 打印"待合并清单"（其他 agent 的成果，见 _collab/README.md）

用法（cwd = 仓库根 FlowerAutoAssistant/，必须用项目 .venv）:
    python tools/check_project.py          # 全量校验（退出码 0=通过, 1=有错）
    python tools/check_project.py --map    # 打印项目地图（目录职责 / 常用命令），不校验
    python tools/check_project.py -v       # 附带每类检查的逐项明细
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 本文件在 <repo>/tools/ 下 → 仓库根 = 上一级
ROOT = Path(__file__).resolve().parent.parent

FLOWS_DIR = ROOT / "flows"
DATA_DIR = ROOT / "data"
ENGINE = ROOT / "ocr_engine.py"

# 协作开发区（工作区根，与代码区同级；其他 agent 只在此区域开发，成果等待合并）
COLLAB_DIR = ROOT.parent / "_collab"

# 代码区需做语法校验的 .py（跳过 .venv / _dev / legacy / __pycache__）
PY_SOURCES = [
    ROOT / "main.py",
    ROOT / "ocr_engine.py",
    ROOT / "ocr_ui.py",
    ROOT / "pollin.py",
    ROOT / "community_like.py",
    ROOT / "webui.py",
    ROOT / "tools",
]

# flow 文件 → FLOWS.md 章节关键字（文档同步提醒用，仅做软提示）
FLOW_DOC_HINT = {
    "flow_startup.json": "§1 开始启动",
    "flow_signin.json": "§2 签到",
    "flow_plant.json": "§3 种植 / 花田",
    "flow_social.json": "§4 社交任务",
    "flow_energy.json": "§5 体力任务",
    "flow_daily_task.json": "§6 每日任务",
    "flow_claim.json": "§7 领取奖励",
    "flow_idle.json": "§8 挂机任务",
    "daily.json": "§0 全局编排",
    "common/entries.json": "§9 公共导航系统",
}

MAP_TEXT = """\
FAA 项目地图（仓库根 = FlowerAutoAssistant/）
─────────────────────────────────────────────
入口 / 运行
  main.py          CLI: main.py [--flow 名称] [--loop N] [--list]
  webui.py         WebUI 后端（端口 8765）: webui.py  /  start_webui.bat
  ocr_engine.py    引擎 CLI: python ocr_engine.py 查看用法（--ocr-screen 等）

业务逻辑（改 JSON 不改代码）
  flows/daily.json        8 模块编排（startup→signin→plant→social→energy→daily→claim→idle）
  flows/flow_*.json       各模块流程
  flows/common/entries.json  navigate 导航注册表

核心代码
  ocr_engine.py    引擎：run_step 分派步骤类型（改引擎=改"动作原子"）
  ocr_ui.py        RapidOCR 单例
  pollin.py        好友采粉闭环（步骤 friend_pollin）
  community_like.py 社区点赞闭环（步骤 community_like）
  webui.html / tpltool.html / start_webui.bat  WebUI 前端与标注页

运行期数据
  data/config.json          功能开关（出仓；模板 data/config.example.json）
  data/close_buttons.json   关闭按钮注册表（入仓）
  data/click_log.json       坐标知识库（自动累积，出仓）

文档
  PROGRESS.md            活进度（末尾里程碑最新）
  docs/FLOWS.md          功能流程手册
  docs/DEV_PROMPT.md     编码约定 / 7 区契约
  docs/PROJECT_GUIDE.md  总纲 / 接手接口（本脚本所属体系）

出仓区（不入 git）
  <工作区根>/_collab/   协作开发区：其他 agent 只在此开发，成果等待合并（README.md 有规则）
  <工作区根>/_dev/      workbench/ dev_tools/ _stage_faa/ ...（开发区）
  debug/               截图与诊断图（测试区，不可搬移）
  legacy/ _backup/     备份区

常用命令（PowerShell，必须 .venv）
  & ".venv\\Scripts\\python.exe" tools\\check_project.py     # 合并闸门
  & ".venv\\Scripts\\python.exe" main.py --flow 社交 --loop 1
  & ".venv\\Scripts\\python.exe" ..\\_dev\\dev_tools\\analysis\\log_triage.py <日志>
"""


def _log(msg: str) -> None:
    print(msg)


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def known_step_types() -> set[str]:
    """从 ocr_engine.py 实时提取 run_step 分派的步骤类型（s_type == "xxx"）。"""
    if not ENGINE.exists():
        return set()
    src = ENGINE.read_text(encoding="utf-8", errors="ignore")
    return set(re.findall(r's_type\s*==\s*"([a-zA-Z_]+)"', src))


def walk_steps(node, path: str):
    """递归产出 (步骤type, 位置说明)。列表/字典任意嵌套。"""
    if isinstance(node, list):
        for i, item in enumerate(node):
            yield from walk_steps(item, f"{path}[{i}]")
    elif isinstance(node, dict):
        t = node.get("type")
        if isinstance(t, str) and t:
            yield t, path
        for k, v in node.items():
            if isinstance(v, (list, dict)):
                yield from walk_steps(v, f"{path}.{k}")


def check_json(errors: list[str], verbose: bool) -> list[Path]:
    """1) JSON 解析校验；返回所有解析成功的 json 文件列表。"""
    targets: list[Path] = []
    if FLOWS_DIR.exists():
        targets += sorted(FLOWS_DIR.rglob("*.json"))
    if DATA_DIR.exists():
        targets += sorted(DATA_DIR.glob("*.json"))

    ok: list[Path] = []
    for f in targets:
        try:
            json.loads(f.read_text(encoding="utf-8"))
            ok.append(f)
            if verbose:
                _log(f"    ok  {_rel(f)}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"[JSON] 解析失败: {_rel(f)} -> {e}")
    _log(f"  JSON 校验: {len(ok)}/{len(targets)} 个文件可解析")
    return ok


def check_step_types(errors: list[str], verbose: bool) -> None:
    """2) 步骤类型白名单校验。"""
    known = known_step_types()
    if not known:
        errors.append("[步骤] 无法从 ocr_engine.py 提取步骤类型集合（文件缺失或分派写法变了）")
        _log("  步骤类型: 提取失败")
        return

    bad = 0
    checked = 0
    for f in sorted(FLOWS_DIR.rglob("*.json")) if FLOWS_DIR.exists() else []:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue  # 已在 JSON 校验里报过
        for t, loc in walk_steps(data, _rel(f)):
            checked += 1
            if t not in known:
                bad += 1
                errors.append(f"[步骤] 未知步骤类型 '{t}' @ {loc}")

    _log(f"  步骤类型: 已识别 {len(known)} 种; 流程中检查 {checked} 处; 未知 {bad} 处")
    if verbose:
        _log("    已知: " + ", ".join(sorted(known)))


def check_syntax(errors: list[str], verbose: bool) -> None:
    """3) 语法校验（compile 内置，不落 .pyc，不污染工作区）。"""
    files: list[Path] = []
    for src in PY_SOURCES:
        if src.is_dir():
            files += [p for p in sorted(src.rglob("*.py")) if "__pycache__" not in p.parts]
        elif src.exists():
            files.append(src)

    bad = 0
    for f in files:
        try:
            compile(f.read_text(encoding="utf-8"), str(f), "exec")
            if verbose:
                _log(f"    ok  {_rel(f)}")
        except SyntaxError as e:
            bad += 1
            errors.append(f"[语法] {_rel(f)}:{e.lineno} -> {e.msg}")
        except Exception as e:  # noqa: BLE001
            bad += 1
            errors.append(f"[语法] {_rel(f)} -> {e}")
    _log(f"  语法校验: {len(files) - bad}/{len(files)} 个 .py 通过")


def check_collab(errors: list[str], verbose: bool) -> None:
    """5) 协作开发区预检：inbox 待合并清单 + JSON 硬判 + 步骤类型软提示。"""
    inbox = COLLAB_DIR / "inbox"
    if not COLLAB_DIR.exists():
        _log("  协作开发区: 未创建（跳过）")
        return

    dirs = lambda p: [d for d in sorted(p.iterdir()) if d.is_dir()] if p.exists() else []  # noqa: E731
    pending = dirs(inbox)
    merged = dirs(COLLAB_DIR / "merged")

    # JSON 硬判：inbox 里的 flow 必须先能解析，否则合并必炸（merged/ 已归档，不重复校验）
    jsons = [p for p in sorted(COLLAB_DIR.rglob("*.json")) if "merged" not in p.parts]
    ok = 0
    for f in jsons:
        try:
            json.loads(f.read_text(encoding="utf-8"))
            ok += 1
        except Exception as e:  # noqa: BLE001
            errors.append(f"[协作区] JSON 解析失败: {_rel(f)} -> {e}")

    _log(f"  协作开发区: 待合并 {len(pending)} 份 / 已归档 {len(merged)} 份; inbox JSON {ok}/{len(jsons)} 可解析")

    if pending:
        for d in pending:
            has_files = (d / "files").is_dir()
            has_report = (d / "REPORT.md").exists()
            _log(f"    · {d.name}: "
                 f"{'有 files/' if has_files else '⚠ 缺 files/'}, "
                 f"{'有 REPORT.md' if has_report else '⚠ 缺 REPORT.md'}")
    else:
        _log("    （inbox 为空，无待合并成果）")

    # 步骤类型：软提示（其他 agent 可能同时提交引擎补丁，故不计为失败）
    known = known_step_types()
    if known:
        for f in jsons:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            for t, loc in walk_steps(data, _rel(f)):
                if t not in known:
                    _log(f"    ⚠ 待合并步骤类型 '{t}' @ {loc}（合并时需引擎先支持，或随补丁一并合并）")

    if verbose:
        _log("    （协作区规则见 _collab/README.md）")


def doc_hint() -> None:
    """4) 文档同步软提示（不做失败判定）。"""
    _log("  文档同步提醒:")
    _log("    - 功能/修复完成后: PROGRESS.md 追加里程碑 + docs/FLOWS.md 同步该功能流程")
    for name, sec in FLOW_DOC_HINT.items():
        _log(f"      {name:<22} -> docs/FLOWS.md {sec}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="FAA 项目校验 / 合并闸门")
    ap.add_argument("--map", action="store_true", help="只打印项目地图，不校验")
    ap.add_argument("-v", "--verbose", action="store_true", help="打印逐项明细")
    args = ap.parse_args(argv)

    # Windows 控制台默认 GBK，确保中文输出不炸
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    if args.map:
        _log(MAP_TEXT)
        return 0

    _log(f"FAA 项目校验（仓库根: {ROOT}）")
    _log("-" * 46)
    errors: list[str] = []
    check_json(errors, args.verbose)
    check_step_types(errors, args.verbose)
    check_syntax(errors, args.verbose)
    check_collab(errors, args.verbose)
    doc_hint()
    _log("-" * 46)

    if errors:
        _log(f"✗ 校验未通过：{len(errors)} 个问题")
        for e in errors:
            _log("  - " + e)
        return 1

    _log("✓ 全部通过，可以合并。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())