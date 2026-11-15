using System.Text.Json;
using System.Text.Json.Serialization;

namespace FAA.WpfGui.Models;

/// <summary>失败条目(ocr_engine.py report_failure 110-115 行: id/ts/module/detail)。</summary>
public sealed record FailureItem(
    [property: JsonPropertyName("id")] long Id,
    [property: JsonPropertyName("ts")] string Ts,
    [property: JsonPropertyName("module")] string Module,
    [property: JsonPropertyName("detail")] string Detail);

/// <summary>GET /api/failures?after=N 响应(webui.py _failures 876-883 行): {"items": [...], "next": 最新id}。</summary>
public sealed record FailuresPage(
    [property: JsonPropertyName("items")] FailureItem[] Items,
    [property: JsonPropertyName("next")] long Next);

/// <summary>GET /api/kb 响应(webui.py _kb 812-826 行): click_log 场景嵌套字典 + close_buttons 列表, 内部形状不固定 → JsonElement。</summary>
public sealed record KbData(
    [property: JsonPropertyName("click_log")] Dictionary<string, JsonElement> ClickLog,
    [property: JsonPropertyName("close_buttons")] JsonElement[] CloseButtons);

/// <summary>GET /api/log?after=N 响应(webui.py _log 1101-1109 行): {"next": 游标, "lines": 原始分片}。分片≠行(一次 write 一个分片)。</summary>
public sealed record LogBatch(
    [property: JsonPropertyName("next")] long Next,
    [property: JsonPropertyName("lines")] string[] Lines);
