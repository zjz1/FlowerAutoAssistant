using System.Net.Http;
using System.Text;
using System.Text.Json;
using FAA.WpfGui.Models;

namespace FAA.WpfGui.Services;

/// <summary>代理调用结果: 异常/HTTP 错误一律转 Result 返回, 不向上抛、也不静默吞掉。</summary>
/// <param name="Success">2xx 且反序列化成功才为 true。</param>
/// <param name="StatusCode">HTTP 状态码; 0 = 连接层失败(没拿到 HTTP 响应, 如连接拒绝/超时)。</param>
/// <param name="Value">2xx 时的反序列化结果。</param>
/// <param name="Error">失败原因(Exception.ToString 或 "HTTP {code}: body 前段")。</param>
/// <param name="RawBody">原始响应体(前 4KB), 供自测判定降级形状(如 503 {"error","status"})。</param>
public sealed record ProxyResult<T>(
    bool Success, int StatusCode, T? Value, string Error, string RawBody)
{
    public static ProxyResult<T> Ok(int code, T value, string raw) => new(true, code, value, "", raw);
    public static ProxyResult<T> HttpErr(int code, string body) =>
        new(false, code, default, $"HTTP {code}: {(body.Length > 200 ? body[..200] : body)}", body);
    public static ProxyResult<T> NetErr(Exception ex, string raw = "") =>
        new(false, 0, default, $"{ex.GetType().Name}: {ex.Message}", raw);
}

/// <summary>
/// FAA WebUI 服务端全量类型化代理(GET 11 + POST 15 = 26 个唯一端点)。
/// 端点契约全部对照 FlowerAutoAssistant/webui.py 的 Handler._route(478-655 行);
/// 26 口径含 GET /api/tplt_init(webui.py:646-647, mock_contract.md #11)。
/// HttpClient 静态共享(复用连接池, 每次新建会耗尽本地端口); base url 可配(实例字段, 单例 HttpClient 不绑 BaseAddress)。
/// 所有请求统一 10s 超时(HttpClient.Timeout 兜底 + 每请求 CTS)。
/// </summary>
public sealed class FaaProxy
{
    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(10) };

    /// <summary>统一 JSON 编解码选项: 属性名已用 [JsonPropertyName] 显式对应 snake_case, 这里不再做策略转换。</summary>
    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull,
    };

    /// <summary>服务端 base url, 如 "http://127.0.0.1:8765/"(可配; 缺省 8765 与 webui_app.py 启动口一致)。</summary>
    public string BaseUrl { get; }

    public FaaProxy(string? baseUrl = null)
    {
        BaseUrl = baseUrl ?? "http://127.0.0.1:8765/";
        if (!BaseUrl.EndsWith('/'))
        {
            BaseUrl += "/";
        }
    }

    // ==================== 内部工具 ====================

    /// <summary>GET 并反序列化为 T。任何异常转 Result。</summary>
    private async Task<ProxyResult<T>> GetAsync<T>(string pathAndQuery, CancellationToken ct = default)
    {
        try
        {
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(10));
            using var resp = await Http.GetAsync(BaseUrl + pathAndQuery, cts.Token);
            var body = await resp.Content.ReadAsStringAsync(cts.Token);
            if (!resp.IsSuccessStatusCode)
            {
                return ProxyResult<T>.HttpErr((int)resp.StatusCode, body);
            }
            var value = JsonSerializer.Deserialize<T>(body, JsonOpts);
            return value is null
                ? new ProxyResult<T>(false, (int)resp.StatusCode, default, "空响应体", body)
                : ProxyResult<T>.Ok((int)resp.StatusCode, value, body);
        }
        catch (Exception ex)
        {
            return ProxyResult<T>.NetErr(ex);
        }
    }

    /// <summary>POST JSON 并反序列化为 T。任何异常转 Result。</summary>
    private async Task<ProxyResult<T>> PostAsync<T>(string path, object payload, CancellationToken ct = default)
    {
        try
        {
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(10));
            var json = JsonSerializer.Serialize(payload, payload.GetType(), JsonOpts);
            using var content = new StringContent(json, Encoding.UTF8, "application/json");
            using var resp = await Http.PostAsync(BaseUrl + path, content, cts.Token);
            var body = await resp.Content.ReadAsStringAsync(cts.Token);
            if (!resp.IsSuccessStatusCode)
            {
                return ProxyResult<T>.HttpErr((int)resp.StatusCode, body);
            }
            var value = JsonSerializer.Deserialize<T>(body, JsonOpts);
            return value is null
                ? new ProxyResult<T>(false, (int)resp.StatusCode, default, "空响应体", body)
                : ProxyResult<T>.Ok((int)resp.StatusCode, value, body);
        }
        catch (Exception ex)
        {
            return ProxyResult<T>.NetErr(ex);
        }
    }

    /// <summary>POST 空体(服务端 _read_json 对 Content-Length=0 返回 {})</summary>
    private async Task<ProxyResult<T>> PostEmptyAsync<T>(string path, CancellationToken ct = default)
        => await PostAsync<T>(path, new Dictionary<string, object?>(), ct);

    /// <summary>GET 原始字节(log_download 是 text/plain 附件, 不走 JSON 反序列化)</summary>
    public async Task<ProxyResult<byte[]>> GetBytesAsync(string pathAndQuery, CancellationToken ct = default)
    {
        try
        {
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(10));
            using var resp = await Http.GetAsync(BaseUrl + pathAndQuery, cts.Token);
            if (!resp.IsSuccessStatusCode)
            {
                var errBody = await resp.Content.ReadAsStringAsync(cts.Token);
                return ProxyResult<byte[]>.HttpErr((int)resp.StatusCode, errBody);
            }
            var bytes = await resp.Content.ReadAsByteArrayAsync(cts.Token);
            return ProxyResult<byte[]>.Ok((int)resp.StatusCode, bytes, "");
        }
        catch (Exception ex)
        {
            return ProxyResult<byte[]>.NetErr(ex);
        }
    }

    // ==================== GET 11 端点 ====================

    /// <summary>GET /api/status —— 状态快照(webui.py _status 404 行)。</summary>
    public Task<ProxyResult<StatusSnapshot>> GetStatusAsync(CancellationToken ct = default)
        => GetAsync<StatusSnapshot>("api/status", ct);

    /// <summary>GET /api/flows —— 流程清单(webui.py 492 行)。</summary>
    public Task<ProxyResult<FlowList>> GetFlowsAsync(CancellationToken ct = default)
        => GetAsync<FlowList>("api/flows", ct);

    /// <summary>GET /api/kb —— 点击知识库(webui.py _kb 812 行)。</summary>
    public Task<ProxyResult<KbData>> GetKbAsync(CancellationToken ct = default)
        => GetAsync<KbData>("api/kb", ct);

    /// <summary>GET /api/daily —— 每日编排与设置面板(webui.py _daily 901 行)。</summary>
    public Task<ProxyResult<DailyPlan>> GetDailyAsync(CancellationToken ct = default)
        => GetAsync<DailyPlan>("api/daily", ct);

    /// <summary>GET /api/plant_presets —— 种植种子数据库（花名→颜色→种子/稀有/肥力消耗）。</summary>
    public Task<ProxyResult<PlantPresetsDoc>> GetPlantPresetsAsync(CancellationToken ct = default)
        => GetAsync<PlantPresetsDoc>("api/plant_presets", ct);

    /// <summary>POST /api/preflight —— 运行前开/关功能与风险汇总（统一确认框）。</summary>
    public Task<ProxyResult<PreflightResult>> GetPreflightAsync(string[] modules, CancellationToken ct = default)
        => PostAsync<PreflightResult>("api/preflight", new { modules }, ct);

    /// <summary>GET /api/screen —— JPEG 预览帧(webui.py _screen 841 行; 未连接 503)。</summary>
    public Task<ProxyResult<ScreenShot>> GetScreenAsync(CancellationToken ct = default)
        => GetAsync<ScreenShot>("api/screen", ct);

    /// <summary>GET /api/ocr —— 按需 OCR 文字框(webui.py _ocr 866 行; 未连接 503)。</summary>
    public Task<ProxyResult<OcrBoxList>> GetOcrAsync(CancellationToken ct = default)
        => GetAsync<OcrBoxList>("api/ocr", ct);

    /// <summary>GET /api/failures?after=N —— 失败清单增量(webui.py _failures 876 行)。</summary>
    public Task<ProxyResult<FailuresPage>> GetFailuresAsync(long after = 0, CancellationToken ct = default)
        => GetAsync<FailuresPage>($"api/failures?after={after}", ct);

    /// <summary>GET /api/log?after=N —— 运行日志增量分片(webui.py _log 1101 行)。</summary>
    public Task<ProxyResult<LogBatch>> GetLogAsync(long after = 0, CancellationToken ct = default)
        => GetAsync<LogBatch>($"api/log?after={after}", ct);

    /// <summary>GET /api/log_download —— 全量日志导出 txt(BOM + 头注释, webui.py _log_download 1112 行)。</summary>
    public Task<ProxyResult<byte[]>> DownloadLogAsync(CancellationToken ct = default)
        => GetBytesAsync("api/log_download", ct);

    /// <summary>GET /api/fail_cache_info —— 截图缓存统计(webui.py 624 行; 真实服务端因 set 序列化恒 500)。</summary>
    public Task<ProxyResult<FailCacheStat>> GetFailCacheInfoAsync(CancellationToken ct = default)
        => GetAsync<FailCacheStat>("api/fail_cache_info", ct);

    /// <summary>GET /api/tplt_init —— 标注工具初始化截图(webui.py 646-647/685-694 行; 成功形状 {jpeg,w,h} 无 ok 键)。</summary>
    public Task<ProxyResult<TpltInitResult>> TpltInitAsync(CancellationToken ct = default)
        => GetAsync<TpltInitResult>("api/tplt_init", ct);

    // ==================== POST 15 端点 ====================

    /// <summary>POST /api/connect —— 连接设备(webui.py _connect 829 行)。</summary>
    public Task<ProxyResult<ConnectResult>> ConnectAsync(CancellationToken ct = default)
        => PostEmptyAsync<ConnectResult>("api/connect", ct);

    /// <summary>POST /api/set_mode {mode} —— 测试/使用模式(webui.py 598-601 行)。</summary>
    public Task<ProxyResult<OkResult>> SetModeAsync(string mode, CancellationToken ct = default)
        => PostAsync<OkResult>("api/set_mode", new Dictionary<string, object?> { ["mode"] = mode }, ct);

    /// <summary>POST /api/click {rel:[rx,ry]} —— 相对坐标点击(webui.py _click 886 行)。</summary>
    public Task<ProxyResult<OkResult>> ClickRelAsync(double relX, double relY, CancellationToken ct = default)
        => PostAsync<OkResult>("api/click", new Dictionary<string, object?> { ["rel"] = new[] { relX, relY } }, ct);

    /// <summary>POST /api/click {x,y} —— 绝对坐标点击(webui.py _click 894-895 行)。</summary>
    public Task<ProxyResult<OkResult>> ClickAbsAsync(int x, int y, CancellationToken ct = default)
        => PostAsync<OkResult>("api/click", new Dictionary<string, object?> { ["x"] = x, ["y"] = y }, ct);

    /// <summary>POST /api/run {flow, mode} —— 运行单个流程(webui.py _run 1061 行)。</summary>
    public Task<ProxyResult<RunResult>> RunAsync(string flow, string mode = "use", CancellationToken ct = default)
        => PostAsync<RunResult>("api/run", new Dictionary<string, object?> { ["flow"] = flow, ["mode"] = mode }, ct);

    /// <summary>
    /// POST /api/run_daily {selected, mode, finish_action} —— 按勾选模块跑每日编排(webui.py _run_daily_sel 1000 行)。
    /// finish_action=完成后动作: none=无动作 / close_client=完成后关闭客户端。
    /// 键名收尾方案 A1 由批 21 的 "finish" 更名 "finish_action" —— 对齐批 22 真后端
    /// data["finish_action"](_backend/webui.py:1020), 消除批 21 键名与批 22 键名不一致这一笔误源。
    /// 旧后端只读 selected/mode, 未知键 finish_action 被忽略(=安全); 引擎批 22 合并后生效。
    /// ⚠ Mock(_mock/mock_faa_api.py)对缺 finish_action 键的请求回 400(A1 防再犯 tripwire,
    ///   见该文件 MOCK: 注记); finish=null 时按 JsonOpts(忽略 null)整键省略 —— 客户端现行调用
    ///   (HomeViewModel.StartAsync / ApiSelfTest)均传非 null, 不会触发该 400。
    /// </summary>
    public Task<ProxyResult<RunDailyResult>> RunDailyAsync(IEnumerable<string> selected, string mode = "use",
        string? finish = null, CancellationToken ct = default)
        => PostAsync<RunDailyResult>("api/run_daily", new Dictionary<string, object?>
        {
            ["selected"] = selected,
            ["mode"] = mode,
            ["finish_action"] = finish,   // 收尾方案 A1: 键名 finish → finish_action(批 22 真后端键名)
        }, ct);

    /// <summary>POST /api/stop —— 请求停止当前流程(webui.py _stop 1167 行)。</summary>
    public Task<ProxyResult<MessageResult>> StopAsync(CancellationToken ct = default)
        => PostEmptyAsync<MessageResult>("api/stop", ct);

    /// <summary>
    /// POST /api/set_config —— 设置保存(webui.py 512-594 行)。白名单过滤(见 SetConfigKeys:
    /// 服务端 19 键 + 批 21 过渡键 finish_action), 传入字典按白名单过滤后提交;
    /// 对真实实例这是唯一受支持的设置写入面。
    /// </summary>
    public Task<ProxyResult<SetConfigResult>> SetConfigAsync(IReadOnlyDictionary<string, object?> config, CancellationToken ct = default)
    {
        var filtered = new Dictionary<string, object?>();
        foreach (var kv in config)
        {
            if (SetConfigKeys.Contains(kv.Key, StringComparer.Ordinal))
            {
                filtered[kv.Key] = kv.Value;
            }
        }
        return PostAsync<SetConfigResult>("api/set_config", filtered, ct);
    }

    /// <summary>
    /// set_config 白名单: 前 19 键与 webui.py 516-565 行的 if 分支一一对应;
    /// 第 20 键 finish_action 为批 21 过渡新增(完成后动作 none/close_client) ——
    /// 旧后端无此键分支会被**静默丢弃**(如实降级: 仅随请求携带, 不报错), 引擎批 22 合并后生效;
    /// 第 21 键 ocr_execution_provider 为 OCR3 批新增(OCR 执行后端 cpu/dml/cuda, 默认 cpu) ——
    /// 与 webui.py _CONFIG_KEYS 元数据表同批同步(五处白名单对账, 闸门 check_webui_contract);
    /// 第 22 键 use_angle_cls 为 OCR2 批新增(OCR 方向分类器开关, bool, 默认 true=现状逐字节
    /// 等价; det736 配对 A/B 落盘前默认保持 true, 负清单 N8) —— 同批同步。
    /// </summary>
    public static readonly string[] SetConfigKeys =
    [
        "enable_switch", "target_tail",          // startup ⚙(936-940)
        "claim_online", "claim_party", "claim_hb", "claim_fairyland",  // claim ⚙(2026-11-17 花仙乐园)
        "enable_water", "enable_shine", "enable_mine", "enable_rabbit", "enable_pollin",  // social ⚙(948-959)
        "plant_flower", "plant_flower_type", "plant_pollinate", "plant_harvest", "plant_buy_seed",  // plant ⚙(2026-11-16 四功能)
        "plant_seed_mode", "plant_seed_preset", "plant_count_mode", "plant_count",  // 种植增强(2026-11-20)
        "plant_buy_missing", "plant_auto_buy", "plant_rare_confirm",
        "plant_harvest_allowed",                  // 收获保护白名单(WPF 原生面板编辑, 列表值)
        "enable_like", "enable_hot_sale", "enable_baobao", "enable_baobao_buy",           // daily ⚙(963-976)
        "log_click_pos", "use_cache_pos",        // 识别设置(539-542)
        "ocr_threads",                            // OCR 线程数(543-549)
        "ocr_execution_provider",                 // OCR 执行后端(OCR3 batch-08; cpu/dml/cuda, 默认 cpu)
        "use_angle_cls",                          // OCR 方向分类(OCR2 batch-10; bool, 默认 true)
        "confirm_page_close", "fail_cache_prompt_mb",  // 页面确认(558)/缓存阈值(561)
        "minimize_to_tray",                       // 界面: 最小化自动收进托盘(默认 false)
        "finish_action",                          // 完成后动作(批 21 过渡键; 旧后端静默忽略, 批 22 生效)
    ];

    /// <summary>POST /api/shutdown —— 关闭服务(webui.py _shutdown 1173 行: 0.3s 后退出)。</summary>
    public Task<ProxyResult<MessageResult>> ShutdownAsync(CancellationToken ct = default)
        => PostEmptyAsync<MessageResult>("api/shutdown", ct);

    /// <summary>POST /api/failures_clear —— 清空失败清单(webui.py 608-610 行)。</summary>
    public Task<ProxyResult<OkResult>> FailuresClearAsync(CancellationToken ct = default)
        => PostEmptyAsync<OkResult>("api/failures_clear", ct);

    /// <summary>POST /api/log_clear —— 清空日志缓冲(连缓存像素一并清, 回 next=0; webui.py _log_clear 1149 行)。</summary>
    public Task<ProxyResult<LogClearResult>> LogClearAsync(CancellationToken ct = default)
        => PostEmptyAsync<LogClearResult>("api/log_clear", ct);

    /// <summary>POST /api/fail_cache_clean {mode, days} —— 清缓存像素(webui.py 629-632 行; mode: all|days)。</summary>
    public Task<ProxyResult<FailCacheCleanResult>> FailCacheCleanAsync(string mode, int? days = null, CancellationToken ct = default)
        => PostAsync<FailCacheCleanResult>("api/fail_cache_clean",
            new Dictionary<string, object?> { ["mode"] = mode, ["days"] = days }, ct);

    /// <summary>POST /api/fail_cache_open —— 打开缓存目录(webui.py 633-641 行)。</summary>
    public Task<ProxyResult<FailCacheOpenResult>> FailCacheOpenAsync(CancellationToken ct = default)
        => PostEmptyAsync<FailCacheOpenResult>("api/fail_cache_open", ct);

    /// <summary>POST /api/tplt_load {path} —— 载入 debug/ 下图片供标注(webui.py _tplt_load 696 行)。</summary>
    public Task<ProxyResult<TpltLoadResult>> TpltLoadAsync(string path, CancellationToken ct = default)
        => PostAsync<TpltLoadResult>("api/tplt_load", new TpltLoadRequest(path), ct);

    /// <summary>POST /api/tplt_submit —— 提交标注记录(webui.py _tplt_submit 761 行)。</summary>
    public Task<ProxyResult<TpltSubmitResult>> TpltSubmitAsync(TpltSubmitRequest payload, CancellationToken ct = default)
        => PostAsync<TpltSubmitResult>("api/tplt_submit", payload, ct);

    /// <summary>POST /api/tplt_contour {x0,y0,x1,y1} —— 框选区提取主轮廓(webui.py _tplt_contour 716 行)。</summary>
    public Task<ProxyResult<TpltContourResult>> TpltContourAsync(int x0, int y0, int x1, int y1, CancellationToken ct = default)
        => PostAsync<TpltContourResult>("api/tplt_contour",
            new Dictionary<string, object?> { ["x0"] = x0, ["y0"] = y0, ["x1"] = x1, ["y1"] = y1 }, ct);
}
