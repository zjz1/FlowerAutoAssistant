"""OCREngine 主类(全部实例状态集中于 __init__, E01 原文保留)。

E01(batch-03, 2026-11-14) 自单文件 ocr_engine.py 机械拆包: 本文件各段为原文件对应
行段的**逐行原文**(唯 __file__ 锚点因包层级 +1 机械重锚定, 见 ast_hash_compare.py
allowlist)。行为等价口径: 帧集回归 0 退化 + 闸门全绿 + import 面零改动。
原行段映射: evidence/batch-03/tiles_manifest.json。
"""
from __future__ import annotations

from ._registry import _RegistryMixin
from ._config import _ConfigMixin
from ._closebtn import _CloseButtonMixin
from ._clicklog import _ClickLogMixin
from ._device import _DeviceMixin
from ._ocr import _OcrMixin
from ._collect import _CollectMixin
from ._reward import _RewardMixin
from ._findtext import _FindTextMixin
from ._judges import _JudgeMixin
from ._guard import _GuardMixin
from ._template import _TemplateMixin
from ._flowexec import _FlowExecMixin
from ._steps import _StepHandlersMixin
from ._buy import _BuyMixin
from ._buyseed import _BuySeedMixin
from ._plant import _PlantMixin
from ._fairyland import _FairylandMixin
from ._orchestrate import _OrchestrateMixin

from .._constants import ADB_ADDRESS, ADB_PATH
from .._stat import _new_ocr_stat
from ocr_ui import set_thread_limit

import threading
import time

import numpy as np

# ---------- 核心引擎 ----------
class OCREngine(
    _RegistryMixin,
    _ConfigMixin,
    _CloseButtonMixin,
    _ClickLogMixin,
    _DeviceMixin,
    _OcrMixin,
    _CollectMixin,
    _RewardMixin,
    _FindTextMixin,
    _JudgeMixin,
    _GuardMixin,
    _TemplateMixin,
    _FlowExecMixin,
    _StepHandlersMixin,
    _BuyMixin,
    _BuySeedMixin,
    _PlantMixin,
    _FairylandMixin,
    _OrchestrateMixin,
):
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
        # V03(ii)(batch-11): 本轮「归位已失败」编排状态位(纯编排层状态, 不改任何判定语义)。
        # pollin.ensure_home 归位失败时经公有口 note_home_recover_failed() 置位; run_daily
        # 入口按轮重置; run_module 入口据此做一次 at_home_main 轻验短路(见 _orchestrate)。
        self._home_recover_failed: bool = False
        # G1 v2(2026-11-03): 单轮已尝试购买次数 —— 硬上限, 由 run_module/run_flow 入口重置。
        # 只在「真正进入 buy_item 原子」时 +1(含失败尝试), 防止异常路径反复烧仙豆。
        self._buy_count: int = 0
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

    # ---- F02(batch-05, 2026-11-14): OCR 观测计数的公有读法(引擎协议化) ----
    def get_ocr_stat(self) -> dict:
        """取本引擎的 OCR 观测计数器(即 `self._ocr_stat`, 结构见 _stat._new_ocr_stat)。

        F02(batch-05): 采集层 pollin._panel_friend_pt 经此累计「好友」粗识/精识探测计数
        (原私有跨界 `eng._ocr_stat`, 协议化后走公有面, 引擎可被假引擎 mock 替换单测)。
        ⚠ 返回的是**引擎活引用而非副本**: 调用方(pollin)需要在其中做纯观测自增
        (friend_coarse_n 等键随后被 [OCR统计]/[粗OCR] 打印消费), 副本会丢失这些增量 ——
        这是「读法」而非「只读快照」的设计原因。键名一律不得改(离线分诊按 key 消费)。
        """
        return self._ocr_stat

    # ---- V03(ii)(batch-11): 「本轮归位已失败」编排状态的公有登记口 ----
    def note_home_recover_failed(self) -> None:
        """登记「本轮归位已失败」状态位(纯编排层状态, 不改任何判定语义)。

        pollin.ensure_home 归位失败(退出动作连续 2 轮画面无变化如实放弃 / 收尾未确认)时
        调用(F02 公有面口径, 采集层不触引擎私有成员); run_module 入口据此对后续模块做
        **一次** at_home_main 轻验: 画面已自行恢复 → 清位照常执行; 仍卡在同一画面 → 该模块
        短路记 fail(report_failure 照发, 不掩盖失败), 不再每模块重复烧 4 轮归位。
        作用域 = 本轮编排: run_daily 入口重置。
        """
        self._home_recover_failed = True
