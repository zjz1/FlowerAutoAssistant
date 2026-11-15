"""日志时间戳与 OCR 观测计数。

E01(batch-03, 2026-11-14) 自单文件 ocr_engine.py 机械拆包: 本文件各段为原文件对应
行段的**逐行原文**(唯 __file__ 锚点因包层级 +1 机械重锚定, 见 ast_hash_compare.py
allowlist)。行为等价口径: 帧集回归 0 退化 + 闸门全绿 + import 面零改动。
原行段映射: evidence/batch-03/tiles_manifest.json。
"""
from __future__ import annotations

import time
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
        # P1(2026-11-10) split 两个子类(纯观测, 计时与 split_n/t 重叠、非独立口径):
        "split_wide_n": 0, "split_wide_t": 0.0,   # _split_wide 过宽块固定 2x 拆分(裁片耗时大头)
        "refine_n": 0, "refine_t": 0.0,           # _refine_wide_block 命中合并块后的定向精识
        "hit_n": 0,              # 帧缓存命中(不产生 OCR)
        "direct_n": 0, "direct_t": 0.0,   # 流程外直调 OCR(页码/诊断等)
        "split_cache_hit": 0,     # 拆分结果缓存命中(不产生 OCR)
        "split_only_hit": 0,      # 仅子块命中(判断类跳过拆分的安全指标)
        "scene_calls": 0,         # judge_scene 调用次数
        "miss_silent_n": 0,       # E1: 静默未命中次数(弹窗/启动守卫的常态负判定)
        "scene_quiet_n": 0,       # P2-5: 被折叠的场景判断次数(轮询内负判定, 由等待汇总替代)
        "friend_coarse_n": 0, "friend_coarse_hit": 0,   # P2-5③: 社交面板「好友」粗 OCR 探测/命中
        "friend_fine_n": 0, "friend_fine_hit": 0,       # P2-5③: 粗识失败后的滤色精识兜底 探测/命中
        # Q04(batch-05, 2026-11-14): 截图次数/耗时(纯新增键, 既有键不动) —— 输入管道是主要
        # 慢因之一, 此前 [OCR统计] 只有 OCR 各口径计时, OCR 慢 vs 截图慢无法分账。
        # screenshot()(engine/_device.py) 计时并入; 旧统计结构缺键由 .get 兼容。
        "shot_n": 0, "shot_t": 0.0,
        # V01-a(batch-11): TM_SQDIFF 低对比塌缩观测(纯新增键, 既有键不动; locate_template 写入,
        # _print_ocr_stat 仅在 tm_low_n 非零时追加 [模板观测] 汇总行 —— 常态零输出,
        # [OCR统计] 既有行文案/键序零漂移; 方案 [OCR统计] 键面白名单: V01-a 允许新增观测键)。
        # 背景: 07 笔记实测「低灰度std模板 × 低对比背景」下 1.0−minVal 分数塌缩
        # (12 真实模板 6/12 最佳分=0.0000), 标定数据须先观测化才可信。纯观测, 不改判定。
        "tm_low_n": 0,            # 低灰度std模板(<25, 07 笔记 V01 口径)匹配调用次数
        "tm_low_hit_n": 0,        # 其中判命中次数(判定结果本身不变, 仅观测)
        "tm_low_score_sum": 0.0,  # 最佳分累计(均分=和/次数, 供逐模板标定)
        "tm_low_by_tpl": {},      # 模板名 -> {n, hit, sum} 逐模板标定数据(_stat_add 递归合并)
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
