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
    [property: JsonPropertyName("ocr_threads")] int OcrThreads);

/// <summary>daily.modules 元素: id/flow/name/required + settings 面板。</summary>
public sealed record DailyModule(
    [property: JsonPropertyName("id")] string Id,
    [property: JsonPropertyName("flow")] string? Flow,
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("required")] bool Required,
    [property: JsonPropertyName("settings")] SettingItem[] Settings);

/// <summary>daily.modules[].settings 元素(webui.py _module_settings): value 为 switch→bool / text→string, 类型不定 → JsonElement。</summary>
public sealed record SettingItem(
    [property: JsonPropertyName("key")] string Key,
    [property: JsonPropertyName("type")] string Type,
    [property: JsonPropertyName("label")] string Label,
    [property: JsonPropertyName("desc")] string Desc,
    [property: JsonPropertyName("value")] JsonElement Value);
