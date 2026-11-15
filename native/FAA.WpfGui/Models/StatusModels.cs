using System.Text.Json.Serialization;

namespace FAA.WpfGui.Models;

/// <summary>
/// GET /api/status 响应快照。字段名与 webui.py _status() (404-440 行) 的 snake_case 一一对应。
/// </summary>
public sealed record StatusSnapshot(
    [property: JsonPropertyName("connected")] bool Connected,
    [property: JsonPropertyName("screen")] int[]? Screen,
    [property: JsonPropertyName("work")] int[]? Work,
    [property: JsonPropertyName("flow_dir")] string FlowDir,
    [property: JsonPropertyName("debug_click")] bool DebugClick,
    [property: JsonPropertyName("running")] bool Running,
    [property: JsonPropertyName("current_module")] string? CurrentModule,
    [property: JsonPropertyName("confirm_page_close")] bool ConfirmPageClose,
    [property: JsonPropertyName("ui_build")] string UiBuild,
    [property: JsonPropertyName("fail_cache")] FailCacheInfo FailCache);

/// <summary>status.fail_cache 嵌套对象(webui.py 433-439 行)。</summary>
public sealed record FailCacheInfo(
    [property: JsonPropertyName("mb")] double Mb,
    [property: JsonPropertyName("count")] int Count,
    [property: JsonPropertyName("sessions")] int Sessions,
    [property: JsonPropertyName("oldest")] string? Oldest,
    [property: JsonPropertyName("threshold_mb")] double ThresholdMb,
    [property: JsonPropertyName("exceed")] bool Exceed,
    [property: JsonPropertyName("prompt")] bool Prompt,
    [property: JsonPropertyName("archived")] FailCacheArchived? Archived);

/// <summary>fail_cache.archived: 最近一次归档信息(键不存在时为 null)。</summary>
public sealed record FailCacheArchived(
    [property: JsonPropertyName("ts")] long Ts,
    [property: JsonPropertyName("count")] int Count,
    [property: JsonPropertyName("mb")] double Mb,
    [property: JsonPropertyName("all")] bool All);

/// <summary>
/// GET /api/fail_cache_info 响应(webui.py 624-628 行: _fail_cache_stat() 展开 + mb/threshold_mb/exceed)。
/// ⚠ 已知服务端隐患: stat 里 files 是 Python set, json.dumps 无法序列化 → 真实服务端该端点恒 500。
/// Mock 按 list 给出 files 的合理形状; 真实实例上由 api-selftest 如实暴露为 FAIL。
/// </summary>
public sealed record FailCacheStat(
    [property: JsonPropertyName("bytes")] long Bytes,
    [property: JsonPropertyName("count")] int Count,
    [property: JsonPropertyName("sessions")] int Sessions,
    [property: JsonPropertyName("oldest")] string? Oldest,
    [property: JsonPropertyName("session")] string Session,
    [property: JsonPropertyName("session_files")] int SessionFiles,
    [property: JsonPropertyName("mb")] double Mb,
    [property: JsonPropertyName("threshold_mb")] double ThresholdMb,
    [property: JsonPropertyName("exceed")] bool Exceed);
