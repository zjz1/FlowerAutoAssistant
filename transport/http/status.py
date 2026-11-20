# -*- coding: utf-8 -*-
"""HTTP 路由 mixin：status。"""
from __future__ import annotations

from .common import *  # noqa: F401,F403
class StatusRoutes:
    def _daily(self):
        eng = get_engine()
        plan = None
        import json as _json
        p = BASE / "flows" / "daily.json"
        if p.exists():
            try:
                plan = _json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                plan = None
        # 中文任务名映射 (id -> 显示名)
        id2name = {
            "startup": "开始启动",
            "signin": "签到",
            "plant": "种植任务",
            "social": "社交任务",
            "energy": "体力任务",
            "daily": "每日任务",
            "idle": "挂机",
            "claim": "领取奖励",
        }
        modules = []
        # 各模块的可配置面板 meta (右侧 ⚙ 设置面板渲染数据)
        def _module_settings(mid):
            # F06+W03(batch-04): ⚙ 面板 meta 由 _MODULE_SETTINGS(归属与顺序) × _CONFIG_KEYS
            # (文案/缺省/type) 表生成, 与 set_config 白名单同源 —— 新增面板键不再可能被白名单
            # 静默丢弃(里程碑 82/87「勾选被静默丢弃」事故类的结构性消除)。
            # 2026-11-20: 支持 enum/int 控件(选种模式/数量模式/数量)。
            out = []
            for key in _MODULE_SETTINGS.get(mid, ()):
                spec = _CONFIG_KEYS[key]
                label, desc = spec["meta"]
                t = spec["type"]
                if t == "text":
                    mtype = "text"
                    val = str(eng.config.get(key, spec.get("meta_default", "")))
                elif t == "int":
                    mtype = "int"
                    val = int(eng.config.get(key, spec.get("meta_default", 1)))
                elif t == "enum":
                    mtype = "enum"
                    val = str(eng.config.get(key, spec.get("meta_default", "")))
                else:
                    mtype = "switch"
                    val = bool(eng.config.get(key, spec.get("meta_default", False)))
                item = {"key": key, "type": mtype, "label": label, "desc": desc, "value": val}
                if mtype == "enum":
                    item["options"] = list(spec.get("enum_values", ()))
                elif mtype == "int":
                    lo, hi = spec.get("clamp", (1, 360))
                    item["min"], item["max"] = lo, hi
                out.append(item)
            return out
        def _plant_seed_state():
            """当前生效种子与稀有标记（开始一轮前的二次确认用）。"""
            try:
                from plant import load_presets, resolve_seed_name
                mode = str(eng.config.get("plant_seed_mode", "manual"))
                raw = (eng.config.get("plant_seed_preset", "白色桃花") if mode == "preset"
                       else eng.config.get("plant_flower_type", "桃花"))
                ok, _msg, seed = resolve_seed_name(raw)
                if not ok or not seed:
                    return "", False
                return seed, bool(load_presets()["seeds"][seed]["rare"])
            except Exception:  # noqa: BLE001
                return "", False
        if plan and plan.get("modules"):
            for m in plan["modules"]:
                mid = m.get("id")
                modules.append({
                    "id": mid,
                    "flow": m.get("flow"),
                    "name": id2name.get(mid, mid),
                    "required": bool(m.get("required", False)),
                    "settings": _module_settings(mid),
                })
        seed_name, seed_rare = _plant_seed_state()
        return self._send_json({
            "name": plan.get("name") if plan else "每日挂机编排",
            "modules": modules,
            # W1(2026-10-27): 删除顶层 enable_switch/target_tail —— 消费方(右栏旧「账号切换」面板)
            # 已由 codex-20261025-4 删除, 现网回显唯一来源=modules[].settings(startup ⚙)。
            # 全局识别设置(供右栏「识别设置」面板回显); ocr_threads 改后重启生效(ONNX 会话)
            # ocr_execution_provider 同口径(OCR3 batch-08: 执行后端三档, 默认 cpu; 改后重启生效)
            # use_angle_cls 同口径(OCR2 batch-10: cls 方向分类器, 默认 true=现状逐字节等价;
            # det736 A/B 落盘(batch-12)前默认保持 true, 不得凭 det32/64 数字默认关 —— 负清单 N8)
            "log_click_pos": bool(eng.config.get("log_click_pos", False)),
            "use_cache_pos": bool(eng.config.get("use_cache_pos", False)),
            "ocr_threads": int(eng.config.get("ocr_threads", 2)),
            "ocr_execution_provider": str(eng.config.get("ocr_execution_provider", "cpu")),
            "use_angle_cls": bool(eng.config.get("use_angle_cls", True)),
            # 2026-11-20 种植增强：设置页「稀有种子确认」开关 + 当前种子稀有状态
            "plant_rare_confirm": bool(eng.config.get("plant_rare_confirm", True)),
            "plant_seed_name": seed_name,
            "plant_seed_rare": seed_rare,
        })
