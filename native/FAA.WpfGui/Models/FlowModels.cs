using System.Text.Json;
using System.Text.Json.Serialization;

namespace FAA.WpfGui.Models;

/// <summary>GET /api/flows 元素(webui.py 492-502 行)。modules 为流程文件里的原样对象, 形状不固定 → JsonElement。</summary>
public sealed record FlowInfo(
    [property: JsonPropertyName("name")] string? Name,
    [property: JsonPropertyName("file")] string? File,
    [property: JsonPropertyName("description")] string Description,
    [property: JsonPropertyName("modules")] JsonElement[] Modules);

/// <summary>GET /api/flows 响应: {"flows": [...]}</summary>
public sealed record FlowList(
    [property: JsonPropertyName("flows")] FlowInfo[] Flows);

/// <summary>GET /api/daily 响应(webui.py _daily 901-997 行): 每日编排 + 各模块设置面板 + 全局识别设置。</summary>
public sealed record DailyPlan(
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("modules")] DailyModule[] Modules,
    [property: JsonPropertyName("log_click_pos")] bool LogClickPos,
    [property: JsonPropertyName("use_cache_pos")] bool UseCachePos,
    [property: JsonPropertyName("ocr_threads")] int OcrThreads,
    [property: JsonPropertyName("plant_rare_confirm")] bool PlantRareConfirm = true,
    [property: JsonPropertyName("plant_seed_name")] string? PlantSeedName = null,
    [property: JsonPropertyName("plant_seed_rare")] bool PlantSeedRare = false,
    [property: JsonPropertyName("plant_harvest_allowed")] string[]? PlantHarvestAllowed = null);

/// <summary>daily.modules 元素: id/flow/name/required + settings 面板。</summary>
public sealed record DailyModule(
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("flow")] string? Flow,
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("required")] bool Required,
    [property: JsonPropertyName("settings")] SettingItem[] Settings);

/// <summary>daily.modules[].settings 元素(webui.py _module_settings): switch→bool / text→string / enum→string / int→number。</summary>
public sealed record SettingItem(
    [property: JsonPropertyName("key")] string Key,
    [property: JsonPropertyName("type")] string Type,
    [property: JsonPropertyName("label")] string Label,
    [property: JsonPropertyName("desc")] string Desc,
    [property: JsonPropertyName("value")] JsonElement Value,
    [property: JsonPropertyName("options")] string[]? Options = null,
    [property: JsonPropertyName("min")] int? Min = null,
    [property: JsonPropertyName("max")] int? Max = null);

/// <summary>GET /api/plant_presets —— 种植种子数据库（2026-11-20）。</summary>
public sealed record PlantPresetsDoc(
    [property: JsonPropertyName("version")] int Version,
    [property: JsonPropertyName("flowers")] PlantFlower[] Flowers);

public sealed record PlantFlower(
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("colors")] PlantColor[] Colors);

public sealed record PlantColor(
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("seed")] string Seed,
    [property: JsonPropertyName("rare")] bool Rare = false,
    [property: JsonPropertyName("cost")] int Cost = 2,
    [property: JsonPropertyName("cost_source")] string? CostSource = null);

/// <summary>POST /api/preflight —— 运行前开/关功能与风险汇总（2026-11-20）。</summary>
public sealed record PreflightResult(
    [property: JsonPropertyName("enabled")] string[] Enabled,
    [property: JsonPropertyName("disabled")] string[] Disabled,
    [property: JsonPropertyName("risks")] string[] Risks,
    [property: JsonPropertyName("text")] string Text);
