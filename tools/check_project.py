"""FAA 项目校验 / 合并闸门
================================
任何 agent 的开发成果「合并进本项目」之前，先跑本脚本并全绿。

不做任何联网 / 连模拟器 / 依赖 maafw 的动作，秒级完成，只做静态校验：

  1. JSON 校验      : flows/**/*.json 与 data/*.json 全部可解析
  2. 步骤类型白名单 : 递归比对 flow 里所有 "type"，是否都在引擎 run_step 支持的类型集合内
                      （E02 起优先 import 引擎显式导出的 ocr_engine.STEP_TYPES; 旧源文本
                       正则提取降级为 import 失败时的兜底，不再依赖分派写法细节）
  3. 语法校验       : 代码区全部 .py 做语法校验（内置 compile，不落 .pyc）
  4. 文档同步提醒   : 提示同步 PROGRESS.md / docs/FLOWS.md，并给出各 flow 与 FLOWS.md 的对应关系
  5. 协作开发区预检 : <工作区根>/_collab/inbox/** 的 JSON 可解析（硬判）
                      + 步骤类型软提示 + 打印"待合并清单"（其他 agent 的成果，见 _collab/README.md）
  6. webui 契约一致性(Q03): ⚙面板键 ⊆ set_config 白名单（里程碑 82/87「勾选被静默丢弃」
                      防线，先 WARN 一轮）+ POST 分派 ↔ _POST_ROUTES 白名单（漏同步=405，硬判）
  7. config 键一致性: flow 的 if_config.key/keys ↔ config.example.json（硬判缺键）
                      ↔ WebUI ⚙ 面板 / WPF SetConfigKeys（缺控件 WARN）
  8. 原生 UI 预检(N01): native/FAA.WpfGui csproj/sln 存在性 + dotnet build 退出码硬判；
                      dotnet 不在 PATH 或 native/ 未落位时降级 WARN（无 SDK 环境不假红）
  9. 离线单元测试(可选) : --with-tests 运行 tests/（stdlib unittest，不联网/不连 ADB）

用法（cwd = 仓库根 FlowerAutoAssistant/，必须用项目 .venv）:
    python tools/check_project.py          # 全量校验（退出码 0=通过, 1=有错）
    python tools/check_project.py --map    # 打印项目地图（目录职责 / 常用命令），不校验
    python tools/check_project.py -v       # 附带每类检查的逐项明细
    python tools/check_project.py --strict-webui   # webui 白名单一致性 WARN 升 FAIL（烧完观察期后用）
    python tools/check_project.py --with-tests     # 额外运行 tests/ 离线单元测试
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

# 本文件在 <repo>/tools/ 下 → 仓库根 = 上一级
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    from config import schema as config_schema
except Exception:  # pragma: no cover - schema 缺失时回退 AST 提取
    config_schema = None

FLOWS_DIR = ROOT / "flows"
DATA_DIR = ROOT / "data"
ENGINE = ROOT / "ocr_engine.py"
WEBUI = ROOT / "webui.py"
HTTP_COMMON = ROOT / "transport" / "http" / "common.py"
HTTP_ROUTER = ROOT / "transport" / "http" / "router.py"
CONFIG_SERVICE = ROOT / "app" / "config_service.py"
WEBUI_HTML = ROOT / "webui.html"

# 原生 UI 工程（N01, 2026-11-13 批）: C# 侧最小闸门的锚点
NATIVE_DIR = ROOT / "native" / "FAA.WpfGui"
NATIVE_CSPROJ = NATIVE_DIR / "FAA.WpfGui.csproj"
NATIVE_SLN = NATIVE_DIR / "FAA.WpfGui.sln"
FAA_PROXY_CS = NATIVE_DIR / "Services" / "FaaProxy.cs"   # set_config 第五处白名单(F06+W03 对账)
DOTNET_BUILD_TIMEOUT_S = 300      # 本工程 27 行 csproj, 常态构建 <1min; 超时按失败判

# 协作开发区（工作区根，与代码区同级；其他 agent 只在此区域开发，成果等待合并）
COLLAB_DIR = ROOT.parent / "_collab"

# inbox 下的常驻台账目录（不是待合并批次，不参与 files/ + REPORT.md 检查）
COLLAB_LEDGER_DIRS = {"zcode-developing", "zcode-handover"}

# 代码区需做语法校验的 .py（跳过 .venv / _dev / legacy / __pycache__）
PY_SOURCES = [
    ROOT / "main.py",
    ROOT / "metrics_recorder.py",   # 度量基座(2026-11-13 批): 整轮指标落盘模块, 新增根 .py 随批入闸
    ROOT / "ocr_engine.py",         # E01(2026-11-14 批)拆包后为 CLI shim(facade 再导出在 ocr_engine/ 包)
    ROOT / "ocr_engine",            # E01(2026-11-14 批): ocr_engine/ 包全部 .py 入语法闸(目录递归)
    ROOT / "ocr_ui.py",
    ROOT / "pollin.py",
    *sorted((ROOT / "pollin").glob("*.py")),  # 2026-11-17 Stage 5: 好友采粉分包
    ROOT / "community_like.py",
    ROOT / "plant.py",             # 2026-11-17: 种植/收获业务闭环
    ROOT / "buy_seed.py",          # 2026-11-17: 购买种子独立功能
    ROOT / "fairyland.py",         # 2026-11-17: 花仙乐园领取
    ROOT / "ui_ops.py",            # 2026-11-17: 通用截图/精识/输入原语
    ROOT / "navigation.py",        # 2026-11-17: 通用家园归位原语
    *sorted((ROOT / "core").glob("*.py")),   # 2026-11-17 Stage 3: EnginePort 端口
    *sorted((ROOT / "config").glob("*.py")),  # 2026-11-17 Stage 2: 配置 schema 单源
    *sorted((ROOT / "app").glob("*.py")),    # 2026-11-17 Stage 1: 应用服务层
    *sorted((ROOT / "diagnostics").glob("*.py")),  # 2026-11-20: 诊断/脱敏/错误目录纳入语法闸
    *sorted((ROOT / "transport").rglob("*.py")),  # 2026-11-17 Stage 3: HTTP 路由 mixin
    *sorted((ROOT / "tests").glob("*.py")),  # 2026-11-17 Stage 0: 离线测试基线
    ROOT / "webui.py",
    ROOT / "webui_app.py",          # 原生窗口壳(Q03, 2026-11-13 批): 此前不在闸门内, 语法 11/11 -> 12/12
    ROOT / "tools",
]

# flow 文件 → FLOWS.md 章节关键字（文档同步提醒用，仅做软提示）
FLOW_DOC_HINT = {
    "flow_startup.json": "§1 开始启动",
    "flow_plant.json": "§3 种植 / 花田",
    "flow_buy_seed.json": "§3.4 购买种子（独立手动流程）",
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
  flows/daily.json        7 模块编排（startup→plant→social→energy→claim→daily→idle）
  flows/flow_*.json       各模块流程
  flows/common/entries.json  navigate 导航注册表

核心代码
  ocr_engine/ 包   引擎：run_step 分派步骤类型（改引擎=改"动作原子"; E01 拆包 Mixin 纵切,
                   根 ocr_engine.py 为 CLI shim + facade 再导出）
  app/lifecycle_service.py  服务进程探测/拉起/就绪等待/优雅停/父进程看护（Stage 4）
  ocr_ui.py        RapidOCR 单例
  pollin/ 包       好友采粉闭环（步骤 friend_pollin）: constants/primitives/popups/
                   navigation/list_panel/collect/runner；根 pollin.py 为 CLI shim
  community_like.py 社区点赞闭环（步骤 community_like）
  webui.html / tpltool.html / start_webui.bat  WebUI 前端与标注页

运行期数据
  data/config.json          功能开关（出仓；模板 data/config.example.json）
  data/close_buttons.json   关闭按钮注册表（入仓）
  data/click_log.json       坐标知识库（自动累积，出仓）

文档
  PROGRESS.md            活进度（按里程碑编号查；100+ 在文件后半段顶部，新→旧）
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
    """run_step 分派的步骤类型集合。

    E02(2026-11-13 批): 优先 import 引擎显式导出的 ``ocr_engine.STEP_TYPES``（模块级
    frozenset, 常量区维护契约见引擎内注释），闸门从「解析实现细节」变为「消费显式清单」;
    import 失败（如无 numpy/maa 的裸解释器）或引擎尚未导出该常量时，回退旧的源文本
    正则提取（兜底不删，行为与 2026-11-13 前逐字节一致）。
    E01(2026-11-14 批): run_step 分派已随 ocr_engine/ 拆包迁入包内 engine/_flowexec.py,
    兜底正则改为对 根 ocr_engine.py(CLI shim) + ocr_engine/ 包全部 .py 求并集,
    输出集合与拆包前逐字节一致（42 种）。
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        import ocr_engine as _eng  # 引擎模块级只有常量/锁, import 零副作用、不连 adb
        st = getattr(_eng, "STEP_TYPES", None)
        if isinstance(st, (frozenset, set)) and st and all(isinstance(x, str) for x in st):
            return set(st)
    except Exception:  # noqa: BLE001 —— 兜底路径不因 import 环境问题而断
        pass
    targets = [ENGINE] if ENGINE.exists() else []
    pkg = ROOT / "ocr_engine"
    if pkg.is_dir():
        targets += [p for p in sorted(pkg.rglob("*.py"))
                    if "__pycache__" not in p.parts]
    found: set[str] = set()
    for t in targets:
        src = t.read_text(encoding="utf-8", errors="ignore")
        found |= set(re.findall(r's_type\s*==\s*"([a-zA-Z_]+)"', src))
    return found


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


def check_flow_struct(errors: list[str], verbose: bool) -> None:
    """2b) flow 结构校验（1.0 #12）：必填字段 / region_rel 形状 / 关键字列表 / 模块引用。

    只做**结构**校验（不改语义、不推断默认值）:
      - 普通流程: 顶层 name 非空 + steps 非空列表;
      - 编排流程(daily.json): modules 非空, 每项 id/flow 非空且 flow 文件存在, on_fail ∈ {skip, stop_round};
      - 注册表(entries/scenes): targets/scenes 非空对象;
      - 任意节点: region_rel 为 2(中心点)或 4(框) 个 0~1 数字, 4 元须 x1<x2/y1<y2;
        text/keywords/exclude/kws 为非空字符串或非空字符串列表;
        then/else/do/nav/steps 为列表; min_score ∈ (0,1]; timeout/interval/delay/seconds >= 0;
        fallback_rel 为 2 个 0~1 数字。
    """
    def is_num(v) -> bool:
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    def check_region(reg, loc: str) -> None:
        if not isinstance(reg, list) or len(reg) not in (2, 4):
            errors.append(f"[flow] region_rel 须为 2(中心点)或 4(框) 个数字 @ {loc}")
            return
        if not all(is_num(x) and 0.0 <= x <= 1.0 for x in reg):
            errors.append(f"[flow] region_rel 取值须在 0~1 @ {loc}: {reg}")
            return
        if len(reg) == 4 and not (reg[0] < reg[2] and reg[1] < reg[3]):
            errors.append(f"[flow] region_rel 需 x1<x2 且 y1<y2 @ {loc}: {reg}")

    def check_kws(val, field: str, loc: str) -> None:
        items = [val] if isinstance(val, str) else val
        if not isinstance(items, list) or not items:
            errors.append(f"[flow] {field} 须为非空字符串或非空字符串列表 @ {loc}")
            return
        if not all(isinstance(x, str) and x.strip() for x in items):
            errors.append(f"[flow] {field} 含空/非字符串项 @ {loc}: {items}")

    def walk(node, loc: str):
        """递归产出 (dict, 位置)。"""
        if isinstance(node, list):
            for i, item in enumerate(node):
                yield from walk(item, f"{loc}[{i}]")
        elif isinstance(node, dict):
            yield node, loc
            for k, v in node.items():
                if isinstance(v, (list, dict)):
                    yield from walk(v, f"{loc}.{k}")

    checked = 0
    for f in sorted(FLOWS_DIR.rglob("*.json")) if FLOWS_DIR.exists() else []:
        rel = _rel(f)
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue  # 已在 JSON 校验里报过
        if not isinstance(data, dict):
            errors.append(f"[flow] 顶层须为 JSON 对象 @ {rel}")
            continue
        checked += 1

        # ---- 顶层形态 ----
        if "modules" in data:
            mods = data["modules"]
            if not isinstance(mods, list) or not mods:
                errors.append(f"[flow] modules 须为非空列表 @ {rel}")
                mods = []
            seen_ids: set[str] = set()
            for i, m in enumerate(mods):
                loc = f"{rel}.modules[{i}]"
                if not isinstance(m, dict):
                    errors.append(f"[flow] 模块项须为对象 @ {loc}")
                    continue
                mid, flow = m.get("id"), m.get("flow")
                if not (isinstance(mid, str) and mid.strip()):
                    errors.append(f"[flow] 模块缺 id @ {loc}")
                elif mid in seen_ids:
                    errors.append(f"[flow] 模块 id 重复 '{mid}' @ {loc}")
                else:
                    seen_ids.add(mid)
                if not (isinstance(flow, str) and flow.strip()):
                    errors.append(f"[flow] 模块缺 flow @ {loc}")
                elif not (FLOWS_DIR / flow).is_file():
                    errors.append(f"[flow] 模块引用的流程不存在 '{flow}' @ {loc}")
                if "required" in m and not isinstance(m["required"], bool):
                    errors.append(f"[flow] required 须为 bool @ {loc}")
                if "on_fail" in m and m["on_fail"] not in ("skip", "stop_round"):
                    errors.append(f"[flow] on_fail 须为 skip|stop_round @ {loc}: {m['on_fail']!r}")
        elif "targets" in data:
            if not isinstance(data["targets"], dict) or not data["targets"]:
                errors.append(f"[flow] targets 须为非空对象 @ {rel}")
        elif "scenes" in data:
            if not isinstance(data["scenes"], dict) or not data["scenes"]:
                errors.append(f"[flow] scenes 须为非空对象 @ {rel}")
        else:
            name = data.get("name")
            if not (isinstance(name, str) and name.strip()):
                errors.append(f"[flow] 流程缺 name @ {rel}")
            steps = data.get("steps")
            if not isinstance(steps, list) or not steps:
                errors.append(f"[flow] steps 须为非空列表 @ {rel}")

        # ---- 节点级通用结构 ----
        for node, loc in walk(data, rel):
            if "region_rel" in node:
                check_region(node["region_rel"], loc)
            for field in ("text", "keywords", "exclude", "kws"):
                if field in node:
                    check_kws(node[field], field, loc)
            for field in ("then", "else", "do", "nav", "steps"):
                if field in node and not isinstance(node[field], list):
                    errors.append(f"[flow] {field} 须为列表 @ {loc}")
            if "min_score" in node:
                v = node["min_score"]
                if not (is_num(v) and 0.0 < v <= 1.0):
                    errors.append(f"[flow] min_score 须在 (0,1] @ {loc}: {v!r}")
            for field in ("timeout", "interval", "delay", "seconds"):
                if field in node:
                    v = node[field]
                    if not (is_num(v) and v >= 0):
                        errors.append(f"[flow] {field} 须为非负数字 @ {loc}: {v!r}")
            if "fallback_rel" in node:
                v = node["fallback_rel"]
                if not (isinstance(v, list) and len(v) == 2
                        and all(is_num(x) and 0.0 <= x <= 1.0 for x in v)):
                    errors.append(f"[flow] fallback_rel 须为 2 个 0~1 数字 @ {loc}: {v!r}")

    _log(f"  flow 结构: 已校验 {checked} 个 JSON")
    if verbose:
        _log("    规则: name/steps 必填; modules 引用存在; region_rel 2|4 元 0~1; text 非空列表")


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


# ---------------------------------------------------------------------------
# webui 契约一致性（Q03, 2026-11-13 批）—— 全部走 AST/静态结构提取，不 import webui
# （闸门零副作用: import webui 会初始化日志路径等运行态）。提取不到锚点时降级 WARN，
# 宁漏勿噪（立项清单 Q03 约束）。
# ---------------------------------------------------------------------------
def _ast_tree_of(path: Path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _cmp_eq_str(node, name: str) -> "str | None":
    """匹配 Compare(Name(name) == Constant(str))，命中返回字符串值。"""
    if (isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq)
            and isinstance(node.left, ast.Name) and node.left.id == name
            and isinstance(node.comparators[0], ast.Constant)
            and isinstance(node.comparators[0].value, str)):
        return node.comparators[0].value
    return None


def _is_post_cmd(node) -> bool:
    """匹配 Compare(self.command == "POST")。"""
    return (isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq)
            and isinstance(node.left, ast.Attribute) and node.left.attr == "command"
            and isinstance(node.left.value, ast.Name) and node.left.value.id == "self"
            and isinstance(node.comparators[0], ast.Constant)
            and node.comparators[0].value == "POST")


def _set_config_whitelist_keys(tree) -> set[str]:
    """set_config 处理块内 ``if "KEY" in data:`` 的 KEY 集合（保存白名单, webui.py if-chain）。"""
    keys: set[str] = set()
    for fn in ast.walk(tree):
        if not (isinstance(fn, ast.FunctionDef) and fn.name == "_route"):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            if not (isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And)
                    and any(_cmp_eq_str(v, "api") == "set_config" for v in test.values)
                    and any(_is_post_cmd(v) for v in test.values)):
                continue
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Compare) and len(sub.ops) == 1
                        and isinstance(sub.ops[0], ast.In)
                        and isinstance(sub.left, ast.Constant) and isinstance(sub.left.value, str)
                        and isinstance(sub.comparators[0], ast.Name)
                        and sub.comparators[0].id == "data"):
                    keys.add(sub.left.value)
    return keys


def _module_settings_meta_keys(tree) -> set[str]:
    """_module_settings 内 ``{"key": ..., "type": ...}`` 字典的 key 集合（⚙ 面板渲染源）。

    F06+W03(batch-04) 表驱动后此形态消失, 保留作旧结构兜底（宁漏勿噪）。
    """
    keys: set[str] = set()
    for fn in ast.walk(tree):
        if not (isinstance(fn, ast.FunctionDef) and fn.name == "_module_settings"):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Dict):
                continue
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and k.value == "key"
                        and isinstance(v, ast.Constant) and isinstance(v.value, str)):
                    keys.add(v.value)
    return keys


def _module_dict_keys(tree, name: str) -> set[str]:
    """模块级 ``NAME = {...}`` / ``NAME: ann = {...}`` 的外层字符串键集合（表驱动锚点）。

    F06+W03(batch-04): webui.py 的 set_config 白名单/校验/日志/回显/⚙meta 五处同源收敛到
    _CONFIG_KEYS 元数据表 —— 本函数提取表外层键即白名单（单一事实来源, 表缺锚点时回退
    旧 if-chain 字面量提取, 宁漏勿噪）。
    """
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name
                and isinstance(node.value, ast.Dict)):
            return {k.value for k in node.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        if (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                and node.target.id == name and node.value is not None
                and isinstance(node.value, ast.Dict)):
            return {k.value for k in node.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    return set()


def _module_settings_table_keys(tree) -> set[str]:
    """模块级 _MODULE_SETTINGS 表的值键并集（⚙ 面板渲染源, F06+W03 表驱动锚点）。"""
    for node in ast.walk(tree):
        target = None
        value = None
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "_MODULE_SETTINGS"):
            target, value = node.targets[0], node.value
        elif (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
              and node.target.id == "_MODULE_SETTINGS" and node.value is not None):
            target, value = node.target, node.value
        if value is None or not isinstance(value, ast.Dict):
            continue
        keys: set[str] = set()
        for v in value.values:
            if isinstance(v, (ast.Tuple, ast.List, ast.Set)):
                keys |= {e.value for e in v.elts
                         if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        return keys
    return set()


def _wpf_set_config_keys() -> set[str]:
    """FaaProxy.cs SetConfigKeys 数组的字符串元素（set_config 第五处白名单, F06+W03 登记对账:
    不改 C#, 与 webui 白名单漂移即 WARN —— 一天两笔跨轨漂移的人工盘点教训, 升为闸门可见）。"""
    if not FAA_PROXY_CS.exists():
        return set()
    try:
        txt = FAA_PROXY_CS.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set()
    m = re.search(r"SetConfigKeys\s*=\s*\[(.*?)\]", txt, re.S)
    if not m:
        return set()
    return set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"', m.group(1)))


def _handled_post_apis(tree) -> set[str]:
    """_route() 内 ``api == "X" and self.command == "POST"`` 分派到的 api 名集合。"""
    apis: set[str] = set()
    for fn in ast.walk(tree):
        if not (isinstance(fn, ast.FunctionDef) and fn.name == "_route"):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And)
                    and any(_is_post_cmd(v) for v in node.values)):
                for v in node.values:
                    name = _cmp_eq_str(v, "api")
                    if name:
                        apis.add(name)
    return apis


def _post_routes_whitelist(tree) -> set[str]:
    """模块级 _POST_ROUTES 白名单集合（do_POST 405 门）。"""
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "_POST_ROUTES"
                and isinstance(node.value, (ast.Set, ast.List, ast.Tuple))):
            return {e.value for e in node.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return set()


def _html_set_config_keys(html_path: Path) -> set[str]:
    """webui.html 里直接 POST /api/set_config 的静态键（⚙ meta 键由后端渲染, 单独统计）。"""
    if not html_path.exists():
        return set()
    txt = html_path.read_text(encoding="utf-8", errors="ignore")
    keys: set[str] = set()
    for m in re.finditer(r'set_config",\s*\{method:"POST",\s*body:JSON\.stringify\(\{([^{}]*?)\}\)',
                         txt, re.S):
        keys |= set(re.findall(r'([A-Za-z_][A-Za-z0-9_]*)\s*:', m.group(1)))
    return keys


def check_webui_contract(errors: list[str], warns: list[str], verbose: bool,
                         strict: bool = False) -> None:
    """6) webui 契约一致性（Q03, 2026-11-13 批）:
       a) ⚙面板键 ⊆ set_config 白名单 —— 里程碑 82/87「勾选被静默丢弃」同型事故防线
          （webui.py set_config 段事故注释「必进白名单…里程碑 87 教训」）。默认 WARN，
          --strict-webui 升 FAIL（先 WARN 一轮观察、确认无误报后再切默认，立项 Q03 约束）。
       b) POST 分派 ↔ _POST_ROUTES 白名单 —— 漏同步=前端 405，硬判 FAIL（白名单注释自警）。
       c) WPF FaaProxy.SetConfigKeys ↔ webui 白名单对账（F06+W03 batch-04 登记项, 不改 C#,
          漂移 WARN）—— 跨轨漂移一天两笔的人工盘点教训升为闸门可见。
       「白名单 − 面板」死键只 INFO 不判违规（按违规判会永久挡住 WARN→FAIL 升级）;
       W01(batch-04) 接线后 finish_action 已被浏览器轨消费。"""
    _log("  webui 契约:")
    if not WEBUI.exists():
        warns.append("[webui] webui.py 不存在, 跳过契约一致性校验")
        _log("    webui.py 不存在（跳过）")
        return
    try:
        tree = _ast_tree_of(WEBUI)
    except SyntaxError as e:
        warns.append(f"[webui] webui.py 语法错误({e.lineno}: {e.msg}), 契约校验跳过（语法检查另报）")
        _log("    webui.py 语法错误, 契约校验跳过")
        return
    try:
        router_tree = _ast_tree_of(HTTP_ROUTER)
    except SyntaxError as e:
        errors.append(f"[webui] transport/http/router.py 语法错误({e.lineno}: {e.msg})")
        return
    try:
        common_tree = _ast_tree_of(HTTP_COMMON)
    except SyntaxError as e:
        errors.append(f"[webui] transport/http/common.py 语法错误({e.lineno}: {e.msg})")
        return

    # F06+W03(batch-04): 白名单/⚙meta 优先走配置 schema（Stage 2 单源）；
    # schema 不可用时回退 app/config_service.py / webui.py 的 AST 提取。
    if config_schema is not None:
        whitelist = set(config_schema.SETTABLE_KEYS)
        meta = {k for k, spec in config_schema.CONFIG_KEYS.items() if spec.get("meta")}
        wl_anchor = "schema"
        meta_anchor = "schema"
    else:
        try:
            cfg_tree = _ast_tree_of(CONFIG_SERVICE) if CONFIG_SERVICE.exists() else tree
        except SyntaxError:
            cfg_tree = tree
        whitelist = _module_dict_keys(cfg_tree, "_CONFIG_KEYS") or _set_config_whitelist_keys(tree)
        meta = _module_settings_table_keys(cfg_tree) or _module_settings_meta_keys(tree)
        wl_anchor = "表" if _module_dict_keys(cfg_tree, "_CONFIG_KEYS") else "if-chain兜底"
        meta_anchor = "表" if _module_settings_table_keys(cfg_tree) else "_module_settings兜底"
    handled = _handled_post_apis(router_tree)
    routes = _post_routes_whitelist(common_tree)
    html_keys = _html_set_config_keys(WEBUI_HTML)

    degraded = []
    if not whitelist:
        degraded.append("set_config 白名单键=0")
    if not handled:
        degraded.append("POST 分派=0")
    if not routes:
        degraded.append("_POST_ROUTES=空")
    if not meta:
        degraded.append("_module_settings meta=0")
    if degraded:
        warns.append("[webui] 契约锚点提取为空(" + "; ".join(degraded) + ") —— webui.py 结构漂移? "
                     "一致性校验降级不误报")
    panel = meta | html_keys

    _log(f"    ⚙面板键 {len(panel)}(meta {len(meta)}[{meta_anchor}] + html 静态 {len(html_keys)})"
         f" / set_config 白名单 {len(whitelist)}[{wl_anchor}]"
         f" / POST 分派 {len(handled)} ↔ 白名单 {len(routes)}")

    # a) 面板键必进白名单（事故方向: 面板有键、白名单漏键 = 勾选被静默丢弃）
    missing_wl = panel - whitelist
    if missing_wl:
        msg = ("⚙面板键未进 set_config 白名单（保存将被静默丢弃, 里程碑 82/87 同型事故）: "
               + ", ".join(sorted(missing_wl)))
        if strict:
            errors.append("[webui] " + msg)
        else:
            warns.append("[webui] " + msg)
        _log(f"    {'✗' if strict else '⚠'} 白名单缺键: {', '.join(sorted(missing_wl))}")
    else:
        _log("    面板键 ⊆ set_config 白名单 ✓")
    only_wl = whitelist - panel
    if only_wl:
        _log(f"    · 白名单死键(无面板控件, 仅提示): {', '.join(sorted(only_wl))}")

    # b) POST 分派 ↔ 白名单（漏同步 = 405, 硬判）
    missing_route = {f"/api/{a}" for a in handled} - routes
    if missing_route:
        errors.append("[webui] POST 路由未同步 _POST_ROUTES 白名单（前端将收到 method not allowed）: "
                      + ", ".join(sorted(missing_route)))
        _log(f"    ✗ POST 分派漏白名单: {', '.join(sorted(missing_route))}")
    else:
        _log("    POST 分派 ⊆ _POST_ROUTES ✓")
    dead_routes = routes - {f"/api/{a}" for a in handled}
    if dead_routes:
        warns.append("[webui] _POST_ROUTES 死键（白名单有、无 POST 分派）: "
                     + ", ".join(sorted(dead_routes)))
        _log(f"    ⚠ 白名单死路由: {', '.join(sorted(dead_routes))}")

    # c) WPF 第五处对账（F06+W03 batch-04 登记项: 不改 C#, 漂移 WARN; 双侧都提取到才判,
    #    宁漏勿噪 —— native/ 未落位或锚点注释变形时静默跳过）
    wpf = _wpf_set_config_keys()
    if wpf and whitelist:
        drift = wpf ^ whitelist
        if drift:
            warns.append("[webui] WPF FaaProxy.SetConfigKeys 与 webui set_config 白名单漂移"
                         f"（跨轨漂移, 保存会被另一侧静默丢弃/忽略）: {', '.join(sorted(drift))}")
            _log(f"    ⚠ WPF SetConfigKeys 漂移 {len(wpf)}↔{len(whitelist)}: "
                 + ", ".join(sorted(drift)))
        else:
            _log(f"    WPF SetConfigKeys 对账 ✓ ({len(wpf)} 键一致)")
    if verbose:
        _log("    面板键: " + ", ".join(sorted(panel)))
        _log("    白名单: " + ", ".join(sorted(whitelist)))


def check_native(errors: list[str], warns: list[str], verbose: bool) -> None:
    """7) 原生 UI(C#) 预检（N01, 2026-11-13 批）: csproj/sln 存在性 + dotnet build 退出码硬判。
       dotnet 不在 PATH → 降级 WARN 不 FAIL（无 SDK 环境闸门不能假红, run_selftest.ps1:11-13
       自举先例）; native/ 整体不存在（未落位, 或 A 案 .gitignore 下不含源码的干净克隆）同样
       降级 WARN —— 存在性硬判只对「native/ 在位但工程文件残缺」生效。"""
    _log("  原生 UI(C#):")
    if not NATIVE_DIR.exists():
        warns.append("[原生UI] native/FAA.WpfGui 不存在（未落位或 A 案出仓克隆）—— C# 侧零闸门覆盖")
        _log("    native/FAA.WpfGui 不存在（降级 WARN, 跳过）")
        return
    miss = [p.name for p in (NATIVE_CSPROJ, NATIVE_SLN) if not p.exists()]
    if miss:
        errors.append("[原生UI] native/ 在位但缺少 " + "、".join(miss))
        _log(f"    ✗ 缺少 {'、'.join(miss)}")
        return
    dotnet = shutil.which("dotnet")
    if not dotnet:
        warns.append("[原生UI] dotnet 不在 PATH —— csproj/sln 存在性 ✓, 构建硬判降级 WARN 跳过")
        _log("    csproj/sln 存在 ✓; dotnet 不在 PATH → 构建硬判跳过（降级 WARN）")
        return
    _log(f"    csproj/sln 存在 ✓; dotnet build {NATIVE_SLN.name}（首次构建可达分钟级）...")
    try:
        r = subprocess.run([dotnet, "build", str(NATIVE_SLN), "-nologo", "-v", "q"],
                           cwd=str(NATIVE_DIR), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=DOTNET_BUILD_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        errors.append(f"[原生UI] dotnet build 超时(>{DOTNET_BUILD_TIMEOUT_S}s)")
        _log("    ✗ dotnet build 超时")
        return
    except OSError as e:
        errors.append(f"[原生UI] dotnet build 无法启动: {e}")
        _log(f"    ✗ dotnet build 无法启动: {e}")
        return
    if r.returncode != 0:
        tail = " | ".join((r.stdout or "").strip().splitlines()[-3:]) or "(无输出)"
        errors.append(f"[原生UI] dotnet build 退出码 {r.returncode} != 0; 尾部输出: {tail}")
        _log(f"    ✗ dotnet build 退出码 {r.returncode}")
    else:
        _log("    dotnet build 退出码 0 ✓")


def walk_step_dicts(node, path: str):
    """递归产出 (步骤dict, 位置说明)，供需要读取步骤参数的检查复用。"""
    if isinstance(node, list):
        for i, item in enumerate(node):
            yield from walk_step_dicts(item, f"{path}[{i}]")
    elif isinstance(node, dict):
        t = node.get("type")
        if isinstance(t, str) and t:
            yield node, path
        for k, v in node.items():
            if isinstance(v, (list, dict)):
                yield from walk_step_dicts(v, f"{path}.{k}")


def check_flow_config_keys(errors: list[str], warns: list[str], verbose: bool) -> None:
    """8) flow 的 if_config 键 ↔ config.example / WebUI ⚙ / WPF 三方对账。

    历史教训（里程碑 87）：`enable_mine`/`enable_rabbit` 在 flow 里用了，
    但 WebUI set_config 白名单漏了 → 勾选被静默丢弃。本检查把「flow 用了什么键」
    作为源头，提前暴露缺键/缺控件。
    """
    _log("  config 键一致性(if_config):")
    flow_keys: dict[str, list[str]] = {}
    for f in sorted(FLOWS_DIR.rglob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for step, loc in walk_step_dicts(data, _rel(f)):
            if step.get("type") != "if_config":
                continue
            keys = step.get("keys")
            if isinstance(keys, (list, tuple)):
                for k in keys:
                    if isinstance(k, str) and k:
                        flow_keys.setdefault(k, []).append(loc)
                continue
            key = step.get("key")
            if isinstance(key, str) and key:
                flow_keys.setdefault(key, []).append(loc)

    try:
        example = json.loads((DATA_DIR / "config.example.json").read_text(encoding="utf-8"))
        example_keys = {k for k in example if not k.startswith("_")}
    except Exception as e:  # noqa: BLE001
        errors.append(f"[config键] 读取 config.example.json 失败: {e}")
        return

    if config_schema is not None:
        for e in config_schema.validate_example(example):
            errors.append(f"[config键] config.example.json: {e}")
        unknown = sorted(set(flow_keys) - set(config_schema.ALL_KEYS))
        if unknown:
            errors.append(f"[config键] flow 使用 schema 未定义键: {unknown}")

    meta_keys: set[str] = set()
    if config_schema is not None:
        meta_keys = {k for k, spec in config_schema.CONFIG_KEYS.items() if spec.get("meta")}
    else:
        try:
            src = CONFIG_SERVICE if CONFIG_SERVICE.exists() else WEBUI
            tree = ast.parse(src.read_text(encoding="utf-8"))
            meta_keys = _module_settings_table_keys(tree) or _module_settings_meta_keys(tree)
        except Exception as e:  # noqa: BLE001
            warns.append(f"[config键] 无法解析 WebUI 面板键: {e}")

    wpf_keys: set[str] = set()
    try:
        wpf_keys = _wpf_set_config_keys()
    except Exception as e:  # noqa: BLE001
        warns.append(f"[config键] 无法解析 WPF SetConfigKeys: {e}")

    missing_example = sorted(set(flow_keys) - example_keys)
    missing_meta = sorted(set(flow_keys) - meta_keys) if meta_keys else []
    missing_wpf = sorted(set(flow_keys) - wpf_keys) if wpf_keys else []

    _log(f"    flow if_config {len(flow_keys)} 键 / example {len(example_keys)} 键"
         f" / 面板 {len(meta_keys)} 键 / WPF {len(wpf_keys)} 键")
    for k in missing_example:
        errors.append(f"[config键] flow 使用 '{k}' 但 config.example.json 缺键 @ {flow_keys[k][0]}")
    for k in missing_meta:
        warns.append(f"[config键] flow 使用 '{k}' 但 WebUI ⚙ 面板无控件（确认是否仅命令行）")
    for k in missing_wpf:
        warns.append(f"[config键] flow 使用 '{k}' 但 WPF SetConfigKeys 未包含")
    if verbose:
        for k in sorted(flow_keys):
            _log(f"      {k}: {len(flow_keys[k])} 处")


def check_collab(errors: list[str], verbose: bool) -> None:
    """5) 协作开发区预检：inbox 待合并清单 + JSON 硬判 + 步骤类型软提示。"""
    inbox = COLLAB_DIR / "inbox"
    if not COLLAB_DIR.exists():
        _log("  协作开发区: 未创建（跳过）")
        return

    dirs = lambda p: [d for d in sorted(p.iterdir()) if d.is_dir()] if p.exists() else []  # noqa: E731
    inbox_dirs = dirs(inbox)
    ledgers = [d for d in inbox_dirs if d.name in COLLAB_LEDGER_DIRS]
    pending = [d for d in inbox_dirs if d.name not in COLLAB_LEDGER_DIRS]
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
    if ledgers:
        _log(f"    常驻台账 {len(ledgers)} 份（不计待合并）: " + "、".join(d.name for d in ledgers))

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


def check_tests(errors: list[str], verbose: bool) -> None:
    """9) 离线单元测试：tests/ 下 stdlib unittest，不联网、不连 ADB。"""
    _log("  离线单元测试(tests/):")
    r = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
        cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        errors.append(f"[tests] unittest 失败 (rc={r.returncode})\n{r.stdout}\n{r.stderr}")
        return
    tail = (r.stderr or "").strip().splitlines()
    _log("    " + (tail[-1] if tail else "OK"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="FAA 项目校验 / 合并闸门")
    ap.add_argument("--map", action="store_true", help="只打印项目地图，不校验")
    ap.add_argument("-v", "--verbose", action="store_true", help="打印逐项明细")
    ap.add_argument("--strict-webui", action="store_true",
                    help="webui 面板键↔set_config 白名单一致性由 WARN 升 FAIL（Q03 观察期结束后切默认）")
    ap.add_argument("--with-tests", action="store_true",
                    help="额外运行 tests/ 离线单元测试（不联网、不连 ADB）")
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
    warns: list[str] = []
    check_json(errors, args.verbose)
    check_step_types(errors, args.verbose)
    check_flow_struct(errors, args.verbose)
    check_syntax(errors, args.verbose)
    check_collab(errors, args.verbose)
    check_webui_contract(errors, warns, args.verbose, strict=args.strict_webui)
    check_flow_config_keys(errors, warns, args.verbose)
    check_native(errors, warns, args.verbose)
    if args.with_tests:
        check_tests(errors, args.verbose)
    doc_hint()
    _log("-" * 46)

    if warns:
        _log(f"⚠ {len(warns)} 个警告（不阻断合并; 台账记「待人工确认」）:")
        for w in warns:
            _log("  - " + w)
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