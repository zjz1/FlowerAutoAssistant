# -*- coding: utf-8 -*-
"""click_log.json 脏分组清理工具(协作区 zcode-20261003-4 交付)。

背景(PROJECT_GUIDE §5 遗留待办): 独立跑 --flow 的时期, 未声明 scene 的点击落进「未分类」;
体力界面/家族活动界面 混入跨场景杂入条目与误点样本(如浇水误点「浇水次数标签」的 17 条)。
这些脏数据在 log_click_pos/use_cache_pos 开关重新打开后会参与均值复核, 造成误杀。

设计:
- 清理对象是**逐条人工核定**的静态清单(本文件内), 不做任何自动推断 —— 每条带理由, 可审计;
- 默认 --dry-run 只打印将执行的动作; --apply 才写盘;
- --apply 前自动备份 data/click_log.backup-<时刻>.json; 写盘前后各做一次 JSON 解析校验;
- 只删除「与正常分组完全重复(同名且 rel 距离<=0.01)」或「明确错误(死路径/错位/测试残留)」的条目,
  模糊存疑的一律不动(如 两个「家园」/「在线礼包」双位置记录, 活动图标每日轮换, 两种位置都出现过)。

用法(仓库根 FlowerAutoAssistant/ 下):
    .venv\\Scripts\\python.exe tools\\clean_click_log.py            # 干跑预览
    .venv\\Scripts\\python.exe tools\\clean_click_log.py --apply    # 备份并写盘
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent          # FlowerAutoAssistant/
CLICK_LOG = BASE / "data" / "click_log.json"

# ---- 清理清单(逐条核定, 证据见协作区 zcode-20261003-4 REPORT §3) ----

# 整组删除: 测试残留(2026-08-27 手工测试写入, 1 条)
DELETE_GROUPS = ["测试场景"]

# 组内删条目: {组名: [(按钮名, 理由), ...]}
DELETE_ENTRIES = {
    "未分类": [
        # 死路径: workbench 旧目录的模板名当按钮名记进来了(2026-09-19), 路径已不存在, 永远无法复用
        ("E:\\my_project\\trae project\\FAA_2026-9-18\\FlowerAutoAssistant\\workbench\\template\\friend_pollin.png", "死路径模板名"),
        ("E:\\my_project\\trae project\\FAA_2026-9-18\\FlowerAutoAssistant\\workbench\\template\\friend_enter_pollin.png", "死路径模板名"),
        ("E:\\my_project\\trae project\\FAA_2026-9-18\\FlowerAutoAssistant\\workbench\\template\\friend_page_jump.png", "死路径模板名"),
        # 错位: rel(0.052,0.038) 在左上角「菜单」附近, 而「种草社区」真位置在 rel(0.961,0.457)(2026-10-03 实测), n=2 属早期误录
        ("种草社区", "错位条目(真位置 0.961,0.457)"),
        # 以下与正常分组同名且 rel 距离<=0.01(完全重复), 信息在正常分组保留:
        ("登录", "重复=登录界面/登录"),
        ("社交", "重复=家园主界面/社交"),
        ("家族", "重复=社交界面/家族"),
        ("家族活动", "重复=家族界面/家族活动"),
        ("离开", "重复=家园主界面/离开"),
        ("菜单", "重复=家园主界面/菜单"),
        ("弹窗关闭", "重复=弹窗/关闭/弹窗关闭"),
        ("点击任意处关闭", "重复=弹窗/关闭/点击任意处关闭"),
        ("确定", "重复=弹窗/关闭/确定"),
        ("确认", "重复=弹窗/关闭/确认"),
        ("花灵派对", "重复=家园主界面/花灵派对"),
        ("光偶像", "重复=家园主界面/光偶像"),
        ("速通", "重复=家园主界面/速通"),
        ("快捷操作", "重复=家园主界面+好友花园/快捷操作"),
        ("采粉", "重复=好友花园/采粉"),
        ("闪耀变身", "重复=家园主界面/闪耀变身"),
    ],
    "体力界面": [
        # 能量模块运行期间在其它界面上产生的 1 样本杂入(场景误标), 均与正常分组完全重复:
        ("账号条目#1", "跨场景杂入=未分类同位"),
        ("社交", "跨场景杂入=家园主界面/社交"),
        ("家族", "跨场景杂入=社交界面/家族"),
        ("家族活动", "跨场景杂入=家族界面/家族活动"),
        ("在线礼包", "跨场景杂入=家园主界面/在线礼包"),
        ("菜单", "跨场景杂入=家园主界面/菜单"),
        ("花灵派对", "跨场景杂入=家园主界面/花灵派对"),
        ("close_online_small.png", "跨场景杂入=未分类同位"),
        # 保留: 光偶像/速通/确定/确认/弹窗关闭 为体力模块本场景条目
    ],
    "家族活动界面": [
        # 浇水误点样本: 17 条落在「今日浇水次数」标签 rel(0.8313,0.7833)(2026-10-03 两轮 bug 的知识库污染),
        # 真按钮在 rel(0.8484,0.6861); flow_social 已改 exact:true, 旧均值会误导复核, 删除后由新点击重新累积
        ("浇水", "误点标签样本(真按钮 0.8484,0.6861)"),
        ("家族", "重复=社交界面/家族"),
        ("家族活动", "重复=家族界面/家族活动"),
        # 保留: 捐献/活跃/贡献/摇钱树/闪耀委托挑战/参与挑战/弹窗关闭 等
    ],
}


def main() -> int:
    apply = "--apply" in sys.argv
    if not CLICK_LOG.exists():
        print(f"[清理] 未找到 {CLICK_LOG}")
        return 1
    data = json.loads(CLICK_LOG.read_text(encoding="utf-8"))
    scenes = data.get("scenes", {})

    actions: list[tuple[str, str, str]] = []   # (组, 按钮名, 理由)
    for g in DELETE_GROUPS:
        if g in scenes:
            for name in scenes[g]:
                actions.append((g, name, "整组删除(测试残留)"))
    for g, items in DELETE_ENTRIES.items():
        btns = scenes.get(g, {})
        for name, reason in items:
            if name in btns:
                actions.append((g, name, reason))
            else:
                print(f"  [跳过] {g}/{name} 不存在(可能已清理)")

    print(f"[清理] 计划动作 {len(actions)} 项" + ("(dry-run)" if not apply else "(apply)"))
    for g, name, reason in actions:
        print(f"  - 删 {g}/{name}  # {reason}")

    if not actions:
        print("[清理] 无可执行动作")
        return 0
    if not apply:
        print("[清理] dry-run 结束(加 --apply 执行写盘)")
        return 0

    backup = CLICK_LOG.with_name(f"click_log.backup-{time.strftime('%Y%m%d-%H%M%S')}.json")
    shutil.copy2(CLICK_LOG, backup)
    print(f"[清理] 已备份 -> {backup.name}")

    for g in DELETE_GROUPS:
        scenes.pop(g, None)
    n = 0
    for g, name, _ in actions:
        if g in scenes and name in scenes[g]:
            del scenes[g][name]
            n += 1
    out = json.dumps(data, ensure_ascii=False, indent=1)
    json.loads(out)  # 写盘前校验
    CLICK_LOG.write_text(out, encoding="utf-8")
    json.loads(CLICK_LOG.read_text(encoding="utf-8"))  # 写盘后校验
    print(f"[清理] 已删除 {n} 条, 写盘并二次校验通过")
    print(f"[清理] 清理后分组: { {s: len(b) for s, b in scenes.items()} }")
    return 0


if __name__ == "__main__":
    sys.exit(main())
