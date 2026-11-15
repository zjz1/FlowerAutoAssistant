using System.Text.Json;
using System.Text.Json.Serialization;

namespace FAA.WpfGui.Models;

// ---- 通用响应 ----

/// <summary>{ok: true} 型响应(set_mode/click/failures_clear 等, webui.py _send_ok 465-466 行)。</summary>
public sealed record OkResult(
    [property: JsonPropertyName("ok")] bool Ok);

/// <summary>{ok, message} 型响应(stop 1170 行 / shutdown 1176 行)。</summary>
public sealed record MessageResult(
    [property: JsonPropertyName("ok")] bool Ok,
    [property: JsonPropertyName("message")] string Message);

/// <summary>POST /api/log_clear 响应(1164 行): {ok, next:0} —— 前端必须把游标复位到 0。</summary>
public sealed record LogClearResult(
    [property: JsonPropertyName("ok")] bool Ok,
    [property: JsonPropertyName("next")] long Next);

/// <summary>错误响应: {"error": "..."}(各端点 4xx/5xx 通用)。</summary>
public sealed record ErrorResponse(
    [property: JsonPropertyName("error")] string Error);

// ---- POST 各端点专属响应 ----

/// <summary>POST /api/connect 响应(838 行): {"ok": ok, **_status()} —— status 字段平铺在顶层; 失败(502)时只有 ok。</summary>
public sealed record ConnectResult(
    [property: JsonPropertyName("ok")] bool Ok,
    [property: JsonPropertyName("connected")] bool Connected = false,
    [property: JsonPropertyName("screen")] int[]? Screen = null,
    [property: JsonPropertyName("work")] int[]? Work = null,
    [property: JsonPropertyName("flow_dir")] string? FlowDir = null,
    [property: JsonPropertyName("debug_click")] bool DebugClick = false,
    [property: JsonPropertyName("running")] bool Running = false,
    [property: JsonPropertyName("current_module")] string? CurrentModule = null,
    [property: JsonPropertyName("confirm_page_close")] bool ConfirmPageClose = false,
    [property: JsonPropertyName("ui_build")] string? UiBuild = null,
    [property: JsonPropertyName("fail_cache")] FailCacheInfo? FailCache = null);

/// <summary>POST /api/run 响应(1098 行): {ok, started}; 失败时 {"error"}。</summary>
public sealed record RunResult(
    [property: JsonPropertyName("ok")] bool Ok,
    [property: JsonPropertyName("started")] string Started = "");

/// <summary>POST /api/run_daily 响应(1058 行): {ok, started, count}。</summary>
public sealed record RunDailyResult(
    [property: JsonPropertyName("ok")] bool Ok,
    [property: JsonPropertyName("started")] string Started = "",
    [property: JsonPropertyName("count")] int Count = 0);

/// <summary>POST /api/set_config 响应(584-594 行): 回显 10 个关键开关。</summary>
public sealed record SetConfigResult(
    [property: JsonPropertyName("ok")] bool Ok,
    [property: JsonPropertyName("changed")] bool Changed,
    [property: JsonPropertyName("enable_switch")] bool EnableSwitch,
    [property: JsonPropertyName("claim_online")] bool ClaimOnline,
    [property: JsonPropertyName("claim_party")] bool ClaimParty,
    [property: JsonPropertyName("claim_hb")] bool ClaimHb,
    [property: JsonPropertyName("enable_shine")] bool EnableShine,
    [property: JsonPropertyName("enable_pollin")] bool EnablePollin,
    [property: JsonPropertyName("enable_like")] bool EnableLike,
    [property: JsonPropertyName("log_click_pos")] bool LogClickPos,
    [property: JsonPropertyName("use_cache_pos")] bool UseCachePos);

/// <summary>POST /api/fail_cache_clean 响应(631-632 行): {ok, removed, bytes, sessions, kept}。</summary>
public sealed record FailCacheCleanResult(
    [property: JsonPropertyName("ok")] bool Ok,
    [property: JsonPropertyName("removed")] int Removed,
    [property: JsonPropertyName("bytes")] long Bytes,
    [property: JsonPropertyName("sessions")] int Sessions,
    [property: JsonPropertyName("kept")] int Kept);

/// <summary>POST /api/fail_cache_open 响应(639 行): {ok, dir}; 失败 500 {ok:false, error}。</summary>
public sealed record FailCacheOpenResult(
    [property: JsonPropertyName("ok")] bool Ok,
    [property: JsonPropertyName("dir")] string Dir = "");

// ---- 截图 / OCR / 模板标注 ----

/// <summary>GET /api/screen 响应(860-863 行): jpeg 为 base64(不带 data: 前缀), w/h 为引擎工作区尺寸。</summary>
public sealed record ScreenShot(
    [property: JsonPropertyName("jpeg")] string Jpeg,
    [property: JsonPropertyName("w")] int W,
    [property: JsonPropertyName("h")] int H);

/// <summary>GET /api/ocr 响应(873 行): {"boxes": [...]}。</summary>
public sealed record OcrBoxList(
    [property: JsonPropertyName("boxes")] OcrBox[] Boxes);

/// <summary>OCR 文字块(_ocr_boxes 376-382 行): text/score + rel 相对中心坐标 + box 相对矩形。</summary>
public sealed record OcrBox(
    [property: JsonPropertyName("text")] string Text,
    [property: JsonPropertyName("score")] double Score,
    [property: JsonPropertyName("rel")] double[] Rel,
    [property: JsonPropertyName("box")] double[] Box);

/// <summary>POST /api/tplt_load 请求体(696-714 行): path 仅允许 debug/ 目录下文件。</summary>
public sealed record TpltLoadRequest(
    [property: JsonPropertyName("path")] string Path);

/// <summary>POST /api/tplt_load 响应(713-714 行): {jpeg, w, h, loaded}。</summary>
public sealed record TpltLoadResult(
    [property: JsonPropertyName("jpeg")] string Jpeg,
    [property: JsonPropertyName("w")] int W,
    [property: JsonPropertyName("h")] int H,
    [property: JsonPropertyName("loaded")] string Loaded);

/// <summary>GET /api/tplt_init 响应(685-694 行): {jpeg, w, h} —— 成功形状无 ok 键(webui.py 独有, mock_contract.md #11)。</summary>
public sealed record TpltInitResult(
    [property: JsonPropertyName("jpeg")] string Jpeg,
    [property: JsonPropertyName("w")] int W,
    [property: JsonPropertyName("h")] int H);

/// <summary>POST /api/tplt_submit 请求体(761-799 行): 最小必填 w/h, 其余标注集合形状不固定 → JsonElement 可空。</summary>
public sealed record TpltSubmitRequest(
    [property: JsonPropertyName("w")] int W,
    [property: JsonPropertyName("h")] int H,
    [property: JsonPropertyName("annotation_id")] string AnnotationId = "",
    [property: JsonPropertyName("shot")] string Shot = "",
    [property: JsonPropertyName("rects")] JsonElement? Rects = null,
    [property: JsonPropertyName("points")] JsonElement? Points = null,
    [property: JsonPropertyName("strokes")] JsonElement? Strokes = null,
    [property: JsonPropertyName("contours")] JsonElement? Contours = null,
    [property: JsonPropertyName("annotations")] JsonElement? Annotations = null,
    [property: JsonPropertyName("coord_note")] string CoordNote = "",
    [property: JsonPropertyName("meta")] JsonElement? Meta = null);

/// <summary>POST /api/tplt_submit 响应(809 行): {ok, annotation_id}。</summary>
public sealed record TpltSubmitResult(
    [property: JsonPropertyName("ok")] bool Ok,
    [property: JsonPropertyName("annotation_id")] string AnnotationId);

/// <summary>POST /api/tplt_contour 响应(759 行): {ok, points: [[x,y]...], n}。</summary>
public sealed record TpltContourResult(
    [property: JsonPropertyName("ok")] bool Ok,
    [property: JsonPropertyName("points")] int[][] Points,
    [property: JsonPropertyName("n")] int N);
