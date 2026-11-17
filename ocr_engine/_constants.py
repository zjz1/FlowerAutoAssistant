"""模块级常量与 STEP_TYPES(E02 显式步骤类型白名单)。

E01(batch-03, 2026-11-14) 自单文件 ocr_engine.py 机械拆包: 本文件各段为原文件对应
行段的**逐行原文**(唯 __file__ 锚点因包层级 +1 机械重锚定, 见 ast_hash_compare.py
allowlist)。行为等价口径: 帧集回归 0 退化 + 闸门全绿 + import 面零改动。
原行段映射: evidence/batch-03/tiles_manifest.json。
"""
from __future__ import annotations

from pathlib import Path
ADB_ADDRESS = "127.0.0.1:16384"
ADB_PATH = r"D:\Program Files\Netease\MuMu\nx_main\adb.exe"
FLOW_DIR = Path(__file__).resolve().parent.parent / "flows"
CLICK_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "click_log.json"
CLOSE_BUTTONS_PATH = Path(__file__).resolve().parent.parent / "data" / "close_buttons.json"
CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "config.json"
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "resource" / "template"
# 公共「进入目标界面」导航注册表(flows/common/entries.json), 供 navigate 步骤按 target 查进入链。
# 子目录不被 load_flows() 扫入主流程列表(load_flows 只 glob 顶层 *.json), 故作为公共资源单独加载。
NAV_ENTRIES_PATH = FLOW_DIR / "common" / "entries.json"
NAV_SCENES_PATH = FLOW_DIR / "common" / "scenes.json"

# 过宽块拆分/定向精识共用 LRU 上限（2026-11-17 由 400 扩至 1000；C47 实测单轮拆分
# 1470 次/1737s、缓存命中 312 次，扩大热工作集可把跨屏重复的静态碎片转为命中）。
SPLIT_CACHE_MAX = 1000

# ---------------------------------------------------------------------------
# 步骤类型白名单（E02, 2026-11-13 批）: run_step 分派支持的步骤类型显式导出。
# 值由 tools/check_project.py known_step_types() 现跑输出机械生成(46 种; 2026-11-16 新增
# plant_flower/plant_harvest, 2026-11-17 新增 fairyland_claim/buy_seed), 锚点=run_step 分派段
# (『---- 流程执行 ----』 banner 之后的 s_type == 分支)。维护契约: run_step 新增/删除 s_type 分支时必须同步本集合 ——
# 闸门 tools/check_project.py 优先 import 本集合做流程校验(不再解析源文本),
# 旧正则提取仅作 import 失败时的兜底路径保留。
# ---------------------------------------------------------------------------
STEP_TYPES: frozenset[str] = frozenset({
    "buy_item",
    "buy_seed",
    "claim_scroll",
    "click_account_tail",
    "click_rel",
    "click_row_button",
    "click_template",
    "click_text",
    "close_dialog",
    "community_like",
    "count_probe",
    "count_text",
    "dump_frame",
    "dump_text",
    "ensure_home",
    "ensure_menu",
    "fail_flow",
    "fairyland_claim",
    "friend_pollin",
    "if_account_tail",
    "if_collected",
    "if_color_count",
    "if_config",
    "if_count",
    "if_fraction",
    "if_greater",
    "if_scene",
    "if_text",
    "if_time",
    "if_weekday",
    "loop_fraction",
    "loop_text",
    "loop_times",
    "navigate",
    "plant_flower",
    "plant_harvest",
    "retry_loop",
    "reward_dialog",
    "sleep",
    "slide",
    "store_fraction",
    "touch_drag",
    "wait_scene",
    "wait_text",
    "wait_text_gone",
    "wait_update_done",
})

# 方案②「立体化分级+均值+偏差复核」: OCR 命中点与历史均值偏差超过该像素数即视为可疑,
# 触发二次更精细处理(局部放大重识别, 无更优子块则沿用原命中, 仅记录日志)。
BIAS_MAX_PX = 60
# 硬阈值: 偏差超过该像素数(约屏宽 14%)且局部重识别仍无更优子块时, 判为 OCR 误命中并**弃用**
# (不点击、不写知识库), 转入回退链。否则类似「采粉」被聊天文字误命中(偏差数百px)会误点邻区并污染均值。
BIAS_HARD_PX = 180
