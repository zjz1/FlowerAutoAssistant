using System.IO;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using FAA.WpfGui.Models;

namespace FAA.WpfGui.Services;

/// <summary>
/// SSE frame 事件负载(B1 帧指纹推送): {"jpeg":"...","w":1280,"h":720} —— 与 GET /api/screen 响应同形状
/// (mock_faa_api.py:585 canned 帧与真实副本 webui.py:1263 引擎帧同形; jpeg=base64 无 data: 前缀,
/// w/h 为引擎工作区尺寸仅供诊断展示)。仅 ?frames=1 订阅的连接才会收到该事件。
/// </summary>
public sealed record FramePush(
    [property: JsonPropertyName("jpeg")] string Jpeg,
    [property: JsonPropertyName("w")] int W = 0,
    [property: JsonPropertyName("h")] int H = 0);

/// <summary>
/// SSE 客户端: 流式读 GET {base}/api/stream(text/event-stream), 解析 event/data 行分发:
///   event:log      data={"next":N,"lines":[...]} → OnLog(LogBatch) → LogStore.Append(契约4 游标语义不变)
///   event:status   data=与 /api/status 同形状     → OnStatus(StatusSnapshot) → 状态区
///   event:failures data={"items":[{id,ts,module,detail}...],"next":游标} → OnFailures(FailuresPage)
///                  → 浮层逐条+游标更新(批 19 审计实锤的服务端契约: 批量形状, 与 GET /api/failures 同形,
///                    对照 webui.py:1221 _sse_send("failures", {"items": items, "next": nxt}))
///   event:failure  data={"id","ts","module","detail"} → OnFailure(FailureItem) → 浮层
///                  (单数分支保留兼容: 真实副本/mock 均只推复数 failures, 单数留作未来契约回退)
///   event:frame    data={"jpeg","w","h"}(仅 ?frames=1 订阅的连接才推; B1 帧指纹推送,
///                  真实副本 webui.py:1200 引擎帧指纹变化才推) → OnFrame(FramePush) → 调试页上屏
/// 断线自动重连: 退避 2s/5s/10s(封顶后保持 10s), 连接健康(本连接收到过事件)后退避归零;
/// 响应头阶段 10s 超时(实例未起/断网时尽快进入退避)。任何事件/断线/解析失败都经事件如实上报, 不吞。
/// 专用静态 HttpClient: Timeout=InfiniteTimeSpan(长流不能带全局超时, 与 FaaProxy 的 10s 客户端分离)。
/// </summary>
public sealed class SseClient : IDisposable
{
    /// <summary>断线重连退避序列(毫秒): 2s → 5s → 10s, 之后保持 10s。</summary>
    private static readonly int[] BackoffMs = [2000, 5000, 10000];

    /// <summary>SSE 长连接专用客户端(流式, 无全局超时)。</summary>
    private static readonly HttpClient SseHttp = new() { Timeout = Timeout.InfiniteTimeSpan };

    private static readonly JsonSerializerOptions JsonOpts = new();

    private readonly string _baseUrl;
    private readonly string _streamPath;
    private CancellationTokenSource _cts = new();
    private Task? _loop;
    private int _backoffIndex;

    /// <summary>本客户端发起的连接尝试次数(首个连接之后的所有尝试, 含失败重试)。</summary>
    public int ReconnectCount { get; private set; }

    /// <summary>最近一次收到事件的时间(UTC); 诊断用。</summary>
    public DateTime? LastEventUtc { get; private set; }

    /// <summary>(event, data 原文)全量回调 —— 分发前的原始事件流。</summary>
    public event Action<string, string>? OnRaw;

    /// <summary>log 事件(LogBatch, 供 LogStore.Append)。</summary>
    public event Action<LogBatch>? OnLog;

    /// <summary>status 事件(状态区刷新)。</summary>
    public event Action<StatusSnapshot>? OnStatus;

    /// <summary>failures 批量事件(浮层提醒; data={items,next} 与 GET /api/failures 同形)。</summary>
    public event Action<FailuresPage>? OnFailures;

    /// <summary>failure 单数事件(浮层提醒; 兼容保留 —— 现役服务端只推复数 failures 批量)。</summary>
    public event Action<FailureItem>? OnFailure;

    /// <summary>frame 事件(B1: 仅 ?frames=1 订阅; data={jpeg,w,h} 与 GET /api/screen 同形)。</summary>
    public event Action<FramePush>? OnFrame;

    /// <summary>流建立(响应头到达)。</summary>
    public event Action? OnConnected;

    /// <summary>断线(带原因; EOF/异常/超时都触发, 随后退避重连)。</summary>
    public event Action<string>? OnDisconnected;

    /// <summary>(event, 原文/原因) 事件解析失败或未知事件类型, 不吞。</summary>
    public event Action<string, string>? OnParseError;

    /// <param name="streamPath">流端点相对路径(批 21: 自测可带查询串, 如 "api/stream?cutfirst=1"
    /// 让 mock 掐断首连以验证退避重连; 缺省 "api/stream", 与真实服务端契约一致)。</param>
    /// <param name="frames">B1: true 时订阅 URL 追加 ?frames=1(帧推送); 与既有查询串正确拼接 ——
    /// 已带 ? 用 & 连接(如 "api/stream?cutfirst=x" → "api/stream?cutfirst=x&frames=1"), 无 ? 用 ?。</param>
    public SseClient(string baseUrl, string? streamPath = null, bool frames = false)
    {
        _baseUrl = baseUrl.EndsWith('/') ? baseUrl : baseUrl + "/";
        var path = string.IsNullOrWhiteSpace(streamPath) ? "api/stream" : streamPath.TrimStart('/');
        if (frames)
        {
            path += path.Contains('?') ? "&frames=1" : "?frames=1";
        }
        _streamPath = path;
    }

    /// <summary>启动常驻连接循环(幂等: 已启动则忽略)。</summary>
    public void Start()
    {
        if (_loop is not null)
        {
            return;
        }
        _cts = new CancellationTokenSource();
        _loop = Task.Run(() => RunAsync(_cts.Token));
    }

    /// <summary>停止: 取消令牌并等循环收尾(退出期抛 OperationCanceled 属正常)。</summary>
    public async Task StopAsync()
    {
        _cts.Cancel();
        if (_loop is not null)
        {
            try
            {
                await _loop;
            }
            catch
            {
                // 停止期的取消异常/流读取异常都视为正常收尾
            }
        }
        _loop = null;
    }

    /// <summary>常驻循环: 连接 → 读流 → 断线退避重连, 直到令牌取消。</summary>
    private async Task RunAsync(CancellationToken ct)
    {
        var attempted = false;
        while (!ct.IsCancellationRequested)
        {
            if (attempted)
            {
                ReconnectCount++; // 首次连接之后的每次尝试都计入(含失败重试)
            }
            attempted = true;
            int received;
            try
            {
                received = await ReadConnectionAsync(ct);
                OnDisconnected?.Invoke($"流结束(本连接收到 {received} 个事件)"); // 服务端断流(EOF)也算断线
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                return; // 主动停止, 非故障
            }
            catch (Exception ex)
            {
                // 404/500/响应头超时/网络异常 → 如实上报后退避重连
                OnDisconnected?.Invoke($"{ex.GetType().Name}: {ex.Message}");
                received = 0;
            }
            // 退避: 本连接健康(收到过事件)则从 2s 重新起步, 否则按 2s/5s/10s 逐档递进(首败=2s)
            var delay = received > 0
                ? BackoffMs[0]
                : BackoffMs[Math.Min(_backoffIndex, BackoffMs.Length - 1)];
            if (received == 0)
            {
                _backoffIndex++;
            }
            try
            {
                await Task.Delay(delay, ct);
            }
            catch (OperationCanceledException)
            {
                return;
            }
        }
    }

    /// <summary>单次连接: 读响应头(10s 超时) → 逐行解析 SSE 帧 → 每帧回调。返回本连接收到的事件数。</summary>
    private async Task<int> ReadConnectionAsync(CancellationToken ct)
    {
        using var connectCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        connectCts.CancelAfter(TimeSpan.FromSeconds(10)); // 只限响应头阶段
        using var req = new HttpRequestMessage(HttpMethod.Get, _baseUrl + _streamPath);
        using var resp = await SseHttp.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, connectCts.Token);
        resp.EnsureSuccessStatusCode(); // 非 2xx → 异常 → 上层退避重连

        OnConnected?.Invoke();
        var count = 0;
        var eventType = "";
        var dataLines = new List<string>();

        using var stream = await resp.Content.ReadAsStreamAsync(ct);
        using var reader = new StreamReader(stream, Encoding.UTF8);
        while (await reader.ReadLineAsync(ct) is { } line)
        {
            if (line.Length == 0)
            {
                // 空行 = 帧结束 → 分发
                if (eventType.Length > 0 && dataLines.Count > 0)
                {
                    count++;
                    Dispatch(eventType, string.Join("\n", dataLines));
                }
                eventType = "";
                dataLines.Clear();
                continue;
            }
            if (line.StartsWith(':'))
            {
                continue; // SSE 注释/心跳行
            }
            if (line.StartsWith("event:"))
            {
                eventType = line["event:".Length..].Trim();
            }
            else if (line.StartsWith("data:"))
            {
                dataLines.Add(line["data:".Length..].TrimStart(' '));
            }
            // 其余字段(id:/retry:)按需忽略
        }
        return count;
    }

    /// <summary>按事件类型分发; JSON 解析失败与未知类型都走 OnParseError, 不静默吞。</summary>
    private void Dispatch(string eventType, string data)
    {
        LastEventUtc = DateTime.UtcNow;
        OnRaw?.Invoke(eventType, data);
        try
        {
            switch (eventType)
            {
                case "log" when JsonSerializer.Deserialize<LogBatch>(data, JsonOpts) is { } batch:
                    OnLog?.Invoke(batch);
                    return;
                case "status" when JsonSerializer.Deserialize<StatusSnapshot>(data, JsonOpts) is { } status:
                    OnStatus?.Invoke(status);
                    return;
                case "failures" when JsonSerializer.Deserialize<FailuresPage>(data, JsonOpts) is { } page:
                    // 批 21 修复(批 19 审计实锤): 服务端契约是复数 failures 批量事件({items,next}),
                    // 原先只分发单数 failure → 批量事件全落 OnParseError, SSE 失败推送旁路(轮询兜底还在, 不丢提醒)。
                    OnFailures?.Invoke(page);
                    return;
                case "failure" when JsonSerializer.Deserialize<FailureItem>(data, JsonOpts) is { } failure:
                    OnFailure?.Invoke(failure);   // 单数分支保留兼容(现役服务端不推, 留作契约回退)
                    return;
                case "frame" when JsonSerializer.Deserialize<FramePush>(data, JsonOpts) is { } frame:
                    OnFrame?.Invoke(frame);   // B1: 帧推送({jpeg,w,h}; 仅 ?frames=1 订阅的连接会收到)
                    return;
                default:
                    OnParseError?.Invoke(eventType, $"未知事件类型或缺字段: {Trunc(data, 120)}");
                    return;
            }
        }
        catch (JsonException ex)
        {
            OnParseError?.Invoke(eventType, $"{ex.Message} | {Trunc(data, 120)}");
        }
    }

    private static string Trunc(string s, int n) => s.Length <= n ? s : s[..n] + "…";

    /// <summary>同步取消(长驻客户端随应用生命周期; 不 dispose CTS 以免与在用令牌竞态)。</summary>
    public void Dispose()
    {
        _cts.Cancel();
    }
}
