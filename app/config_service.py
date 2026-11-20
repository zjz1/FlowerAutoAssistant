# -*- coding: utf-8 -*-
"""配置服务：键元数据表、校验应用、日志文案、回显、测试/使用模式。

从 webui.py 迁出（Stage 1）。HTTP 适配器只做请求解析与响应序列化。
"""
from __future__ import annotations

from pathlib import Path

from ocr_engine import OCREngine
from app.engine_service import get_engine

BASE = Path(__file__).resolve().parents[1]


def set_mode(mode: str) -> None:
    """切换测试/使用模式。测试模式=每步截图保存点击区。"""
    eng = get_engine()
    eng.debug_click = (mode == "test")
    if eng.debug_click:
        eng.debug_dir = BASE / "data" / "click_debug"
        eng.debug_dir.mkdir(parents=True, exist_ok=True)
        eng._click_seq = getattr(eng, "_click_seq", 0)


from config.schema import (CONFIG_KEYS as _CONFIG_KEYS,
                           LOG_ORDER as _CONFIG_LOG_ORDER,
                           LOG_SUFFIX as _CONFIG_LOG_SUFFIX,
                           MODULE_SETTINGS as _MODULE_SETTINGS,
                           NO_DEFAULT as _NO_DEFAULT)

def _apply_config_key(eng: OCREngine, key: str, spec: dict, value) -> str | None:
    """按表规格校验并落一个配置键(eng.update_config = 内存+data/config.json 双写)。

    返回 None=成功; str=400 错误文案(enum 键白名单外: 拒收不落配置, 且中断本请求后续
    处理 —— 已应用键保持已应用, 与改前 finish_action 分支原语义一致)。
    """
    t = spec["type"]
    # 2026-11-20 种植增强：数量必须 1~360（拒绝并回退，不钳制）；种子名必须在数据库
    if key == "plant_count":
        try:
            n = int(value)
        except (TypeError, ValueError):
            return "种植数量须为 1~360 的整数"
        if not 1 <= n <= 360:
            return "种植数量须在 1~360 之间"
        eng.update_config(plant_count=n)
        return None
    if key in ("plant_seed_preset", "plant_flower_type"):
        from plant import resolve_seed_name
        ok, msg, seed = resolve_seed_name(str(value))
        if not ok:
            return msg
        if key == "plant_seed_preset":
            eng.update_config(plant_seed_preset=seed)
        else:
            eng.update_config(plant_flower_type=str(value))
        return None
    if t == "bool":
        eng.update_config(**{key: bool(value)})
    elif t == "text":
        eng.update_config(**{key: str(value)})
    elif t == "int":
        try:
            n = int(value)
        except (TypeError, ValueError):
            n = spec["bad_int"]                    # ocr_threads: 解析失败回 2(改前原语义)
        lo, hi = spec["clamp"]
        n = max(lo, min(hi, n))                    # ocr_threads: max(0, min(8, thr))(改前原语义)
        eng.update_config(**{key: n})
    elif t == "float":
        try:
            eng.update_config(**{key: max(spec["min_v"], float(value))})
        except (TypeError, ValueError):
            pass                                   # fail_cache_prompt_mb: 坏值跳过不落盘(改前原语义)
    elif t == "enum":
        v = str(value or "")
        if v not in spec["enum_values"]:
            return spec["enum_error"].format(v=v)
        eng.update_config(**{key: v})
    return None


def _config_log_segment(eng: OCREngine, key: str, spec: dict, now: bool) -> str | None:
    """生成一个键的 [config] 日志片段; None=本行不渲染该键(如 target_tail 在切换账号关时)。"""
    if spec.get("log_cond") == "switch_now" and not now:
        return None
    if spec["log_fmt"] == "raw":
        return f"{spec['log_label']}={eng.config.get(key)}"
    if spec.get("log_value") == "now":
        v = now
    elif spec.get("log_default") is _NO_DEFAULT:
        v = eng.config.get(key)
    else:
        v = eng.config.get(key, spec["log_default"])
    if spec["log_fmt"] == "sw2":
        return f"{spec['log_label']} {'启用' if v else '关闭'}"
    return f"{spec['log_label']}={'开' if v else '关'}"


def _config_log_lines(eng: OCREngine, now: bool) -> list[str]:
    """生成 set_config 的 [config] 日志行(固定 3 行, 无论本请求改了哪些键 —— 与改前一致)。

    文案/键序/.get 缺省形态与改前逐字节一致(键序见 _CONFIG_LOG_ORDER)。
    """
    out: list[str] = []
    for ln in (1, 2, 3):
        segs = [s for s in (_config_log_segment(eng, k, _CONFIG_KEYS[k], now)
                            for k in _CONFIG_LOG_ORDER[ln]) if s is not None]
        line = "[config] " + segs[0] + "".join(", " + s for s in segs[1:]) \
            + _CONFIG_LOG_SUFFIX.get(ln, "")
        out.append(line)
    return out


def _config_echo(eng: OCREngine, now: bool, pre: bool) -> dict:
    """set_config 响应。回显键集/键序/缺省形态与改前逐字节一致(键序 = 表序过滤 echo≠None)。"""
    out: dict = {"ok": True, "changed": pre != now}
    for key, spec in _CONFIG_KEYS.items():
        e = spec.get("echo")
        if e is None:
            continue
        if e == "post":
            out[key] = now
        elif e == "enum_none":
            out[key] = str(eng.config.get(key, "none") or "none")
        else:
            out[key] = bool(eng.config.get(key, e))
    return out
