"""
FlowerAutoAssistant - OCR 数据驱动引擎核心（替代 MAA 模板匹配路线）

核心循环: 截图 -> OCR识别文字 -> 按关键字定位按钮 -> 计算相对坐标(归一化) -> 点击

与 MAA 模板匹配的区别:
- 不依赖模板图片, 每次运行通过 OCR 直接识别文字/按钮位置
- 使用「相对坐标」: 记录 (x/宽, y/高) 归一化坐标, 屏幕尺寸变化时相对位置不变
- 数据驱动: 流程由 JSON 描述(flow), 无需改代码即可适配新流程
- 回退缓存: 记录「最后已知相对坐标」, 当 OCR 瞬时失败时可用缓存补点击, 提高鲁棒性

用法:
    python ocr_engine.py --list            # 列出可用流程
    python ocr_engine.py --flow 每日      # 运行指定流程(按关键字匹配)
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# 复用 OCR 单例模块
from ocr_ui import ocr_image, ocr_find, set_thread_limit

ADB_ADDRESS = "127.0.0.1:16384"
ADB_PATH = r"D:\Program Files\Netease\MuMu\nx_main\adb.exe"
FLOW_DIR = Path(__file__).parent / "flows"
CLICK_LOG_PATH = Path(__file__).parent / "data" / "click_log.json"
CLOSE_BUTTONS_PATH = Path(__file__).parent / "data" / "close_buttons.json"
CONFIG_PATH = Path(__file__).parent / "data" / "config.json"
TEMPLATE_DIR = Path(__file__).parent / "resource" / "template"
# 公共「进入目标界面」导航注册表(flows/common/entries.json), 供 navigate 步骤按 target 查进入链。
# 子目录不被 load_flows() 扫入主流程列表(load_flows 只 glob 顶层 *.json), 故作为公共资源单独加载。
NAV_ENTRIES_PATH = FLOW_DIR / "common" / "entries.json"
NAV_SCENES_PATH = FLOW_DIR / "common" / "scenes.json"


# ---------------------------------------------------------------------------
# 全局停止机制: 用于「停止当前所有流程但不关闭服务/进程」。
# 任意调用方(CLI/WebUI/编排)均可 request_stop() 请求停止;
# 引擎在 run_flow/run_daily 入口 clear_stop(), 在步骤/模块/等待循环之间检查
# stop_requested(), 命中即抛出 StopRequested 中断本轮全部流程执行。
# ---------------------------------------------------------------------------
_STOP_EV = threading.Event()


class StopRequested(BaseException):
    """流程被 request_stop() 请求停止时抛出, 用于从深层(等待/循环/嵌套步骤)向上冒泡中断。
    继承 BaseException-> 不会被引擎内的 `except Exception`(run_module 容错)吞掉,
    从而一路穿透到最外层 run_flow/run_daily 的统一停止处理。"""


class BranchAborted(Exception):
    """E2(2026-10-27, zcode-20261028-3): 分支内短路 —— 带 `required: true` 的步骤失败时抛出,
    由 run_steps 捕获后**中止当前 then/else 列表**、继续执行列表之后的步骤。
    与 FlowFailed(模块级中止, on_fail 处置)的区别: 本异常只放弃"当前分支的剩余步骤"
    (例如 if_collected.then 里的任务链), 编排与后续模块不受影响; 失败本身已由
    report_failure 如实登记, 不伪装成功。"""

class FlowFailed(Exception):
    """流程主动判定失败(由流程 JSON 的 `fail_flow` 步骤抛出)。

    与 StopRequested 的区别: StopRequested 是「用户请求停止」(中断整轮, 不算失败);
    FlowFailed 是「本模块确实没做成」(如实上报失败, 由 run_module 收成 'fail', 再交给编排的
    on_fail 决定跳过还是终止本轮)。用于「前置条件不满足时, 继续往下会跑出一整轮假结果」的场景
    ——例如切换账号失败仍去点「登录」, 就会用错误账号跑完当天全部任务。
    继承 Exception -> 会被 run_module 捕获并登记失败, 不会冒泡到进程外。
    """


def request_stop() -> None:
    """请求停止当前正在进行的所有流程。服务/进程保持运行, 可再次开始新一轮。"""
    _STOP_EV.set()


def clear_stop() -> None:
    """清除停止请求(新一轮流程开始前自动调用)。"""
    _STOP_EV.clear()


def stop_requested() -> bool:
    """是否已被请求停止。"""
    return _STOP_EV.is_set()


# ---------------------------------------------------------------------------
# 功能失败登记: 供「任意功能失败就提醒」(WebUI 弹窗, 2026-10-02 需求)。
# 只登记**真实失败**(等待超时 / 放弃 / 跑满轮数 / 模块异常), 不得把缓存回退当失败或成功判据。
# 登记 = ① print(带 [失败] 前缀, 落盘进运行日志) ② 存内存清单, 供 WebUI 增量拉取弹窗。
# ---------------------------------------------------------------------------
_FAIL_LOCK = threading.Lock()
_FAILURES: list[dict] = []
_FAIL_SEQ = 0


def report_failure(module: str, detail: str) -> None:
    """登记一次功能失败。module=当前模块/场景, detail=人可读原因。"""
    global _FAIL_SEQ
    with _FAIL_LOCK:
        _FAIL_SEQ += 1
        _FAILURES.append({
            "id": _FAIL_SEQ,
            "ts": time.strftime("%H:%M:%S"),
            "module": str(module or "未分类"),
            "detail": str(detail),
        })
    print(f"[失败] [{module or '未分类'}] {detail}")


def get_failures(after: int = 0) -> tuple[list[dict], int]:
    """取 id > after 的失败清单, 返回 (items, 最新 id)。供 WebUI 增量轮询。"""
    with _FAIL_LOCK:
        items = [dict(f) for f in _FAILURES if f["id"] > after]
        return items, _FAIL_SEQ


def clear_failures() -> None:
    """清空失败清单(不影响已打印落盘的日志)。"""
    with _FAIL_LOCK:
        _FAILURES.clear()


def _ts() -> str:
    """日志正文统一时间戳(本地时, HH:MM:SS), 供离线分诊统计各阶段耗时(见 A3/P2-03)。"""
    return time.strftime("%H:%M:%S")


# ---------------------------------------------------------------------------
# OCR 观测计数(O0, 2026-10-21): 纯观测, 不改任何判定行为。
# 背景: 原 `[OCR统计]` 只有 full/region/split/缓存 四个聚合数, 无法回答「这次全图是谁发起的」,
#   导致 social 44min 归因只能估算。新增三个维度:
#   ① by_src: 每个 OCR/拆分按**发起处**计数(步骤类型, 如 click_text/if_text/wait_scene;
#      judge_scene 内部标记为 scene; pollin 直调标 read_page/diag);
#   ② split_only_hit: 关键词**只在拆分子块里**命中(合并块本身不中)—— 这是「判断类是否可安全
#      跳过拆分」的安全指标, 为 0 才允许开惰性拆分(见 O2);
#   ③ split_cache_hit / direct_n: 拆分缓存命中与 pollin 直调 OCR —— 原实现对这两项完全失明。
# 内存: 几张 source→int 的小字典(键数 = 步骤类型数量级, 十几个), 可忽略。
# ---------------------------------------------------------------------------
def _new_ocr_stat() -> dict:
    """一套新的 OCR 观测计数器(模块级清零/整轮累计共用同一结构)。"""
    return {
        "full_n": 0, "full_t": 0.0,
        "region_n": 0, "region_t": 0.0,
        "split_n": 0, "split_t": 0.0,
        "hit_n": 0,              # 帧缓存命中(不产生 OCR)
        "direct_n": 0, "direct_t": 0.0,   # 流程外直调 OCR(页码/诊断等)
        "split_cache_hit": 0,     # 拆分结果缓存命中(不产生 OCR)
        "split_only_hit": 0,      # 仅子块命中(判断类跳过拆分的安全指标)
        "scene_calls": 0,         # judge_scene 调用次数
        "miss_silent_n": 0,       # E1: 静默未命中次数(弹窗/启动守卫的常态负判定)
        "scene_quiet_n": 0,       # P2-5: 被折叠的场景判断次数(轮询内负判定, 由等待汇总替代)
        "friend_coarse_n": 0, "friend_coarse_hit": 0,   # P2-5③: 社交面板「好友」粗 OCR 探测/命中
        "friend_fine_n": 0, "friend_fine_hit": 0,       # P2-5③: 粗识失败后的滤色精识兜底 探测/命中
        "by_src": {},             # kind(full/region/split/direct) -> {来源: 次数}
    }


def _stat_add(dst: dict, src: dict) -> None:
    """把一套 OCR 统计累加进另一套(数值相加, by_src 这类嵌套字典递归合并)。"""
    for k, v in src.items():
        if isinstance(v, dict):
            d = dst.get(k)
            if not isinstance(d, dict):      # 兼容 fromkeys 遗留的 0 值
                d = {}
                dst[k] = d
            _stat_add(d, v)
        else:
            dst[k] = dst.get(k, 0) + v


# 方案②「立体化分级+均值+偏差复核」: OCR 命中点与历史均值偏差超过该像素数即视为可疑,
# 触发二次更精细处理(局部放大重识别, 无更优子块则沿用原命中, 仅记录日志)。
BIAS_MAX_PX = 60
# 硬阈值: 偏差超过该像素数(约屏宽 14%)且局部重识别仍无更优子块时, 判为 OCR 误命中并**弃用**
# (不点击、不写知识库), 转入回退链。否则类似「采粉」被聊天文字误命中(偏差数百px)会误点邻区并污染均值。
BIAS_HARD_PX = 180


# ---------- 坐标 ----------
@dataclass
class Point:
    """绝对坐标 (px) 与相对坐标 (0~1 归一化)。"""
    x: int
    y: int
    w: int  # 屏幕宽
    h: int  # 屏幕高

    @property
    def rel(self) -> tuple[float, float]:
        return (self.x / self.w if self.w else 0.0,
                self.y / self.h if self.h else 0.0)

    @staticmethod
    def from_rel(rx: float, ry: float, w: int, h: int) -> "Point":
        return Point(int(rx * w), int(ry * h), w, h)


# ---------- 核心引擎 ----------
class OCREngine:
    """OCR 自动化引擎: 管理设备连接、截图、OCR、定位、点击。"""

    def __init__(self, adb_path: str = ADB_PATH, address: str = ADB_ADDRESS):
        self.adb_path = adb_path
        self.address = address
        self._ctrl = None
        self.last_rel: dict[str, tuple[float, float]] = {}  # 文字关键字 -> 相对坐标缓存
        self.screen_w = 0
        self.screen_h = 0
        # 实机显示分辨率(2026-10-07 用户反馈): MAA 截图管道有**长边 1280 缩放上限**
        # (set_screenshot_target_long_side), 故 screen_w/h 是**引擎工作区**尺寸而非实机
        # 分辨率 —— MuMu 配 1920×1080 时 MAA 实测仍返回 1280×720(同画面等比 0.667,
        # 灰度差 2.1)。引擎 OCR/点击全部自洽地工作在工作区内(相对坐标不受影响),
        # 但 WebUI 应展示**实机分辨率**: adb 原生截图直读(不经 MAA 缩放)。
        self.display_w = 0
        self.display_h = 0
        self.click_log_scenes: dict[str, dict[str, dict]] = self._load_click_log()
        # 扁平索引 按钮名 -> 记录 (跨场景同名取最新), 供既有查找回退链零改动使用
        self.click_log: dict[str, dict] = self._build_flat_index(self.click_log_scenes)
        self.close_buttons: list[dict] = self._load_close_buttons()  # 关闭按钮特殊逻辑注册表
        self.config: dict = self._load_config()  # 用户配置 (data/config.json), 支持 CLI 覆盖
        if "ocr_threads" in self.config:  # RapidOCR 每会话线程数 (0=不限制; 缺省 2, 见 ocr_ui.py)
            set_thread_limit(self.config.get("ocr_threads"))
        self._navigation: dict = self._load_navigation()  # 公共「进入目标界面」注册表 (navigate 步骤用)
        self._scenes: dict = self._load_scenes()          # 公共「场景判断」注册表 (judge_scene/if_scene 用)
        self._rr_hit = False  # retry_loop 本轮命中标记 (仅「真实识别命中」置真, 缓存回退不计)
        self._last_locate_source: str | None = None  # 上一次定位来源: ocr/anchor/color/template/fallback
        self._scene: str = "未分类"  # 当前界面场景 (流程步骤可声明, 默认未分类)
        self._step_category: str | None = None  # 步骤临时声明的按钮类别(click_text/click_rel 用)
        self._module: str = "未分类"  # 当前模块名 (run_flow/run_module 设置), 供失败登记标注来源
        self._count_probes: dict[str, int | None] = {}  # 数量计数探针存值(if_count 变化判定用, 2026-10-25)
        # 同帧 OCR 结果复用 (性能长期目标 §11.3-2): 静态画面反复轮询时不再重复全屏 OCR, 见 _ocr_frame
        self._frame_sig: bytes | None = None
        self._frame_cache: tuple | None = None
        self._frame_lock = threading.Lock()
        # 批C-②: OCR 计时统计(模块级 _ocr_stat, run_module 收尾打印并累计进 _ocr_stat_total,
        # run_daily 结束打整轮汇总)。纯观测, 不改任何判定行为。
        # O0(2026-10-21): 结构见模块级 _new_ocr_stat(), 增加来源/拆分缓存/仅子块命中三个维度。
        self._ocr_stat = _new_ocr_stat()
        self._ocr_stat_total = _new_ocr_stat()
        self._ocr_src = "other"   # 当前 OCR 发起处(步骤类型; judge_scene 置 scene), 仅用于观测
        # 批C-①: 区域化 OCR 结果 LRU(裁片像素指纹 -> (blocks, sub_blocks))。
        # 值为**裁片相对坐标**, 映射用当次 origin —— 同内容不同位置不会错位, 批A「缓存键必须
        # 含位置」的教训在此天然规避; 独立 LRU 不占用全图单槽帧缓存(避免全图/区域交替查询
        # 互相顶掉造成反复重扫)。
        self._region_cache: dict = {}
        # v2(2026-10-12): 行分组采集内存 (label -> rows), 供 if_collected 查询; claim_scroll 同步写入
        # v2.1(2026-10-17): rows=该次调用的**跨屏累计**行(调用开始重置, 轮间 _merge_rows 并入各屏行)
        self._last_dump: dict = {}
        self._region_lock = threading.Lock()
        # 过宽块拆分结果缓存(2026-10-07 性能批 zcode-20261007-15): 裁片像素指纹 → 拆分子块。
        # 实测拆分环节 7.5~9.6s/帧(占单轮 OCR 60~85%), 而过宽块多为静态 UI 碎片(顶栏簇/花园名/
        # 横幅)逐帧原样重现 —— 内容没变直接复用拆分结果, 行为与逐帧拆分完全一致(等价幂等)。
        self._split_cache: dict = {}
        self._split_lock = threading.Lock()
        # 最近一帧缓存: WebUI 预览在流程运行期直接复用引擎刚截的帧, 免去预览自己截图与引擎争抢 ADB
        self.last_frame: np.ndarray | None = None
        self.last_frame_ts: float = 0.0
        # 「同画面未命中折叠」状态(见 _log_ocr_miss): 帧指纹+exact+区域 相同的连续未命中只打首条
        self._miss_sig: tuple | None = None
        self._miss_count = 0
        # E1(2026-10-22): 静默未命中的末帧证据 —— log_miss=False 时不再逐条打印
        #   `[OCR未命中]`, 但保留最后一次的 blocks/keywords, 供 reward_dialog 输出
        #   「无弹窗」摘要与「疑似存在但分数不足」提示。
        self._last_miss_blocks: list | None = None
        self._last_miss_keywords = None
        # 相邻定位复用 (性能批 zcode-20261007-16 批B): 上一步(if_text/wait_text)刚 OCR 命中的
        # 点位, 供**紧邻的下一步** click_text 在查询兼容时直接复用, 免去二次截图 + 全图 OCR。
        # _step_seq: run_step 单调递增的步骤序号, 保证"仅紧邻下一步"可复用(中间隔了任何步骤即失效)。
        self._guard_hit: dict | None = None
        self._step_seq: int = 0
        # 故障现场全量存证 (2026-10-14 用户要求): 离散错误点做一次全量 OCR + 截图留档;
        # 预算上限 + (tag, 帧指纹) 去重, 防日志/磁盘膨胀。纯观测, 不改判定行为。
        # 注: 预算为**引擎实例级**(webui 常驻单例 → 实际跨轮次累计, 非每轮重置);
        #     如需每轮重置可在 run_daily 追加一行 —— 主 agent 里程碑 91 记, 当前维持进程级(上限 20)。
        self._dump_left = int(self.config.get("fail_dump_budget", 20))
        self._dump_sig = None
        # 里程碑 94(用户方案): 截图存 data/fail_cache/<会话戳>/ 下 —— 会话戳=引擎实例创建时刻
        # (webui 常驻单例 ⇒ 一次服务运行=一个会话目录, 跨重启保留不清), 归档/清理按会话粒度操作。
        self._session_stamp = time.strftime("%Y%m%d_%H%M%S")
        self._dump_seq = 0

    # ---- 公共导航注册表 (flows/common/entries.json) ----
    def _load_navigation(self) -> dict:
        """加载公共「进入目标界面」注册表。返回 {"targets": {目标名: {scene, mark_text, mark_fallback_rel, max_rounds, nav}}}。"""
        try:
            if NAV_ENTRIES_PATH.exists():
                with open(NAV_ENTRIES_PATH, encoding="utf-8") as fp:
                    data = json.load(fp)
                    return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"[导航注册表加载失败] {e}")
        return {}

    def _load_scenes(self) -> dict:
        """加载公共「场景判断」注册表。返回 {"scenes": {场景名: {description, markers, any_of, min_total}}}。"""
        try:
            if NAV_SCENES_PATH.exists():
                with open(NAV_SCENES_PATH, encoding="utf-8") as fp:
                    data = json.load(fp)
                    return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"[场景注册表加载失败] {e}")
        return {}

    # ---- 场景判断 (继 OCR 判断 / template 判断后的第三种判定, 2026-10-05 用户定立) ----
    # 判定条件完全声明在 flows/common/scenes.json 每个场景的 rule 条件树里(JSON 声明式,
    # 改条件/加场景不动引擎代码, 条件树可整体复制迁移到其它场景甚至其它项目):
    #   {"op":"hit",   "kw":"X",              "region_rel"?}  单关键字命中(子串包含)
    #   {"op":"any",   "kws":[...],           "region_rel"?}  至少其一命中
    #   {"op":"all",   "kws":[...],           "region_rel"?}  全部命中
    #   {"op":"count", "kws":[...],"min":N,"max":M,"region_rel"?}  命中数落在 [min,max]
    #   {"op":"absent","kws":[...],           "region_rel"?}  关键字均不出现(排除法)
    #   {"op":"and","conds":[...]} / {"op":"or","conds":[...]} / {"op":"not","cond":{...}}
    # region_rel=[x1,y1,x2,y2](0~1, 相对截图宽高)限定该叶子条件的判定区域。
    # 兼容旧版简写 schema(markers/any_of/min_total): 无 rule 时自动编译为等价条件树。
    @staticmethod
    def _rule_kws(cond) -> set:
        """收集条件树引用的全部关键字(仅用于日志展示命中集)。"""
        op = cond.get("op")
        if op in ("and", "or"):
            out: set = set()
            for c in cond.get("conds", []):
                out |= OCREngine._rule_kws(c)
            return out
        if op == "not":
            return OCREngine._rule_kws(cond.get("cond") or {})
        kws = set(cond.get("kws") or [])
        if cond.get("kw"):
            kws.add(cond["kw"])
        return kws

    @staticmethod
    def _compile_legacy_scene(entry: dict) -> dict:
        """旧版简写(markers/any_of/min_total) → 等价条件树, 保证旧条目继续可用。"""
        markers = list(entry.get("markers") or [])
        any_of = list(entry.get("any_of") or markers)
        min_total = entry.get("min_total", 1)
        conds = [{"op": "any", "kws": any_of}]
        if min_total > 1 and markers:
            conds.append({"op": "count", "kws": markers, "min": min_total})
        return conds[0] if len(conds) == 1 else {"op": "and", "conds": conds}

    def _scene_blocks(self, img, min_score: float, region_rel=None) -> list:
        """场景判定的 OCR 块(默认一次全图识别, 引擎帧缓存复用)。

        O0(2026-10-21): 把发起处临时标为 scene —— 这样 `[OCR统计]` 能直接量出「场景判断触发了
        多少次全图 OCR / 多少次拆分」。拆分结果(子块)在本函数里**从未被读取**, 该计数也是
        O1「场景判断不做拆分」的基线。
        O1(2026-10-21): 传 need_split=False —— 场景判定只需要 blocks, 拆分纯属浪费。
        E1(2026-10-27, zcode-20261028-2): 场景级 `region_rel`(scenes.json 场景条目可选字段)——
        该场景全部判据锚点所在的固定条带(面积须 <=40% 才生效, 否则按 None 走全图)。区域化后
        **区域 MISS 即最终判定**(场景判据的轮询负判定占调用大头 —— 若未命中回退全图,
        每次轮询 MISS 变成"裁片+全图"两次识别反而更慢; 与 find_text 的"未命中回退"语义**有意不同**,
        正确性前提=region 覆盖该场景全部锚点, 由 scenes.json 注明的实机证据与 C 类实机验证保证;
        `region_ocr: false` 总开关可一键回退全图)。块坐标仍映射回全图, rule 树叶节点自身的
        region_rel 过滤语义不变。
        """
        prev = self._ocr_src
        self._ocr_src = "scene"
        try:
            if region_rel and len(region_rel) == 4 and self.config.get("region_ocr", True):
                r = self._ocr_frame_region(img, region_rel, need_split=False)
                if r is not None:
                    return [b for b in r[0] if b.get("score", 1) >= min_score]
            return [b for b in self._ocr_frame(img, need_split=False)[0]
                    if b.get("score", 1) >= min_score]
        finally:
            self._ocr_src = prev

    @staticmethod
    def _kw_hits(blocks: list, kws, region=None) -> set:
        """返回 kws 中命中的子集(子串包含)。region=(x1,y1,x2,y2) 绝对像素, 限定块中心。"""
        if region is not None:
            x1, y1, x2, y2 = region
            blocks = [b for b in blocks
                      if x1 <= b.get("center", [0, 0])[0] <= x2
                      and y1 <= b.get("center", [0, 0])[1] <= y2]
        texts = [b.get("text", "") for b in blocks]
        return {kw for kw in kws if any(kw in t for t in texts)}

    def _eval_rule(self, cond, blocks) -> bool:
        """递归求值条件树。叶子节点带 region_rel 时按截图宽高换算为绝对像素区域。"""
        op = cond.get("op")
        if op in ("and", "or"):
            conds = cond.get("conds", [])
            if op == "and":
                return all(self._eval_rule(c, blocks) for c in conds)
            return any(self._eval_rule(c, blocks) for c in conds)
        if op == "not":
            return not self._eval_rule(cond.get("cond") or {}, blocks)
        region = None
        rr = cond.get("region_rel")
        if rr and self.screen_w and self.screen_h:
            region = (rr[0] * self.screen_w, rr[1] * self.screen_h,
                      rr[2] * self.screen_w, rr[3] * self.screen_h)
        kws = list(cond.get("kws") or [])
        if cond.get("kw"):
            kws.append(cond["kw"])
        hits = self._kw_hits(blocks, kws, region)
        if op in ("hit", "any"):
            return bool(hits)
        if op == "all":
            return len(hits) >= len(kws) if kws else False
        if op == "count":
            n = len(hits)
            return n >= cond.get("min", 0) and (cond.get("max") is None or n <= cond["max"])
        if op == "absent":
            return not hits
        print(f"[场景判断] 未知条件 op='{op}', 按 MISS")
        return False

    def judge_scene(self, name: str, img=None, min_score: float = 0.4,
                    quiet: bool = False) -> bool:
        """按 flows/common/scenes.json 注册表判定当前画面是否为指定场景(第三种判定)。
        判定条件 = 注册表里该场景的 rule 条件树(JSON 声明式, 改条件不动代码, ops 见类头注释);
        旧版简写(markers/any_of/min_total)自动编译为等价条件树。未注册场景按 MISS(不抛错)。

        quiet=True(2026-10-24 P2-5): 不打印逐次判定行, 只累加 `scene_quiet_n`。
        仅用于**轮询/重试循环内的常态负判定**(如等进园时每秒探一次「好友列表」),
        由调用方的汇总行保留信息; 一次性判定(如 ensure_home)仍应 quiet=False。
        """
        entry = self._scenes.get("scenes", {}).get(name)
        if not entry:
            print(f"[场景判断] 场景『{name}』未在 scenes.json 注册, 按 MISS")
            return False
        img = img if img is not None else self.screenshot()
        if img is None:
            return False
        rule = entry.get("rule") or self._compile_legacy_scene(entry)
        self._ocr_stat["scene_calls"] += 1   # O0: 场景判定调用次数(含帧缓存命中)
        # E1(2026-10-27): 场景条目可选 region_rel —— 该场景锚点集中的固定条带, 区域化省全图
        blocks = self._scene_blocks(img, min_score, entry.get("region_rel"))
        hits = self._kw_hits(blocks, self._rule_kws(rule))
        ok = self._eval_rule(rule, blocks)
        if quiet:
            self._ocr_stat["scene_quiet_n"] = self._ocr_stat.get("scene_quiet_n", 0) + 1
        else:
            print(f"[场景判断] {name}: 命中{len(hits)}处{sorted(hits)} -> {'HIT' if ok else 'MISS'}")
        return ok

    # ---- 用户配置 (data/config.json) ----
    def _load_config(self) -> dict:
        """加载用户配置 (data/config.json)。流程 JSON 中可用 ${key} 占位符引用配置值,
        例如 ${target_tail} -> config["target_tail"]。缺失字段返回空字符串。"""
        cfg = {}
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, encoding="utf-8") as fp:
                    data = json.load(fp)
                    if isinstance(data, dict):
                        cfg = {k: v for k, v in data.items() if not k.startswith("_")}
        except Exception as e:
            print(f"[配置加载失败] {e}")
        return cfg

    def _save_config(self) -> None:
        """把 self.config 写回 data/config.json (合并注释字段除外)。"""
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, encoding="utf-8") as fp:
                    data = json.load(fp)
        except Exception:
            data = {}
        for k, v in self.config.items():
            data[k] = v
        with open(CONFIG_PATH, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=4)

    def update_config(self, **kwargs) -> None:
        """更新配置项并持久化。例如 update_config(enable_switch=True, target_tail="61")。"""
        self.config.update(kwargs)
        self._save_config()

    def resolve(self, val):
        """把字符串中的 ${key} 占位符替换为配置值; 非字符串或未含占位符则原样返回。"""
        if isinstance(val, str) and "${" in val:
            def _repl(m):
                key = m.group(1)
                if key not in self.config:
                    print(f"[配置] 提示: 配置键 '{key}' 未定义, 使用空值")
                return str(self.config.get(key, ""))
            return re.sub(r"\$\{(\w+)\}", _repl, val)
        return val

    # ---- 关闭按钮特殊逻辑注册表 ----
    def _load_close_buttons(self) -> list:
        """加载『关闭按钮-特殊逻辑』注册表 (data/close_buttons.json)。
        每个条目是一种关闭按钮的定位逻辑; 找关闭按钮时会依次遍历。
        """
        try:
            if CLOSE_BUTTONS_PATH.exists():
                with open(CLOSE_BUTTONS_PATH, encoding="utf-8") as fp:
                    data = json.load(fp)
                    if isinstance(data, list):
                        return data
        except Exception as e:
            print(f"[关闭按钮注册表加载失败] {e}")
        return []

    def _save_close_buttons(self) -> None:
        CLOSE_BUTTONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CLOSE_BUTTONS_PATH, "w", encoding="utf-8") as fp:
            json.dump(self.close_buttons, fp, ensure_ascii=False, indent=2)

    def register_close_button(self, new_entry: dict) -> None:
        """新增/更新一种关闭按钮特殊逻辑到注册表 (按 name 去重) 并持久化。"""
        for i, e in enumerate(self.close_buttons):
            if e.get("name") == new_entry.get("name"):
                self.close_buttons[i] = new_entry
                break
        else:
            self.close_buttons.append(new_entry)
        self._save_close_buttons()
        print(f"[注册表] 已保存关闭按钮特殊逻辑: {new_entry.get('name')}")

    # ---- 点击日志 (持久化知识库) ----
    # 磁盘格式(version 2, 两层嵌套): {"version":2, "scenes": {场景名: {按钮名: {记录, "category":类别}}}}
    # 兼容: 旧扁平格式 {"按钮名": {记录}} 加载时自动收敛到 "未分类" 场景。
    @staticmethod
    def _build_flat_index(scenes: dict) -> dict[str, dict]:
        """把场景嵌套结构收敛为 按钮名->记录 扁平索引(跨场景同名取最后一个)。"""
        flat: dict[str, dict] = {}
        for scene, buttons in scenes.items():
            for name, entry in buttons.items():
                flat[name] = entry
        return flat

    def _load_click_log(self) -> dict[str, dict[str, dict]]:
        """加载知识库并转为 场景->按钮->记录 两级嵌套。旧扁平格式自动归入「未分类」。"""
        try:
            if CLICK_LOG_PATH.exists():
                with open(CLICK_LOG_PATH, encoding="utf-8") as fp:
                    data = json.load(fp)
                if isinstance(data, dict):
                    if "scenes" in data and isinstance(data["scenes"], dict):
                        return data["scenes"]
                    # 旧扁平格式: 每条记录若有 scene 字段则按其归组, 否则归「未分类」
                    scenes: dict[str, dict[str, dict]] = {}
                    for name, entry in data.items():
                        sc = (entry or {}).get("scene") or "未分类"
                        scenes.setdefault(sc, {})[name] = entry
                    return scenes
        except Exception as e:
            print(f"[点击日志加载失败] {e}")
        return {}

    def _save_click_log(self) -> None:
        CLICK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CLICK_LOG_PATH, "w", encoding="utf-8") as fp:
            json.dump({"version": 2, "scenes": self.click_log_scenes}, fp,
                      ensure_ascii=False, indent=2)

    def _log_click(self, name: str, keywords, pt: "Point", method: str,
                   scene: str | None = None, category: str | None = None) -> None:
        """记录一次成功点击: 按钮名 + 文本 + 相对坐标 + 绝对坐标, 按场景分组存储。
        scene 缺省用 self._scene; 同场景同名按钮只保留一次(跨场景互不覆盖)。
        旧条目中人工标注的扩展字段(anchor/color/scene/note/category)会被保留, 不被自动日志覆盖。
        全局开关 `log_click_pos`(data/config.json, **默认 false**) 关闭时本方法直接返回, 不做任何记录:
        历史坐标一旦写错会被回退链放大成系统性误点(2026-10-03「切换账号」误登录), 故默认不记。
        注意: 只 gate「引擎运行时的自动记录」; 人工标注(`/tpltool` 提交后写库)或直接编辑
        `data/click_log.json` 是显式动作, 不受此开关影响。
        """
        if not self.config.get("log_click_pos", False):
            # 全局开关「记录按钮位置」(log_click_pos) 默认关闭: 运行时不再把点到的坐标写入知识库
            # data/click_log.json。历史坐标一旦写错, 会被回退链反复放大成系统性误点
            # (2026-10-03「切换账号」误登录即此链路), 故默认不记 —— 由用户显式开启后再积累样本。
            # 注意: 只 gate「运行时自动记录」; 人工标注/直接编辑 click_log.json 是用户显式动作, 不受此开关影响。
            # 提示只打印一次: 每次点击都刷一行会把日志淹掉(性能/可读性)。
            if not getattr(self, "_logpos_notice_done", False):
                self._logpos_notice_done = True
                print("[记录] 记录按钮位置已关闭(log_click_pos=false), 运行时点击坐标不写入知识库(本提示只打一次)")
            return
        kws = keywords if isinstance(keywords, list) else [keywords]
        sc = scene or self._scene or "未分类"
        old = (self.click_log_scenes.get(sc) or {}).get(name) or {}
        # 缓存回退(fallback)不产生新位置证据 → 一律不落库。
        # 曾只挡「已有 ocr/color/anchor 条目」的情形；旧条目本身就是 fallback 时会再次写入, 错坐标被固化并
        # 自我强化：2026-10-03 日志里「切换账号」正是被历史 fallback 坐标(0.7727,0.3944) 盲点到「登录」,
        # 误登录后公告/进入游戏/收尾守卫全部空转。回退坐标永远不是位置证据, 不得据以续传。
        if method == "fallback":
            kept = f"(已有 {old['method']} 条目, 其位置证据保留不变)" if old else "(本场景无既有条目, 不新建)"
            print(f"[记录] 按钮[{name}] 本次为缓存回退, 不产生新位置证据, 不落库 {kept}")
            return
        entry = {
            "name": name,
            "text": kws,
            "rel": [round(pt.rel[0], 4), round(pt.rel[1], 4)],
            "method": method,  # ocr / color / anchor / fallback
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        for k in ("anchor", "color", "scene", "note", "category"):
            if k in old:
                entry[k] = old[k]
        if scene is not None:
            entry["scene"] = scene
        elif "scene" not in entry and self._scene != "未分类":
            entry["scene"] = self._scene
        # 方案②: 立体化分级 + 均值累积。仅「整体相对坐标」定位(ocr/color)的命中纳入均值样本
        # (锚点-像素偏移属固定尺寸界面, 整体相对坐标不可比; fallback 是缓存回退, 不产生新位置证据)。
        if method in ("ocr", "color"):
            old_n = int(old.get("sample_n", 0) or 0)
            old_mean = old.get("mean_rel")
            rel = entry["rel"]
            if old_n > 0 and old_mean:
                m = old_n + 1
                entry["mean_rel"] = [round((old_mean[0] * old_n + rel[0]) / m, 4),
                                     round((old_mean[1] * old_n + rel[1]) / m, 4)]
                entry["sample_n"] = m
            else:
                entry["mean_rel"] = list(rel)
                entry["sample_n"] = 1
        entry.setdefault("category", category or self.auto_category(name))
        self.click_log_scenes.setdefault(sc, {})[name] = entry
        self.click_log[name] = entry  # 同步扁平索引, 兼容既有查找回退链
        self._save_click_log()
        tail = f" 均值{entry['mean_rel']}(样本{entry.get('sample_n',1)})" if "mean_rel" in entry else ""
        print(f"[记录] [{sc}] 按钮[{name}] 相对{entry['rel']}{tail} 已存入 {CLICK_LOG_PATH.name}")

    def set_scene(self, name: str, quiet: bool = False) -> None:
        """**显式声明**当前所处界面场景, 之后的点击记录/均值复核都归到这个场景。

        为什么需要这个 public 接口: `self._scene` 原本只在三处被改写 —— flow 的 "scene" 字段、
        单步骤的 "scene" 字段、以及 navigate 命中进入时置为目标场景。**没有任何地方会在界面
        真的切换后复位**, 于是 `navigate(家族活动)` 把场景钉死在「家族活动界面」, 之后同模块里
        跑的好友采粉/社区点赞等操作全被误记进「家族活动界面」(实测 63 次误归)。
        → 由 pollin/community_like 这类"自己会换界面"的子模块在切换点调用本方法声明场景。
        """
        if name and name != self._scene:
            self._scene = name
            if not quiet:
                print(f"[场景] -> {name}")

    # ---- 方案②: 立体化分级 + 均值 + 偏差复核 ----
    def _entry_for(self, name: str) -> dict | None:
        """按当前场景优先取知识库条目(场景分组), 场景未收录时回退扁平索引(跨场景同名取最新)。"""
        sc = self._scene
        if sc:
            e = (self.click_log_scenes.get(sc) or {}).get(name)
            if e is not None:
                return e
        return self.click_log.get(name)

    @staticmethod
    def _bias_px(pt: "Point", mean_rel, w: int, h: int) -> float | None:
        """计算命中点与历史均值点的欧氏像素偏差; 无均值返回 None。"""
        if not mean_rel:
            return None
        dx = pt.x - int(mean_rel[0] * w)
        dy = pt.y - int(mean_rel[1] * h)
        return (dx * dx + dy * dy) ** 0.5

    def _refine_hit(self, keywords, pt: "Point", img) -> "Point | None":
        """二次更精细处理: 以命中点为中心局部截图, 放大 2x 重识别关键字(近似 find_text 的过宽块拆分),
        返回与均值更吻合的精确子块中心; 无结果返回 None。用于 OCR 命中点偏差过大时校准, 避免点整块中心误触邻钮。
        """
        try:
            import cv2
            x1 = max(0, pt.x - 60); y1 = max(0, pt.y - 40)
            x2 = min(self.screen_w, pt.x + 60); y2 = min(self.screen_h, pt.y + 40)
            crop = img[y1:y2, x1:x2]
            if crop.size == 0:
                return None
            big = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            kws = keywords if isinstance(keywords, list) else [keywords]
            for b in ocr_image(big):
                text = b.get("text", "")
                if any(kw in text for kw in kws):
                    ox = int(b["center"][0] / 2) + x1
                    oy = int(b["center"][1] / 2) + y1
                    return Point(ox, oy, self.screen_w, self.screen_h)
        except Exception as e:
            print(f"[复核] 局部重识别失败: {e}")
        return None

    @staticmethod
    def auto_category(name: str) -> str:
        """按按钮名语义自动推断功能类别(导航/作业/活动/账号/弹窗/关闭按钮/状态/其他)。"""
        if "关闭" in name:
            return "关闭按钮"
        if name in ("家园", "菜单", "社交", "世界", "家族", "离开"):
            return "导航"
        if name in ("在线礼包", "花灵派对", "家族活动", "摇钱树", "签到", "点击签到",
                    "矿洞探险", "闪耀委托挑战", "守望兔子", "花香垂钓", "花仙乐园"):
            return "活动"
        if name in ("切换账号", "登录", "点击进入游戏"):
            return "账号"
        if name in ("恭喜获得", "点击任意处关闭", "确定", "确认", "弹窗关闭", "提示"):
            return "弹窗"
        if any(k in name for k in ("领取", "抽奖", "投喂", "采集")):
            return "作业"
        if name in ("浇水", "施肥", "收花", "授粉", "开花", "清理", "照料",
                    "一键种植", "种植箱", "快捷操作", "造型种植", "随机种植",
                    "速通", "光偶像"):
            return "作业"
        if any(k in name for k in ("/", "：")):
            return "状态"
        return "其他"


    # ---- 设备 ----
    def connect(self) -> bool:
        from maa.controller import AdbController
        from maa.toolkit import Toolkit

        Toolkit.init_option("./")
        ctrl = AdbController(adb_path=self.adb_path, address=self.address)
        ctrl.post_connection().wait()
        if not ctrl.connected:
            print("[错误] 连接失败")
            return False
        self._ctrl = ctrl
        self.debug_click = bool(os.environ.get("FAA_DEBUG_CLICK", ""))
        self._click_seq = 0
        if self.debug_click:
            self.debug_dir = Path(__file__).parent / "data" / "click_debug"
            self.debug_dir.mkdir(parents=True, exist_ok=True)
        # 连接即读取画面尺寸(2026-10-06 用户要求, 2026-10-07 细化为两套):
        # ① 工作区(screen_w/h): MAA 首帧, 先清零再探, 重连/换模拟器必拿当前值, 供
        #    全部相对坐标运算使用(与 MAA 点击同空间, 自洽);
        # ② 实机分辨率(display_w/h): adb 原生截图直读(不经 MAA 长边缩放), 供 WebUI
        #    展示与用户多分辨率适配决策; 读取失败时置 0, WebUI 回退显示工作区。
        self.screen_w = 0
        self.screen_h = 0
        if self.screenshot() is not None:
            print(f"[连接] 引擎工作区: {self.screen_w}x{self.screen_h}")
        else:
            print("[连接] 警告: 连接后首帧截图失败, 工作区尺寸留待下次截图时读取")
        self.display_w, self.display_h = 0, 0
        try:
            import subprocess
            raw = subprocess.run(
                [self.adb_path, "-s", self.address, "exec-out", "screencap", "-p"],
                capture_output=True, timeout=15).stdout
            import cv2 as _cv2
            dimg = _cv2.imdecode(np.frombuffer(raw, np.uint8), _cv2.IMREAD_COLOR)
            if dimg is not None:
                self.display_h, self.display_w = dimg.shape[:2]
        except Exception as e:
            print(f"[连接] 实机分辨率直读失败(仅影响显示, 不影响运行): {e}")
        if self.display_w:
            tag = " (MAA 长边缩放)" if self.display_w != self.screen_w or self.display_h != self.screen_h else ""
            print(f"[连接] 实机分辨率: {self.display_w}x{self.display_h} / 引擎工作区: {self.screen_w}x{self.screen_h}{tag}")
        else:
            print(f"[连接] 实机分辨率未读到, 显示回退引擎工作区 {self.screen_w}x{self.screen_h}")
        return True

    def screenshot(self) -> np.ndarray | None:
        """截图, 并记录当前屏幕尺寸。返回 BGR ndarray。
        同时记录最近一帧 last_frame/last_frame_ts, 供 WebUI 预览在流程运行期直接复用
        (见 webui._screen) —— 引擎本就连续截图, 预览不再自己截, 消除两者对 ADB 控制器的争抢。
        """
        img = self._ctrl.post_screencap().wait().get()
        if img is None:
            return None
        # img shape = (H, W, 3)
        self.screen_h, self.screen_w = img.shape[:2]
        self.last_frame = img
        self.last_frame_ts = time.monotonic()
        return img

    def click_abs(self, x: int, y: int) -> None:
        if getattr(self, "debug_click", False):
            self._snapshot_click(int(x), int(y))
        self._ctrl.post_click(int(x), int(y)).wait()
        print(f"[点击] 绝对({x},{y})")

    def _snapshot_click(self, x: int, y: int) -> None:
        """调试: 点击前截图, 用红框标注点击点并保存, 便于逐帧核对点击区域。"""
        try:
            img = self.screenshot()
            if img is None:
                return
            import cv2
            img = img.copy()
            cv2.rectangle(img, (x - 25, y - 25), (x + 25, y + 25), (0, 0, 255), 2)
            cv2.circle(img, (x, y), 5, (0, 0, 255), -1)
            self._click_seq += 1
            fp = self.debug_dir / f"click_{self._click_seq:03d}_({x}_{y}).png"
            cv2.imwrite(str(fp), img)
            self._last_snapshot = fp
            print(f"[截图] 点击区域已保存 -> {fp.name}")
        except Exception as e:
            print(f"[截图调试] 失败: {e}")

    def click_rel(self, rx: float, ry: float) -> None:
        """按相对坐标点击 (自适应屏幕尺寸)。
        若屏幕尺寸未知(尚未截图)则先截图获取; 避免相对坐标算成 (0,0)。
        """
        if not self.screen_w or not self.screen_h:
            self.screenshot()
        if not self.screen_w or not self.screen_h:
            print("[点击] 相对坐标失败: 屏幕尺寸未知")
            return
        x = int(rx * self.screen_w)
        y = int(ry * self.screen_h)
        print(f"[点击] 相对({rx:.3f},{ry:.3f}) -> 绝对({x},{y})")
        self.click_abs(x, y)

    def swipe_rel(self, rx1: float, ry1: float, rx2: float, ry2: float,
                  duration_ms: int = 300) -> None:
        """按相对坐标执行滑动手势(滚屏/拖动, 2026-10-06 方案一引入, 供好友列表底行补救等)。
        ⚠ 规则6边界(2026-10-06 用户裁定): 滑动是**手势动作**, 没有「识别目标」可定位 ——
        起终点是手势参数而非点击坐标, 用相对坐标随分辨率自适应, 不属被禁的『直接坐标点击』;
        点击类操作仍必须 OCR/template/场景识别实时定位后才进行。
        屏幕尺寸未知时先截图获取, 避免换算成 (0,0)。
        """
        if not self.screen_w or not self.screen_h:
            self.screenshot()
        if not self.screen_w or not self.screen_h:
            print("[滑动] 失败: 屏幕尺寸未知")
            return
        x1, y1 = int(rx1 * self.screen_w), int(ry1 * self.screen_h)
        x2, y2 = int(rx2 * self.screen_w), int(ry2 * self.screen_h)
        self._ctrl.post_swipe(x1, y1, x2, y2, int(duration_ms)).wait()
        print(f"[滑动] 相对({rx1:.3f},{ry1:.3f})->({rx2:.3f},{ry2:.3f}) "
              f"绝对({x1},{y1})->({x2},{y2}) {duration_ms}ms")

    def back(self) -> bool:
        """发送 Android 返回键 (adb shell input keyevent 4)。用于关闭弹窗/返回上一级。
        返回 True/False。失败时回退点击屏幕左上角。
        """
        import subprocess
        try:
            # 尝试用 adb 命令行发 keyevent (返回键 code=4)
            subprocess.run(
                [self.adb_path, "-s", self.address, "shell", "input", "keyevent", "4"],
                capture_output=True, timeout=5, check=True,
            )
            print("[back] 已发送返回键 keyevent=4")
            return True
        except Exception as e:
            print(f"[back] adb keyevent 失败({e}), 回退点击左上角")
            self.click_abs(20, 20)
            return False

    # ---- OCR 定位 ----
    @staticmethod
    def _frame_hash(img) -> "bytes | None":
        """静态帧指纹: 画面像素完全一致则指纹一致。1280x720 实测 ~3ms, 远低于一次全屏 OCR。"""
        try:
            return hashlib.blake2b(img.tobytes(), digest_size=16).digest()
        except Exception:
            return None

    def locate_fine(self, kws, region_rel, upscale=2, min_score=0.4,
                    img=None, exact=False, exclude=None) -> "Point | None":
        """滤色精识: 对 region_rel 小区域「裁剪 → 放大 → 白字滤色 → OCR」定位关键字。

        背景(2026-10-06, 用户方案): 小花仙按钮为统一白字彩底, 部分好友花园的紫/蓝底会把
        常规 OCR 置信度压到阈值以下造成整词 MISS(当日日志: 好友花园「社交」110 次尝试
        0 命中, 10 页采粉全部放弃)。滤色 = 提取高亮低饱和像素(白字)转黑字白底, 彩底噪声
        全部归零, 与按钮「色调统一」的美术规格正好互补。
        开销约束(用户要求不加重性能/内存): 只在调用方常规定位未命中后对小裁片运行,
        一次小图推理毫秒级, 不做全图二次扫描; 中间数组为瞬态小裁片; 命中路径零额外开销。
        返回坐标已映射回全图绝对像素; 未命中返回 None。"""
        import cv2
        img = img if img is not None else self.screenshot()
        if img is None:
            return None
        H, W = img.shape[:2]
        x1 = max(0, int(region_rel[0] * W)); y1 = max(0, int(region_rel[1] * H))
        x2 = min(W, int(region_rel[2] * W)); y2 = min(H, int(region_rel[3] * H))
        if x2 <= x1 or y2 <= y1:
            return None
        crop = img[y1:y2, x1:x2]
        crop = cv2.resize(crop, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        white = cv2.inRange(hsv, (0, 0, 170), (180, 70, 255))  # 高亮 + 低饱和 → 白字
        binimg = np.full(crop.shape[:2], 255, np.uint8)
        binimg[white > 0] = 0                                  # 黑字白底(OCR 友好)
        kws = kws if isinstance(kws, list) else [kws]
        exclude = exclude or []
        best = None
        for b in ocr_image(cv2.cvtColor(binimg, cv2.COLOR_GRAY2BGR)):
            if b.get("score", 1) < min_score:
                continue
            t = b.get("text", "").strip()
            if not any(((t == kw) if exact else (kw in t)) for kw in kws):
                continue
            if any(e in t for e in exclude):
                continue
            bx = b["box"]
            cx = int((bx[0] + bx[2]) / 2 / upscale) + x1
            cy = int((bx[1] + bx[3]) / 2 / upscale) + y1
            if best is None or b["score"] > best[0]:
                best = (b["score"], Point(cx, cy, W, H))
        if best:
            print(f"[精识] {kws} 滤色放大命中 score={best[0]:.2f} "
                  f"@({best[1].x},{best[1].y}) region={region_rel}")
            return best[1]
        return None

    def _ocr_frame(self, img, need_split: bool = True) -> tuple[list, list]:
        """对一帧做全图 OCR(+ 可选过宽块 2x 拆分), 同一静态帧(指纹一致)直接复用上次结果。

        性能(2026-10-03, 长期目标 §11.3-2「同一静态帧内的重复 OCR 必须复用」): wait_text 每个轮询周期、
        相邻步骤(if_text 判断后紧跟 click_text)都会对**画面未变**的帧反复全屏 OCR, 每次实测烧 ~13 核 × 400ms。
        这里对帧内容做 blake2b 指纹: 指纹一致 → 复用; 画面一变指纹失效 → 自动重新识别,
        语义与逐次 OCR 完全一致(等待变化的循环不会被陈旧结果卡住 —— 变了指纹必然变)。
        返回 (全图文字块, 过宽块拆出的精确子块)。

        O1(2026-10-21): **拆分改为按需**。`judge_scene` 只读 blocks[0]、从不使用子块, 却让整帧所有
        过宽块都做 2× 重识别 —— social 单轮实测拆分 1093s(占模块 41%), 其中场景判断这一支纯浪费。
        现在: `need_split=False` 时只做全图 OCR; 帧缓存先存 blocks、子块置 None(未算);
        同一帧后续若需要坐标精度(点击)再补算一次并写回缓存 —— 同帧仍只拆一次, 语义零变化。
        """
        sig = self._frame_hash(img)
        if sig is not None:
            with self._frame_lock:
                if sig == self._frame_sig:
                    self._ocr_stat["hit_n"] += 1
                    blocks_c, subs_c = self._frame_cache
                else:
                    blocks_c = subs_c = None
            if blocks_c is not None:
                if need_split and subs_c is None:
                    # 命中缓存但子块未算(O1 惰性): 补算一次; 若期间帧已变则不写回, 防止串帧
                    subs_c = self._split_wide(img, blocks_c)
                    with self._frame_lock:
                        if sig == self._frame_sig:
                            self._frame_cache = (blocks_c, subs_c)
                return blocks_c, (subs_c or [])
        blocks = self._timed_ocr(img, "full")
        sub_blocks = self._split_wide(img, blocks) if need_split else None
        if sig is not None:
            with self._frame_lock:
                self._frame_cache = (blocks, sub_blocks)
                self._frame_sig = sig
        return blocks, (sub_blocks or [])

    def _timed_ocr(self, img, kind: str):
        """批C-②: 带 OCR 计时统计的 ocr_image 封装。kind: full(全图)/region(区域裁片)/split(2x拆分)。
        计时为纯观测, 不改行为; 缓存命中不经过本函数(由各缓存点自行计 hit_n)。
        O0(2026-10-21): 同时按 self._ocr_src(当前步骤/内部模块) 计数, 用于回答“谁花的这笔时间”。"""
        t0 = time.perf_counter()
        blocks = ocr_image(img)
        self._ocr_stat[kind + "_n"] += 1
        self._ocr_stat[kind + "_t"] += time.perf_counter() - t0
        d = self._ocr_stat["by_src"].setdefault(kind, {})
        d[self._ocr_src] = d.get(self._ocr_src, 0) + 1
        return blocks

    def ocr_direct(self, img, src: str = "direct"):
        """流程外的直调 OCR(供 pollin 的页码/诊断等): 计入 direct 统计并按 src 归属。
        与 _timed_ocr 的区别仅在于 kind=direct —— 不会混进“全图/区域”口径, 避免低估问题被掩盖。"""
        prev = self._ocr_src
        self._ocr_src = src
        try:
            return self._timed_ocr(img, "direct")
        finally:
            self._ocr_src = prev

    def _split_wide(self, img, blocks):
        """过宽块(宽>90) 2x 重识别拆分(批C 自 _ocr_frame 原样抽出, 全图/区域化两路径共用)。
        返回精确子块列表; 拆分缓存键含裁片内 origin(批A 修订), 语义与原实现逐字节一致。"""
        sub_blocks: list = []  # 过宽块 2x 重识别拆出的精确子块, 点击定位时优先(点击点落到目标文字自身中心)
        for b in blocks:
            x1, y1, x2, y2 = b["box"]
            w = x2 - x1
            if w > 90:  # 过宽, 疑似合并(如「菜单/奇妙花宝」挤在一起): 放大重识别尝试拆出更精确的子按钮
                crop = img[max(0, y1 - 10):y2 + 10, max(0, x1 - 10):x2 + 10]
                if crop.size:
                    import cv2
                    # 拆分缓存(2026-10-07 性能批 zcode-20261007-15): 拆分环节实测 7.5~9.6s/帧
                    # (占单轮 OCR 60~85%), 而过宽块多为静态 UI 碎片逐帧原样重现却帧帧重拆。
                    # 按裁片像素指纹缓存拆分结果: 内容没变直接复用(等价幂等), 变了(跑马灯/滚动)
                    # 自动重拆 —— 行为与逐帧拆分完全一致。命中重插=简单 LRU 续期, 上限 400 条。
                    origin = (max(0, x1 - 10), max(0, y1 - 10))
                    # ⚠ 键必须含**裁片位置**（主 agent 修订, 里程碑 83）：缓存值存的是**全帧绝对坐标**
                    # (/2 + origin)，若同一像素内容出现在不同位置（重复 UI 元素 / 移动中的横幅，
                    # 且 10px 边距也恰好一致），纯像素键会把上一位置的**陈旧坐标**当结果复用 →
                    # 定位错误（正是本项目反复警惕的"陈旧坐标"类风险）。加入 origin 后只有
                    # 「同一位置 + 同内容」才复用：静态 UI 碎片照旧全命中（速收益不变），
                    # 移动/重复内容自动重拆（安全优先）。
                    key = (origin[0], origin[1],
                           hashlib.blake2b(np.ascontiguousarray(crop).tobytes(),
                                           digest_size=16).digest())
                    with self._split_lock:
                        cached = self._split_cache.get(key)
                        if cached is not None:
                            self._split_cache.pop(key)
                            self._split_cache[key] = cached
                    if cached is not None:
                        self._ocr_stat["split_cache_hit"] += 1   # O0: 缓存命中(无 OCR)
                        sub_blocks.extend(dict(nb) for nb in cached)
                        continue
                    big = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                    newly: list = []
                    for nb in self._timed_ocr(big, "split"):
                        ox = int(nb["center"][0] / 2) + max(0, x1 - 10)
                        oy = int(nb["center"][1] / 2) + max(0, y1 - 10)
                        nb2 = dict(nb)
                        nb2["center"] = [ox, oy]
                        nb2["box"] = [int(nb["box"][0] / 2) + max(0, x1 - 10),
                                      int(nb["box"][1] / 2) + max(0, y1 - 10),
                                      int(nb["box"][2] / 2) + max(0, x1 - 10),
                                      int(nb["box"][3] / 2) + max(0, x1 - 10)]
                        newly.append(nb2)
                    with self._split_lock:
                        if len(self._split_cache) >= 400:
                            self._split_cache.pop(next(iter(self._split_cache)))
                        self._split_cache[key] = newly
                    sub_blocks.extend(dict(nb) for nb in newly)
        return sub_blocks

    def _ocr_frame_region(self, img, region_rel, need_split: bool = True):
        """批C-①: 区域化 OCR —— region 面积<=全图 40% 时只 OCR 裁片, 坐标映射回全图。
        返回 (blocks, sub_blocks)(全图坐标系) 或 None(调用方回退全图路径)。
        - pad 按 region 宽/高各 5% 外扩(用户 2026-10-11 裁定: 纯比例适配任意分辨率, 不用固定像素),
          保证贴边文字块完整进入裁片, 消除 det 边界截断;
        - 裁片 OCR 走独立 LRU(键=裁片像素指纹, 值=裁片相对坐标块), 不占用全图单槽帧缓存;
          拆分复用 _split_wide(其缓存键含裁片内 origin, 语义一致);
        - 语义: 调用方拿到块后照常执行原有区域过滤, 过滤语义与全图路径一致; 区域内未命中时
          由调用方回退一次全图 —— 区域化只省命中路径耗时, 不制造新 MISS。
        O2(2026-10-21): `need_split=False` 时跳过拆分子块(判断类调用); 缓存值用 None 表示“未算”,
          同一裁片后续需要坐标精度时再补算并写回 —— 与 _ocr_frame 的惰性策略一致。
        """
        w, h = self.screen_w, self.screen_h
        if not w or not h or img is None or len(region_rel) != 4:
            return None
        rx1, ry1 = int(region_rel[0] * w), int(region_rel[1] * h)
        rx2, ry2 = int(region_rel[2] * w), int(region_rel[3] * h)
        rw, rh = rx2 - rx1, ry2 - ry1
        if rw <= 0 or rh <= 0 or rw * rh > 0.4 * w * h:
            return None
        pad_x, pad_y = max(1, int(rw * 0.05)), max(1, int(rh * 0.05))
        cx1, cy1 = max(0, rx1 - pad_x), max(0, ry1 - pad_y)
        cx2, cy2 = min(w, rx2 + pad_x), min(h, ry2 + pad_y)
        crop = img[cy1:cy2, cx1:cx2]
        if crop.size == 0:
            return None
        sig = self._frame_hash(crop)
        cached = None
        if sig is not None:
            with self._region_lock:
                cached = self._region_cache.get(sig)
                if cached is not None:
                    self._region_cache.pop(sig)
                    self._region_cache[sig] = cached
        if cached is not None:
            self._ocr_stat["hit_n"] += 1
            # ⚠ 命中副本与存储副本必须分离: 下面要按当次 origin 重映射(键重绑定),
            # 若直接改缓存内字典, 第二次命中会叠加两次偏移(坐标错位) —— 测试 T2 实证。
            blocks = [dict(b) for b in cached[0]]
            subs_cached = cached[1]      # None = 未拆分(O2 惰性)
        else:
            blocks = self._timed_ocr(crop, "region")
            subs_cached = None
        if need_split and subs_cached is None:
            subs_cached = self._split_wide(crop, blocks)
            if sig is not None:
                with self._region_lock:
                    if sig in self._region_cache:
                        self._region_cache.pop(sig)
                    elif len(self._region_cache) >= 200:
                        self._region_cache.pop(next(iter(self._region_cache)))
                    # 存**原始副本**(未经映射); 每次返回另出映射副本(见下), 缓存内容永不带偏移
                    self._region_cache[sig] = ([dict(b) for b in blocks],
                                               [dict(b) for b in subs_cached])
            sub_blocks = [dict(b) for b in subs_cached]
        else:
            sub_blocks = [dict(b) for b in subs_cached] if subs_cached else []
            if cached is None and sig is not None:
                with self._region_lock:
                    if len(self._region_cache) >= 200:
                        self._region_cache.pop(next(iter(self._region_cache)))
                    self._region_cache[sig] = ([dict(b) for b in blocks], None)
        # 裁片相对坐标 -> 全图绝对坐标(映射用当次 origin, 缓存命中也重映射)
        for b in blocks + sub_blocks:
            b["center"] = [b["center"][0] + cx1, b["center"][1] + cy1]
            b["box"] = [b["box"][0] + cx1, b["box"][1] + cy1,
                        b["box"][2] + cx1, b["box"][3] + cy1]
        return blocks, sub_blocks

    def _ocr_candidates(self, img, region_rel, need_refine: bool = True):
        """批C-①: 判定入口共用的块获取。region 面积<=40% 且 region_ocr 开启时走区域化。
        返回 (blocks, sub_blocks, used_region); 区域路径零命中时由调用方回退全图。
        O2(2026-10-21): need_refine=False 时不做过宽块拆分(判断类只需布尔/计数)。"""
        if region_rel and len(region_rel) == 4 and self.config.get("region_ocr", True):
            r = self._ocr_frame_region(img, region_rel, need_split=need_refine)
            if r is not None:
                return r[0], r[1], True
        b, sb = self._ocr_frame(img, need_split=need_refine)
        return b, sb, False

    def _print_ocr_stat(self, mid):
        """批C-②: 模块级 OCR 计时汇总(纯观测), 并累计进整轮统计。
        O0(2026-10-21): 追加「来源 / 拆分缓存 / 仅子块命中 / 直调」三行, 用于把 44min 之类的耗时
        精确归因到步骤类型, 并为 O1/O2 提供前后对照基线。"""
        st = self._ocr_stat
        _stat_add(self._ocr_stat_total, st)
        print(f"[OCR统计] 模块 {mid}: 全图 {st['full_n']} 次 {st['full_t']:.2f}s · "
              f"区域 {st['region_n']} 次 {st['region_t']:.2f}s · 拆分 {st['split_n']} 次 {st['split_t']:.2f}s · "
              f"缓存命中 {st['hit_n']} 次")
        by = st.get("by_src") or {}

        def _fmt(kind, limit=8):
            d = by.get(kind) or {}
            if not d:
                return "-"
            items = sorted(d.items(), key=lambda kv: -kv[1])[:limit]
            return " · ".join(f"{k} {v}" for k, v in items)

        print(f"[OCR来源] 全图: {_fmt('full')}  |  区域: {_fmt('region')}  |  拆分: {_fmt('split')}")
        print(f"[OCR健康] 拆分缓存命中 {st['split_cache_hit']} 次 · 仅子块命中 {st['split_only_hit']} 次 · "
              f"场景判断 {st['scene_calls']} 次(折叠 {st.get('scene_quiet_n', 0)}) · "
              f"直调 {st['direct_n']} 次 {st['direct_t']:.2f}s "
              f"({_fmt('direct', 4)}) · 静默未命中 {st.get('miss_silent_n', 0)} 次(弹窗/启动守卫确认无)")
        cn = st.get("friend_coarse_n", 0)
        if cn:
            ch = st.get("friend_coarse_hit", 0)
            fn = st.get("friend_fine_n", 0)
            fh = st.get("friend_fine_hit", 0)
            total_ok = ch + fh
            total = cn
            print(f"[粗OCR] 社交面板「好友」: 粗识 {ch}/{cn} ({ch / cn:.0%}) · "
                  f"精识兜底 {fh}/{fn} ({(fh / fn if fn else 0):.0%}) · "
                  f"综合 {total_ok}/{total} ({(total_ok / total if total else 0):.0%})"
                  f"  ← 粗识成功率偏低时优先改进粗 OCR(用户 2026-10-24: 日志保留, 只统计)")

    # ---- 采集: dump_text (2026-10-12 每日任务/手账采集, 用户确认方案; 实机原型见协作区 v7/v8) ----
    def _group_task_rows(self, blocks):
        """行分组: 每个含 (a/b) 进度的块, 向上 Δy∈[0.01,0.09](屏高比) 找最近描述块配对。
        返回 [(desc_core, 'a/b', center_abs), ...] 按屏幕 y 排序; desc 去装饰前缀
        (·+*★?？!！~空白——实测这些符号 OCR 乱跳, 不可进指纹)。
        无进度的块不参与配对。2026-10-12 每日任务采集实机原型(协作区 v7/v8 两轮验证)。"""
        if not self.screen_w or not self.screen_h or not blocks:
            return []
        prog_re = re.compile(r"(\d+)\s*/\s*(\d+)")
        desc_re = re.compile(r"[\u4e00-\u9fff]")
        strip_re = re.compile(r"[·+*★?？!！~\s]")
        items = []
        for b in blocks:
            c = b.get("center")
            if not c and b.get("box"):
                box = b["box"]
                c = [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]
            if not c:
                continue
            items.append((b.get("text", ""), c[0] / self.screen_w, c[1] / self.screen_h, b, c))
        rows = []
        for text, rx, ry, b, c in items:
            m = prog_re.search(text)
            if not m:
                continue
            best = None
            for t2, rx2, ry2, b2, c2 in items:
                if b2 is b or not desc_re.search(t2) or prog_re.search(t2):
                    continue
                dy = ry - ry2
                if 0.01 <= dy <= 0.09 and 0.45 <= rx2 <= 0.85:
                    if best is None or dy < best[0]:
                        best = (dy, t2)
            core = strip_re.sub("", best[1]) if best else "?"
            rows.append((core, f"{int(m.group(1))}/{int(m.group(2))}", (c[0], c[1])))
        rows.sort(key=lambda r: r[2][1])
        return rows

    @staticmethod
    def _merge_rows(acc: list, rows: list) -> None:
        """把本屏行分组并入「本次采集」的累计列表 (按 (desc, progress) 去重, 先见先留, 保持上→下顺序)。

        v2.1(2026-10-17): 修复 _last_dump 曾**每轮覆盖**的丢行缺陷 —— 每日任务点赞门槛
        (if_collected 查「献上点赞」) 因内存只剩**末屏**行而查不到中段行, 点赞被误跳过
        (2026-10-16 日志实锤: 第 4 轮屏幕采到「为精美搭配献上点赞吧=0/2」, 8 轮扫到底后
        if_collected 判「命中行=None」走 else)。
        作用域(须与文档一致): acc 与 _last_dump[label] 均为**单次采集调用**的跨屏累计,
        调用开始时重置(防同进程重复调用残留旧行, 如循环跑第二次时把已完成任务误判为未完成);
        _write_collect 留档仍按**每屏**原样写入, 不受本合并影响。
        已知限制(观察项 O1, 暂不处理): OCR 对同一任务文字的轻微变体(尾标点/近形字)会使
        (desc, progress) 不完全相等而各留一条 -> 同一任务可能重复入列; 查询按先见序取第一条,
        对现有点赞门槛无影响; 若后续有按行计数用途再定模糊归并方案(见本批 REPORT 观察列表)。
        """
        seen = {(d, p) for d, p, _c in acc}
        for d, p, c in rows:
            if (d, p) not in seen:
                seen.add((d, p))
                acc.append((d, p, c))

    def _dump_text(self, step: dict) -> None:
        """dump_text 采集步骤: 区域 OCR → (可选)行分组 → [采集] 日志 + data/collect/<save>.jsonl。
        可选 scroll 滚动采集: 内部手势滑动(规则6边界: 手势参数非点击坐标, 2026-10-06 用户
        裁定沿用; 700ms 慢滑——400ms 实测被游戏/输入链吞掉致假冻结), 以「行分组指纹」连续
        两屏一致判列表到底(内容锚定, 免疫滚动位移/装饰噪声/动画闪烁)。
        页签守卫在 tab_region_rel 小区域独立检测——页签通常在采集区域外, 守卫不可复用采集区
        文本(2026-10-12 实机踩坑)。只读采集: 本步骤不点击任何业务按钮。参数:
          region_rel=[x1,y1,x2,y2] 采集区; label 日志标签; save jsonl 文件名(可省);
          row_pair=true 启用行分组; tab_region_rel+tab_variants 页签守卫;
          scroll={swipe:[x1,y1,x2,y2], duration_ms=700, settle=1.8, max_rounds=18}。"""
        region_rel = step.get("region_rel")
        label = step.get("label", "dump")
        save = step.get("save")
        use_pair = bool(step.get("row_pair"))
        tab_region = step.get("tab_region_rel")
        tab_vars = step.get("tab_variants") or []
        scroll = step.get("scroll") or {}
        max_rounds = max(1, int(scroll.get("max_rounds", 1)))
        settle = float(scroll.get("settle", 1.8))
        swipe = scroll.get("swipe")
        dur = int(scroll.get("duration_ms", 700))
        acc_rows: list = []                     # v2.1: 本次调用的跨屏累计行(供 _last_dump/if_collected)
        self._last_dump[label] = acc_rows       # 重置: 本 label 以本次采集为准(防跨次调用残留)
        prev_fp = None
        for round_no in range(1, max_rounds + 1):
            self._check_stop()
            img = self.screenshot()
            if img is None:
                print(f"[采集] {label}: 第{round_no}轮截图失败, 如实停止")
                return
            if tab_region and tab_vars:
                # O2: 页签守卫只需布尔 -> 不拆分
                tb, _sub, _used = self._ocr_candidates(img, tab_region, need_refine=False)
                if not any(v in b.get("text", "") for b in tb for v in tab_vars):
                    print(f"[采集] {label}: 第{round_no}轮页签守卫 MISS(变体={tab_vars}), 如实停止")
                    return
            # O2: 行分组只用 blocks(不看子块) -> 不拆分
            blocks, _sub, _used = self._ocr_candidates(img, region_rel, need_refine=False)
            rows = self._group_task_rows(blocks) if use_pair else []
            self._merge_rows(acc_rows, rows)    # v2.1: 跨屏累计(供 if_collected; 修复曾只留末屏)
            fp = frozenset((d, p) for d, p, _c in rows) if use_pair else None
            print(f"[采集] {label} 第{round_no}轮: 块{len(blocks)} 行{len(rows)}"
                  + (f" (累计 {len(acc_rows)})" if use_pair else "")
                  + (" " + "; ".join(f"{d}={p}" for d, p, _c in rows) if rows else ""))
            if save:
                self._write_collect(save, label, round_no, rows, blocks)
            if not swipe:
                return                       # 单发模式: 一轮即止
            if prev_fp is not None and fp == prev_fp:
                print(f"[采集] {label}: 连续两屏行分组指纹一致 -> 列表到底(共 {round_no} 轮)")
                return
            prev_fp = fp
            self.swipe_rel(*swipe, duration_ms=dur)
            time.sleep(settle)
        print(f"[采集] {label}: 达到 max_rounds={max_rounds} 上限仍未稳定, 如实登记")

    def _write_collect(self, save, label, round_no, rows, blocks):
        """采集留档: 追加 data/collect/<save>.jsonl(ts/label/round/rows/blocks 全量)。
        dump_text 与 claim_scroll 共用(2026-10-12 v2 抽取)。"""
        try:
            out_dir = Path(__file__).parent / "data" / "collect"
            out_dir.mkdir(parents=True, exist_ok=True)
            rec = {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "label": label, "round": round_no,
                "screen": [self.screen_w, self.screen_h],
                "rows": [{"desc": d, "progress": p,
                          "rel": [round(c[0] / self.screen_w, 4),
                                  round(c[1] / self.screen_h, 4)]}
                         for d, p, c in rows],
                "blocks": [{"text": b.get("text", ""),
                            "score": round(float(b.get("score", 1.0)), 3),
                            "rel": [round(b["center"][0] / self.screen_w, 4),
                                    round(b["center"][1] / self.screen_h, 4)]}
                           for b in blocks if b.get("center")],
            }
            with open(out_dir / f"{save}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError as e:
            print(f"[采集] {label}: jsonl 写入失败(不影响流程): {e}")

    # ---- 领取成功界面 (2026-10-20 D13, 方案A): 统一判定原语 ----
    # 背景(用户 2026-10-19 裁定 + 本轮日志实证): 全项目共 13 处「点领取 -> 关成功弹窗」,
    #   写成 5 种不同样子, 且**没有一处判断"是否真的领取成功"** —— 多是"点领取返回 ok 就当成功"。
    #   实证: `[OCR未命中]['恭喜获得']` 27 次 / `[if_text]['恭喜获得'] -> MISS` 6 次, 甚至在活动列表
    #   画面也去查成功弹窗 => 「点击成功」≠「真领取到」。且多数落点把**页脚**「点击任意处关闭」当关闭点,
    #   弹窗已消失时会**点击穿透**到底层 UI(矿洞页曾误开「我的背包」)。
    # 本原语统一三件事: ①判据(标题或页脚在屏=成功界面出现) ②收尾(标题优先点击, 页脚仅兜底)
    #   ③上报(未见/关不掉如实 print, required=true 时登记软失败)。范式取自 pollin.dismiss_reward_popup。
    REWARD_TITLE_KW = "恭喜获得"
    REWARD_FOOTER_KW = "点击任意处关闭"
    # 性能批 zcode-20261028-9(两段式区域化): 默认搜索带(相对坐标 [x1,y1,x2,y2], 0~1)。
    # 依据=三源实测落点一致:「恭喜获得」rel(0.499,0.237) —— 10-27 日志「领取成功界面 @(639,171)」
    # 与 _recon_daily/v9_popup.png (0.499,0.237)、v10_like_popup.png (0.500,0.239);
    # 「点击任意处关闭」rel(0.500,0.938) —— v9/v10 两帧一致。标题带面积 0.70*0.30=0.21、
    # 页脚带面积 0.60*0.15=0.09, 均满足批C 区域化闸门(<=0.40, 见 _ocr_frame_region)。
    # ⚠ 收益重估(离线实测, 证据见本批 evidence/): 本项目 det 固定 rapidocr 默认
    #   limit_side_len=736/limit_type=min(venv 内 rapidocr_onnxruntime/config.yaml),
    #   短边<736px 的宽扁裁片会先被**反向放大**再进 det —— 标题带裁片(984x236→约3069x736)
    #   耗时≈全图的 0.8~0.95 倍(几乎不省), 页脚带裁片(844x113→约5497x736)为全图的
    #   1.1~2.4 倍(反而更慢); 「小裁片更快」前提不成立, 故加配置闸门 reward_region_ocr
    #   **默认关闭**, 保持与旧版全图路径逐字节一致, 待实机 A/B(开闸跑一轮看 [OCR统计])
    #   复核后再定默认值。仅 region_rel=None(调用方未显式限定)时才可能启用;
    #   显式 region_rel 依旧原样透传不受影响。
    REWARD_TITLE_REGION = [0.15, 0.10, 0.85, 0.40]
    REWARD_FOOT_REGION = [0.20, 0.85, 0.80, 1.0]

    def _reward_popup_point(self, img=None, region_rel=None, kws=None, need_refine: bool = True,
                            log_miss: bool = True):
        """定位奖励弹窗的文字块(标题优先, 页脚兜底)。标题落在弹窗内, 点击无穿透风险。
        O2: `need_refine=False` 供「只判是否存在」的守卫使用(has_reward_popup), 点击路径保持 True。
        E1: `log_miss=False` 供 required=false 的弹窗守卫静默(见 reward_dialog)。
        性能批 zcode-20261028-9: region_rel=None 且配置 reward_region_ocr=true 时, 标题/页脚
        改为在各自搜索带内找(两段式区域化); 闸门默认关=全图路径与旧版逐字节一致(原因见
        REWARD_*_REGION 注释的收益重估)。其它自定义关键字即便开闸也维持全图(保守, 无实测落点
        依据不设带)。回退兜底语义(批C find_text): 带区域搜索零命中时自动回退一次全图重试、
        结果仍按**原 region 过滤** —— 挽回的是「文字确在区域内但裁片 det 失读」的场景, 不扩大
        搜索面, 故区域化不制造新 MISS(离线已构造出该挽回实例, 见本批 evidence/)。
        显式传入 region_rel 时行为与旧版逐字节一致。"""
        img = img if img is not None else self.screenshot()
        if img is None:
            return None
        kws = list(kws or [self.REWARD_TITLE_KW, self.REWARD_FOOTER_KW])
        # 显式两段式: locate 只返回首个命中块, 块序不保证按关键字先后 -> 必须标题单独先试
        order = ([self.REWARD_TITLE_KW] if self.REWARD_TITLE_KW in kws else []) \
            + [k for k in kws if k != self.REWARD_TITLE_KW]
        for kw in order:
            # zcode-20261028-9: 仅「未显式限定 + 闸门开」时按关键字选带; 显式 region_rel
            # (含空列表)原样透传, 与旧版行为逐字节一致(_ocr_candidates 对非 4 元素区域本就走全图)。
            kw_region = region_rel
            if kw_region is None and self.config.get("reward_region_ocr", False):
                if kw == self.REWARD_TITLE_KW:
                    kw_region = self.REWARD_TITLE_REGION
                elif kw == self.REWARD_FOOTER_KW:
                    kw_region = self.REWARD_FOOT_REGION
            pt = self.locate([kw], img=img, min_score=0.4, region_rel=kw_region,
                             need_refine=need_refine, log_miss=log_miss)
            if pt is not None:
                return pt
        return None

    def has_reward_popup(self, img=None, region_rel=None, keywords=None) -> bool:
        """当前画面是否在屏奖励弹窗(标题「恭喜获得」或页脚「点击任意处关闭」)。公开给 pollin 守卫复用。
        O2: 只判存在 -> 不拆分(拆分的唯一用途是给点击提供精确坐标)。
        E1: 强静默 —— 调用点都是「有弹窗才做事」的高频守卫, 未命中是常态, 不逐条打印。"""
        return self._reward_popup_point(img=img, region_rel=region_rel, kws=keywords,
                                        need_refine=False, log_miss=False) is not None

    def reward_dialog(self, step: dict) -> bool:
        """步骤 reward_dialog / 公开原语: 等待「领取成功界面」出现 -> 关闭 -> 如实上报。

        参数: wait(秒, 等弹窗出现的窗口, 默认 2.0; 0=立即判定一次) / interval(轮询间隔, 默认 0.6)
              tries(最多点击关闭次数, 默认 2) / required(true=未见或关不掉时登记软失败)
              region_rel(限定搜索区域, 可选) / name(日志标签) / keywords(识别词, 可选)
              quiet(true=完全静默: 未见时既不打日志也不登记失败, 供"可能本就没有弹窗"的守卫复用)
        返回 True=见到并已关闭 / False=未见或关不掉。
        注意: 判据仍是 OCR 读到弹窗文字。真领到了但 OCR 未读到时 required=true 会误报 ——
        故 required 只挂"点击前已用模板/OCR 确认过领取按钮"的领取链; 浇水/抽奖/签到等守卫用 false。
        """
        wait = max(0.0, float(step.get("wait", 2.0)))
        interval = max(0.2, float(step.get("interval", 0.6)))
        tries = max(1, int(step.get("tries", 2)))
        required = bool(step.get("required", False))
        quiet = bool(step.get("quiet", False))
        region = step.get("region_rel")
        kws = step.get("keywords")
        label = step.get("name") or "领取成功界面"
        mod = getattr(self, "current_module", None) or ""

        # 1) 等弹窗出现(轮询 OCR; wait=0 只判定一次)。B1(2026-10-22): 判定/关闭定位一律
        #    need_refine=False —— 本原语只需“弹窗在不在”(关闭点用标题中心, 页脚横贯全屏),
        #    10-22 日志 `拆分: reward_dialog 73` 全是白拆(≈60s/轮)。
        # E1(2026-10-22 方案A): 逐次未命中日志按 required 分流 —— required=true(点击前已 OCR/模板确认
        #    过领取按钮)保留 [OCR未命中] 全量证据; required=false(抽奖/浇水/时间礼包等「可能本就没有」)
        #    逐次静默, 整段结束打一行摘要 + 拟低分提示(见 _near_miss_hint), 避免日志被常态负判定淹没。
        log_miss = bool(required and not quiet)
        probes = 0

        def _probe():
            nonlocal probes
            probes += 1
            return self._reward_popup_point(region_rel=region, kws=kws, need_refine=False,
                                           log_miss=log_miss)

        deadline = time.time() + wait
        pt = _probe()
        while pt is None and time.time() < deadline:
            if stop_requested():
                return False
            time.sleep(interval)
            pt = _probe()
        if pt is None:
            if not quiet:
                if required:
                    print(f"[领取] {label}: 未见到「领取成功」界面(如实上报)")
                else:
                    print(f"[弹窗] {label}: 无(检查 {probes} 次)")
                    hint = self._near_miss_hint(kws)
                    if hint:
                        print(f"[弹窗] {label}: 疑似低分块 {hint}(低于 0.4 阈值, 未计为命中)")
            if required and not quiet:
                report_failure(mod, f"{label}: 未见到「领取成功」界面(点击可能被吞/未达标)")
            return False
        print(f"[领取] {label}: 见到「领取成功」界面 @({pt.x},{pt.y})")

        # 2) 关闭(标题优先; 每次点击后复查, 仍在屏才再点)
        for i in range(1, tries + 1):
            if stop_requested():
                return False
            pt = _probe()
            if pt is None:
                print(f"[领取] {label}: 已关闭")
                return True
            print(f"[领取] {label}: 第{i}次点击关闭 @({pt.x},{pt.y})")
            self.click_abs(pt.x, pt.y)
            time.sleep(1.2)
        gone = _probe() is None
        if gone:
            print(f"[领取] {label}: 已关闭")
        else:
            print(f"[领取] {label}: {tries} 次点击后仍在屏, 如实上报")
            if required and not quiet:
                report_failure(mod, f"{label}: 成功界面 {tries} 次点击后仍在屏")
        return gone

    def _near_miss_hint(self, kws, lo=0.2, hi=0.4) -> str:
        """E1: 静默未命中后的一行「疑似低分」提示。

        静默的前提是「画面里确实没有弹窗」；若有块文字与关键字互为子串、但 OCR 分低于 0.4 阈值
        (弹窗文字被读残/半透明过渡态), 则可能是**漏判真弹窗**。长期观察名单(B9)靠这行发现。
        只返回前 3 条, 不改变任何判定结果。
        """
        out = []
        for b in (self._last_miss_blocks or []):
            txt = (b.get("text") or "").strip()
            sc = float(b.get("score", 0.0) or 0.0)
            if not txt or not (lo <= sc < hi):
                continue
            if any(kw and (kw in txt or (len(txt) >= 4 and txt in kw)) for kw in (kws or [])):
                out.append(f"'{txt[:10]}'@{sc:.2f}")
        return " | ".join(out[:3])

    def _claim_scroll(self, step: dict) -> None:
        """领取循环(2026-10-12 v2, 每日任务四步闭环①④): 每屏点尽「领取」-> 关奖励弹窗 -> 上滑;
        行分组指纹连续两屏一致判到底。可选 save/row_pair 顺带按屏留档(同屏采集+领取一趟完成,
        同时写 _last_dump(跨屏累计, 见 _merge_rows) 供 if_collected)。只点 claim_keywords(默认「领取」)与弹窗关闭词,
        不点其它任何按钮。参数: region_rel; claim_keywords; close_keywords; tab_region_rel+
        tab_variants 页签守卫; max_claim_per_screen(默认8, 防单屏死循环); save/label/row_pair;
        stop_claim_after_first(D14a: 领取成功一次后不再找「领取」, 只滚动采行);
        scroll={swipe,duration_ms,settle,max_rounds}。

        D13: 奖励弹窗统一交给 _reward_dialog 判定/关闭/上报(未见成功界面 required 时登记软失败)。
        D14a: 用户 2026-10-19 领域知识 —— 点任一已完成任务的「领取」后**所有已完成任务一并领取**,
        故首次领取成功后本屏/后续屏都不必再找「领取」(只保留滚动采行, 供 if_collected/留档)。"""
        region_rel = step.get("region_rel")
        label = step.get("label", "claim")
        save = step.get("save")
        use_pair = bool(step.get("row_pair"))
        claim_kws = step.get("claim_keywords", ["领取"])
        close_kws = step.get("close_keywords", ["点击任意处关闭", "恭喜获得"])
        tab_region = step.get("tab_region_rel")
        tab_vars = step.get("tab_variants") or []
        scroll = step.get("scroll") or {}
        max_rounds = max(1, int(scroll.get("max_rounds", 12)))
        settle = float(scroll.get("settle", 1.5))
        swipe = scroll.get("swipe")
        dur = int(scroll.get("duration_ms", 700))
        max_per_screen = int(step.get("max_claim_per_screen", 8))
        stop_after_first = bool(step.get("stop_claim_after_first"))   # D14(a)
        claimed_ok = 0                          # 真正见到「领取成功」界面的次数(不是点击次数)
        acc_rows: list = []                     # v2.1: 本次调用的跨屏累计行(供 _last_dump/if_collected)
        self._last_dump[label] = acc_rows       # 重置: 本 label 以本次采集为准(防跨次调用残留)
        prev_fp = None
        for round_no in range(1, max_rounds + 1):
            self._check_stop()
            img = self.screenshot()
            if img is None:
                print(f"[领取] {label}: 第{round_no}轮截图失败, 如实停止")
                return
            if tab_region and tab_vars:
                # O2: 页签守卫只需布尔 -> 不拆分
                tb, _s, _u = self._ocr_candidates(img, tab_region, need_refine=False)
                if not any(v in b.get("text", "") for b in tb for v in tab_vars):
                    print(f"[领取] {label}: 第{round_no}轮页签守卫 MISS(变体={tab_vars}), 如实停止")
                    return
            # 1) 本屏点尽「领取」(每次点击后重截图; 奖励弹窗即时关闭)
            claimed = 0
            skipped_scan = False
            if stop_after_first and claimed_ok > 0:
                skipped_scan = True
                print(f"[领取] {label} 第{round_no}轮: 已领取成功(全部已完成任务一并领取)"
                      f" -> 跳过「{'/'.join(claim_kws)}」定位, 只采行")
            else:
                for _ in range(max_per_screen):
                    self._check_stop()
                    img = self.screenshot()
                    blocks, _s, _u = self._ocr_candidates(img, region_rel)
                    claims = [b for b in blocks if any(k in b.get("text", "") for k in claim_kws)]
                    if not claims:
                        break
                    c = max(claims, key=lambda b: float(b.get("score", 1.0)))
                    cc = c.get("center")
                    if not cc and c.get("box"):
                        cc = [(c["box"][0] + c["box"][2]) / 2, (c["box"][1] + c["box"][3]) / 2]
                    if not cc:
                        break
                    print(f"[领取] {label} 第{round_no}轮 点「{c.get('text', '')}」"
                          f"@rel({cc[0] / self.screen_w:.3f},{cc[1] / self.screen_h:.3f})")
                    self.click_abs(int(cc[0]), int(cc[1]))
                    time.sleep(1.5)
                    # 2) 奖励弹窗(D13 统一原语; 全图 OCR——弹窗可覆盖采集区域外)
                    # A1(2026-10-22): wait 0.5 → 2.0 —— 10-22 日志 L2265-2269 点击后同帧仍读到
                    #   「领取」, 0.5s 窗口内未见弹窗就登记失败(假失败); 服务端回包+弹窗动画通常需 1~2s。
                    ok = self.reward_dialog({
                        "wait": 2.0, "tries": 2, "required": True,
                        "keywords": close_kws, "name": f"{label} 奖励弹窗",
                    })
                    claimed += 1
                    if ok:
                        claimed_ok += 1
                        if stop_after_first:
                            print(f"[领取] {label} 第{round_no}轮: 领取成功 -> 本屏不再找"
                                  f"「{'/'.join(claim_kws)}」(D14a: 已完成任务一并领取)")
                            break
            if claimed == 0 and not skipped_scan:
                print(f"[领取] {label} 第{round_no}轮: 本屏无「{'/'.join(claim_kws)}」")
            # 3) 留档 + 内存(供 if_collected)
            img3 = self.screenshot()
            if img3 is None:
                return
            # O2: 行分组只用 blocks -> 不拆分
            blocks3, _s, _u = self._ocr_candidates(img3, region_rel, need_refine=False)
            rows = self._group_task_rows(blocks3) if use_pair else []
            self._merge_rows(acc_rows, rows)    # v2.1: 跨屏累计(修复曾只留末屏行)
            if save:
                self._write_collect(save, label, round_no, rows, blocks3)
            fp = frozenset((d, p) for d, p, _c in rows) if use_pair else None
            print(f"[领取] {label} 第{round_no}轮小结: 领取 {claimed} 个, 行 {len(rows)}"
                  + (f" (累计 {len(acc_rows)})" if use_pair else ""))
            # 4) 到底判定 / 滑动
            if not swipe:
                return
            if prev_fp is not None and fp == prev_fp:
                print(f"[领取] {label}: 连续两屏一致 -> 到底(共 {round_no} 轮)")
                return
            prev_fp = fp
            self.swipe_rel(*swipe, duration_ms=dur)
            time.sleep(settle)
        print(f"[领取] {label}: 达到 max_rounds={max_rounds} 上限, 如实登记")

    def _if_collected(self, step: dict, indent: int) -> None:
        """条件分支(2026-10-12 v2): 查询最近一次采集(label)的**跨屏累计**行分组结果, 按 desc 关键字找行,
        对进度 (a/b) 求条件; 命中且条件为真走 then, 否则(含行缺失/无进度)走 else。
        参数: label; keywords(子串列表); cond(默认 "a<b", 支持 a<b/a<=b/a==b/a>b/a>=b/a!=b); then/else。
        用途: 每日任务点赞门槛——「献上点赞」行 a<b 才执行社区点赞; 行缺失=当日无此任务要求 -> else。"""
        label = step.get("label", "")
        kws = step.get("keywords") or []
        cond = (step.get("cond") or "a<b").replace(" ", "")
        rows = self._last_dump.get(label) or []
        hit = None
        for d, p, _c in rows:
            if any(k in d for k in kws):
                hit = p
                break
        ok = False
        if hit and "/" in hit:
            try:
                a, b = (int(x) for x in hit.split("/")[:2])
                ok = bool({"a<b": a < b, "a<=b": a <= b, "a==b": a == b,
                           "a>b": a > b, "a>=b": a >= b, "a!=b": a != b}.get(cond, a < b))
            except (ValueError, TypeError):
                ok = False
        print(f"{'  ' * indent}[if_collected] {label} 关键词{kws} 命中行={hit} 条件'{cond}' "
              f"-> {'TRUE' if ok else 'FALSE'}" + ("" if hit else " (未找到该行, 走 else)"))
        branch = step.get("then") if ok else step.get("else")
        if branch:
            self.run_steps(branch, indent=indent + 1)

    def click_row_button(self, step: dict, indent: int) -> None:
        """行级按钮点击(2026-10-25 浏览热卖): 在**当前帧**重新定位目标任务行并点击行内按钮,
        不写死任何坐标, 不复用历史采集坐标。

        为什么不复用 claim_scroll 采集的行坐标(2026-10-25 E2E 实锤):
        采集跨屏滚动后, _last_dump 里各行的坐标是「该行首次被看见那屏」的位置;
        claim_scroll 结束时列表已滚动到底, 当前画面同 y 位置是**另一行任务**
        (实测: 采集时「查看最新热卖套装」@y435, 点击时 y435 处已是别的任务行)。
        按陈旧 y 开行带会锚错行 —— 窄行带防误点的设计反而成了「锚错行的精确执行」。

        因此本原子每轮: 截图 → 全图 OCR → 行分组(_group_task_rows) → 按 keywords 子串找
        目标行 → 用**本帧**该行进度块中心 y 开窄行带 → 带内实时识别 text 按钮词(如「前往」)
        并点击该按钮自身的本次命中坐标(规则6合规范式①)。行不在当前画面则滑动翻页找:
        claim_scroll 结束时列表在底部故先向上翻, 连续两屏行集合不变(到边)则反向,
        最多 max_rounds 轮; 找到行但带内无按钮时**不点击**并存证, 交调用方处置。

        行带几何: 进度块与按钮同 y(五日留档 Δy≤0.003), 相邻行距 Δy≈0.189,
        半高默认 0.028(≈行距 1/7)不会跨行; find_text 区域过滤保证回退全图重试的
        结果仍须落回行带内, 窄带 MISS 不会点到其它行的同名按钮。
        """
        pad = "  " * indent
        row_kws = step.get("keywords") or []
        row_kws = row_kws if isinstance(row_kws, list) else [row_kws]
        kws = step.get("text") or ["前往"]
        kws = kws if isinstance(kws, list) else [kws]
        half_h = float(step.get("row_half_h", 0.028))
        x1_rel, x2_rel = (float(v) for v in step.get("row_x_range", (0.60, 1.0)))
        max_rounds = max(1, int(step.get("max_rounds", 8)))
        settle = float(step.get("settle", 1.5))
        swipe = step.get("swipe") or [0.68, 0.60, 0.68, 0.35]
        sx1, sy1, sx2, sy2 = (float(v) for v in swipe[:4])
        if not self.screen_h:
            self.screenshot()
        direction = -1   # claim_scroll 结束时列表在底部: 先向上翻找目标行
        prev_sig = None
        for round_no in range(1, max_rounds + 1):
            self._check_stop()
            img = self.screenshot()
            if img is None:
                print(f"{pad}[click_row_button] 第{round_no}轮截图失败, 如实放弃")
                return
            blocks, _subs = self._ocr_frame(img, need_split=False)
            rows = self._group_task_rows(blocks)
            hit = None
            for d, p, c in rows:
                if any(k in d for k in row_kws):
                    hit = (d, p, c)
                    break
            if hit:
                d, p, c = hit
                ry = c[1] / self.screen_h if self.screen_h else 0.0
                band = [x1_rel, max(0.0, ry - half_h), x2_rel, min(1.0, ry + half_h)]
                print(f"{pad}[click_row_button] 第{round_no}轮 行'{d}'={p} y={ry:.4f} "
                      f"行带={[round(v, 3) for v in band]}")
                pt = self.locate(kws, img=img, min_score=0.4, region_rel=band,
                                 exclude=step.get("exclude"))
                if pt is not None:
                    print(f"{pad}[click_row_button] {kws} -> ({pt.x},{pt.y}) 本帧行内命中, 点击")
                    self.click_abs(pt.x, pt.y)
                    time.sleep(step.get("delay", 1.0))
                    return
                print(f"{pad}[click_row_button] 行带内未命中{kws}, 不点击")
                self.dump_full_frame(f"行按钮未命中:{kws[0]}")
                if step.get("required"):
                    report_failure(self._module, f"click_row_button 行'{d}'带内未命中{kws}(required)")
                    raise BranchAborted(f"click_row_button 行内无按钮 {kws}")
                return
            sig = frozenset((d, p) for d, p, _c in rows)
            if sig == prev_sig and sig:
                direction = -direction
                print(f"{pad}[click_row_button] 第{round_no}轮 行集合未变化(到边), 反向翻页")
            else:
                print(f"{pad}[click_row_button] 第{round_no}轮 当前画面无{row_kws}行, "
                      f"{'向下' if direction > 0 else '向上'}翻页")
            prev_sig = sig
            if direction > 0:   # 向下翻: 手指从下往上滑(同 claim_scroll swipe)
                self.swipe_rel(sx1, sy1, sx2, sy2, duration_ms=700)
            else:               # 向上翻: 手指从上往下滑(反向)
                self.swipe_rel(sx1, sy2, sx2, sy1, duration_ms=700)
            time.sleep(settle)
        print(f"{pad}[click_row_button] {max_rounds} 轮未找到含{row_kws}的行, 如实放弃")
        self.dump_full_frame(f"行未命中:{row_kws[0] if row_kws else '?'}")
        if step.get("required"):
            report_failure(self._module, f"click_row_button {max_rounds}轮未找到行{row_kws}(required)")
            raise BranchAborted(f"click_row_button 未找到行 {row_kws}")

    def _refine_wide_block(self, img, block):
        """O3(2026-10-21): **只对命中的合并块**做一次定向精识(替代全帧预拆)。

        为什么不直接复用 _split_wide 的固定参数:
          - 横向留 10px 会把隔壁按钮的字重新纳入裁片 -> det 又合并成一块(越拆越合);
          - 纵向需要更宽余量, 防上下切掉笔画/标点。
        故: pad_x=3(紧), pad_y=max(6, 0.35×块高)(松), 放大倍率按块高自适应(小字 3×, 常规 2×)。
        返回映射回全帧坐标的子块列表; 缓存与 _split_wide 共用 `_split_cache`(键含 pad/scale, 不会串用)。
        """
        x1, y1, x2, y2 = block["box"]
        bh = max(1, y2 - y1)
        pad_y = max(6, int(bh * 0.35))
        pad_x = 3
        ox, oy = max(0, x1 - pad_x), max(0, y1 - pad_y)
        ex, ey = min(self.screen_w, x2 + pad_x), min(self.screen_h, y2 + pad_y)
        crop = img[oy:ey, ox:ex]
        if crop.size == 0:
            return []
        scale = 3.0 if bh < 16 else 2.0
        key = (ox, oy, pad_x, pad_y, int(round(scale * 10)),
               hashlib.blake2b(np.ascontiguousarray(crop).tobytes(), digest_size=16).digest())
        with self._split_lock:
            cached = self._split_cache.get(key)
            if cached is not None:
                self._split_cache.pop(key)
                self._split_cache[key] = cached
        if cached is not None:
            self._ocr_stat["split_cache_hit"] += 1
            return [dict(nb) for nb in cached]
        import cv2
        big = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        subs: list = []
        for nb in self._timed_ocr(big, "split"):
            nb2 = dict(nb)
            nb2["center"] = [int(nb["center"][0] / scale) + ox,
                             int(nb["center"][1] / scale) + oy]
            nb2["box"] = [int(nb["box"][0] / scale) + ox,
                          int(nb["box"][1] / scale) + oy,
                          int(nb["box"][2] / scale) + ox,
                          int(nb["box"][3] / scale) + oy]
            subs.append(nb2)
        with self._split_lock:
            if len(self._split_cache) >= 400:
                self._split_cache.pop(next(iter(self._split_cache)))
            self._split_cache[key] = subs
        return [dict(nb) for nb in subs]

    def _is_merged_hit(self, block, keywords) -> bool:
        """O3: 该命中块是否是**合并块**(文本比关键字更长, 且宽度>90)。
        注意必须在 `_narrow_merged` 之前判断 —— 窄化后 box 已缩到关键字本身, 宽度失去意义。
        归一化只用于“是否需要精识”的判断, 不参与坐标计算。"""
        if (block["box"][2] - block["box"][0]) <= 90:
            return False
        text = re.sub(r"\s+", "", block.get("text", "") or "")
        if not text:
            return False
        kws = keywords if isinstance(keywords, list) else [keywords]
        for kw in kws:
            nk = re.sub(r"\s+", "", str(kw))
            if nk and nk in text and len(text) > len(nk):
                return True
        return False

    def find_text(self, keywords, img=None, top_k=3, exact=False, region_rel=None, exclude=None,
                  need_refine: bool = True, log_miss: bool = True):
        """在截图(或给定图)中按关键字找文字块。返回 OCR 块列表 (含坐标)。
        exact=True 要求块文本与关键字完全相等, 避免『家园』误命中『勇气国花园』等。
        region_rel=[x1,y1,x2,y2] (0~1) 时只保留中心落在该区域内的块 (用于区域限定文本判断)。
        exclude=['已领取'] 时剔除「文字里含这些排除词」的块: 关键字默认是**子串匹配**,
        所以「领取」会命中「已领取」——按钮已领取时点它当然什么都不会发生, 必须排除。

        O3(2026-10-21) 三级策略(取代“先对全帧所有过宽块做 2× 拆分”):
          ① 精确等值命中 -> 直接用, 零额外开销;
          ② 模糊命中在**合并块**内(文本比关键字长且宽>90) -> 只对该块做一次定向精识
             (`_refine_wide_block`: 横向紧/纵向松/自适应倍率), 再在“子块+合并块”中重匹配;
          ③ 仍未命中且需要精度 -> 兜底全量拆分一次(保持旧召回, 防“只在子块可读”的极端情况);
        判断类调用(need_refine=False)完全不拆分(O2)。合并块始终保留, `_narrow_merged` 仍兜底。
        """
        img = img if img is not None else self.screenshot()
        if img is None:
            return []
        # O3: 先不拆分; 后面只对命中的合并块按需精识
        blocks, sub_blocks, used_region = self._ocr_candidates(img, region_rel, need_refine=False)
        hits = []
        refined_ids: set = set()
        did_full_split = False
        rx1 = ry1 = rx2 = ry2 = 0
        if region_rel:
            w, h = self.screen_w, self.screen_h
            rx1, ry1 = int(region_rel[0] * w), int(region_rel[1] * h)
            rx2, ry2 = int(region_rel[2] * w), int(region_rel[3] * h)

        def _in_region(lst):
            if not region_rel:
                return list(lst)
            return [b for b in lst
                    if rx1 <= b["center"][0] <= rx2 and ry1 <= b["center"][1] <= ry2]

        for _attempt in range(2):
            # 精确子块优先(点击点优先落到目标文字自身中心), 原合并块兜底保证整体命中
            hits = ocr_find(_in_region(sub_blocks + blocks), keywords, exact=exact)
            # O0: 安全指标 —— 本次命中是否**完全依赖拆分子块**?
            if hits and sub_blocks:
                if not ocr_find(_in_region(blocks), keywords, exact=exact):
                    self._ocr_stat["split_only_hit"] += 1
            # O3-②: 命中的合并块定向精识(只处理这一块, 不碰全帧其它过宽块)
            if need_refine and hits:
                merged = [b for b in hits
                          if id(b) not in refined_ids and self._is_merged_hit(b, keywords)]
                if merged:
                    new_subs = []
                    for b in merged:
                        refined_ids.add(id(b))
                        new_subs.extend(self._refine_wide_block(img, b))
                    if new_subs:
                        sub_blocks = sub_blocks + new_subs
                        hits = ocr_find(_in_region(sub_blocks + blocks), keywords, exact=exact)
            # O3-③: 仍未命中 -> 兜底全量拆分一次(与旧行为一致的召回)。
            # 仅在**全图**块上做: 区域化未命中时先回退全图再拆, 避免对裁片块做无用拆分。
            if need_refine and not hits and not did_full_split and not used_region:
                did_full_split = True
                more = self._split_wide(img, blocks)
                if more:
                    sub_blocks = sub_blocks + more
                    hits = ocr_find(_in_region(sub_blocks + blocks), keywords, exact=exact)
            if not exact:
                kws = keywords if isinstance(keywords, list) else [keywords]
                hits = [self._narrow_merged(b, kws) for b in hits]
            if exclude:
                ex = exclude if isinstance(exclude, list) else [exclude]
                keep = [b for b in hits if not any(e in b["text"] for e in ex)]
                if hits and not keep:
                    # 命中块全被排除词剔除: 典型情况是「领取」其实读到的是「已领取」(按钮已领),
                    # 必须如实报出来 —— 否则日志会显示"识别到领取却没领到", 让人以为是点击不准。
                    print(f"[排除] {keywords} 命中{len(hits)}块但均含排除词{ex}, 不点击: "
                          + " | ".join(f"{b['text'][:10]}@({b['center'][0]},{b['center'][1]})" for b in hits[:5]))
                hits = keep
            if hits or not used_region:
                break
            # 批C-①: 区域化未命中 → 回退一次全图重试(防小图 det 上下文差异制造新 MISS;
            # 结果照常入全图单槽缓存)。区域化只省命中路径耗时, 不制造新 MISS。
            # O3: 回退的全图也不预拆 —— 若命中合并块, 下一轮会定向精识。
            blocks, sub_blocks = self._ocr_frame(img, need_split=False)
            used_region = False
        if hits:
            self._miss_sig = None  # 命中即复位「同画面未命中折叠」(2026-10-03, 见 _log_ocr_miss)
        if not hits:
            # E1(2026-10-22): log_miss=False 供弹窗/启动状态等“常态负判定”使用 ——
            #   不再逐次打印 `[OCR未命中]`; 但保留末帧证据 + 汇总计数,
            #   便于其他调用方(如 reward_dialog)输出一行摘要与“疑似低分”提示。
            if log_miss:
                self._log_ocr_miss(keywords, exact, region_rel, blocks)
            else:
                self._ocr_stat["miss_silent_n"] += 1
                self._last_miss_blocks = list(blocks or [])
                self._last_miss_keywords = keywords if isinstance(keywords, list) else [keywords]
        return hits

    def _log_ocr_miss(self, keywords, exact, region_rel, blocks, max_blocks=10):
        """诊断输出: 文本未命中时打印本次 OCR 实际读到的文字块摘要。

        用于区分三种失败: ① 该文字根本没被检出(画面未就绪/低对比/艺术字);
        ② 检出了但文字不符或被合并(如把「家族」「家族活动」并成一块);
        ③ 检出了但落在限定区域之外 —— 即区域坐标写错(此前只打全屏前 10 块, 无法区分 ③)。
        区域限定时分别打印「区域内实读」与「区域外含同字块(疑似区域坐标不对)」。
        只打印前 max_blocks 块, 控制日志体积。

        ⚠ 同画面重复未命中折叠(2026-10-03, 协作区 zcode-20261003-2): 卡死画面会让每种探测
          每轮都完整打印「实读到前10块」(2026-10-03 日志: 93×删除好友 / 51×社交 / 36×确定,
          日志膨胀难检索)。签名=帧指纹+exact+区域(同帧块内容本就相同, 不再按关键字区分),
          同签名只完整打印首条, 其后每 10 次折叠为一行计数; 画面一变(指纹变)或命中即复位。
        """
        kws = keywords if isinstance(keywords, list) else [keywords]

        # ---- 同画面重复未命中折叠 ----
        # 仅在帧指纹可用时折叠(哈希失败则逐条打印, 宁多勿漏); 并发下计数最多偏差 1, 纯日志层可接受
        if self._frame_sig is not None:
            sig = (self._frame_sig, bool(exact),
                   tuple(region_rel) if region_rel else None)
            if sig == self._miss_sig:
                self._miss_count += 1
                if self._miss_count % 10 == 0:  # 每 10 次提一条, 避免完全静默
                    print(f"[OCR未命中] 同画面重复 x{self._miss_count} (已折叠): {kws}")
                return
            self._miss_sig = sig
            self._miss_count = 1

        def brief(bs):
            return " | ".join(
                f"{b['text'][:10]}@{b['score']:.2f}({b['center'][0]},{b['center'][1]})"
                for b in bs[:max_blocks])

        if not region_rel:
            more = f" 共{len(blocks)}块" + (f"(只列前{max_blocks}块)" if len(blocks) > max_blocks else "")
            print(f"[OCR未命中] {kws} exact={exact} 区域=None{more}"
                  + (f" 实读到: {brief(blocks)}" if blocks else " 未读到任何文字块"))
            return
        w, h = self.screen_w, self.screen_h
        rx1, ry1 = int(region_rel[0] * w), int(region_rel[1] * h)
        rx2, ry2 = int(region_rel[2] * w), int(region_rel[3] * h)
        inside = [b for b in blocks
                  if rx1 <= b["center"][0] <= rx2 and ry1 <= b["center"][1] <= ry2]
        inside_ids = {id(b) for b in inside}
        chars = {c for kw in kws for c in kw if not c.isspace()}
        outside_same = [b for b in blocks
                        if id(b) not in inside_ids and any(c in b["text"] for c in chars)]
        lines = [f"[OCR未命中] {kws} exact={exact} 区域={region_rel}"
                 f" 全屏{len(blocks)}块 / 区域内{len(inside)}块"
                 f" (区域绝对像素 x{rx1}-{rx2} y{ry1}-{ry2})",
                 "  区域内实读: " + (brief(inside) if inside else "无")]
        if outside_same:
            lines.append("  ⚠ 区域外含同字块(疑似区域坐标不对): " + brief(outside_same))
        print("\n".join(lines))

    # 故障存证 tag → 文件名 ASCII slug(里程碑 94): 中文 tag 在 Windows 下经 cv2.imwrite 落盘会**乱码**
    # (现网实测 fail_绛夊緟瓒呮椂___…png), 故文件名一律 ASCII; 中文原文保留在日志与 index.jsonl 的 tag 字段。
    _DUMP_TAG_MAP = (("未命中", "miss"), ("等待超时", "wait_timeout"), ("消失超时", "vanish_timeout"))

    @classmethod
    def _dump_tag_slug(cls, tag: str) -> str:
        for zh, en in cls._DUMP_TAG_MAP:
            if tag.startswith(zh):
                return en
        s = re.sub(r"_+", "_", "".join(
            ch if (ch.isascii() and (ch.isalnum() or ch in "_-")) else "_" for ch in str(tag))).strip("_")
        return (s or "misc")[:32]

    def dump_full_frame(self, tag: str, img=None) -> None:
        """故障现场存证: 全量 OCR(不截断) + 当前帧截图落盘 (2026-10-14 用户要求)。

        常规未命中日志(_log_ocr_miss)只列前 10 块, 卡死/报错时无法判断画面到底有什么
        (弹窗遮挡? 动画中间帧? 艺术字被读错?) —— 故在**离散错误点**(等待超时/点击未命中)
        额外做一次**全量** OCR 并保存当帧, 供离线复核与模板/区域校准。

        ⚠ 里程碑 94(用户方案) 存证策略重构 —— "缓存"语义 + 零内存 + 信息不死:
        - **零运行内存**: 截图**当场同步写盘**, 进程内不缓存 numpy/bytes/图片数据(只留一条元数据);
          代价是该点阻塞若干毫秒~百毫秒(全量 OCR 是大头), 属用户明示接受的取舍。
        - **缓存目录**: `data/fail_cache/<会话戳>/`(会话戳=引擎实例创建时刻 ⇒ 一次服务运行一个目录,
          跨服务重启**保留不清**, 便于崩溃后仍能看现场)。
        - **纯 ASCII 文件名**: `fail_<日期>_<时刻>_<序号>_<slug>.jpg` —— 修 O2(Windows 中文名乱码)。
        - **JPEG(q85)** 而非 PNG: 单张 ≈200KB(原 PNG 1.3~1.6MB) —— 缓解 O3。
        - **不设自动淘汰**: 无任何大小/张数守卫(避免每次落盘都统计的开销); 清理**只由用户触发**
          (启动超阈值提醒弹窗 / 「清除日志」按钮), 详见 webui.py::clean_fail_cache。
        - **元数据墓碑(信息不死)**: 每次落盘追加一条到 `data/fail_cache/index.jsonl`, 含
          时间/会话/tag(中文原文)/文件名/字节数/**全量 OCR 文本**/帧指纹 —— 日后像素被清理时
          该条目标 `evicted:true` 而**记录永久保留** ⇒ 不会"静默丢失信息"。
        - 预算 `fail_dump_budget` 与 (tag,帧指纹) 去重维持不变; 异常一律吞掉, 不影响流程。
        """
        try:
            if self._dump_left <= 0:
                return
            if img is None:
                img = self.last_frame if self.last_frame is not None else self.screenshot()
            if img is None:
                print(f"[故障存证] {tag}: 取帧失败, 跳过")
                return
            sig = self._frame_hash(img)
            key = (tag, sig)
            if sig is not None and key == self._dump_sig:
                return
            self._dump_sig = key
            self._dump_left -= 1
            # O2: 存证只打印/落盘文字块 -> 不拆分
            blocks, _sub = self._ocr_frame(img, need_split=False)
            print(f"[故障存证] {tag}: 全量 OCR {len(blocks)} 块 (本轮预算余 {self._dump_left})")
            for b in blocks:
                c = b.get("center") or (0, 0)
                print(f"    · {str(b.get('text',''))[:24]} @{float(b.get('score',1.0)):.2f} ({c[0]},{c[1]})")
            import cv2
            import json
            base = Path(__file__).parent / "data" / "fail_cache"
            out = base / self._session_stamp
            out.mkdir(parents=True, exist_ok=True)
            self._dump_seq += 1
            slug = self._dump_tag_slug(tag)
            fn = f"fail_{time.strftime('%Y%m%d_%H%M%S')}_{self._dump_seq:03d}_{slug}.jpg"
            fp = out / fn
            ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok:
                print(f"[故障存证] {tag}: JPEG 编码失败, 跳过")
                return
            buf.tofile(str(fp))   # 用 tofile 而非 imwrite: 绕开 OpenCV 对非 ASCII 路径的处理差异
            nbytes = fp.stat().st_size
            rel = f"{self._session_stamp}/{fn}"
            print(f"[故障存证] {tag}: 画面已保存 -> data/fail_cache/{rel} ({nbytes/1024:.0f} KB, {len(blocks)} 块)")
            # 元数据墓碑: 记录永久留档, 供日后"像素已清理但记录仍在"的追溯
            try:
                entry = {
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "session": self._session_stamp,
                    "tag": str(tag), "slug": slug, "file": rel, "bytes": nbytes,
                    "sig": (sig.hex()[:16] if sig is not None else None),
                    "ocr": [f"{str(b.get('text',''))[:40]}@{float(b.get('score',1.0)):.2f}"
                            f"({(b.get('center') or (0,0))[0]},{(b.get('center') or (0,0))[1]})"
                            for b in blocks],
                    "evicted": False,
                }
                with open(base / "index.jsonl", "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception as e2:
                print(f"[故障存证] {tag}: 索引写入失败(不影响流程): {e2}")
        except Exception as e:
            print(f"[故障存证] {tag}: 存证异常(不影响流程): {e}")

    @staticmethod
    def _narrow_merged(b: dict, kws: list[str]) -> dict:
        """合并块纠偏: OCR 常把相邻按钮并成一块(实测「快捷操作种植箱」[1275..1480]),
        此时子串命中返回的是**合并块中心**, 落点正好在两按钮之间的空隙上, 点击无效
        (实测偏差 50px: 真实中心 1327 vs 返回 1377)。
        按字符占比把关键字在块内的位置还原出来, 重算中心与框。
        仅当块文本比关键字更长(确为合并块)时生效; 文本与关键字等长(精确命中)原样返回。
        """
        text = b["text"].strip()
        for k in kws:
            if k in text and len(text) > len(k):
                idx = text.find(k)
                x1, y1, x2, y2 = b["box"]
                n, w = len(text), x2 - x1
                sx, ex = x1 + w * idx / n, x1 + w * (idx + len(k)) / n
                nb = dict(b)
                nb["box"] = [int(sx), y1, int(ex), y2]
                nb["center"] = [int((sx + ex) / 2), int((y1 + y2) / 2)]
                return nb
        return b

    def locate(self, keywords, img=None, min_score=0.5, exact=False, region_rel=None, exclude=None,
               need_refine: bool = True, log_miss: bool = True):
        """返回第一个命中块的中心绝对坐标 Point; 未命中返回 None。
        命中后更新 last_rel 缓存, 并把**实际命中的原始文字**记到 self._last_match_text,
        便于日志区分「命中就是关键字本身」与「命中的是含关键字的更长文字(如已领取)」。
        E1: `log_miss=False` 透传给 find_text —— 供「确认没有弹窗/不在更新页」这类高频负判定静默。
        """
        blocks = self.find_text(keywords, img=img, exact=exact, region_rel=region_rel, exclude=exclude,
                                need_refine=need_refine, log_miss=log_miss)
        for b in blocks:
            if b.get("score", 1.0) < min_score:
                continue
            cx, cy = b["center"]
            pt = Point(cx, cy, self.screen_w, self.screen_h)
            for kw in (keywords if isinstance(keywords, list) else [keywords]):
                self.last_rel[kw] = pt.rel
            self._last_match_text = b["text"].strip()
            self._last_match_block = b  # 命中块(含 score/text/center), 供相邻定位复用的严谨校验(批B)
            return pt
        self._last_match_text = None
        self._last_match_block = None
        return None

    def locate_color(self, color_cfg: dict, img=None) -> "Point | None":
        """颜色特征定位: HSV 过滤 + 连通区域分析, 返回中心 Point。
        color_cfg: {"hsv_lower": [h,s,v], "hsv_upper": [h,s,v],
                    "area_min": int, "area_max": int, "region": [x1,y1,x2,y2]}
        """
        import cv2
        import numpy as np
        img = img if img is not None else self.screenshot()
        if img is None:
            return None
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        lower = np.array(color_cfg["hsv_lower"])
        upper = np.array(color_cfg["hsv_upper"])
        mask = cv2.inRange(hsv, lower, upper)
        # 可选: 限定搜索区域
        region = color_cfg.get("region")
        if region:
            x1, y1, x2, y2 = region
            sub_mask = np.zeros_like(mask)
            sub_mask[y1:y2, x1:x2] = mask[y1:y2, x1:x2]
            mask = sub_mask
        num_labels, _, stats, centroids = cv2.connectedComponentsWithStats(mask)
        area_min = color_cfg.get("area_min", 50)
        area_max = color_cfg.get("area_max", 999999)
        candidates = []
        for i in range(1, num_labels):
            area = stats[i, cv2.CC_STAT_AREA]
            if area_min < area < area_max:
                cx, cy = centroids[i]
                candidates.append((cx, cy, area))
        if not candidates:
            return None
        # 取面积最大的
        candidates.sort(key=lambda c: c[2], reverse=True)
        cx, cy = int(candidates[0][0]), int(candidates[0][1])
        return Point(cx, cy, self.screen_w, self.screen_h)

    def count_color(self, color_cfg: dict, img=None) -> int:
        """统计指定 HSV 颜色连通域的个数。

        用于「画面里某种色块出现多少次」的计数(如已领取的绿色勾号)。
        color_cfg: {"hsv_lower": [h,s,v], "hsv_upper": [h,s,v],
                    "area_min": int, "area_max": int, "region": [x1,y1,x2,y2]}
        与 locate_color 同一套 HSV 过滤 + 连通域分析, 但返回**命中个数**而非最大块中心;
        仅保留面积在 (area_min, area_max) 区间内的连通域, 默认排除过小/过大的噪点。
        """
        import cv2
        import numpy as np
        img = img if img is not None else self.screenshot()
        if img is None:
            return 0
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        lower = np.array(color_cfg["hsv_lower"])
        upper = np.array(color_cfg["hsv_upper"])
        mask = cv2.inRange(hsv, lower, upper)
        region = color_cfg.get("region")
        if region:
            x1, y1, x2, y2 = region
            sub_mask = np.zeros_like(mask)
            sub_mask[y1:y2, x1:x2] = mask[y1:y2, x1:x2]
            mask = sub_mask
        num_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        area_min = color_cfg.get("area_min", 20)
        area_max = color_cfg.get("area_max", 999999)
        n = 0
        for i in range(1, num_labels):
            area = stats[i, cv2.CC_STAT_AREA]
            if area_min < area < area_max:
                n += 1
        return n

    def locate_anchor_offset(self, anchor_cfg: dict, img=None, min_score=0.4) -> "Point | None":
        """锚点 + 像素偏移定位: 适用于「固定尺寸界面」(如小花仙登录界面不随设备分辨率缩放),
        整体画面相对坐标(0~1)会失效, 但「界面内元素相对锚点的像素偏移」恒定不变。

        anchor_cfg: {"anchors": [
            {"text_contains": "****", "offset": [dx, dy]},   # 按子串找锚点块(如账号 abc****de)
            {"text": ["登录"], "offset": [dx, dy]},           # 按关键字找锚点块
        ]}
        依次尝试各锚点, 首个命中即返回 锚点中心+offset 的 Point; 全部失败返回 None。
        """
        img = img if img is not None else self.screenshot()
        if img is None:
            return None
        for a in anchor_cfg.get("anchors", []):
            dx, dy = a.get("offset", [0, 0])
            pat = a.get("text_contains")
            if pat:
                # O2: 锚点查询只用合并块文本 -> 不拆分
                hit = next((b for b in self._ocr_frame(img, need_split=False)[0]
                            if pat in b.get("text", "")), None)
                if hit is None:
                    print(f"[锚点偏移] 未找到含 '{pat}' 的文本块")
                    continue
                cx, cy = hit["center"]
            else:
                pt = self.locate(a.get("text", []), img=img, min_score=min_score)
                if pt is None:
                    continue
                cx, cy = pt.x, pt.y
            tx = max(0, min(self.screen_w - 1, int(cx + dx)))
            ty = max(0, min(self.screen_h - 1, int(cy + dy)))
            return Point(tx, ty, self.screen_w, self.screen_h)
        return None

    def click_account_tail(self, tail: str, region_rel=None, min_score=0.4) -> bool:
        """在账号选择界面点击「账号文本尾部数字」匹配的账号条目并返回坐标缓存。

        账号条目文本形如 `abc****de`(中部脱敏的账号文本)。登录界面固定尺寸, 用 OCR 识别各账号块,
        locale 匹配文本尾部数字==tail 的块(可能合并块需取尾部), 点击其中心。
        region_rel=[x1,y1,x2,y2] 限定时只在账号列表区域匹配, 避免误点其它数字文本。
        """
        img = self.screenshot()
        if img is None:
            return False
        blocks = [b for b in self._ocr_frame(img)[0] if b.get("score", 1) >= min_score]
        # 区域限定
        if region_rel:
            w, h = self.screen_w, self.screen_h
            rx1, ry1 = int(region_rel[0] * w), int(region_rel[1] * h)
            rx2, ry2 = int(region_rel[2] * w), int(region_rel[3] * h)
            blocks = [b for b in blocks if rx1 <= b["center"][0] <= rx2 and ry1 <= b["center"][1] <= ry2]
        tail = str(tail).strip()
        best = None
        for b in blocks:
            txt = b.get("text", "").strip()
            # 匹配账号格式: 尾部数字 == tail (可含 **** 脱敏)
            m = re.search(r"(\d+)\s*$", txt)
            if not m or m.group(1) != tail:
                continue
            if "****" in txt:  # 确认是脱敏账号块
                best = b
                break
        if best is None:
            print(f"[账号尾部] 未找到尾部={tail} 的账号条目")
            report_failure(self._module, f"切换账号: 账号列表中未找到尾部={tail} 的账号条目"
                                        f"(账号列表可能未展开或已改版)")
            return False
        cx, cy = best["center"]
        pt = Point(cx, cy, self.screen_w, self.screen_h)
        print(f"[账号尾部] {best['text']} 尾部={tail} -> {cx},{cy}")
        self.click_abs(cx, cy)
        # 知识库键名不含真实账号文本: 按账号列表中的行序编号(每行坐标不同, 仍需分别缓存)
        rows = sorted([b for b in blocks if "****" in b.get("text", "")],
                      key=lambda b: b["center"][1])
        idx = next((i for i, b in enumerate(rows) if b is best), 0) + 1
        self._log_click(f"账号条目#{idx}", [], pt, "account_tail")
        for kw in (best["text"], f"账号尾{tail}"):
            self.last_rel[kw] = pt.rel
        return True

    def locate_anchor_color(self, anchor_kw, color_cfg: dict, dx_range=(150, 400), dy_tol=60,
                            img=None, min_score=0.4, quiet: bool = False) -> "Point | None":
        """锚点 + 颜色复合定位: 先 OCR 找锚点文字(如「提示」), 在锚点右侧/某偏移区域按颜色找目标按钮。
        用于弹窗关闭按钮等「有文字作锚点 + 按钮自身无文字」的场景, 比固定绝对坐标更健壮。
        color_cfg 的 region 若未提供, 则由锚点动态计算。
        quiet=True: 不打印（P1-2 批2 的“点后复检”用, 避免每次关闭都刷常态 MISS）。
        """
        img = img if img is not None else self.screenshot()
        if img is None:
            return None
        anchor = self.locate([anchor_kw], img=img, min_score=min_score,
                             log_miss=not quiet)
        if anchor is None:
            if not quiet:
                print(f"[锚点定位] 未找到锚点文字 '{anchor_kw}'")
            return None
        import cv2
        import numpy as np
        ax, ay = anchor.x, anchor.y
        # 若颜色配置未给定 region, 用锚点动态生成右侧搜索区
        cfg = dict(color_cfg)
        if not cfg.get("region"):
            x1, x2 = ax + dx_range[0], ax + dx_range[1]
            y1, y2 = ay - dy_tol, ay + dy_tol
            cfg["region"] = [max(0, x1), max(0, y1), x2, y2]
        return self.locate_color(cfg, img=img)

    def parse_fraction_at(self, region_rel, img=None, tol=60) -> "tuple[int,int] | None":
        """OCR 整图, 找形如 'a/b' 的数字块, 取中心离 region_rel*屏 最近且距离<=tol 的, 返回 (a,b)。
        未找到返回 None。
        """
        img = img if img is not None else self.screenshot()
        if img is None:
            return None
        w, h = self.screen_w, self.screen_h
        tx, ty = int(region_rel[0] * w), int(region_rel[1] * h)

        def _scan(blks):
            b_best, b_d = None, float("inf")
            for b in blks:
                m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", b.get("text", "").strip())
                if not m:
                    continue
                cx, cy = b["center"]
                d = (cx - tx) ** 2 + (cy - ty) ** 2
                if d < b_d:
                    b_d, b_best = d, (int(m[1]), int(m[2]))
            return b_best, b_d

        # 批C-①: 点+tol 查询换算小方框区域化(半径 tol*1.25: 覆盖中心在 tol 内的计数文字全像素;
        # a/b 计数器位置稳定, 裁片约 1~2% 全图面积)。区域内未找到 → 回退一次全图。
        if self.config.get("region_ocr", True) and w and h:
            r = int(tol * 1.25)
            box = (max(0, tx - r) / w, max(0, ty - r) / h, min(w, tx + r) / w, min(h, ty + r) / h)
            rr = self._ocr_frame_region(img, box, need_split=False)
            if rr is not None:
                best, best_d = _scan(rr[0])
                if best is not None and best_d ** 0.5 <= tol:
                    return best
        best, best_d = _scan(self._ocr_frame(img, need_split=False)[0])
        if best is not None and best_d ** 0.5 <= tol:
            return best
        return None

    def parse_count_at(self, region_rel, img=None, tol=120) -> "int | None":
        """OCR 整图, 找形如 '关键字:N' 或纯数字('N') 的数字块, 取中心离 region_rel*屏 最近且距离<=tol 的, 返回 N。
        用于解析『剩余抽奖次数:3』这类带关键字的单值数字。未找到返回 None。
        """
        img = img if img is not None else self.screenshot()
        if img is None:
            return None
        w, h = self.screen_w, self.screen_h
        tx, ty = int(region_rel[0] * w), int(region_rel[1] * h)

        def _scan(blks):
            b_best, b_d = None, float("inf")
            for b in blks:
                m = re.search(r"[:：]?\s*(\d+)\s*$", b.get("text", "").strip())
                if not m:
                    continue
                cx, cy = b["center"]
                d = (cx - tx) ** 2 + (cy - ty) ** 2
                if d < b_d:
                    b_d, b_best = d, int(m[1])
            return b_best, b_d

        # 批C-①: 同 parse_fraction_at(半径 tol*1.25 小方框区域化, 未命中回退全图)
        if self.config.get("region_ocr", True) and w and h:
            r = int(tol * 1.25)
            box = (max(0, tx - r) / w, max(0, ty - r) / h, min(w, tx + r) / w, min(h, ty + r) / h)
            rr = self._ocr_frame_region(img, box, need_split=False)
            if rr is not None:
                best, best_d = _scan(rr[0])
                if best is not None and best_d ** 0.5 <= tol:
                    return best
        best, best_d = _scan(self._ocr_frame(img, need_split=False)[0])
        if best is not None and best_d ** 0.5 <= tol:
            return best
        return None

    def eval_count(self, step, img=None) -> bool:
        """判断指定相对位置处 '关键字:N' 的数字 N 是否满足 condition (变量 N)。如 N>0。"""
        reg = step.get("region_rel")
        if not reg:
            print("[if_greater] 缺少 region_rel")
            return False
        n = self.parse_count_at(reg, img=img)
        if n is None:
            print(f"[if_greater] 区域{reg} 未识别到 '关键字:N' 数字")
            return False
        cond = step.get("condition", "N>0")
        if not re.fullmatch(r"[N0-9+\-*/<>!= ().,]+", cond):
            print(f"[if_greater] 非法条件 '{cond}'")
            return False
        try:
            ok = bool(eval(cond, {"__builtins__": {}}, {"N": n}))
        except Exception as e:
            print(f"[if_greater] 条件求值异常 '{cond}': {e}")
            return False
        print(f"[if_greater] 区域{reg} N={n} 条件'{cond}' -> {'TRUE' if ok else 'FALSE'}")
        return ok

    def count_text(self, kws, region_rel=None, img=None) -> int:
        """统计文本关键字在(限定时)区域内出现的总次数。跨 OCR 块去重: 挡块文本本身可能含多个关键字时按出现次数计。"""
        img = img if img is not None else self.screenshot()
        if img is None:
            return 0
        w, h = self.screen_w, self.screen_h
        blocks, _sub, used_region = self._ocr_candidates(img, region_rel, need_refine=False)
        hits = 0
        for _attempt in range(2):
            hits = 0
            for b in blocks:
                x1, y1, x2, y2 = b["box"]
                if region_rel:
                    rx1, ry1, rx2, ry2 = region_rel
                    if not (rx1 * w <= x1 and x2 <= rx2 * w and ry1 * h <= y1 and y2 <= ry2 * h):
                        continue
                text = b.get("text", "")
                for kw in (kws if isinstance(kws, list) else [kws]):
                    hits += text.count(kw)
            if hits or not used_region:
                break
            # 批C-①: 区域化零命中 → 回退一次全图重试(语义同 find_text); O2: 只数块 -> 不拆分
            blocks = self._ocr_frame(img, need_split=False)[0]
            used_region = False
        print(f"[count_text] {kws} 区域{region_rel or '全屏'} 命中 {hits} 次")
        return hits

    def eval_fraction(self, step, img=None) -> bool:
        """判断某个相对位置处 'a/b' 数字是否满足 condition。
        condition 使用变量 a(分子)/b(分母) 的表达式, 如 'a<b'、'a>=20'。返回 True/False。
        """
        reg = step.get("region_rel")
        if not reg:
            print("[if_fraction] 缺少 region_rel")
            return False
        res = self.parse_fraction_at(reg, img=img)
        if res is None:
            print(f"[if_fraction] 区域{reg} 未识别到 'a/b' 数字块")
            return False
        a, b = res
        cond = step.get("condition", "a<b")
        # 配置可信, 但仅放行数字/变量/运算符, 避免任意代码
        if not re.fullmatch(r"[ab0-9+\-*/<>!= ().,]+", cond):
            print(f"[if_fraction] 非法条件 '{cond}'")
            return False
        try:
            ok = bool(eval(cond, {"__builtins__": {}}, {"a": a, "b": b}))
        except Exception as e:
            print(f"[if_fraction] 条件求值异常 '{cond}': {e}")
            return False
        print(f"[if_fraction] 区域{reg} a={a}/b={b} 条件'{cond}' -> {'TRUE' if ok else 'FALSE'}")
        return ok

    def store_fraction(self, step: dict, img=None) -> bool:
        """读取指定相对位置处 'a/b' 数字的分子(a), 存入 config 并持久化。
        用于记录『已浇水次数』等带冷却/每日上限的行为, 便于流程判断当天是否已满。
        键名规则: config[step.key]=a, config[step.key+"_date"]=YYYYMMDD。
        读取不到 a/b 时返回 False (不写入)。
        """
        reg = step.get("region_rel")
        key = step.get("key")
        if not reg or not key:
            print("[store_fraction] 缺少 region_rel/key")
            return False
        res = self.parse_fraction_at(reg, img=img)
        if res is None:
            print(f"[store_fraction] 区域{reg} 未识别到 'a/b', 不写入")
            return False
        a, _b = res
        self.update_config(**{key: a, key + "_date": time.strftime("%Y%m%d")})
        print(f"[store_fraction] 区域{reg} a/b={a}/{_b} -> 已存 {key}={a}")
        return True

    def eval_config(self, step: dict) -> bool:
        """判断 config 中键值是否满足条件, 用于流程内做配置开关。返回 True/False。
        step: {key, value, op} op ∈ {==,!=,>=,<=,>,<}, 默认 ==。
        value 支持 ${key} 占位符解析与 bool/int/str 自动转换。
        """
        key = step.get("key")
        if not key:
            print("[if_config] 缺少 key")
            return False
        raw = self.config.get(key)
        want_raw = self.resolve(str(step.get("value", "")))
        if want_raw in ("True", "true"):
            want = True
        elif want_raw in ("False", "false"):
            want = False
        else:
            try:
                want = int(want_raw)
            except (TypeError, ValueError):
                want = want_raw
        op = step.get("op", "==")
        try:
            ok = {
                "==": lambda: raw == want,
                "!=": lambda: raw != want,
                ">=": lambda: raw >= want,
                "<=": lambda: raw <= want,
                ">": lambda: raw > want,
                "<": lambda: raw < want,
            }[op]()
        except Exception as e:
            print(f"[if_config] 比较失败 {key}={raw} {op} {want}: {e}")
            return False
        print(f"[if_config] config[{key}]={raw} {op} {want} -> {'TRUE' if ok else 'FALSE'}")
        return ok

    def _calc_int(self, formula, a, b) -> int:
        """受信配置内安全求值整数公式。可用变量 a=分子, b=分母, 函数 ceil()/floor(), 四则运算。
        非法字符/求值异常抛 ValueError / 返回 0。
        """
        if not re.fullmatch(r"[a-zA-Z0-9+\-*/<>!= ().,]+", formula):
            raise ValueError(f"非法公式 '{formula}'")
        ns = {"a": a, "b": b, "ceil": math.ceil, "floor": math.floor}
        try:
            return int(eval(formula, {"__builtins__": {}}, ns))
        except Exception as e:
            raise ValueError(f"公式求值异常 '{formula}': {e}")

    def run_loop_fraction(self, step, indent=0):
        """按『分数区域算出的循环次数』重复执行 do 子流程。
        iterations: [{region_rel, formula}] 各自从相对位置读取 a/b 并按公式算一个整数值;
        combine: 取 min(默认) 或 max 合并; 结果再夹到 max_loop; 为 0 则不循环。
        典型用法: n=ceil((b-a)/57) 与 m=floor(a/20), combine=min → 每次消耗 20 体力直到结束或所需满足。
        """
        pad = "  " * indent
        img = self.screenshot()
        vals = []
        for spec in step.get("iterations", []):
            res = self.parse_fraction_at(spec["region_rel"], img=img)
            if res is None:
                print(f"{pad}[loop_fraction] 区域{spec['region_rel']} 未识别到 a/b, 循环次数=0")
                return
            v = self._calc_int(spec["formula"], res[0], res[1])
            print(f"{pad}[loop_fraction] 区域{spec['region_rel']} a={res[0]} b={res[1]} 公式'{spec['formula']}' -> {v}")
            vals.append(v)
        combine = step.get("combine", "min")
        m = min(vals) if combine != "max" else max(vals)
        if m < 0:
            m = 0
        m = min(m, step.get("max_loop", 100))
        print(f"{pad}[loop_fraction] 合并({combine})={vals} -> 循环 {m} 次")
        # 一次性步骤(如读完顶栏后点「光偶像」进入新界面), 在循环前执行一次
        if step.get("once"):
            print(f"{pad}[loop_fraction] 执行入场步骤 once")
            self.run_steps(step["once"], indent=indent + 1)
        for i in range(m):
            print(f"{pad} --- 逻辑 {i + 1}/{m} ---")
            self.run_steps(step.get("do", []), indent=indent + 1)

    def _pink_ratio_at(self, pt, img, color_cfg: dict, tol: int) -> float:
        """统计命中点附近小窗口内「粉色」像素占比。

        2026-10-24: 用于『粉色关闭钮』的二次校验。右上角的「收起菜单」是**纯白箭头**(无文字),
        与 close_corner_pink.png(白圆+粉花) 的背景/白色轮廓相近, 实测能以 0.865 骗过 0.85 阈值,
        点下去会收起右侧功能菜单 → 手账/在线礼包等按钮消失, 后续模块整段失效。
        真关闭钮必然带粉色(粉花或粉圆钮), 模板本体实测粉色占比 5.6%;
        白色箭头窗口内为 0.0%。用该占比做「纯白图标」否决项。
        """
        import cv2
        import numpy as np
        h, w = img.shape[:2]
        x1, y1 = max(0, pt.x - tol), max(0, pt.y - tol)
        x2, y2 = min(w, pt.x + tol), min(h, pt.y + tol)
        patch = img[y1:y2, x1:x2]
        if patch.size == 0:
            return 0.0
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array(color_cfg["hsv_lower"]),
                           np.array(color_cfg["hsv_upper"]))
        return float(cv2.countNonZero(mask)) / float(mask.size)

    def _locate_close_by_entry(self, entry: dict, img, w, h, quiet: bool = False):
        """按单条『关闭按钮-特殊逻辑』注册项尝试定位。
        返回 `(Point, channel, score)` 或 None；channel ∈ `anchor` / `template` / `color`。
        score 仅模板通道有值(1−sqdiff)，供 P1-2 批2 在同通道内排序；
        锚点(靠标题文字自证)与色块(无相似度概念)不参与跨通道比分数。
        quiet=True: 不打印（点后复检用，避免常态 MISS 刷屏）。
        """
        t = entry.get("type")
        color = entry.get("color", {})
        if t == "anchor_color":
            pt = self.locate_anchor_color(
                entry.get("anchor", "提示"), color,
                dx_range=entry.get("dx_range", (150, 400)),
                dy_tol=entry.get("dy_tol", 60),
                img=img, min_score=entry.get("min_score", 0.4), quiet=quiet)
            return (pt, "anchor", None) if pt is not None else None
        if t in ("corner", "corner_white", "corner_pink_small"):
            # region_rel: [x1,y1,x2,y2] 相对坐标(0~1) → 转绝对坐标
            rx = entry.get("region_rel", [0.82, 0.0, 1.0, 0.18])
            region_abs = [max(0, int(rx[0] * w)), max(0, int(rx[1] * h)),
                          min(w, int(rx[2] * w)), min(h, int(rx[3] * h))]
            # 支持模板优先: 注册项带 template 字段时, 先在该区内做模板匹配(纯图形关闭钮更稳);
            # 未命中再回退原颜色特征定位。
            tpl = entry.get("template")
            if tpl:
                rr = [rx[0], rx[1], rx[2], rx[3]]
                got = self.locate_template(tpl, img=img,
                                           region_rel=rr,
                                           threshold=entry.get("template_threshold", 0.8),
                                           return_score=True, quiet=quiet)
                pt, score = got if got is not None else (None, None)
                # 2026-10-24: 粉色一致性否决 —— 纯白图标(右上角「收起菜单」箭头)会以中等分
                # 误命中粉色关闭模板; 模板命中点附近没有粉色块时弃用, 交回下面的颜色兜底。
                if pt is not None and entry.get("verify_pink") and color:
                    tol = max(20, int(0.05 * h))
                    ratio = self._pink_ratio_at(pt, img, color, tol)
                    need = float(entry.get("verify_pink_ratio", 0.02))
                    if ratio < need:
                        if not quiet:
                            print(f"[关闭按钮] '{entry.get('name', '?')}' 模板命中({pt.x},{pt.y})"
                                  f" 但附近粉色占比 {ratio:.1%} < {need:.0%}, 判为纯白图标, 弃用")
                        pt = None
                if pt is not None:
                    return (pt, "template", score)
            cfg = dict(color)
            cfg["region"] = region_abs
            pt = self.locate_color(cfg, img=img)
            return (pt, "color", None) if pt is not None else None
        return None

    def find_all_close_buttons(self, img=None, only_types=None) -> list:
        """遍历『关闭按钮-特殊逻辑』注册表, 返回**所有**可定位到的关闭按钮候选。
        每个已注册类型一个条目 `{"name":..., "type":..., "pt": Point}`, 未命中/异常类型不入列。
        支持的特殊逻辑 type:
          - "anchor_color": 以锚点文字(如「提示」)为锚, 在其右侧 dx_range 内按颜色找关闭按钮
          - "corner": 在画面固定相对区域(如右上角)按颜色找关闭按钮

        2026-10-24(P1-1): 新增 only_types —— **遍历前**跳过不在白名单里的条目。
        原先 close_dialog 是「先全表定位、后按类型过滤」, 指定 only_types 时仍会白跑其它类型的
        OCR 锚点(实测每个 close_dialog 多打 3 次 `[锚点定位] 未找到…` + 2~4 次无关模板匹配),
        一轮 31 分钟日志里 `['跳转页签']` 这类无效锚点探测共 30 次。
        """
        img = img if img is not None else self.screenshot()
        w, h = self.screen_w, self.screen_h
        allowed = None
        if only_types is not None:
            allowed = {only_types} if isinstance(only_types, str) else set(only_types)
        hits = []
        for entry in self.close_buttons:
            name = entry.get("name", "?")
            if allowed is not None and entry.get("type") not in allowed:
                continue
            try:
                res = self._locate_close_by_entry(entry, img, w, h)
            except Exception as e:
                print(f"[关闭按钮] 逻辑 '{name}' 执行异常: {e}")
                res = None
            if res is not None:
                pt, channel, score = res
                hits.append({"name": name, "type": entry.get("type"), "pt": pt,
                             "channel": channel, "score": score,
                             "score_base": entry.get("score_base"),
                             "rank_last": bool(entry.get("rank_last")), "entry": entry})
        return hits

    def find_close_button(self, img=None) -> "Point | None":
        """遍历注册表返回**第一个**命中的关闭按钮; 全未命中返回 None。
        （兼容调用方/--close-test; 需要"逐个试所有类型"请用 find_all_close_buttons() 或 close_dialog()）
        """
        hits = self.find_all_close_buttons(img=img)
        if hits:
            h = hits[0]
            print(f"[关闭按钮] 特殊逻辑 '{h['name']}' 命中 -> {h['pt'].x},{h['pt'].y}")
            return h["pt"]
        return None

    def _verify_close_candidate(self, hit: dict, wait: float) -> bool:
        """点后复检: 该候选的“存在证据”是否已消失（P1-2 批2）。

        比全屏帧差更准：只复核**该候选自身**，不受无关动画/滚动干扰。
          · 锚点 → 标题文字/锚点侧按钮不再命中
          · 模板 → 同模板在同一区域已低于阈值
          · 色块 → 该区域不再有匹配色块
        复检走 `quiet=True`，不刷常态 MISS 日志。
        """
        time.sleep(max(0.2, float(wait)))
        img = self.screenshot()
        if img is None:
            return False
        entry = hit.get("entry")
        if not entry:
            return False
        try:
            res = self._locate_close_by_entry(entry, img, self.screen_w, self.screen_h, quiet=True)
        except Exception:
            res = None
        return res is None

    def close_dialog(self, img=None, anchor_kw="提示", dx_range=(150, 400),
                     dy_tol=60, min_score=0.4, only_types=None,
                     verify_wait: float = 1.2, max_tries: int = 2) -> bool:
        """关闭通用弹窗（P1-2 批2 起：语义优先 → 同通道分数 → 点后复检 → 至多 2 次）。

        选择顺序：
          1) **Tier 1 锚点**（anchor_color）：靠面板标题文字自证，按注册表顺序先试；
          2) **Tier 2 其余候选**：模板通道内按模板分降序；纯色块用 `score_base`（默认 0.60，
             `corner_white` 在 JSON 里配 0.70）——**不做跨通道分数比较**；
          3) 每次点击后用 `_verify_close_candidate` 复核；未关闭才试下一个，最多 `max_tries` 次。

        共享小✕门控（2026-10-24 用户裁定）：`corner_pink_small` 在通用链里仍参与（大多数面板关闭
        就是这枚 ✕），但当前帧若命中**户外主界面 / 家园界面 / 好友列表**（这些画面有右上角「收起菜单」
        且没有面板可关）则跳过；调用方**显式 `only_types`** 点名时不受门控。

        only_types: 可选, 字符串或类型列表; 仅在注册表中挑选指定类型, **遍历前**过滤（P1-1）。
        （anchor_kw/dx_range/dy_tol 参数仅为兼容旧调用保留, 实际以注册表为准。）
        返回语义保持旧版：**True=至少点击了一次**（不表示“已验证关闭”），False=没有可用候选。
        """
        img = img if img is not None else self.screenshot()
        hits = self.find_all_close_buttons(img=img, only_types=only_types)
        if not hits:
            print("[关闭弹窗(only_types)] 未定位到匹配类型的关闭按钮")
            return False

        def _fmt(x):
            s = x.get("channel") or "?"
            if x.get("score") is not None:
                s += f" {x['score']:.3f}"
            elif x.get("score_base") is not None:
                s += f" base {float(x['score_base']):.2f}"
            return f"'{x['name']}' ({x['type']}, {s})"

        # 主界面门控（2026-10-24 用户裁定「这些画面有右上角关闭菜单按键」）：
        # 共享小✕ 与纯白圆都可能在 户外/家园/好友列表 命中「收起菜单」白箭头/空白，
        # 通用链整体跳过它们；显式 only_types 视为调用方已确知面板开着，不受门控。
        # corner(粉色花钮) 不受门控 —— 它已有 verify_pink 保护，且花园上的家族面板需要它。
        GATE_TYPES = ("corner_pink_small", "corner_white")
        gated = False
        if only_types is None and any(x["type"] in GATE_TYPES for x in hits):
            on_main = any(self.judge_scene(n, img=img, quiet=True)
                          for n in ("户外主界面", "家园界面", "好友列表"))
            if on_main:
                gated = True
                print("[关闭弹窗] 当前为主界面(户外/家园/好友列表): 共享小✕/纯白圆不参与(防收起菜单/空白误点)")
                hits = [x for x in hits if x["type"] not in GATE_TYPES]
                if not hits:
                    print("[关闭弹窗] 门控后无候选")
                    return False

        def _eff(x):
            if x.get("score") is not None:
                return float(x["score"])
            return float(x.get("score_base") or 0.60)

        anchors = [x for x in hits if x.get("channel") == "anchor"]
        # rank_last 条目(共享小✕)永久排在 Tier 2 末尾：它在任意画面都能 0.9x 命中，
        # 拿原始分与独立关闭钮比较会反客为主（推荐活动页实测 0.911 > corner 色块 0.60）；
        # 但“大多数面板关闭就是这枚 ✕”仍然成立 —— 它是唯一候选时照常点击。
        rest = [x for x in hits if x.get("channel") != "anchor"]
        rest.sort(key=lambda x: (bool(x.get("rank_last")), -_eff(x)))
        ordered = anchors + rest
        # 同点去重：不同条目可能定位到同一颗按钮（corner 色块 / corner_white 白圆 / family 色块），
        # 重复点同一坐标 = 多余点击 + 双击风险 → 只保留排名最高的一个。
        tol = max(8, int(0.01 * (self.screen_w or 1280)))
        uniq = []
        for h in ordered:
            if any(abs(h["pt"].x - u["pt"].x) <= tol and abs(h["pt"].y - u["pt"].y) <= tol
                   for u in uniq):
                continue
            uniq.append(h)
        if len(uniq) < len(ordered):
            print(f"[关闭弹窗] 合并同点候选 {len(ordered) - len(uniq)} 个(防重复点击同一按钮)")
        ordered = uniq
        print("[关闭弹窗] 候选: " + " | ".join(_fmt(x) for x in ordered)
              + ("  (小✕已门控)" if gated else ""))

        tries = max(1, int(max_tries))
        clicked = 0
        for i, h in enumerate(ordered[:tries], 1):
            pt = h["pt"]
            print(f"[关闭弹窗] 第{i}次选中 {_fmt(h)} -> {pt.x},{pt.y}")
            self.click_abs(pt.x, pt.y)
            self._log_click("弹窗关闭", [anchor_kw], pt, "color")
            clicked += 1
            if self._verify_close_candidate(h, verify_wait):
                print(f"[关闭弹窗] 已确认关闭(复检: {h.get('channel')}证据消失, 等待{verify_wait:g}s)")
                return True
            if i < min(tries, len(ordered)):
                print("[关闭弹窗] 未确认关闭 -> 尝试下一候选")
        print(f"[关闭弹窗] {clicked} 次点击后仍未确认关闭(如实报出; 返回 True=已点击, 交调用方复核)")
        return True

    def ensure_menu_expanded(self, step: dict | None = None) -> bool:
        """顶部活动菜单被「收起菜单」折叠时, 点右上角白色箭头展开(2026-10-24 P1-3)。

        背景: 2026-10-24 实机日志里 close_dialog 误点右上角「收起菜单」纯白箭头 → 顶部菜单整排
        收起, `手账`/`在线礼包` 入口消失 → claim 在线礼包静默跳过、daily 手账整模块失败。
        误点本身已由 close_buttons.json 的 `verify_pink` 拦住; 本方法负责**已处于收起态**时的自愈
        (人工误点 / 上一轮遗留 / 其它路径收起)。

        判据(全部满足才动作):
          ① 常驻入口「推荐活动」在屏 → 确认当前有顶部菜单带;
          ② 「手账」与「在线礼包」都读不到 → 收起态特征(展开态二者必有其一);
          ③ 右上角 collapse_menu.png 命中(默认阈值 0.95) 且命中点附近**没有粉色**
             (占比 < 2%) —— 收起态白箭头实测 0.0%; 推荐活动页右上角的粉色✕实测 8.9%/9.1%,
             会被粉色否决; 且该✕在区域内的模板分更低, 双保险。
        动作: 点一次箭头 → 等 1.5s → 复检; 仍未展开只告警(返回 False), 不抛错、不登记失败。
        返回 True=已展开 / 无需动作(含「疑似收起但箭头未确认」——宁可不动);
        False=点击箭头后仍未能确认展开(只告警)。
        """
        step = step or {}
        region = step.get("region_rel") or [0.94, 0.035, 1.0, 0.10]
        threshold = float(step.get("threshold", 0.95))
        pink_max = float(step.get("pink_max", 0.02))
        wait = float(step.get("wait", 1.5))
        img = self.screenshot()
        if img is None:
            return True
        hit = self._kw_hits(self._scene_blocks(img, 0.4), ["推荐活动", "手账", "在线礼包"])
        if "手账" in hit or "在线礼包" in hit:
            return True                      # 展开态: 入口可见, 不动
        if "推荐活动" not in hit:
            return True                      # 不在有顶部菜单的画面, 不动
        pink_cfg = {"hsv_lower": [150, 80, 90], "hsv_upper": [175, 255, 255]}
        got = self.locate_template("collapse_menu.png", img=img,
                                   region_rel=region, threshold=threshold, return_score=True)
        pt, tpl_score = got if got is not None else (None, None)
        if pt is None:
            print("[菜单] 疑似收起(推荐活动在屏/手账与在线礼包均不可见), 但右上角箭头未命中 -> 不动作")
            return True
        # 2026-10-26(codex-20261025-7 实机反馈): 收起态的箭头模板分可达 0.982, 但同窗口内的
        # 邻近粉色装饰会把粉色占比推到 14.9% -> 旧逻辑错误否决、菜单无法自愈。
        # 高分(≥0.96)已足以确认是 arrow 本体, 跳过粉色否决; 低分候选仍保留否决
        # (推荐活动页右上角粉色✕的模板分低于箭头, 由阈值+粉色双保险拦住)。
        if tpl_score is not None and tpl_score >= 0.96:
            print(f"[菜单] 箭头模板分 {tpl_score:.3f} ≥ 0.96, 跳过粉色否决(高置信白箭头)")
        else:
            ratio = self._pink_ratio_at(pt, img, pink_cfg, max(20, int(0.05 * self.screen_h)))
            if ratio >= pink_max:
                print(f"[菜单] 右上角候选({pt.x},{pt.y})粉色占比 {ratio:.1%} ≥ {pink_max:.0%}, "
                      f"判为粉色关闭钮/其它图标(非收起箭头), 不动作")
                return True
        print(f"[菜单] 顶部菜单已收起(手账/在线礼包均不可见) -> 点右上角箭头 ({pt.x},{pt.y}) 展开")
        self.click_abs(pt.x, pt.y)
        time.sleep(wait)
        img2 = self.screenshot()
        if img2 is None:
            return False
        hit2 = self._kw_hits(self._scene_blocks(img2, 0.4), ["手账", "在线礼包"])
        if hit2:
            print(f"[菜单] 展开成功: {sorted(hit2)} 已可见")
            return True
        print("[菜单] 箭头已点击, 但仍未读到手账/在线礼包 -> 如实告警(不判失败, 交后续步骤)")
        return False

    def click_text(self, keywords, img=None, fallback_rel=None, min_score=0.5, exact=False,
                   region_rel=None, exclude=None, no_fallback=False) -> bool:
        """OCR 定位关键字并点击。命中返回 True。
        回退链: OCR → 颜色特征(若知识库有 color 配置) → 进程缓存 → 知识库坐标 → 失败
        exact=True 时用精确匹配(要求块文本完全等于关键字)。
        no_fallback=True 时**禁止缓存回退**: OCR/锚点/颜色全部未命中就直接如实返回 False,
        不采信任何历史坐标盲点。用于「点错后果严重」的高危按钮(如「切换账号」一旦盲点到
        「登录」就会用错误账号跑完当天全部任务), 宁可失败交调用方处置。
        全局开关 `use_cache_pos`(data/config.json, **默认 false**) 关闭时, **自动学习到的缓存**整条停用:
        「均值复核」(拿历史均值 veto 本次 OCR 命中)不执行, 回退链也不再查 `mean_rel`/进程缓存 `last_rel`/
        知识库 `rel`。但**步骤里显式手写的 `fallback_rel` 仍生效** —— 那是人工设计的兜底(flows 中数十处),
        与"自动学到的历史坐标"性质不同, 全局开关不得静默禁用它。
        no_fallback(步骤级)比全局开关更严格: 连显式 `fallback_rel` 一并禁用, 只认本次实时识别结果。
        配套开关 `log_click_pos`(**默认 false**) 关闭时 `_log_click` 不再把坐标写入知识库(见 docstring)。
        region_rel 给定时只在限定区域内找文字, 并**跳过均值复核**: 同一个按钮在界面上出现多次时
        (如花灵派对面板里多处「领取」)单一均值必然对不上, 区域限定本身已是可信来源,
        不能再让缓存 veto 掉一个真实的 OCR 命中(缓存回退不得作为命中判据)。
        其余情况方案②复核: OCR 命中点与该按钮(按当前场景)历史均值偏差 > BIAS_MAX_PX 时判为可疑,
        触发局部放大重识别(_refine_hit)校准; 无更优子块时, 偏差未超 BIAS_HARD_PX 则沿用原命中并记录日志,
        超过 BIAS_HARD_PX 则判为误命中并**弃用**(不点击/不写知识库), 交由回退链(均值/缓存)处理。
        """
        kw0 = keywords[0] if isinstance(keywords, list) else keywords
        # 全局开关「使用缓存位置」(use_cache_pos) 默认关闭: 关闭后不采信**自动学习到的**历史坐标
        # ——既不做「均值复核」(拿历史均值去 veto 本次 OCR 命中), 也不走缓存回退(不查 mean_rel/last_rel/
        # 知识库 rel)。步骤里显式手写的 fallback_rel 属人工兜底, 不受此开关影响(见 docstring)。
        use_cache = bool(self.config.get("use_cache_pos", False))
        # 批B 相邻定位复用: 上一步(if_text/wait_text)刚命中的同一点位, 若本次 click_text 的查询
        # 参数兼容(关键字子集/区域子集/阈值不更松/exact 兼容/未传 img/不在均值复核路径)且该点位
        # 自身满足本次判据, 则直接复用 —— 免去二次截图 + 全图 OCR。不兼容返回 None 走原路径。
        guard_pt = self._take_guard_point(keywords, img, min_score, exact,
                                          region_rel, exclude, use_cache)
        if guard_pt is not None:
            self._last_locate_source = "ocr"
            mt = getattr(self, "_last_match_text", None)
            tag = f" 命中块文字'{mt}'" if mt and mt != kw0 else ""
            print(f"[OCR命中] {keywords} -> {guard_pt.x},{guard_pt.y}{tag} (复用上一步守卫定位, 免重扫)")
            self.click_abs(guard_pt.x, guard_pt.y)
            self._log_click(kw0, keywords, guard_pt, "ocr", category=self._step_category)
            return True
        pt = self.locate(keywords, img=img, min_score=min_score, exact=exact,
                         region_rel=region_rel, exclude=exclude)
        dropped_by_review = False   # 是否被复核判为误命中而弃用(用于日志如实描述, 不能与"未OCR到"混淆)
        if pt is not None and region_rel is not None:
            print(f"[复核] {kw0} 区域限定{list(region_rel)}, 跳过均值复核")
        elif pt is not None and not use_cache:
            # 同一条全局事实不要在每次 OCR 命中时重复刷屏(提示只打一次)
            if not getattr(self, "_cachepos_notice_done", False):
                self._cachepos_notice_done = True
                print("[复核] 使用缓存位置已关闭(use_cache_pos=false), 不做均值复核、不用历史坐标回退(本提示只打一次)")
        if pt is not None and region_rel is None and use_cache:
            entry = self._entry_for(kw0)
            mean = entry.get("mean_rel") if entry else None
            dev = self._bias_px(pt, mean, self.screen_w, self.screen_h)
            if dev is not None and dev > BIAS_MAX_PX:
                print(f"[复核] {kw0} OCR命中({pt.x},{pt.y}) 与场景均值{tuple(round(v,3) for v in mean)} "
                      f"偏差{dev:.0f}px > {BIAS_MAX_PX}px, 二次精细处理…")
                rp = self._refine_hit(kw0, pt, img if img is not None else self.screenshot())
                dev2 = self._bias_px(rp, mean, self.screen_w, self.screen_h) if rp is not None else None
                if dev2 is not None and dev2 < dev:
                    print(f"[复核] 局部重识别得更稳子块({rp.x},{rp.y}) 偏差{dev2:.0f}px, 校准确认")
                    pt = rp
                elif dev > BIAS_HARD_PX:
                    print(f"[复核] 偏差{dev:.0f}px 超硬阈值 {BIAS_HARD_PX}px 且无更优子块, 判为误命中, 弃用该 OCR 命中")
                    pt = None                     # 不可信 -> 不点击/不写库, 交回退链
                    dropped_by_review = True
                else:
                    print(f"[复核] 局部重识别无更优子块, 沿用 OCR 命中")
        if pt is not None:
            self._last_locate_source = "ocr"
            mt = getattr(self, "_last_match_text", None)
            # 如实打印实际命中的原始文字: 关键字是子串匹配, 「领取」命中的可能是「已领取」,
            # 不报出来就会被误读成"识别到了领取按钮"。
            tag = f" 命中块文字'{mt}'" if mt and mt != kw0 else ""
            print(f"[OCR命中] {keywords} -> {pt.x},{pt.y}{tag}")
            self.click_abs(pt.x, pt.y)
            self._log_click(kw0, keywords, pt, "ocr", category=self._step_category)
            return True
        # 锚点偏移定位 (固定尺寸界面, 如登录界面无文字图形按钮)
        kws = keywords if isinstance(keywords, list) else [keywords]
        for kw in kws:
            entry = self.click_log.get(kw)
            if entry and "anchor" in entry:
                pt_a = self.locate_anchor_offset(entry["anchor"], img=img)
                if pt_a is not None:
                    self._last_locate_source = "anchor"
                    print(f"[锚点偏移命中] {kw} -> {pt_a.x},{pt_a.y}")
                    self.click_abs(pt_a.x, pt_a.y)
                    self._log_click(kw, [kw], pt_a, "anchor", category=self._step_category)
                    return True
        # 颜色特征检测 (针对无文字的图形按钮)
        for kw in kws:
            entry = self.click_log.get(kw)
            if entry and entry.get("method") == "color" and "color" in entry:
                pt_c = self.locate_color(entry["color"], img=img)
                if pt_c is not None:
                    self._last_locate_source = "color"
                    print(f"[颜色命中] {kw} -> {pt_c.x},{pt_c.y}")
                    self.click_abs(pt_c.x, pt_c.y)
                    self._log_click(kw, [kw], pt_c, "color", category=self._step_category)
                    return True
        if no_fallback:
            # 高危按钮: 本次实时识别(OCR/锚点/颜色)全部未命中时, 连步骤里显式写的回退坐标也不盲点
            # (2026-10-03: 「切换账号」OCR 永远认不到折角图标, 一路回退到历史坐标 (989,283),
            #  该点此时已是「登录」-> 误登录, 公告/进入游戏/收尾守卫全部空转)。
            self._last_locate_source = "none"
            print(f"[未命中] {keywords} (no_fallback=True: 禁用一切缓存/回退坐标, 交调用方处置)")
            self.dump_full_frame(f"未命中:{kw0}")
            return False
        # OCR+锚点+颜色均未命中: 尝试回退缓存 (方案②: 均值点补齐优先于进程缓存/最新坐标; 再无知识库坐标)
        if fallback_rel is None:
            if not use_cache:
                # 全局开关「使用缓存位置」(use_cache_pos) 默认关闭: 不查自动学习到的历史坐标
                # (mean_rel 均值 / last_rel 进程缓存 / click_log 知识库坐标), 认不到就如实失败。
                # 注意: 只挡"自动缓存"; 上面 no_fallback 分支已放行步骤里显式手写的 fallback_rel。
                self._last_locate_source = "none"
                print(f"[未命中] {keywords} (use_cache_pos=false: 不用自动缓存的历史坐标, 交调用方处置)")
                self.dump_full_frame(f"未命中:{kw0}")
                return False
            for kw in kws:
                e = self._entry_for(kw)
                if e and e.get("mean_rel"):
                    fallback_rel = tuple(e["mean_rel"])
                    break
            if fallback_rel is None:
                for kw in kws:
                    if kw in self.last_rel:
                        fallback_rel = self.last_rel[kw]
                        break
            if fallback_rel is None:
                for kw in kws:
                    e = self.click_log.get(kw) or {}
                    if e.get("method") == "fallback":
                        # 回退坐标不是位置证据, 不得再当作缓存复用 —— 否则一次"没识别到就盲点"会把错坐标
                        # 反复续传(毒坐标自我强化)。本条防御与 _log_click 的"fallback 不落库"配套。
                        print(f"[回退] 跳过 [{kw}] 的历史缓存回退条目(method=fallback, 非位置证据)")
                        continue
                    rel = e.get("rel")
                    if rel:
                        fallback_rel = tuple(rel)
                        break
        if fallback_rel is not None:
            self._last_locate_source = "fallback"
            reason = "复核弃用后回退" if dropped_by_review else "未OCR到"
            print(f"[回退缓存] {keywords} {reason}, 用缓存 {fallback_rel}")
            pt_fb = Point.from_rel(fallback_rel[0], fallback_rel[1], self.screen_w, self.screen_h)
            self.click_rel(*fallback_rel)
            self._log_click(kw0, keywords, pt_fb, "fallback", category=self._step_category)
            return True
        self._last_locate_source = "none"
        print(f"[未命中] {keywords}")
        return False

    # ---- 相邻定位复用 (性能批 zcode-20261007-16 批B) ----
    @staticmethod
    def _region_within(c, g) -> bool:
        """相对区域 c 是否被 g 包含(None=全图)。坐标均为 [x1,y1,x2,y2] (0~1), 归一化同帧可比。"""
        if g is None:
            return True          # 守卫全图 -> 任何区域都在其内
        if c is None:
            return False         # 本次全图 ⊄ 守卫子区域
        return c[0] >= g[0] and c[1] >= g[1] and c[2] <= g[2] and c[3] <= g[3]

    def _remember_guard(self, kws, pt, exact, region_rel, min_score,
                        exclude=None) -> None:
        """记录一次定位守卫(if_text/wait_text)的**真实 OCR 命中**, 供**紧邻的下一步**
        click_text 复用同一命中点位。仅在真实命中处调用(缓存回退不在此列)。

        关键: 记下命中块 b 的 score/text 与守卫查询参数 —— click_text 复用时必须逐条校验
        (见 _take_guard_point): 复用点必须自身满足 click 的全部判据, 且 click 判据是守卫判据的
        "子集"(关键字/区域/阈值/exclude), 以保证收窄后 click 的首个命中仍是同一个块。
        """
        if not self.config.get("guard_reuse", True):
            return
        b = getattr(self, "_last_match_block", None) or {}
        kws = list(kws) if isinstance(kws, list) else [kws]
        self._guard_hit = {
            "seq": self._step_seq + 1,               # 仅紧邻的下一次 run_step 可复用
            "kws": frozenset(kws),
            "exact": bool(exact),
            "region": tuple(region_rel) if region_rel else None,
            "min_score": min_score,
            "exclude": frozenset(exclude or ()),
            "pt": pt,
            "text": (b.get("text") or "").strip(),
            "score": b.get("score", 1.0),
        }

    def _take_guard_point(self, keywords, img, min_score, exact, region_rel,
                          exclude, use_cache):
        """若存在**紧邻、兼容**的定位守卫, 复用其命中点位并返回 Point; 否则返回 None。

        安全规则(须全部满足; 任一不满足即返回 None, 走原 locate 路径):
          1) 仅紧邻下一步: 守卫的 seq == 当前步骤 seq(中间隔了任何步骤即失效);
          2) 未显式传 img: 复用点与守卫取自同一帧截图;
          3) 守卫 exact=False(if_text/wait_text 恒为子串匹配) 且 本次关键字 ⊆ 守卫关键字;
          4) 本次区域 ⊆ 守卫区域;  本次 min_score >= 守卫 min_score;  守卫 exclude ⊆ 本次 exclude;
          5) 不在 use_cache 的均值复核路径(region 为空且 use_cache 时, 正常路径会拿均值复核,
             复用会改变该行为, 故不复用);
          6) 复用点自身满足本次全部判据: score 达标 / 命中文字满足关键字语义 / 不含本次 exclude /
             落在本次区域内。
        全局开关 guard_reuse(data/config.json, 默认 true) 置 false 时, _remember_guard 不再记录,
        本方法恒返回 None —— 一键关闭该优化(无需改代码)。
        """
        if not self.config.get("guard_reuse", True):
            return None
        g = self._guard_hit
        if g is None or g["seq"] != self._step_seq or img is not None:
            return None
        if use_cache and region_rel is None:
            return None
        kws = list(keywords) if isinstance(keywords, list) else [keywords]
        if not (frozenset(kws) <= g["kws"]) or g["exact"]:
            return None
        if not self._region_within(region_rel, g["region"]):
            return None
        if min_score < g["min_score"]:
            return None
        ex = set(exclude or ())
        if not (g["exclude"] <= ex):
            return None
        pt, text, score = g["pt"], g["text"], g["score"]
        if score < min_score:
            return None
        if ex and any(e in text for e in ex):
            return None
        if region_rel is not None:
            w, h = self.screen_w, self.screen_h
            rx1, ry1 = int(region_rel[0] * w), int(region_rel[1] * h)
            rx2, ry2 = int(region_rel[2] * w), int(region_rel[3] * h)
            if not (rx1 <= pt.x <= rx2 and ry1 <= pt.y <= ry2):
                return None
        if not any((text == k) if exact else (k in text) for k in kws):
            return None
        # 通过全部校验: 一次性消费, 并补齐与正常命中一致的副作用(last_rel / _last_match_text)
        self._guard_hit = None
        for k in kws:
            self.last_rel[k] = pt.rel
        self._last_match_text = text or None
        return pt

    # ---- 模板匹配识别(纯图形/无文字按钮, 借鉴 MAA TemplateMatch) ----
    @staticmethod
    def _template_path(template: str):
        """解析模板文件名 -> 绝对路径(resource/template/ 下); 不存在返回 None。
        支持省略扩展名(自动补 .png)与子路径(相对 TEMPLATE_DIR)。
        """
        p = Path(template).expanduser()
        if not p.name.lower().endswith(".png"):
            p = p.with_suffix(".png")
        if p.is_absolute():
            return str(p) if p.exists() else None
        full = TEMPLATE_DIR / p
        return str(full) if full.exists() else None

    def locate_template(self, template: str, img=None, threshold=0.8,
                        region_rel=None, scale_range=(0.7, 1.0),
                        metric: str = "sqdiff", return_score: bool = False, quiet: bool = False):
        """模板匹配定位: 在截图中查找与模板图最匹配的位置(多尺度缩放), 返回模板中心 Point。
        借鉴 MAA TemplateMatch, 用于「纯图形(无文字)按钮」如花形关闭钮/折角切换钮等
        颜色或文字难以唯一化的图形。template: 模板文件名(资源根 resource/template/<template>)。
        region_rel: [x1,y1,x2,y2](0~1) 限定搜索区域提速/避干扰。最高分 < threshold 判未命中。
        return_score(2026-10-24, P1-2 批1): True 时返回 `(Point, score)` —— 供关闭按钮候选
        按分数比较/打印; False(默认) 行为与旧版逐字节一致。
        尺度自适应(2026-10-03): 模板均从 1280x720 截图裁切, 引擎按 screen_w/1280 把 scale_range
        整体缩放 —— 720p 下行为与旧版完全一致; 1080p 等更高分辨率自动等效放大搜索尺度
        (实测 close_family 在 1080p 需 scale≈1.5, 旧版 0.7~1.0 全部漏检)。
        metric(2026-10-03): "sqdiff"(默认, 与旧版一致) | "ccoeff"。可选能力, 本项目模板
        (同源截图裁切)实测 sqdiff 即精确命中(里程碑77 七块新模板 源图 0.99+ / 异图 0.33~0.99
        均低于各自阈值, 无假阳性; 早期引用的 b1_switch_down 已随登录页改版失效, 不再作证据);
        ccoeff 保留给「模板与当前背景明暗相反」的场景(相关系数对亮度偏移不敏感)。
        ⚠ 取分注意(2026-10-04 教训): TM_SQDIFF_NORMED 的结果图要取 minMaxLoc 的
        minVal/minLoc 才是最佳命中, 误用 maxVal/maxLoc 会把最差点当成命中 ——
        分析脚本与流程代码各踩过一次; 自测先怀疑自己的解包, 再下「假阳性」结论。
        """
        import cv2
        import numpy as np
        tpl_path = self._template_path(template)
        if tpl_path is None:
            print(f"[模板匹配] 模板不存在: {template}")
            return None
        tpl = cv2.imread(tpl_path, cv2.IMREAD_COLOR)
        if tpl is None:
            print(f"[模板匹配] 读取模板失败: {template}")
            return None
        img = img if img is not None else self.screenshot()
        if img is None:
            return None
        th, tw = tpl.shape[:2]
        if th >= img.shape[0] or tw >= img.shape[1]:
            print(f"[模板匹配] 模板({tw}x{th})不小于截图({img.shape[1]}x{img.shape[0]}), 无法定位")
            return None
        lo, hi = scale_range
        ref = (self.screen_w or img.shape[1]) / 1280.0  # 模板基准分辨率宽 1280
        scales = sorted(set(round(float(s * ref), 2) for s in np.linspace(lo, hi, 4)), reverse=True)
        higher = (metric == "ccoeff")  # ccoeff: max=最佳; sqdiff: min=最佳
        flag = cv2.TM_CCOEFF_NORMED if higher else cv2.TM_SQDIFF_NORMED
        best = None  # (score, mx, my, tw_r, th_r)  mx/my 为原图上命中左上角, tw_r/th_r 为该尺度模板宽高
        for sc in scales:
            tw_r, th_r = max(1, int(tw * sc)), max(1, int(th * sc))
            if th_r >= img.shape[0] or tw_r >= img.shape[1]:
                continue
            rtpl = cv2.resize(tpl, (tw_r, th_r))
            # sqdiff: 模板源自截图(同源抠图), 值越小越匹配, score=1-sqdiff 归一为「越大越匹配」
            shot = cv2.matchTemplate(img, rtpl, flag)
            if region_rel is not None:
                w, h = img.shape[1], img.shape[0]
                rx1, ry1 = int(region_rel[0] * w), int(region_rel[1] * h)
                rx2, ry2 = int(region_rel[2] * w), int(region_rel[3] * h)
                rx1, ry1 = max(0, rx1), max(0, ry1)
                rx2, ry2 = min(shot.shape[1], rx2), min(shot.shape[0], ry2)
                if rx2 <= rx1 or ry2 <= ry1:
                    continue
                sub = shot[ry1:ry2, rx1:rx2]
            else:
                rx1 = ry1 = 0
                sub = shot
            if higher:
                # minMaxLoc 返回 (minVal, maxVal, minLoc, maxLoc): ccoeff 取 maxVal/maxLoc
                _, mval, _, mlo = cv2.minMaxLoc(sub)   # max=最佳
                score = float(mval)
            else:
                mval, _, mlo, _ = cv2.minMaxLoc(sub)   # min=最佳
                score = 1.0 - float(mval)
            mmloc = (mlo[0] + rx1, mlo[1] + ry1)
            if best is None or score > best[0]:
                best = (score, mmloc[0], mmloc[1], tw_r, th_r)
        if best is None or best[0] < threshold:
            top = best[0] if best else 0.0
            if not quiet:
                print(f"[模板匹配] {template} 最高分 {top:.3f} < 阈值 {threshold}, 未命中")
            return None
        mval, mx, my, tw_r, th_r = best
        sw, sh = img.shape[1], img.shape[0]
        cx, cy = mx + tw_r // 2, my + th_r // 2  # 原图模板中心
        cx = max(0, min(sw - 1, cx))
        cy = max(0, min(sh - 1, cy))
        if not quiet:
            print(f"[模板匹配] {template} score={mval:.3f} -> ({cx},{cy})")
        point = Point(cx, cy, sw, sh)
        return (point, float(mval)) if return_score else point

    def locate_template_all(self, template: str, img=None, threshold=0.8,
                            region_rel=None, scale_range=(0.7, 1.0),
                            nms_gap_rel=0.05) -> "list[Point]":
        """模板匹配多命中: 一次匹配返回**所有**高于阈值的局部峰值点(跨尺度 NMS 去重)。

        与 locate_template 的区别: 后者只返回最高分单点; 本方法用于「一屏多个同形图标」
        的场景(如好友列表多个可采粉角标), 避免调用方逐带扫描重复做多尺度全图匹配(极大提速)。
        region_rel/scale_range 语义同 locate_template; 尺度同样按 screen_w/1280 自适应(见彼处注)。
        nms_gap_rel: 峰值去重半径(相对截图宽高), 多尺度会重复命中同一目标, 按此合并。
        """
        import cv2
        import numpy as np
        tpl_path = self._template_path(template)
        if tpl_path is None:
            print(f"[模板匹配] 模板不存在: {template}")
            return []
        tpl = cv2.imread(tpl_path, cv2.IMREAD_COLOR)
        if tpl is None:
            print(f"[模板匹配] 读取模板失败: {template}")
            return []
        img = img if img is not None else self.screenshot()
        if img is None:
            return []
        th, tw = tpl.shape[:2]
        if th >= img.shape[0] or tw >= img.shape[1]:
            print(f"[模板匹配] 模板({tw}x{th})不小于截图({img.shape[1]}x{img.shape[0]}), 无法定位")
            return []
        w, h = img.shape[1], img.shape[0]
        rx1 = ry1 = rx2 = ry2 = None
        if region_rel is not None:
            rx1, ry1 = int(region_rel[0] * w), int(region_rel[1] * h)
            rx2, ry2 = int(region_rel[2] * w), int(region_rel[3] * h)
            rx1, ry1 = max(0, rx1), max(0, ry1)
            rx2, ry2 = min(w, rx2), min(h, ry2)
            if rx2 <= rx1 or ry2 <= ry1:
                return []
        lo, hi = scale_range
        ref = (self.screen_w or img.shape[1]) / 1280.0  # 模板基准分辨率宽 1280 (尺度自适应, 见 locate_template)
        scales = sorted(set(round(float(s * ref), 2) for s in np.linspace(lo, hi, 4)), reverse=True)
        cands = []  # (score, cx, cy)
        for sc in scales:
            tw_r, th_r = max(1, int(tw * sc)), max(1, int(th * sc))
            if th_r >= img.shape[0] or tw_r >= img.shape[1]:
                continue
            rtpl = cv2.resize(tpl, (tw_r, th_r))
            shot = cv2.matchTemplate(img, rtpl, cv2.TM_SQDIFF_NORMED)
            sub = shot if region_rel is None else shot[ry1:ry2, rx1:rx2]
            smap = 1.0 - sub  # 越大越匹配
            # 找局部峰值(膨胀后等于自身)且过阈值
            kernel = np.ones((3, 3), np.uint8)
            dilated = cv2.dilate(smap, kernel)
            peak_mask = (smap >= dilated) & (smap >= threshold)
            ys, xs = np.nonzero(peak_mask)
            ox, oy = (rx1, ry1) if region_rel is not None else (0, 0)
            for yy, xx in zip(ys, xs):
                cx = ox + int(xx) + tw_r // 2
                cy = oy + int(yy) + th_r // 2
                cands.append((float(smap[yy, xx]), cx, cy))
        if not cands:
            print(f"[模板匹配] {template} 多命中: 无 (阈值 {threshold})")
            return []
        # 跨尺度 NMS: 高分优先, 与已接受点距离 < nms_gap 则跳过
        gap_x, gap_y = max(1, int(nms_gap_rel * w)), max(1, int(nms_gap_rel * h))
        cands.sort(key=lambda c: -c[0])
        accepted = []
        for s, cx, cy in cands:
            if all(abs(cx - ax) >= gap_x or abs(cy - ay) >= gap_y for ax, ay, _ in accepted):
                accepted.append((cx, cy, s))
        accepted.sort(key=lambda c: (c[1], c[0]))  # 按 y 从上到下
        print(f"[模板匹配] {template} 多命中 {len(accepted)} 个: "
              + ", ".join(f"({cx},{cy}@{s:.3f})" for cx, cy, s in accepted))
        return [Point(cx, cy, w, h) for cx, cy, _ in accepted]

    def click_template(self, template: str, img=None, threshold=0.8,
                       region_rel=None, scale_range=(0.7, 1.0), fallback_rel=None,
                       no_fallback=False, metric: str = "sqdiff",
                       offset_rel=None) -> "Point | None":
        """模板匹配点击: locate_template 命中则点击并记知识库(method=template)。
        未命中且有 fallback_rel 时回退到该相对坐标点击。返回命中的 Point, 否则 None。
        no_fallback=True 时忽略 fallback_rel: 未命中就如实返回 None, 不用回退坐标盲点
        (高危按钮「切换账号」类, 见 click_text 同名参数)。
        metric: 透传 locate_template("sqdiff"|"ccoeff"), 低对比模板用 ccoeff 防空白假阳性。
        offset_rel(2026-10-24): 命中后按屏幕相对比例偏移再点, 如 [-0.033,0.033]。
        用于「先匹配小徽标定位、再点它旁边的实体按钮」——点击点仍由**本次实时命中推导**,
        不是写死坐标(规则 6 合规); 偏移日志会明确标注。
        """
        pt = self.locate_template(template, img=img, threshold=threshold,
                                  region_rel=region_rel, scale_range=scale_range,
                                  metric=metric)
        if pt is not None:
            self._last_locate_source = "template"
            if offset_rel:
                px = int(pt.x + offset_rel[0] * (self.screen_w or 1280))
                py = int(pt.y + offset_rel[1] * (self.screen_h or 720))
                print(f"[模板匹配] {template} 命中({pt.x},{pt.y}) + 偏移{offset_rel} "
                      f"-> ({px},{py}) (偏移点由本次命中推导, 非写死坐标)")
                pt = Point(px, py, self.screen_w, self.screen_h)
            self.click_abs(pt.x, pt.y)
            self._log_click(template, [template], pt, "template", category=self._step_category)
            return pt
        if fallback_rel is not None and no_fallback:
            print(f"[未命中] 模板 {template} (no_fallback=True: 虽有回退坐标 {fallback_rel} 也不盲点)")
            return None
        if fallback_rel is not None:
            self._last_locate_source = "fallback"
            print(f"[回退缓存] 模板 {template} 未命中, 用回退坐标 {fallback_rel}")
            self.click_rel(*fallback_rel)
            pt = Point.from_rel(fallback_rel[0], fallback_rel[1], self.screen_w, self.screen_h)
            self._log_click(template, [template], pt, "fallback", category=self._step_category)
            return pt
        return None

    # ---- 流程执行 ----
    @staticmethod
    def _check_stop():
        """在需要中断的位置调用: 若已请求停止则抛 StopRequested 中断流程。"""
        if stop_requested():
            raise StopRequested("收到停止请求, 中断流程")

    def wait_text(self, keywords, timeout=30, interval=1.0, need_refine: bool = True,
                  min_score: float = 0.5):
        """轮询等待某文字出现, 返回 Point; 超时返回 None。

        超时语义(2026-10-07 用户决策「等待时间不计 OCR」): timeout 只累计**纯等待**
        (每轮探测后的 sleep), 截图/OCR 耗时不计入 —— 识别再慢也不压缩探测次数。
        背景: 10-07 22:49 实测登录页轮播动画打死帧缓存, 单轮全图 OCR 5.6s,
        旧墙钟语义下 startup 10s 窗口被 OCR 吃掉 83%(仅 2 次探测), 冷加载误报即此。
        wait_text / wait_text_gone / wait_scene 三处循环骨架同步此语义。
        O2(2026-10-22): `need_refine=False` 供启动页状态守卫等纯判断调用跳过拆块。
        2026-10-23: `min_score` 步骤参数接通(此前 JSON 里写 min_score 会被静默忽略, 同 click_text 旧坑)。
        """
        kws = keywords if isinstance(keywords, list) else [keywords]
        waited, probes = 0.0, 0
        while waited < timeout:
            self._check_stop()
            img = self.screenshot()
            probes += 1
            pt = self.locate(kws, img=img, min_score=min_score, need_refine=need_refine)
            if pt is not None:
                # 批B: 登记守卫, 供紧邻下一步 click_text 复用该命中点位(免二次截图+全图 OCR)。
                self._remember_guard(kws, pt, False, None, 0.5)
                print(f"[等待成功] {kws} @ {pt.x},{pt.y} (第{probes}次探测)")
                return pt
            time.sleep(interval)
            waited += interval
        print(f"[等待超时] {kws} (纯等待{timeout}s, 探测{probes}次)")
        self.dump_full_frame(f"等待超时:{kws}")
        report_failure(self._module, f"等待文本 {kws} 超时 纯等待{timeout}s/{probes}次探测")
        return None

    def wait_text_gone(self, keywords, timeout=30, interval=1.0, require_seen=False):
        """轮询等待某文字消失, 返回 True; 超时返回 False。超时语义同 wait_text(纯等待时钟)。

        E2(2026-10-27): `require_seen=True` 时, **首次探测即未见** = 该文字从未出现过 ——
        意味着"已经离开原界面"的前提不成立(前置动作很可能没生效), 返回 False 并如实打印,
        **不再**打出误导性的"[消失成功]"(2026-10-26 双日志实锤: 行未命中后 wait_text_gone
        首探即"消失成功", 把链的空转伪装成了正常完成)。缺省 False 保持旧行为。"""
        kws = keywords if isinstance(keywords, list) else [keywords]
        waited, probes = 0.0, 0
        while waited < timeout:
            self._check_stop()
            img = self.screenshot()
            probes += 1
            if self.locate(kws, img=img, min_score=0.3, need_refine=False) is None:
                if require_seen and probes == 1:
                    print(f"[消失跳过] {kws} (require_seen: 首探即未见=文字从未出现, "
                          f"前置动作可能未生效, 不假装离开成功)")
                    return False
                print(f"[消失成功] {kws} (第{probes}次探测)")
                return True
            time.sleep(interval)
            waited += interval
        print(f"[消失超时] {kws} (纯等待{timeout}s, 探测{probes}次)")
        self.dump_full_frame(f"消失超时:{kws}")
        report_failure(self._module, f"等待文本 {kws} 消失超时 纯等待{timeout}s/{probes}次探测")
        return False

    def wait_update_done(self, step: dict) -> bool:
        """步骤 wait_update_done: 等待游戏资源更新完成并自动进入登录页。

        实机依据(2026-10-23 用户授权探测, 未做额外点击):
          - 更新提示: 弹窗「有需要更新的内容，共57个，109.4MB」+「确定」; 提示在屏时先点确定。
          - 下载期: 底部「开始更新资源..(N/57)」+ 一位小数百分比(20.7%) + 「736KB/S (22.3MB/109.4MB)」。
          - 下载完成后**自动进入登录页**(「登录」「登录其他账号」「186****61」), 无完成弹窗、无重启。
          - ⚠ 进度带不能取 0.78~0.93(108px@720p): RapidOCR 检不出; 0.70~0.98(202px) 可稳定读出。

        参数: timeout(墙钟秒, 默认 600) / interval(默认 4)
              progress_region_rel / prompt_region_rel / done_region_rel
              prompt_keywords / confirm_keywords / confirm_tries
              progress_keywords / done_keywords / update_done_keywords / error_keywords
              max_error_retries / stall_warn / name
        返回 True=已到登录页 / False=超时、提示点不掉或更新异常(均如实 report_failure)。
        注意: 本步骤 timeout 是**墙钟**(含 OCR/点击), 与 wait_text 的纯等待时钟不同 ——
              更新时间不可预估, 且进度/点击本身要算进预算。
        """
        timeout = max(1.0, float(step.get("timeout", 600)))
        interval = max(0.5, float(step.get("interval", 4.0)))
        progress_region = step.get("progress_region_rel") or [0.0, 0.70, 1.0, 0.98]
        prompt_region = step.get("prompt_region_rel") or [0.25, 0.24, 0.75, 0.82]
        done_region = step.get("done_region_rel") or [0.20, 0.30, 0.90, 0.75]
        prompt_kws = step.get("prompt_keywords") or ["有需要更新的内容"]
        confirm_kws = step.get("confirm_keywords") or ["确定"]
        active_kws = step.get("progress_keywords") or ["开始更新资源", "正在检测资源更新"]
        done_kws = step.get("done_keywords") or ["登录", "点击进入游戏", "进入游戏"]
        done_more_kws = step.get("update_done_keywords") or ["更新完成", "重启游戏", "重新启动", "更新完毕"]
        error_kws = step.get("error_keywords") or ["更新失败", "网络异常", "下载失败"]
        confirm_tries = max(0, int(step.get("confirm_tries", 3)))
        max_error_retries = max(0, int(step.get("max_error_retries", 2)))
        stall_warn = max(0.0, float(step.get("stall_warn", 120)))
        label = step.get("name") or "资源更新"
        mod = getattr(self, "current_module", None) or ""
        pct_re = re.compile(r"(\d{1,3}(?:\.\d)?)\s*%")
        mask_re = re.compile(r"\d{3}\*{4}\d{2}")

        def _text(blocks) -> str:
            return " ".join(b.get("text", "") for b in blocks)

        deadline = time.time() + timeout
        confirm_used = confirm_miss = 0
        error_retries = 0
        last_pct = None
        max_pct = -1.0
        last_change = time.time()
        unknown_n = 0
        last_unknown = ""
        probes = 0

        while time.time() < deadline:
            self._check_stop()
            img = self.screenshot()
            if img is None:
                time.sleep(min(interval, 1.0))
                continue
            probes += 1

            # 1) 更新提示仍在屏 -> 点「确定」(最多 confirm_tries 次; 点不掉如实失败)
            pb = self._ocr_candidates(img, prompt_region, need_refine=False)[0]
            if any(k in _text(pb) for k in prompt_kws):
                if confirm_used >= confirm_tries:
                    print(f"[更新] {label}: 更新提示仍在屏, 「确定」已点 {confirm_used} 次仍未生效")
                    self.dump_full_frame(f"更新提示无法关闭:{label}")
                    report_failure(mod, f"{label}: 更新提示无法关闭(确定点击 {confirm_used} 次未生效)")
                    return False
                pt = self.locate(confirm_kws, img=img, min_score=0.5,
                                 region_rel=prompt_region, need_refine=False)
                if pt is None:
                    confirm_miss += 1
                    print(f"[更新] {label}: 更新提示在屏但未定位到「确定」({confirm_miss}/3)")
                    if confirm_miss >= 3:
                        self.dump_full_frame(f"更新提示无确定:{label}")
                        report_failure(mod, f"{label}: 更新提示在屏但 OCR 定位不到「确定」")
                        return False
                    time.sleep(interval)
                    continue
                confirm_miss = 0
                confirm_used += 1
                print(f"[更新] {label}: 更新提示在屏 -> 第{confirm_used}次点击「确定」@({pt.x},{pt.y})")
                self.click_abs(pt.x, pt.y)
                time.sleep(1.5)
                continue

            # 2) 下载进度带(区域够高, 见 docstring 的 108px 教训)
            rb = self._ocr_candidates(img, progress_region, need_refine=False)[0]
            rtext = _text(rb)
            m = pct_re.search(rtext)
            pct = float(m.group(1)) if m else None
            if pct is not None or any(k in rtext for k in active_kws):
                unknown_n = 0
                last_unknown = ""
                if pct is not None:
                    max_pct = max(max_pct, pct)
                    if last_pct is None:
                        print(f"[更新] {label}: 下载中 {pct:g}%")
                        last_change = time.time()
                    elif pct != last_pct:
                        # 2026-10-24(P3-6): 回跳只记「读数变化」, 不伪装成正常进度推进。
                        # 实机出现过 82.6% -> 8%(疑似识别误差/单文件进度与总进度混读),
                        # 完成判据用的是登录页, 与进度读数无关。
                        if pct < last_pct:
                            print(f"[更新] {label}: 进度读数回跳 {last_pct:g}% -> {pct:g}%"
                                  f"(识别误差/多进度源, 仅记录, 不改变完成判据)")
                        else:
                            print(f"[更新] {label}: 进度 {last_pct:g}% -> {pct:g}%")
                        last_change = time.time()
                    last_pct = pct
                    if stall_warn and time.time() - last_change >= stall_warn:
                        print(f"[更新] {label}: 进度停滞({pct:g}%, "
                              f"已 {int(time.time() - last_change)}s 无变化), 继续等待")
                        last_change = time.time()
                elif last_pct is None:
                    print(f"[更新] {label}: 更新进行中")
                    last_change = time.time()
                time.sleep(interval)
                continue

            # 3) 登录页(正向完成判据)
            db = self._ocr_candidates(img, done_region, need_refine=False)[0]
            dtext = _text(db)
            if any(k in dtext for k in done_kws) or mask_re.search(dtext):
                print(f"[更新] {label}: 已进入登录界面 (探测{probes}次, 最高进度"
                      f"{f'{max_pct:g}%' if max_pct >= 0 else '未读到'})")
                return True

            # 4) 底部无进度且未到登录页 -> 每 2 次探测做一次全屏 OCR 判过渡/异常
            unknown_n += 1
            if unknown_n >= 2:
                fb = self._ocr_frame(img, need_split=False)[0]
                ftext = _text(fb)
                if ftext != last_unknown:
                    print(f"[更新] {label}: 过渡画面 -> 全屏 OCR: "
                          + " | ".join(b.get("text", "") for b in fb[:10]))
                    last_unknown = ftext
                if any(k in ftext for k in error_kws):
                    if error_retries < max_error_retries:
                        # exact: 「重试」是子串高发词(如「请重试」是说明文字, 不是按钮), 只认等文本块
                        pt = self.locate(["重试"], img=img, min_score=0.4, exact=True,
                                         need_refine=False)
                        if pt is not None:
                            error_retries += 1
                            print(f"[更新] {label}: 更新异常 -> 第{error_retries}次点击「重试」"
                                  f"@({pt.x},{pt.y})")
                            self.click_abs(pt.x, pt.y)
                            time.sleep(2.0)
                            unknown_n = 0
                            continue
                    print(f"[更新] {label}: 更新异常且无法重试, 如实上报")
                    self.dump_full_frame(f"更新异常:{label}")
                    report_failure(mod, f"{label}: 更新异常(重试 {error_retries} 次仍失败)")
                    return False
                if any(k in ftext for k in done_more_kws):
                    pt = self.locate(confirm_kws, img=img, min_score=0.4, need_refine=False)
                    if pt is not None:
                        print(f"[更新] {label}: 出现更新完成提示 -> 点击「确定」@({pt.x},{pt.y})")
                        self.click_abs(pt.x, pt.y)
                        time.sleep(2.0)
                        unknown_n = 0
                        continue
                if any(k in ftext for k in done_kws) or mask_re.search(ftext):
                    print(f"[更新] {label}: 已进入登录界面 (全屏复核)")
                    return True
                unknown_n = 0

            time.sleep(interval)

        last = f"{max_pct:g}%" if max_pct >= 0 else "未读到"
        print(f"[更新] {label}: 等待超时 {timeout:g}s (最后进度 {last}, 探测{probes}次)")
        self.dump_full_frame(f"更新超时:{label}")
        report_failure(mod, f"{label}: 资源更新等待超时 {timeout:g}s(最后进度 {last})")
        return False

    def detect_scene(self, timeouts: dict) -> str:
        """判断当前所处界面。timeouts: {场景标识文字: 超时秒}。
        依次 OCR 检查每个标识文字是否存在, 返回命中的场景 key; 全未命中返回 'unknown'。
        """
        img = self.screenshot()
        hits = []
        for label, kws in timeouts.items():
            kws_list = kws if isinstance(kws, list) else [kws]
            for kw in kws_list:
                if self.locate([kw], img=img, min_score=0.4) is not None:
                    hits.append(label)
                    break
        return hits[0] if hits else "unknown"

    def run_steps(self, steps: list, indent=1):
        """顺序执行一组 steps, 支持 list 形式的嵌套(用于 loop 子块)。返回达到的最大步骤索引。

        E2(2026-10-27): 步骤抛出 BranchAborted(required 步骤失败)时, 中止**当前这一层列表**
        的剩余步骤并打印一行短路日志; 上一层的后续步骤照常执行 —— 使「任务链首步失败即放弃整链,
        不空跑链内收尾步骤」成为流程可声明的能力(required 缺省 False, 既有流程零行为变化)。
        """
        for step in steps:
            if isinstance(step, list):
                # 嵌套块列表
                try:
                    self.run_steps(step, indent=indent + 1)
                except BranchAborted:
                    print("  " * indent + "[分支短路] 子列表被 required 步骤中止, 继续当前列表后续步骤")
                continue
            try:
                self.run_step(step, indent=indent)
            except BranchAborted as e:
                print("  " * indent + f"[分支短路] required 步骤失败({e or '未附原因'}), "
                      f"中止当前列表剩余 {len(steps) - steps.index(step) - 1} 步, 继续上层后续步骤")
                break
        return 0

    def run_step(self, step: dict, indent=1):
        """执行单个步骤。step 为流程 JSON 中的一个节点。
        支持: wait_text / click_text / click_template / click_rel / sleep / close_dialog /
        if_text / if_fraction / loop_fraction / loop_times / friend_pollin
        """
        self._check_stop()
        pad = "  " * indent
        s_type = step.get("type")
        if not s_type:
            # 纯文档节点(如 {"_note": "..."}): 不是可执行步骤。
            # 此前会一路落到末尾的 [未知步骤] None, 每遇到一个就在日志里刷一行噪音。
            return
        # 批B: 每个可执行步骤递增序号 —— 相邻定位守卫只在"紧邻的下一步"可复用(见 _take_guard_point)。
        # 放在文档节点之后: 注释节点无副作用, 不消耗序号, 不至于平白让紧邻守卫过期。
        self._step_seq += 1
        # O0(2026-10-21): 标记本步骤为 OCR 发起处(纯观测)。不做 save/restore —— 每个步骤都会重置,
        # 残留值只会影响「步骤结束后、非步骤内」的调用(pollin 内部函数在 friend_pollin 步骤内, 正确归属)。
        self._ocr_src = s_type
        kws = step.get("text", step.get("keywords"))
        # 步骤可声明当前界面场景(如 "scene": "家园主界面"), 之后的点击默认记入该场景
        if step.get("scene"):
            self._scene = step["scene"]
        if step.get("category") and (
                s_type in ("click_text", "click_rel", "click_account_tail")):
            self._step_category = step["category"]
        if s_type == "wait_text":
            self.wait_text(kws, timeout=step.get("timeout", 30), interval=step.get("interval", 1.0),
                           need_refine=step.get("need_refine", True),
                           min_score=step.get("min_score", 0.5))
        elif s_type == "dump_frame":
            # G1(2026-10-27, zcode-20261028-7): 手动故障存证步骤 —— 在流程任意位置对当前画面
            # 做一次全量 OCR + 存证(走引擎 dump_full_frame 既有通道: data/fail_cache/, ASCII slug,
            # index.jsonl 墓碑)。用途=取证未知弹窗(如花宝道具「购买道具」弹窗)供后续批次定案,
            # 纯观测零点击。tag 经 slug 化, 中文原文保留在日志与 index。
            self.dump_full_frame(str(step.get("tag") or "手动存证"))
        elif s_type == "wait_text_gone":
            # 等待某文字消失(2026-10-25): 用于「离开原界面」类守卫, 比 wait_text(等新界面文字)
            # 更抗假阳性 —— 原界面文字消失 = 真的离开了原界面。
            # E2(2026-10-27): require_seen=首探即未见按失败处理; required=失败即短路当前分支。
            ok_gone = self.wait_text_gone(kws, timeout=step.get("timeout", 30),
                                          interval=step.get("interval", 1.0),
                                          require_seen=bool(step.get("require_seen", False)))
            if step.get("required") and not ok_gone:
                report_failure(self._module, f"wait_text_gone {kws} 未确认离开(required)")
                raise BranchAborted(f"wait_text_gone {kws} 未确认离开")
        elif s_type == "wait_update_done":
            # 资源更新守卫(2026-10-23): 提示在屏先点确定 -> 等下载/解压 -> 自动到登录页。
            # 失败按 abort_on_fail 中止本模块: 更新没完成时继续走登录链只会触发切号 abort / 一串假失败。
            ok = self.wait_update_done(step)
            if not ok and step.get("abort_on_fail"):
                raise FlowFailed(step.get("abort_reason")
                                 or "资源更新未完成/异常, 按 abort_on_fail 中止本模块")
        elif s_type == "click_text":
            # min_score / region_rel 需要透传: 此前只传 kws/fallback_rel/exact,
            # 导致流程 JSON 里写的 "min_score": 0.4 与 region_rel 被静默忽略。
            ok = self.click_text(kws, fallback_rel=step.get("fallback_rel"),
                                 min_score=step.get("min_score", 0.5),
                                 exact=step.get("exact", False),
                                 region_rel=step.get("region_rel"),
                                 exclude=step.get("exclude"),
                                 no_fallback=step.get("no_fallback", False))
            print(f"{pad}[click_text] {kws} -> {'ok' if ok else 'fail'}")
            if not ok and step.get("abort_on_fail"):
                # 高危步骤(如「切换账号」): 没点到就如实中止本模块, 不让流程带着错前提继续往下跑
                raise FlowFailed(step.get("abort_reason")
                                 or f"click_text {kws} 未命中, 按 abort_on_fail 中止本模块")
            if ok and step.get("mark"):
                # P0-3: 缓存回退只是「照旧点一下」的兜底, 不构成「已进入目标界面」的证据,
                # 否则进入链永远"成功", 识别层整体失效也无人察觉。
                if self._last_locate_source == "fallback":
                    print(f"{pad}[mark] {kws} 本次为缓存回退, 不计入命中(无法证明已在目标界面)")
                else:
                    self._rr_hit = True  # 命中目标步骤, 记为本轮 retry_loop 成功
            time.sleep(step.get("delay", 0.5))
        elif s_type == "click_template":
            # 模板匹配点击「纯图形/无文字按钮」(借鉴 MAA TemplateMatch)。
            # 参数: template(模板文件名, 资源根 resource/template/ 下)、threshold、region_rel、
            #       scale、fallback_rel(回退坐标)。有文字按钮仍走 click_text(OCR), 本步骤仅用于纯图形。
            pt = self.click_template(
                step.get("template"),
                threshold=step.get("threshold", 0.8),
                region_rel=step.get("region_rel"),
                scale_range=step.get("scale_range", (0.7, 1.0)),
                fallback_rel=step.get("fallback_rel"),
                no_fallback=step.get("no_fallback", False),
                metric=step.get("metric", "sqdiff"),
                offset_rel=step.get("offset_rel"),
            )
            ok = pt is not None
            print(f"{pad}[click_template] {step.get('template')} -> {'ok' if ok else 'fail'}")
            if not ok and step.get("abort_on_fail"):
                raise FlowFailed(step.get("abort_reason")
                                 or f"click_template {step.get('template')} 未命中, 按 abort_on_fail 中止本模块")
            if ok and step.get("mark"):
                if self._last_locate_source == "fallback":
                    print(f"{pad}[mark] 模板 {step.get('template')} 本次为回退坐标, 不计入命中")
                else:
                    self._rr_hit = True
            time.sleep(step.get("delay", 0.5))
        elif s_type == "click_account_tail":
            # 点击「账号文本尾部数字」匹配的账号条目(账号选择界面)。
            # 登录界面固定尺寸, 账号条目以 `abc****de` 出现, 用尾部数字识别目标账号。
            tail = self.resolve(step.get("tail"))
            if tail in (None, ""):
                tail = self.resolve(self.config.get("target_tail", ""))
            ok = self.click_account_tail(str(tail), region_rel=step.get("region_rel"),
                                         min_score=step.get("min_score", 0.4))
            print(f"{pad}[click_account_tail] tail={tail} -> {'ok' if ok else 'fail'}")
            if not ok and step.get("abort_on_fail"):
                # 点不到目标账号就不许继续去点「登录」——否则会沿用当前(非目标)账号登录,
                # 之后整轮任务都跑在错误账号上。宁可当天不跑(用户 2026-10-03 决策)。
                raise FlowFailed(step.get("abort_reason")
                                 or f"切换账号: 未找到尾部={tail} 的账号条目, 按 abort_on_fail 中止本模块")
            time.sleep(step.get("delay", 0.5))
        elif s_type == "sleep":
            time.sleep(step.get("seconds", 1.0))
        elif s_type == "click_rel":
            rx, ry = step["rel"]
            self.click_rel(rx, ry)
            time.sleep(step.get("delay", 0.5))
        elif s_type == "close_dialog":
            self.close_dialog(
                anchor_kw=step.get("anchor", "提示"),
                dx_range=step.get("dx_range", (150, 400)),
                dy_tol=step.get("dy_tol", 60),
                only_types=step.get("only_types"),
            )
            time.sleep(step.get("delay", 1.0))
        elif s_type == "dump_text":
            # 采集步骤(2026-10-12 每日任务/手账): 区域OCR+行分组+可选滚动采集, 只读不点业务按钮。
            self._dump_text(step)
        elif s_type == "claim_scroll":
            # 领取循环(2026-10-12 v2): 每屏点尽「领取」+关奖励弹窗+上滑, 行分组指纹判到底。
            self._claim_scroll(step)
        elif s_type == "reward_dialog":
            # 领取成功界面(2026-10-20 D13 方案A): 等弹窗 -> 标题优先关闭 -> 如实上报。
            self.reward_dialog(step)
        elif s_type == "if_collected":
            # 条件分支(2026-10-12 v2): 按最近采集(label)的行分组进度求条件(如点赞任务 a<b)。
            self._if_collected(step, indent)
        elif s_type == "if_text":
            # 条件分支: 检测到任意关键字才执行 then, 否则执行 else(可选)
            # 支持 region_rel=[x1,y1,x2,y2] (0~1) 限定时只在指定区域做文本判断
            region_rel = step.get("region_rel")
            min_score = step.get("min_score", 0.5)
            # B2/B3/B4(2026-10-22): 纯分支判定可传 need_refine=false 跳过拆块。
            #   拆块只为「紧邻下一步 click_text 复用命中点」服务(见 _remember_guard/_take_guard_point,
            #   守卫 seq 只允许紧邻一步); 若 then/else 首步与顶层后继都不点同词, 拆块纯浪费。
            pt = self.locate(kws, min_score=min_score, region_rel=region_rel,
                             need_refine=bool(step.get("need_refine", True)),
                             log_miss=bool(step.get("log_miss", True)))
            hit = pt is not None
            if hit:
                # 批B: 命中后登记守卫, 供紧邻下一步 click_text 复用该点位(免二次截图+全图 OCR)。
                self._remember_guard(kws, pt, False, region_rel, min_score)
            branch = step.get("then") if hit else step.get("else")
            print(f"{pad}[if_text] {kws} {'区域'+str(region_rel)+' ' if region_rel else ''}-> {'HIT' if hit else 'MISS'}")
            if branch:
                self.run_steps(branch, indent=indent + 1)
        elif s_type == "if_scene":
            # 条件分支: 按场景注册表(scenes.json)判定当前画面是否为指定场景
            # (2026-10-05 用户定立的引擎第三种判定; 判据示例见 scenes.json「家园界面」)
            hit = self.judge_scene(step.get("scene", ""), min_score=step.get("min_score", 0.4))
            branch = step.get("then") if hit else step.get("else")
            if branch:
                self.run_steps(branch, indent=indent + 1)
        elif s_type == "wait_scene":
            # 轮询超时语义(2026-10-07 用户决策「等待时间不计 OCR」, 与 wait_text/wait_text_gone
            # 同批同步): timeout 只累计纯等待(每轮探测后的 sleep), 截图/OCR 耗时不计入 ——
            # 10-07 22:49 实弹: 单轮 OCR 5.6s 把 startup 10s 墙钟窗口吃掉 83%(仅 2 次探测),
            # 冷加载 >10s 即误报; 纯等待时钟下探测次数恒定, 与机器快慢解耦。
            # 典型用法: 进面板后的载入守卫(如花灵派对 wait_scene 花灵派对界面)。
            # scene 支持字符串或列表(2026-10-06 用户 A/B 决策, 来自协作区 zcode-20261006-3):
            # 列表时任一场景命中即成功, 谁先出现走谁 —— 如 startup 等待 ["户外主界面",
            # "签到中"]: 已签到先见底栏(B 路), 未签到签到窗先弹出(A 路), 签到窗可见即启动
            # 成功、不再逼底栏判定(16:35 实弹的超时软失败正是底栏被签到窗盖住的形态)。
            # 一帧截图多场景共用(每场景各一次 OCR, 不逐场景重截屏, 轮询成本与单场景持平)。
            scene = step.get("scene", "")
            scenes = scene if isinstance(scene, list) else [scene]
            timeout = step.get("timeout", 10)
            interval = step.get("interval", 1.0)
            okflag = False
            okname = None
            waited, probes = 0.0, 0
            while waited < timeout:
                self._check_stop()
                img = self.screenshot()
                probes += 1
                for nm in scenes:
                    if self.judge_scene(nm, img=img, min_score=step.get("min_score", 0.4)):
                        okflag, okname = True, nm
                        break
                if okflag:
                    break
                time.sleep(interval)
                waited += interval
            if okflag:
                if len(scenes) > 1:
                    print(f"[等待成功] 场景『{okname}』(多场景任一命中, 第{probes}次探测)")
            else:
                print(f"[等待超时] 场景『{scene}』(纯等待{timeout}s, 探测{probes}次)")
                report_failure(self._module, f"等待场景『{scene}』超时 纯等待{timeout}s/{probes}次探测")
        elif s_type == "if_account_tail":
            # 条件分支(登录页): 画面中含 **** 的脱敏账号块的尾部数字 == tail 时执行 then, 否则 else。
            # 用于「当前选中账号已是目标 → 跳过切号直接登录」(2026-10-03 用户决策:
            # 登录页中央恒显示当前选中账号掩码, 当天目标本就是当前账号时免开切号 UI)。
            # 与 click_account_tail 同一套尾号解析(尾部数字 + **** 校验, 不误认普通数字块)。
            tail = str(self.resolve(step.get("tail", ""))).strip()
            img = self.screenshot()
            # O2: 只判尾部数字 -> 不拆分
            blocks = [b for b in (self._ocr_frame(img, need_split=False)[0] if img is not None else [])
                      if b.get("score", 1) >= step.get("min_score", 0.4)]
            if step.get("region_rel"):
                w, h = self.screen_w, self.screen_h
                rx1, ry1 = int(step["region_rel"][0] * w), int(step["region_rel"][1] * h)
                rx2, ry2 = int(step["region_rel"][2] * w), int(step["region_rel"][3] * h)
                blocks = [b for b in blocks
                          if rx1 <= b["center"][0] <= rx2 and ry1 <= b["center"][1] <= ry2]
            cur = None
            for b in blocks:
                txt = b.get("text", "").strip()
                m = re.search(r"(\d+)\s*$", txt)
                if m and "****" in txt:
                    cur = m.group(1)
                    break
            hit = bool(tail) and cur == tail
            print(f"{pad}[if_account_tail] 当前账号尾部={cur} 目标={tail} -> {'HIT' if hit else 'MISS'}")
            branch = step.get("then") if hit else step.get("else")
            if branch:
                self.run_steps(branch, indent=indent + 1)
        elif s_type == "if_fraction":
            # 条件分支: 读取指定相对位置处 'a/b' 数字, 满足 condition(变量 a=分子,b=分母) 则执行 then, 否则 else
            hit = self.eval_fraction(step)
            branch = step.get("then") if hit else step.get("else")
            if branch:
                self.run_steps(branch, indent=indent + 1)
        elif s_type == "store_fraction":
            # 读取区域 'a/b' 的分子存入 config(带日期), 用于记录浇水/每日上限等状态
            self.store_fraction(step)
        elif s_type == "if_greater":
            # 条件分支: 读取指定相对位置处 '关键字:N' 数字(如 剩余抽奖次数:3), 满足 condition(变量 N) 则执行 then, 否则 else
            hit = self.eval_count(step)
            branch = step.get("then") if hit else step.get("else")
            if branch:
                self.run_steps(branch, indent=indent + 1)
        elif s_type == "count_text":
            # 统计数据文本出现次数; 若 >= threshold 执行 then(默认空), 否则执行 else (若有)
            n = self.count_text(step.get("text"), region_rel=step.get("region_rel"))
            ok = n >= step.get("threshold", 1)
            branch = step.get("then") if ok else step.get("else")
            print(f"{pad}[count_text] {step.get('text')} 计数={n} threshold={step.get('threshold',1)} -> {'TRUE' if ok else 'FALSE'}")
            if branch:
                self.run_steps(branch, indent=indent + 1)
        elif s_type == "if_color_count":
            # 颜色计数分支: 统计指定 HSV 颜色连通域个数 n; 若 n 与 threshold 比较成立(默认 n<3)
            # 则执行 then, 否则 else(可选)。用于「已领取绿色勾号 < 目标数才点领取」这类状态判断。
            # region_rel=[x1,y1,x2,y2](0~1) 需转成绝对像素再传 count_color
            # (count_color 的 region 语义是绝对坐标; 直接传 0~1 浮点会切片报错)
            reg = step.get("region_rel")
            if reg:
                if not self.screen_w or not self.screen_h:
                    self.screenshot()
                w, h = self.screen_w, self.screen_h
                reg = [int(reg[0] * w), int(reg[1] * h), int(reg[2] * w), int(reg[3] * h)]
            n = self.count_color({
                "hsv_lower": step.get("hsv_lower"),
                "hsv_upper": step.get("hsv_upper"),
                "area_min": step.get("area_min", 20),
                "area_max": step.get("area_max", 999999),
                "region": reg,
            })
            op = step.get("op", "<")
            target = step.get("threshold", 3)
            ok = {"<": lambda: n < target, "<=": lambda: n <= target,
                  ">": lambda: n > target, ">=": lambda: n >= target,
                  "==": lambda: n == target, "!=": lambda: n != target}[op]()
            branch = step.get("then") if ok else step.get("else")
            print(f"{pad}[if_color_count] {step.get('name','')} 色块数={n} {op} {target} -> {'TRUE' if ok else 'FALSE'}")
            if branch:
                self.run_steps(branch, indent=indent + 1)
        elif s_type == "if_config":
            # 配置开关分支: config[key] 满足 op/value 则执行 then, 否则 else(可选)
            hit = self.eval_config(step)
            branch = step.get("then") if hit else step.get("else")
            if branch:
                self.run_steps(branch, indent=indent + 1)
        elif s_type == "if_time":
            # 时间窗口分支: 当前小时(本地)在 window=[start, end] 内(含边界)则执行 then, 否则 else(可选)。
            # 用于按每日开放时段控制功能开关(如闪耀委托挑战 10-21 点开放), 非开放时段直接跳过不空转。
            # 支持跨天窗口: start>end 时表示跨午夜(如 [21, 10] = 21 点~次日 10 点)。
            import datetime
            w = step.get("window", [10, 21])
            start, end = int(w[0]), int(w[1])
            hour = datetime.datetime.now().hour
            hit = (start <= hour <= end) if start <= end else (hour >= start or hour <= end)
            branch = step.get("then") if hit else step.get("else")
            print(f"{pad}[if_time] 当前 {hour} 时, 窗口 {start}-{end} -> {'TRUE' if hit else 'FALSE'}")
            if branch:
                self.run_steps(branch, indent=indent + 1)
        elif s_type == "if_weekday":
            # 星期几分支(2026-10-25 守望兔子): weekday() 0=周一...6=周日, days 列出开放日。
            # 守望兔子周五~周日开放 => days=[5,6,0]; 非开放日走 else 零开销跳过, 不进家族活动页空转。
            import datetime
            days = {int(d) % 7 for d in step.get("days", [5, 6, 0])}
            today = datetime.datetime.now().weekday()
            hit = today in days
            branch = step.get("then") if hit else step.get("else")
            print(f"{pad}[if_weekday] weekday={today}(0=周一), 开放日{sorted(days)} -> {'TRUE' if hit else 'FALSE'}")
            if branch:
                self.run_steps(branch, indent=indent + 1)
        elif s_type == "loop_text":
            # 循环直到找不到某文本: 只要还能识别到 text(领取等动态按钮)就重复执行 do,
            # 识别不到则退出。用于"有'领取'就点, 领完按钮消失即自然停止"的领取循环。
            kws = step.get("text", step.get("keywords"))
            body = step.get("do", [])
            guard = step.get("max_loop", 20)
            n = 0
            last_pt = None
            stalled = False
            while n < guard:
                pt = self.locate(kws, min_score=step.get("min_score", 0.4),
                                 region_rel=step.get("region_rel"),
                                 exclude=step.get("exclude"))
                if pt is None:
                    break
                # 无进展守卫: 这一轮定位到的还是上一轮那个点, 说明点击对它根本没有作用
                # (按钮是「已领取」或未达标的灰按钮), 再点多少次结果都一样 —— 立刻停,
                # 不要空转满 max_loop 次骗自己"在领取"。
                if last_pt is not None and abs(pt.x - last_pt.x) <= 4 and abs(pt.y - last_pt.y) <= 4:
                    stalled = True
                    break
                n += 1
                last_pt = pt
                print(f"{pad}[loop_text] {kws} 存在({pt.x},{pt.y}), 执行第 {n} 次领取/操作")
                self.run_steps(body, indent=indent + 1)
            if stalled:
                print(f"{pad}[loop_text] {kws} 连续两轮落在同一坐标({last_pt.x},{last_pt.y})且画面无变化, "
                      f"判定该按钮当前不可领(已领取/未达标), 提前退出")
            elif n >= guard:
                # 到上限退出时按钮可能仍然存在, 不能说成"不存在/完成"(否则把放弃谎报成成功)
                print(f"{pad}[loop_text] {kws} 已达上限 {guard} 次仍在, 放弃本轮循环(未确认真已领完)")
                report_failure(self._module, f"loop_text {kws} 达上限 {guard} 次仍在, 放弃本轮(未确认真领完)")
            else:
                print(f"{pad}[loop_text] {kws} 不存在, 领取/操作完成, 退出")
        elif s_type == "loop_fraction":
            # 按分数区域算出的次数重复执行 do (n=ceil((b-a)/57), m=floor(a/20), 取 min)
            self.run_loop_fraction(step, indent)
        elif s_type == "loop_times":
            # 循环执行子块 N 次
            times = step.get("times", 1)
            body = step.get("do", [])
            for i in range(times):
                print(f"{pad}[loop_times] 第 {i+1}/{times} 次")
                self.run_steps(body, indent=indent + 1)
        elif s_type == "retry_loop":
            # 脱困重试循环: 最多 max_rounds 轮。
            # 每轮执行 do; 只要 do 内任一带 mark 的正常点击真实命中(本轮回成),
            # 本轮即成功, 退出循环。若整轮无命中(被弹窗/无关界面挡住), 执行
            # fail_do 脱困(未提供则自动 close_dialog 尝试全部关闭类型)再进入下一轮。
            # 跑满 max_rounds 仍无命中 → 放弃, 继续流程后续步骤(不抛错), 并 report_failure 上报。
            # 若该目标"不存在属正常状态"(如已领取时入口不显示), 步骤可写 "report_fail": false 免打扰。
            rounds = step.get("max_rounds", 3)
            body = step.get("do", [])
            fail_do = step.get("fail_do")
            hit = False
            for i in range(rounds):
                print(f"{pad}[retry_loop] 第 {i+1}/{rounds} 轮")
                self._rr_hit = False
                self.run_steps(body, indent=indent + 1)
                if self._rr_hit:
                    print(f"{pad}[retry_loop] 第 {i+1} 轮命中目标, 退出")
                    hit = True
                    break
                # 末轮措辞如实(2026-10-03, 协作区 zcode-20261003-3): 最后一轮后并无下一轮重试,
                # 旧文案「脱困重试」言过其实; 脱困动作本身保留执行(后续步骤可能依赖末轮清场)。
                if i + 1 < rounds:
                    print(f"{pad}[retry_loop] 第 {i+1} 轮未命中, 脱困重试")
                else:
                    print(f"{pad}[retry_loop] 第 {i+1} 轮未命中(已达最大轮数)")
                if fail_do:
                    self.run_steps(fail_do, indent=indent + 1)
                else:
                    self.close_dialog()
                    time.sleep(step.get("delay", 1.0))
            if not hit and step.get("report_fail", True):
                # 跑满轮数仍无任何带 mark 的真实命中 = 该功能的进入/触发失败(如实上报, 供失败弹窗)
                report_failure(self._module, f"retry_loop 跑满 {rounds} 轮仍未命中目标步骤")
        elif s_type == "navigate":
            # 公共「进入某目标界面」: 从公共注册表按 target 取进入链并执行。
            # 语义与 retry_loop 一致: 目标 mark 命中即本轮成功(进入后自动切换 self._scene);
            # 未命中则 close_dialog 脱困, 最多 max_rounds 轮。避免各流程重复内嵌进入链。
            self.run_navigate(step, indent)
        elif s_type == "friend_pollin":
            # 好友采粉闭环: 密友+好友两类逐页扫可采粉绿花 -> 进家园 -> 快捷操作 -> 采粉,
            # 采完就地重开好友列表去下一个; 两类均到最后一页仍无可采粉则回自己家园结束。
            # 实现见 pollin.py; 定位/点击一律走本体(纯图形走模板匹配, 有文字走 OCR)。
            from pollin import run_friend_pollin
            res = run_friend_pollin(self)
            print(f"{pad}[friend_pollin] 结果 {res}")
            if isinstance(res, dict) and any(v is None for v in res.values()):
                report_failure(self._module, f"好友采粉: 有类别未跑通(打开好友列表失败) 结果={res}")
            time.sleep(step.get("delay", 1.0))
        elif s_type == "ensure_menu":
            # 2026-10-24(P1-3): 顶部活动菜单被「收起菜单」折叠时自愈(点右上角白箭头展开)。
            # 只做一次探测+至多一次点击, 失败只告警不登记失败。
            ok = self.ensure_menu_expanded(step)
            print(f"{pad}[ensure_menu] 顶部菜单 -> {'ok' if ok else '未确认展开(已告警)'}")
            time.sleep(step.get("delay", 0.5))
        elif s_type == "ensure_home":
            # 归位守卫: 确保回到自己家园主界面(pollin.ensure_home: 关提示框→离开好友花园→
            # 关好友列表→关家族面板→右上角兜底)。用于模块开头, 防止上一模块停在别处导致整段空跑
            # (2026-10-02: social 结束停在好友列表 → claim 全程在列表上空跑 5 分钟)。
            from pollin import ensure_home
            ok = ensure_home(self)
            print(f"{pad}[ensure_home] 归位到自己家园 -> {'ok' if ok else 'fail'}")
            if not ok:
                report_failure(self._module, "ensure_home 未确认回到自己家园主界面(已如实报出, 不假装成功)")
            time.sleep(step.get("delay", 0.5))
        elif s_type == "community_like":
            # 社区点赞闭环(社交 4.3): 进「种草社区」-> 随机向右翻页 -> 随机点 2 个未点赞按钮 -> 退出回主界面。
            # 实现见 community_like.py。点赞成功判据 = 点击后该处「亮紫胶囊」消失(实测按钮位置/颜色/大小三者同时变化);
            # 模板匹配在本场景失效(TM_SQDIFF_NORMED 对低纹理模板误命中 30+ 处), 故用 HSV 颜色+形状检测。
            from community_like import run_community_like
            res = run_community_like(self)
            print(f"{pad}[community_like] 结果 {res}")
            time.sleep(step.get("delay", 1.0))
        elif s_type == "click_row_button":
            # 行级按钮点击(2026-10-25 浏览热卖): 手账任务行内按钮, 行锚定 + 行内实时识别,
            # 见 click_row_button docstring。识别未命中不点击, 交后续步骤处置。
            self.click_row_button(step, indent)
        elif s_type == "slide":
            # 滑动手势(2026-10-25 花宝照顾第三部分): 把选中道具拖到目标上执行使用。
            # 规则6边界(2026-10-06 用户裁定, swipe 同源): 滑动是**手势动作**, 没有「识别目标」,
            # start_rel/end_rel 是手势参数(相对比例 0~1)而非被禁的「直接坐标点击」;
            # 点击类操作仍必须 OCR/template 实时定位。花宝照顾场景: 起点=左栏道具(固定栏位),
            # 终点=花宝本体(角色区中心); 道具使用成功与否由数量计数复核(见 REPORT)。
            sx, sy = (float(v) for v in step.get("start_rel", (0, 0)))
            ex, ey = (float(v) for v in step.get("end_rel", (0, 0)))
            dur = int(step.get("duration_ms", 600))
            self.swipe_rel(sx, sy, ex, ey, duration_ms=dur)
            time.sleep(step.get("delay", 1.5))
        elif s_type == "count_probe":
            # 数量计数探针(2026-10-25 花宝照顾, 用户判据): 读 region_rel 中心附近的道具数量数字,
            # store 到具名变量(step["as"]) 供后续 if_count 变化判定; 供「使用前/使用后」对比。
            # 复用 parse_count_at(关键字:N/纯数字就近匹配, 607/872 角标实测 0.73/0.75 可读)。
            n = self.parse_count_at(step.get("region_rel"), tol=int(step.get("tol", 60)))
            self._count_probes[str(step.get("as", "count"))] = n
            print(f"{pad}[count_probe] {step.get('as', 'count')} = {n} (region {step.get('region_rel')})")
            time.sleep(step.get("delay", 0.5))
        elif s_type == "if_count":
            # 数量变化判定(2026-10-25 用户判据「数量比点击前少1=使用成功」):
            # cond 语义: "minus1"=当前比 before 少 1(使用成功), "changed"=当前!=before, "same"=相等。
            # ⚠ 尾位遮挡(2026-10-25 实测定型): 使用成功后反馈气泡(「挠痒痒/增加N点年龄点数」)
            #   长期驻留在角标右下, 数字尾位被圆角遮住 → OCR 只读到前缀(如 597→59)。
            #   故 minus1 判定兼容「前缀」: cur 是 before 的前缀(str 前缀匹配)亦判 TRUE ——
            #   数量减少只发生在尾位(如 597→596 前缀 59 不变, 597→59 遮挡后前缀匹配),
            #   未使用时读数恢复完整(596→597 前缀不匹配会误判?) —— 否: 未使用时无气泡,
            #   读数=完整 before 同值, 不满足前缀条件。取「len(cur)<len(before) 且前缀匹配」。
            cur = self.parse_count_at(step.get("region_rel"), tol=int(step.get("tol", 60)))
            before = self._count_probes.get(str(step.get("before", "count")))
            cond = str(step.get("cond", "minus1"))
            if cur is None or before is None:
                ok = bool(step.get("on_unread", False))
                print(f"{pad}[if_count] 读数失败 cur={cur} before={before} -> {'TRUE(on_unread)' if ok else 'FALSE'}")
            elif cond == "minus1":
                sb, sc = str(before), str(cur)
                ok = (cur == before - 1) or (len(sc) < len(sb) and sb.startswith(sc))
            elif cond == "changed":
                ok = (cur != before)
            elif cond == "same":
                ok = (cur == before)
            else:
                ok = False
            print(f"{pad}[if_count] {step.get('before')}={before} -> cur={cur} cond='{cond}' -> {'TRUE' if ok else 'FALSE'}")
            branch = step.get("then") if ok else step.get("else")
            if branch:
                self.run_steps(branch, indent=indent + 1)
        elif s_type == "touch_drag":
            # 分段慢速拖拽(2026-10-25 花宝照顾第三部分实测定型): 引擎 post_touch_down/move/up
            # 原语组合 —— 按下 → 0.35s 停顿 → 8 段步进(每段 0.15s) → 0.35s 落点停顿 → 抬起。
            # 为什么不用 swipe_rel: 实测 A 快速 swipe(200ms)/B 慢速 swipe(2000ms)/C 单次
            # post_touch_down+move+up 全部无效(数量不变), 仅「分段慢速拖 + 双端停顿」稳定 -1
            # (pat 3/3, touch 1/1, 2026-10-25 实机)。手势参数(相对比例)非点击坐标(规则6边界,
            # 2026-10-06 用户裁定); 终点为花宝本体角色区。
            sx, sy = (float(v) for v in step.get("start_rel", (0, 0)))
            ex, ey = (float(v) for v in step.get("end_rel", (0, 0)))
            press_pause = float(step.get("press_pause", 0.35))
            steps_n = max(2, int(step.get("steps", 8)))
            step_pause = float(step.get("step_pause", 0.15))
            end_pause = float(step.get("end_pause", 0.35))
            if not self.screen_w or not self.screen_h:
                self.screenshot()
            x1, y1 = int(sx * self.screen_w), int(sy * self.screen_h)
            x2, y2 = int(ex * self.screen_w), int(ey * self.screen_h)
            ctrl = self._ctrl
            ctrl.post_touch_down(x1, y1).wait()
            time.sleep(press_pause)
            for i in range(1, steps_n + 1):
                xi = x1 + (x2 - x1) * i // steps_n
                yi = y1 + (y2 - y1) * i // steps_n
                ctrl.post_touch_move(xi, yi).wait()
                time.sleep(step_pause)
            time.sleep(end_pause)
            ctrl.post_touch_up().wait()
            print(f"{pad}[touch_drag] ({x1},{y1})->({x2},{y2}) 分段{steps_n}段 "
                  f"(press {press_pause}s / step {step_pause}s / end {end_pause}s)")
            time.sleep(step.get("delay", 2.5))
        elif s_type == "fail_flow":
            # 流程主动判失败: 如实中止本模块(不再往下执行, 也不假装成功)。
            # 用于「前置条件不满足, 继续执行会跑出一整轮假结果」的场景——
            # 如切换账号失败仍去点「登录」-> 用错误账号跑完当天全部任务。
            # reason 会被 run_module 登记进失败清单(WebUI 弹窗), 并让编排按 on_fail 处置。
            reason = step.get("reason") or "流程主动中止(未说明原因)"
            print(f"{pad}[fail_flow] {reason} -> 中止本模块")
            raise FlowFailed(str(reason))
        else:
            print(f"[未知步骤] {s_type}")

    def run_navigate(self, step: dict, indent=1):
        """按公共导航注册表进入目标界面(target)。返回 True=命中进入, False=轮数耗尽放弃。
        step: {"type":"navigate","target":"家族活动","max_rounds"?,"delay"?}
        每轮 do = [顶层 mark_text 探测点击] + entry["nav"]导航链; 期间任一带 mark 的
        click_text 真实命中会置 self._rr_hit=True -> 本轮成功, 并把 self._scene 切到目标场景。
        未命中则 close_dialog() 脱困(最外层兜底), 进入下一轮; 跑满轮数仍未命中则放弃(不抛错)。
        """
        pad = "  " * indent
        target = step.get("target")
        entry = self._navigation.get("targets", {}).get(target)
        if not entry:
            print(f"{pad}[navigate] 未在注册表找到目标『{target}』, 跳过")
            report_failure(self._module, f"navigate 目标《{target}》未在公共注册表 entries.json 中定义")
            return False
        mark_text = entry.get("mark_text", [])
        mfb = entry.get("mark_fallback_rel")
        scene = entry.get("scene")
        nav = entry.get("nav", [])
        rounds = step.get("max_rounds", entry.get("max_rounds", 3))
        # 每轮 do: 顶层先探测目标文字; 命中则点击(mark)即成功, 否则走上 fail.else? 见下
        # 注意: target 本身可能出现在任意深度(顶层/菜单后/家园后)。nav 已含内层 mark 点击,
        # 顶层这里统一补一个"当前画面即可见目标"的探测分支。
        do = [{
            "type": "if_text", "text": mark_text, "min_score": 0.4,
            "then": [{
                "type": "click_text", "text": mark_text, "mark": True,
                "delay": 1.5, "fallback_rel": mfb
            }]
        }]
        do.extend(nav)
        for i in range(rounds):
            print(f"{pad}[navigate] 《{target}》 第 {i+1}/{rounds} 轮")
            self._rr_hit = False
            self.run_steps(do, indent=indent + 1)
            if self._rr_hit:
                if scene:
                    self._scene = scene
                print(f"{pad}[navigate] 《{target}》 第 {i+1} 轮命中进入, scene={self._scene}")
                return True
            # 末轮措辞如实(同 retry_loop, 2026-10-03): 脱困动作保留, 仅措辞区分有无下一轮。
            if i + 1 < rounds:
                print(f"{pad}[navigate] 《{target}》 第 {i+1} 轮未命中, 脱困重试")
            else:
                print(f"{pad}[navigate] 《{target}》 第 {i+1} 轮未命中(已达最大轮数)")
            self.close_dialog()
            time.sleep(step.get("delay", 1.0))
        print(f"{pad}[navigate] 《{target}》 {rounds} 轮未命中, 放弃")
        report_failure(self._module, f"navigate 进入《{target}》{rounds} 轮未命中, 放弃")
        return False

    def run_flow(self, flow: dict):
        """执行整个流程。flow 含 steps 列表。返回值: 接口回调事件列表。
        流程顶层可声明 scene(如 "scene": "家园主界面"), 之后点击默认记入该场景。
        """
        clear_stop()
        name = flow.get("name", "未命名流程")
        self._module = name          # 失败登记时标注来源模块
        if flow.get("scene"):
            self._scene = flow["scene"]
        print(f"\n[{_ts()}] ===== 流程: {name} (scene={self._scene}) =====")
        try:
            for step in flow.get("steps", []):
                self.run_step(step)
        except StopRequested:
            print(f"[{_ts()}] ===== 流程已由停止请求中断: {name} =====")
            return
        except FlowFailed as e:
            # 单跑该流程(非编排)时同样如实中止, 不把 fail_flow 当成未捕获异常抛到调用方
            print(f"[{_ts()}] ===== 流程中止(主动判失败): {name} -> {e} =====")
            return
        print(f"[{_ts()}] ===== 流程完成: {name} =====")

    def run_module(self, module: dict, registry: dict) -> str:
        """执行单个模块(module), 返回结果: 'ok' | 'skip' | 'fail'。
        module: {"id","flow","flow_data","required","on_fail"}
        registry: {文件名: 已加载的 flow dict}, 避免重复读盘。
        """
        mid = module.get("id", "?")
        self._module = str(mid)      # 失败登记时标注来源模块
        # 批C-②: 模块级 OCR 统计清零(模块结束打印并累计进整轮 _ocr_stat_total)
        self._ocr_stat = _new_ocr_stat()
        _, fail_seq0 = get_failures(0)   # 进入模块前的失败序号, 用于识别流程内软失败(A1)
        fname = module.get("flow")
        flow = module.get("flow_data") or registry.get(fname)
        if flow is None:
            print(f"[{_ts()}] [模块:{mid}] 未找到流程文件 {fname}, 标记失败")
            report_failure(mid, f"模块流程文件缺失: {fname}")
            return "fail"
        on_fail = module.get("on_fail", "stop_round")
        required = module.get("required", False)
        print(f"\n>>> 模块执行: {mid} [{fname}] {'[必选]' if required else '[可选]'}".strip())
        try:
            if isinstance(flow, dict):
                self.run_steps(flow.get("steps", []))
            soft_items, fail_seq1 = get_failures(fail_seq0)
            if fail_seq1 > fail_seq0:
                # 流程内部已 report_failure 登记软失败(等待超时/放弃/跑满轮数等)但未抛异常:
                # 如实收成 'fail', 交编排 on_fail 处置, 避免汇总 fail 与 [失败] 登记自相矛盾(A1)
                self._print_ocr_stat(mid)
                print(f"[{_ts()}] <<< 模块失败(软失败 {len(soft_items)} 项): {mid} (on_fail={on_fail})")
                return "fail"
            self._print_ocr_stat(mid)
            print(f"[{_ts()}] <<< 模块完成: {mid}")
            return "ok"
        except FlowFailed as e:
            # 流程用 fail_flow 步骤主动判失败: 如实收成 'fail'(不是"模块异常"), 交编排 on_fail 处置
            self._print_ocr_stat(mid)
            print(f"[{_ts()}] <<< 模块失败: {mid} -> {e} (on_fail={on_fail})")
            report_failure(mid, str(e))
            return "fail"
        except Exception as e:
            self._print_ocr_stat(mid)
            print(f"[{_ts()}] <<< 模块异常: {mid} -> {e} (on_fail={on_fail})")
            report_failure(mid, f"模块异常: {e}")
            return "fail"

    def run_daily(self, plan: dict) -> dict:
        """按编排 plan 调度各模块。plan: {"name","modules":[{"id","flow",...}]}。
        返回统计: {"ok":[],"skip":[],"fail":[]}。容错规则由每个 module.on_fail 决定:
          skip        -> 失败继续下一个
          stop_round  -> 失败终止本轮后续模块
        收到停止请求时(StopRequested)立即中断本轮全部模块, 返回已执行统计。
        """
        clear_stop()
        # 批C-②: 整轮 OCR 统计清零。⚠ 主 agent 修订(里程碑 88): 原为 dict(self._ocr_stat) ——
        # run_module 只在**入口**清零 _ocr_stat(出口不清), 故同一进程连跑第 2 轮时, 此处会把上一轮
        # **末模块**的残留当成本轮初值, 整轮汇总被翻倍(实测: 伪造 10 次/轮 → 第 2 轮 20 次)。
        # 改为按 key 显式全零, 整轮统计才逐轮独立。
        self._ocr_stat_total = _new_ocr_stat()
        name = plan.get("name", "每日编排")
        # 预加载所有引用到的流程
        registry = {}
        for m in plan.get("modules", []):
            fname = m.get("flow")
            if fname and fname not in registry:
                fp = FLOW_DIR / fname
                if fp.exists():
                    with open(str(fp), encoding="utf-8") as f:
                        registry[fname] = json.load(f)
        result = {"ok": [], "skip": [], "fail": []}
        self.current_module = None   # 当前运行模块(WebUI /api/status 读取, 用于锁定运行中模块的设置)
        print(f"\n[{_ts()}] ########## 编排: {name} ##########")
        try:
            for m in plan.get("modules", []):
                self._check_stop()
                mid = m.get("id")
                self.current_module = mid
                print(f"[{_ts()}] >>> 进入模块: {mid}")
                res = self.run_module(m, registry)
                self.current_module = None
                result[res if res in result else "fail"].append(mid)
                if res == "fail" and m.get("on_fail", "stop_round") == "stop_round":
                    print(f"[编排] 模块 {m.get('id')} 失败且 on_fail=stop_round, 终止本轮")
                    break
        except StopRequested:
            print(f"[{_ts()}] ########## 编排已由停止请求中断 ({len(result['ok'])} ok) ##########")
            return result
        finally:
            self.current_module = None
            t = self._ocr_stat_total
            print(f"[{_ts()}] [OCR统计] 整轮: 全图 {t['full_n']} 次 {t['full_t']:.2f}s · "
                  f"区域 {t['region_n']} 次 {t['region_t']:.2f}s · 拆分 {t['split_n']} 次 {t['split_t']:.2f}s · "
                  f"缓存命中 {t['hit_n']} 次 · 直调 {t['direct_n']} 次 {t['direct_t']:.2f}s")
            by = t.get("by_src") or {}

            def _tot(kind, limit=8):
                d = by.get(kind) or {}
                items = sorted(d.items(), key=lambda kv: -kv[1])[:limit]
                return " · ".join(f"{k} {v}" for k, v in items) or "-"

            print(f"[{_ts()}] [OCR来源] 整轮 全图: {_tot('full')} | 拆分: {_tot('split')}")
            print(f"[{_ts()}] [OCR健康] 整轮 拆分缓存命中 {t['split_cache_hit']} 次 · "
                  f"仅子块命中 {t['split_only_hit']} 次 · 场景判断 {t['scene_calls']} 次"
                  f"(折叠 {t.get('scene_quiet_n', 0)}) · "
                  f"静默未命中 {t.get('miss_silent_n', 0)} 次(弹窗/启动守卫确认无)")
            if t.get("friend_coarse_n"):
                cn, ch = t["friend_coarse_n"], t.get("friend_coarse_hit", 0)
                fn, fh = t.get("friend_fine_n", 0), t.get("friend_fine_hit", 0)
                print(f"[{_ts()}] [粗OCR] 整轮 社交面板「好友」: 粗识 {ch}/{cn} ({ch / cn:.0%}) · "
                      f"精识兜底 {fh}/{fn} ({(fh / fn if fn else 0):.0%})")
        print(f"[{_ts()}] ########## 编排结束: ok={len(result['ok'])} skip={len(result['skip'])} fail={len(result['fail'])} ##########")
        return result

    # ---- 界面采集 ----
    def collect_ui(self, min_score=0.5, scene: str | None = None) -> dict:
        """采集当前界面所有文字块, 写入 click_log 知识库(按场景分组)。
        scene 缺省用 self._scene(流程步骤声明的当前界面)。
        返回: {文字: 记录} 字典。
        """
        img = self.screenshot()
        blocks = ocr_image(img)
        sc = scene or self._scene or "未分类"
        new_entries = {}
        for b in blocks:
            if b.get("score", 1.0) < min_score:
                continue
            text = b["text"].strip()
            if not text or len(text) < 2:
                continue
            cx, cy = b["center"]
            pt = Point(cx, cy, self.screen_w, self.screen_h)
            entry = {
                "name": text,
                "text": [text],
                "rel": [round(pt.rel[0], 4), round(pt.rel[1], 4)],
                "method": "ocr",
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "category": self.auto_category(text),
            }
            # 同场景同名按钮只保留最新(跨场景互不覆盖)
            self.click_log_scenes.setdefault(sc, {})[text] = entry
            self.click_log[text] = entry  # 同步扁平索引
            new_entries[text] = entry
        self._save_click_log()
        print(f"[采集] [{sc}] 当前界面: {len(new_entries)} 个按钮已写入知识库")
        for name, e in sorted(new_entries.items()):
            print(f"  {name:<16} 相对{e['rel']}")
        return new_entries


# ---------- 流程管理 ----------
def load_flows(flow_dir: Path = FLOW_DIR) -> list[dict]:
    flows = []
    if not flow_dir.exists():
        return flows
    for f in sorted(flow_dir.glob("*.json")):
        try:
            with open(f, encoding="utf-8") as fp:
                data = json.load(fp)
                data.setdefault("_file", str(f))
                flows.append(data)
        except Exception as e:
            print(f"[流程加载失败] {f}: {e}")
    return flows


def select_flow(flows, key):
    """按关键字选择流程: 先精确名匹配('name' == key), 再关键字子串匹配。
    避免『种植』误选先载入的「进入种植界面」而非「种植任务」。
    返回命中的 flow dict; 未命中返回 None。
    """
    if not key:
        return None
    for f in flows:
        if f.get("name") == key:
            return f
    for f in flows:
        if f.get("name") and key in f["name"]:
            return f
    return None


def main():
    args = sys.argv[1:]
    if not args or args[0] == "--list":
        for fl in load_flows():
            print(f"- {fl.get('name')}  [{fl.get('_file')}]")
        return

    if args[0] == "--flow":
        key = args[1] if len(args) > 1 else ""
        flows = load_flows()
        target = select_flow(flows, key)
        if target is None:
            print(f"未找到流程包含关键字 '{key}'. 可用: {[f.get('name') for f in flows]}")
            return
        eng = OCREngine()
        # 支持 --tail <数字> 覆盖配置(切换账号目标账户尾部)
        if "--tail" in args:
            i = args.index("--tail")
            if i + 1 < len(args):
                eng.config["target_tail"] = args[i + 1]
        if not eng.connect():
            return
        eng.run_flow(target)
        return

    if args[0] == "--collect":
        eng = OCREngine()
        if not eng.connect():
            return
        eng.collect_ui()
        return

    if args[0] == "--close-test":
        eng = OCREngine()
        if not eng.connect():
            return
        pt = eng.find_close_button()
        if pt is not None:
            print(f"[close-test] 命中关闭按钮 绝对{pt.x},{pt.y} 相对{tuple(round(v,4) for v in pt.rel)}")
        else:
            print("[close-test] 未命中任何关闭按钮")
        return

    if args[0] == "--add-close":
        if len(args) < 3:
            print("用法: python ocr_engine.py --add-close <名称> <corner|anchor_color>")
            return
        name, t = args[1], args[2]
        pink = {"hsv_lower": [150, 80, 90], "hsv_upper": [175, 255, 255],
                "area_min": 300, "area_max": 5000}
        if t == "corner":
            entry = {"name": name, "type": "corner",
                     "region_rel": [0.82, 0.0, 1.0, 0.18], "color": pink}
        elif t == "anchor_color":
            entry = {"name": name, "type": "anchor_color", "anchor": "提示",
                     "dx_range": [150, 400], "dy_tol": 60, "min_score": 0.4,
                     "color": dict(pink, area_max=3000)}
        else:
            print(f"未知类型 '{t}'. 可选: corner | anchor_color")
            return
        OCREngine().register_close_button(entry)
        print(f"[add-close] 已新增关闭按钮特殊逻辑: {name} ({t})")
        return

    if args[0] == "--ocr-screen":
        """开发工具: 连接->截图->一次OCR->打印当前画面所有字符及相对坐标(不写入知识库)。"""
        eng = OCREngine()
        if not eng.connect():
            return
        img = eng.screenshot()
        if img is None:
            print("[失败] 截图失败")
            return
        h, w = img.shape[:2]
        print(f"画面尺寸 W={w} H={h}")
        blocks = [b for b in ocr_image(img) if b.get("score", 1) >= 0.4]
        blocks.sort(key=lambda b: (b["center"][1], b["center"][0]))
        print(f"共识别 {len(blocks)} 块:")
        for b in blocks:
            rx, ry = round(b["center"][0] / w, 4), round(b["center"][1] / h, 4)
            print(f"  {b['text']:<16} rel({rx},{ry})  abs({b['center'][0]},{b['center'][1]})  score{b.get('score',0):.2f}")
        return

    if args[0] == "--ocr-anchor":
        """开发工具: 以指定文字(如「登录」)为锚点, 打印其它各文字块相对锚点的像素偏移。

        适用于「固定尺寸界面」(如小花仙登录界面尺寸不随设备分辨率改变):
        整体画面相对坐标(0~1)会失效, 改用「锚点 + 像素偏移」定位, 偏移不随分辨率变化。
        用法: python ocr_engine.py --ocr-anchor <锚点关键字> [--exact]
        """
        exact = "--exact" in args
        anchor_kw = args[1] if len(args) > 1 and not args[1].startswith("-") else "登录"
        eng = OCREngine()
        if not eng.connect():
            return
        img = eng.screenshot()
        if img is None:
            print("[失败] 截图失败")
            return
        h, w = img.shape[:2]
        print(f"画面尺寸 W={w} H={h} | 锚点='{anchor_kw}' (exact={exact})")
        blocks = [b for b in ocr_image(img) if b.get("score", 1) >= 0.4]
        # 找锚点块(取第一个非空、按文本命中)
        anchors = ocr_find(blocks, [anchor_kw], exact=exact)
        if not anchors:
            print(f"[失败] 未找到锚点文字 '{anchor_kw}'")
            return
        ax, ay = anchors[0]["center"]
        print(f"锚点中心 abs({ax},{ay})")
        blocks.sort(key=lambda b: (b["center"][1], b["center"][0]))
        print(f"共 {len(blocks)} 块, 相对锚点的像素偏移 (dx=center_x-ax, dy=center_y-ay):")
        for b in blocks:
            dx = int(b["center"][0] - ax)
            dy = int(b["center"][1] - ay)
            print(f"  {b['text']:<16} d({dx},{dy})  anchor_abs({b['center'][0]},{b['center'][1]})  score{b.get('score',0):.2f}")
        return

    print("用法: python ocr_engine.py --list | --flow <关键字> | --collect | --close-test | --add-close <名称> <corner|anchor_color> | --ocr-screen | --ocr-anchor <锚点关键字> [--exact]")


if __name__ == "__main__":
    main()
