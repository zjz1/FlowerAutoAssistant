# -*- coding: utf-8 -*-
"""配置 schema：所有配置键的唯一事实源（Stage 2）。

数据来源：原 `app/config_service.py` 的 `_CONFIG_KEYS` / `_MODULE_SETTINGS` /
`_CONFIG_LOG_ORDER` / `_CONFIG_LOG_SUFFIX`，原样迁入后补充：
  - `FILE_ONLY_KEYS`：只存在于 config.json / config.example、不走 set_config 的键；
  - `DEFAULTS` / `EXAMPLE_ORDER` / `example_config()` / `validate_example()`。

使用方：
  - `app/config_service.py`：set_config 校验、日志文案、回显、⚙ meta；
  - `tools/check_project.py`：flow if_config / 示例配置 / WPF 键对账；
  - `tests/test_config_schema.py`：schema 自身不变量。
"""
from __future__ import annotations


_NO_DEFAULT = object()   # 哨兵: 日志 .get 不带默认值(区别于缺省 False)

_CONFIG_KEYS: dict[str, dict] = {
    # 切换账号(startup ⚙): 日志行1 用应用后现值渲染(改前即 now 局部变量语义)
    "enable_switch": dict(
        type="bool", log_line=1, log_label="切换账号功能", log_fmt="sw2", log_value="now",
        echo="post", meta=("切换账号", "登录前自动切换到目标账号"), meta_default=False),
    "target_tail": dict(
        type="text", log_line=1, log_label="目标尾部", log_fmt="raw", log_cond="switch_now",
        meta=("目标账号尾部", "匹配 abc****de 的末尾数字"), meta_default=""),
    # claim ⚙ 三键: 日志 .get 不带默认值(改前原形态; 缺键时 None → 「关」)
    "claim_online": dict(
        type="bool", log_line=2, log_label="领取奖励功能1在线礼包", log_fmt="sw",
        log_default=_NO_DEFAULT, echo=True,
        meta=("功能1 · 在线礼包", "抽奖耗尽次数 + 时间档位领取"), meta_default=True),
    "claim_party": dict(
        type="bool", log_line=2, log_label="功能2花灵派对", log_fmt="sw",
        log_default=_NO_DEFAULT, echo=True,
        meta=("功能2 · 花灵派对", "进入派对并领取 6 个在线时长礼包"), meta_default=True),
    "claim_hb": dict(
        type="bool", log_line=2, log_label="功能3奇妙花宝", log_fmt="sw",
        log_default=_NO_DEFAULT, echo=True,
        meta=("功能3 · 奇妙花宝", "家园→奇妙花宝→奇妙特权，领奇妙礼包每日/每周/每月三档"), meta_default=False),
    # 花仙乐园(2026-11-17): 不进 [config] 日志行(避免改既有日志契约), 仅 ⚙ 面板 + set_config 白名单
    "claim_fairyland": dict(
        type="bool",
        meta=("花仙乐园", "在线骰子 + 每日任务（兑换/浇水/仙豆；购买花种占位）"),
        meta_default=True),
    "enable_shine": dict(
        type="bool", log_line=2, log_label="闪耀委托挑战", log_fmt="sw",
        log_default=_NO_DEFAULT, echo=True,
        meta=("闪耀委托挑战", "家族活动 4.1.2 · 每日 10-21 时开放时段内执行"), meta_default=False),
    "enable_pollin": dict(
        type="bool", log_line=2, log_label="好友采粉", log_fmt="sw",
        log_default=True, echo=True,
        meta=("好友采粉", "4.2 · 密友+好友逐页采集花粉, 无可采则回自己家园"), meta_default=True),
    "enable_like": dict(
        type="bool", log_line=2, log_label="社区点赞", log_fmt="sw",
        log_default=False, echo=True,
        meta=("社区点赞", "完成手账「为精美搭配献上点赞吧」任务(每期上限 20 次; 任务已完成则跳过)"),
        meta_default=False),
    "enable_hot_sale": dict(
        type="bool", log_line=2, log_label="浏览热卖", log_fmt="sw",
        log_default=False,
        meta=("浏览热卖", "完成手账「查看最新热卖套装」任务(点行内前往进页浏览即完成, 不碰抽取按钮; "
              "2026-10-27 自社区点赞拆分独立)"), meta_default=False),
    "enable_baobao": dict(
        type="bool", log_line=2, log_label="花宝照顾", log_fmt="sw",
        log_default=False,
        meta=("花宝照顾", "完成手账「在花园中照顾小花宝一次」任务(道具手套拖拽, 消耗手套道具)"),
        meta_default=False),
    # G1 v2(2026-11-03): 花宝道具自动补货开关(缺键默认 true, 与 config.example 一致)
    "enable_baobao_buy": dict(
        type="bool", log_line=2, log_label="花宝补货", log_fmt="sw", log_default=True,
        meta=("花宝自动补货", "挠痒痒 0 库存时受控购买 22 仙豆/个(单轮最多 1 次; 余额低于 10000 停止; "
              "确认框全文核对+差额复核)"), meta_default=True),
    # 种植模块(2026-11-16 用户定稿): 四功能。种植花朵支持桃花系(白/粉/绿), 阶段0-2 与
    # 关面板归位已实现; 收获已实现; 授粉仍占位; 购买种子为独立流程 flow_buy_seed(本开关仅占位)。
    # 无 log_line/echo —— 不改既有 [config] 日志行与 set_config 回显键面(同 use_angle_cls 口径)。
    "plant_flower": dict(
        type="bool",
        meta=("种植花朵", "已实现: 自己家园归位→搜索→精确点选→数量1→随机种植→详情确认→关面板"),
        meta_default=False),
    "plant_flower_type": dict(
        type="text",
        meta=("花种选择", "可选：桃花(默认白色)/白色桃花/粉色桃花/绿色桃花"),
        meta_default="桃花"),
    "plant_pollinate": dict(
        type="bool",
        meta=("花朵授粉", "占位待开发, 开启暂无实际动作"),
        meta_default=False),
    "plant_harvest": dict(
        type="bool",
        meta=("收获花朵", "已实现: 可收获/可授粉判定; 无待授粉才一键收花; 结束关面板"),
        meta_default=False),
    "plant_buy_seed": dict(
        type="bool",
        meta=("购买种子", "独立功能: 手动单跑「购买种子」流程(flow_buy_seed), 不挂种植流程"),
        meta_default=False),
    "log_click_pos": dict(
        type="bool", log_line=3, log_label="记录按钮位置", log_fmt="sw", log_default=False,
        echo=False, meta=None),
    "use_cache_pos": dict(
        type="bool", log_line=3, log_label="使用缓存位置", log_fmt="sw", log_default=False,
        echo=False, meta=None),
    # W1(2026-10-27): OCR 推理线程数(0=不限制); ONNX 会话级, 改后需重启 webui 生效
    "ocr_threads": dict(type="int", bad_int=2, clamp=(0, 8), meta=None),
    # 2026-10-11 补: 里程碑 82 给 ⚙ 面板加 enable_mine/enable_rabbit 时漏了本处理器,
    # 勾选被静默丢弃(config.json 无键, if_config 读 None) —— 用户实测矿洞勾选无效即此因。
    "enable_mine": dict(
        type="bool", log_line=2, log_label="矿洞探险", log_fmt="sw", log_default=False,
        meta=("矿洞探险", "家族活动 4.1.3 · 每日礼包领取/次日「明日再来」跳过"), meta_default=False),
    "enable_rabbit": dict(
        type="bool", log_line=2, log_label="守望兔子", log_fmt="sw", log_default=False,
        meta=("守望兔子", "家族活动 4.1.4 · 占位待开发, 开启暂无实际动作"), meta_default=False),
    "enable_water": dict(
        type="bool", log_line=2, log_label="摇钱树浇水", log_fmt="sw", log_default=True,
        meta=("摇钱树浇水", "家族活动 4.1.1 · 每日浇水 X/3(含生效复核: 点击被吞自动重试 1 次)"),
        meta_default=True),
    "confirm_page_close": dict(type="bool", meta=None),
    # 2026-11-19: WPF 原生窗口「最小化时自动收进托盘」开关(默认 false=留在任务栏)。
    # 仅 WPF 设置页使用; 无 ⚙ meta / 无 [config] 日志行, 经 set_config + /api/status 回显。
    "minimize_to_tray": dict(type="bool", meta=None),
    # 里程碑 94: 截图缓存提醒阈值(MB) —— 必进白名单, 否则 WebUI 保存被静默丢弃(里程碑 87 教训)
    "fail_cache_prompt_mb": dict(type="float", min_v=1.0, meta=None),
    # 完成动作(2026-11-10, 完成后关闭客户端): 仅接受 none/close_client 二值, 之外一律 400
    # 拒收(不落配置, 不静默改成默认); 合法值经 eng.update_config 落内存+持久化, 供 run_daily
    # 无编排级动作时兜底读取。
    "finish_action": dict(
        type="enum", enum_values=("none", "close_client"),
        enum_error="finish_action 仅接受 none/close_client, 收到: {v!r}",
        echo="enum_none", meta=None),
    # OCR3(batch-08, 2026-11-14): 执行后端三档开关(cpu/dml/cuda, 默认 cpu=零行为)。
    # enum 白名单外 400 拒收(finish_action 同型); **无回显键、无 [config] 日志行** ——
    # set_config 响应键面(SET_CONFIG_ECHO_KEYS)与 [config] 三行文案是逐字节契约(api_contract_selftest
    # 钉住), 本键只经 /api/daily 识别设置回显 + webui.html 右栏下拉落键。改后重启生效
    # (ocr_ui 单例按首次 get_engine 时的档位构建; GPU 档构建失败自动回退 cpu 并在日志如实记录)。
    "ocr_execution_provider": dict(
        type="enum", enum_values=("cpu", "dml", "cuda"),
        enum_error="ocr_execution_provider 仅接受 cpu/dml/cuda, 收到: {v!r}", meta=None),
    # OCR2(batch-10, 2026-11-15): cls 方向分类器开关(RapidOCR use_angle_cls 构造参数透传,
    # 默认 true = 改动前行为逐字节等价)。bool 键; **无回显键、无 [config] 日志行**(键面/
    # 文案逐字节契约不动), 经 /api/daily 识别设置回显 + webui.html 右栏勾选落键。改后重启
    # 生效(ocr_ui 单例按首次 get_engine 时的值构建)。默认 true 是本批终态: det736 配对
    # A/B(实机授权, batch-12)落盘且过 0 退化门才允许默认翻 false —— 不得凭 det32/64
    # 数字默认关(负清单 N8); 速度口径标签: cls 关 median 快 11.0~11.3% 为 det32/64 实验口径,
    # det736 生产口径待本批 A/B。
    "use_angle_cls": dict(type="bool", meta=None),
}

# ⚙ 面板各模块键归属与顺序(_module_settings 渲染顺序; 键文案/缺省在 _CONFIG_KEYS.meta):
# 2026-10-07 用户反馈: ⚙ 只有 startup/claim 可点, 其余模块被 disabled —— 补齐 social 的
# 真实 if_config 开关(与 flow_social.json §4.1.1~4.1.4/4.2/4.3 一一对应, 默认值与
# data/config.example.json 一致)。plant/energy/daily/idle 四个流程无任何 if_config,
# 返回 [] → ⚙ 可点开面板显示「暂无独立子功能」说明。2026-10-11: 新增浇水开关
# enable_water(4.1.1, 默认 true)。2026-10-12: 社区点赞自社交模块迁入每日任务(daily 按
# 手账「献上点赞」行进度 a<b 门控执行, 已完成/行缺失跳过)。
# 2026-11-16: plant 不再是空面板 —— 种植模块四功能(种植花朵/花种选择/授粉/收获/购买种子),
# 前两项已接入, 其余三项占位默认关闭。
_MODULE_SETTINGS: dict[str, tuple[str, ...]] = {
    "claim": ("claim_online", "claim_party", "claim_hb", "claim_fairyland"),
    "startup": ("enable_switch", "target_tail"),
    "plant": ("plant_flower", "plant_flower_type", "plant_pollinate", "plant_harvest", "plant_buy_seed"),
    "social": ("enable_water", "enable_shine", "enable_mine", "enable_rabbit", "enable_pollin"),
    "daily": ("enable_like", "enable_hot_sale", "enable_baobao", "enable_baobao_buy"),
}

# [config] 日志行键序(与改前文案逐字节一致; 故意 ≠ 表的应用键序 —— 后补键不打乱历史顺序):
_CONFIG_LOG_ORDER: dict[int, tuple[str, ...]] = {
    1: ("enable_switch", "target_tail"),
    2: ("claim_online", "claim_party", "claim_hb", "enable_shine", "enable_water",
        "enable_mine", "enable_rabbit", "enable_pollin", "enable_like",
        "enable_hot_sale", "enable_baobao", "enable_baobao_buy"),
    3: ("log_click_pos", "use_cache_pos"),
}
_CONFIG_LOG_SUFFIX: dict[int, str] = {
    3: " (两项默认关闭; 关闭时只认实时识别, 不用历史坐标盲点)",
}

# ---- 供外部使用的稳定命名 ----
CONFIG_KEYS = _CONFIG_KEYS
MODULE_SETTINGS = _MODULE_SETTINGS
LOG_ORDER = _CONFIG_LOG_ORDER
LOG_SUFFIX = _CONFIG_LOG_SUFFIX
NO_DEFAULT = _NO_DEFAULT

# ---- 文件级键：存在 config.json / config.example，但不进 set_config 白名单 ----
FILE_ONLY_KEYS: dict[str, dict] = {
    "schema_version": dict(type="int", default=1, settable=False),
    "baobao_buy_floor": dict(type="int", default=10000, settable=False),
    "baobao_buy_max": dict(type="int", default=1, settable=False),
    "guard_reuse": dict(type="bool", default=True, settable=False),
    "region_ocr": dict(type="bool", default=True, settable=False),
}

# 1.0 #13: 配置版本号。语义 = 程序向 config.json 写入新键/改默认值时 +1, 并在
# `_MIGRATIONS` 中登记"从上一版升级做了什么"(当前仅补键, 无需逐键迁移函数)。
CONFIG_SCHEMA_VERSION = 1

ALL_KEYS: dict[str, dict] = {**CONFIG_KEYS, **FILE_ONLY_KEYS}
SETTABLE_KEYS: tuple[str, ...] = tuple(CONFIG_KEYS)

# ---- 默认值：config.example.json 的权威值 ----
DEFAULTS: dict[str, object] = {
    "schema_version": 1,
    "enable_switch": False,
    "target_tail": "",
    "claim_online": True,
    "claim_party": True,
    "claim_hb": False,
    "claim_fairyland": True,
    "enable_shine": False,
    "enable_pollin": True,
    "enable_like": False,
    "enable_hot_sale": False,
    "enable_baobao": False,
    "enable_baobao_buy": True,
    "plant_flower": False,
    "plant_flower_type": "桃花",
    "plant_pollinate": False,
    "plant_harvest": False,
    "plant_buy_seed": False,
    "log_click_pos": False,
    "use_cache_pos": False,
    "ocr_threads": 2,
    "enable_mine": False,
    "enable_rabbit": False,
    "enable_water": True,
    "confirm_page_close": True,
    "minimize_to_tray": False,
    "fail_cache_prompt_mb": 100,
    "finish_action": "none",
    "ocr_execution_provider": "cpu",
    "use_angle_cls": True,
    "baobao_buy_floor": 10000,
    "baobao_buy_max": 1,
    "guard_reuse": True,
    "region_ocr": True,
}

# ---- 示例配置键序（保持既有顺序；OCR 两项追加在末尾） ----
EXAMPLE_ORDER: tuple[str, ...] = (
    "enable_switch", "target_tail", "claim_online", "claim_party", "enable_shine",
    "enable_mine", "enable_rabbit", "enable_water", "enable_pollin", "enable_like",
    "enable_hot_sale", "enable_baobao", "enable_baobao_buy", "plant_flower",
    "plant_flower_type", "plant_pollinate", "plant_harvest", "plant_buy_seed",
    "baobao_buy_floor", "baobao_buy_max", "claim_hb", "claim_fairyland",
    "log_click_pos", "use_cache_pos", "region_ocr", "confirm_page_close",
    "minimize_to_tray", "fail_cache_prompt_mb", "guard_reuse", "ocr_threads",
    "ocr_execution_provider", "use_angle_cls", "schema_version",
)


def default_for(key: str):
    if key in DEFAULTS:
        return DEFAULTS[key]
    spec = ALL_KEYS[key]
    if "meta_default" in spec:
        return spec["meta_default"]
    if "log_default" in spec and spec["log_default"] is not NO_DEFAULT:
        return spec["log_default"]
    raise KeyError(f"{key} 缺少默认值")


def example_config() -> dict:
    return {k: default_for(k) for k in EXAMPLE_ORDER}


def _type_error(key: str, spec: dict, val) -> str | None:
    """已知键的类型错误文案（validate_example / validate_config / migrate_config 共用）。"""
    t = spec.get("type", "bool")
    if t == "bool" and not isinstance(val, bool):
        return f"{key} 应为 bool, 实为 {type(val).__name__}"
    if t == "text" and not isinstance(val, str):
        return f"{key} 应为 text, 实为 {type(val).__name__}"
    if t == "int" and (isinstance(val, bool) or not isinstance(val, int)):
        return f"{key} 应为 int, 实为 {type(val).__name__}"
    if t == "float" and not isinstance(val, (int, float)):
        return f"{key} 应为 float, 实为 {type(val).__name__}"
    if t == "enum" and val not in spec.get("enum_values", ()):
        return f"{key} 不在合法值 {spec.get('enum_values')}: {val!r}"
    return None


def validate_example(data: dict) -> list[str]:
    """校验 config.example.json 的非注释键：键集、类型、默认值。"""
    errs: list[str] = []
    actual = {k: v for k, v in data.items() if not k.startswith("_")}
    expected = set(EXAMPLE_ORDER)
    missing = sorted(expected - set(actual))
    extra = sorted(set(actual) - expected)
    if missing:
        errs.append(f"缺少键: {missing}")
    if extra:
        errs.append(f"多余键: {extra}")
    for key in EXAMPLE_ORDER:
        if key not in actual:
            continue
        spec = ALL_KEYS[key]
        val = actual[key]
        err = _type_error(key, spec, val)
        if err:
            errs.append(err)
        if val != DEFAULTS.get(key):
            errs.append(f"{key} 默认值漂移: schema={DEFAULTS.get(key)!r} example={val!r}")
    return errs


def validate_config(data: dict) -> list[str]:
    """校验用户 config.json（1.0 #13）。

    与 validate_example 的差别: 不要求键集完整（旧配置允许缺键, 由 migrate_config 补齐）,
    不比对默认值（用户可改），只校验已知键类型；未知键（含 `_` 注释键）一律允许并保留。
    """
    errs: list[str] = []
    for key, spec in ALL_KEYS.items():
        if key in data:
            err = _type_error(key, spec, data[key])
            if err:
                errs.append(err)
    return errs


def migrate_config(data: dict) -> tuple[dict, list[str]]:
    """把任意旧版 config.json 升级到 CONFIG_SCHEMA_VERSION（1.0 #13）。

    规则:
      - **只补不改不删**：缺失的已知键补 schema 默认值；已有值、未知键、`_` 注释键原样保留；
      - 版本高于当前（用户回退旧程序）→ 不降级、不动内容，仅在说明里提示；
      - 幂等：已是当前版本且键齐全时返回空说明，调用方据此跳过写盘。
    返回 (新配置, 变更说明列表)。
    """
    out = dict(data)
    notes: list[str] = []
    ver = out.get("schema_version")
    if isinstance(ver, bool) or not isinstance(ver, int):
        ver = 0
    if ver > CONFIG_SCHEMA_VERSION:
        return out, [f"配置 schema_version={ver} 高于程序支持的 {CONFIG_SCHEMA_VERSION}; "
                     f"保持原样(不降级), 若出现异常请升级程序"]
    added = [k for k in EXAMPLE_ORDER if k != "schema_version" and k not in out]
    for k in added:
        out[k] = default_for(k)
    if added:
        notes.append(f"补齐 {len(added)} 个缺失键: {', '.join(added)}")
    if ver != CONFIG_SCHEMA_VERSION:
        out["schema_version"] = CONFIG_SCHEMA_VERSION
        notes.append(f"schema_version {ver} → {CONFIG_SCHEMA_VERSION}")
    return out, notes


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    ap = argparse.ArgumentParser(description="FAA 配置 schema 工具")
    ap.add_argument("--print", action="store_true", help="打印 schema 生成的 example 配置")
    ap.add_argument("--check", action="store_true", help="校验 data/config.example.json")
    args = ap.parse_args()
    if args.print:
        print(json.dumps(example_config(), ensure_ascii=False, indent=4))
    if args.check:
        p = Path(__file__).resolve().parents[1] / "data" / "config.example.json"
        errs = validate_example(json.loads(p.read_text(encoding="utf-8")))
        if errs:
            print("✗ config.example.json 与 schema 不一致:")
            for e in errs:
                print("  -", e)
            raise SystemExit(1)
        print("✓ config.example.json 与 schema 一致")
