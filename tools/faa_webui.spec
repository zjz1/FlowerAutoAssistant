# -*- mode: python ; coding: utf-8 -*-
"""FAA 后端 PyInstaller one-folder 打包配置（发布计划 Phase 2 / #1）。

产物: build/dist/faa_webui/faa_webui.exe + _internal/

数据布局与源码树一致（冻结后各模块 BASE = Path(__file__).resolve().parents[N] 落在
_internal, 相对路径零改动）:
    _internal/flows/            流程 JSON + common/{entries,scenes}.json
    _internal/resource/template/ 38 个游戏 UI 模板
    _internal/data/             config.example.json / close_buttons.json
                                （config.json、click_log.json、tplt_annotations.jsonl 属本机运行状态,
                                 不入包; 首启由 config.example.json 复制, click_log 缺失可正常运行）
    _internal/webui.html
    _internal/tpltool.html

第三方原生/数据依赖:
    maa/bin/*.dll          maa 包内原生库（maa/__init__.py 用 Path(__file__).parent/"bin"）
    MaaAgentBinary/        maa 的兄弟目录（maa/controller.py 用 ../MaaAgentBinary 定位）
    rapidocr_onnxruntime   内置 OCR 模型 .onnx

构建命令（仓库根执行）:
    .venv\\Scripts\\python.exe -m PyInstaller tools\\faa_webui.spec --noconfirm --clean ^
        --distpath build\\dist --workpath build\\work
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, get_package_paths

ROOT = Path(SPECPATH).resolve().parent

datas = [
    (str(ROOT / "flows"), "flows"),
    (str(ROOT / "resource" / "template"), "resource/template"),
    (str(ROOT / "data" / "config.example.json"), "data"),
    (str(ROOT / "data" / "close_buttons.json"), "data"),
    (str(ROOT / "data" / "blockers.json"), "data"),
    (str(ROOT / "data" / "plant_presets.json"), "data"),
    (str(ROOT / "webui.html"), "."),
    (str(ROOT / "tpltool.html"), "."),
]

binaries = []
hiddenimports = []

# maa（maa/bin 原生 DLL）与 rapidocr_onnxruntime（OCR 模型）的包内数据/二进制全量收集
for pkg in ("maa", "rapidocr_onnxruntime"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# MaaAgentBinary 是 maa 的兄弟目录（controller.AGENT_BINARY_PATH = <site-packages>/MaaAgentBinary）
_pkg_base, _ = get_package_paths("maa")
_agent_bin = Path(_pkg_base) / "MaaAgentBinary"
if _agent_bin.is_dir():
    datas.append((str(_agent_bin), "MaaAgentBinary"))

a = Analysis(
    [str(ROOT / "webui.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "pywebview",
        "webview",
        "pytest",
        "matplotlib",
        "pandas",
        "scipy",
        "IPython",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="faa_webui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="faa_webui",
)
