using System.Windows.Media;
using CommunityToolkit.Mvvm.ComponentModel;
using FAA.WpfGui.Models;
using FAA.WpfGui.Services;

namespace FAA.WpfGui.ViewModels;

/// <summary>徽章/状态用色(冻结画刷, 跨线程只读安全)。色值沿用 NP1a 最小壳的 MAA 深色风格。</summary>
public static class UiBrushes
{
    public static readonly SolidColorBrush Ok = Freeze("#5BC46D");     // 绿: 在线
    public static readonly SolidColorBrush Warn = Freeze("#F2B04C");   // 橙: 探测中/启动中
    public static readonly SolidColorBrush Err = Freeze("#E5534B");    // 红: 冲突/不可达
    public static readonly SolidColorBrush Sub = Freeze("#9AA0A6");    // 灰: 未知/空闲

    private static SolidColorBrush Freeze(string hex)
    {
        var b = new SolidColorBrush((Color)ColorConverter.ConvertFromString(hex));
        b.Freeze();
        return b;
    }
}

/// <summary>
/// 壳(导航+状态徽章+服务生命周期)的 ViewModel。
/// 职责:
///   契约5 —— 启动三态探测: faa=连上现有实例不重起 / other=明确报错退出 / free=FaaProcessHost 自起服务
///            (语义对齐 FlowerAutoAssistant/webui_app.py main() 398-415 行)。
///   状态轮询 1.5s(webui.html:868 autoTimer 同频) → 状态徽章(连接/分辨率/运行中模块) → 下发各子页。
///   契约2 —— 关窗确认的判据数据(IsRunning / ConfirmPageClose)由本类维护, 判定在 MainWindow.Closing。
///   A3 —— 关闭服务入口(托盘菜单/设置页连接卡片共用): IsServiceConnected 判据 + ShutdownServiceAsync
///            (二次确认 → POST /api/shutdown → 状态刷新)。
///   C2 —— 「关于」页导航(静态信息页, AboutViewModel 无服务依赖)。
/// </summary>
public partial class MainViewModel : ObservableObject, IDisposable
{
    public AppSession Session { get; } = new();

    public HomeViewModel Home { get; }
    public LogViewModel Log { get; }
    public SettingsViewModel Settings { get; }
    public DebugViewModel Debug { get; }
    public FlowViewModel Flow { get; }
    public AboutViewModel About { get; }
    public FailuresViewModel Failures { get; }
    public FailCacheViewModel FailCache { get; }

    /// <summary>探测启动序列是否已跑过(Loaded 可能触发多次, 防重入)。</summary>
    private bool _startupDone;

    private CancellationTokenSource? _statusLoopCts;
    private int _statusFailStreak;

    // ---- SSE 推送通道(NP-sse) ----
    /// <summary>SSE 客户端(服务就绪后启动; log→LogStore / status→状态 / failure→浮层, 见 StartSse)。</summary>
    private SseClient? _sse;

    /// <summary>SSE 是否在线(OnConnected 置真 / OnDisconnected 置假); 日志页据此让 800ms 轮询让路或回落。</summary>
    public bool IsSseUp { get; private set; }

    /// <summary>UI 线程调度器(VM 在 UI 线程构造; SSE 事件在后台线程到达, 触 UI 须经此)。</summary>
    private readonly System.Windows.Threading.Dispatcher _uiDispatcher;

    /// <summary>SSE log 事件 / 后端进程输出(B2)已入 LogStore 后, 通知日志页追加显示行。</summary>
    public event Action<LogBatch>? SseLogArrived;

    /// <summary>SSE 游标倒退(服务端重启/缓冲被清): LogStore 已重同步, 日志页清显示。</summary>
    public event Action? SseLogResynced;

    public MainViewModel()
    {
        _uiDispatcher = System.Windows.Threading.Dispatcher.CurrentDispatcher;
        // 组合根: 子页 VM 共享本 VM 的 Session(Proxy/LastStatus/Logs)
        Home = new HomeViewModel(this);
        Log = new LogViewModel(this);
        Settings = new SettingsViewModel(this);
        Debug = new DebugViewModel(this);
        Flow = new FlowViewModel(this);
        About = new AboutViewModel();   // C2: 静态信息页, 不依赖 Session/Proxy
        Failures = new FailuresViewModel(this);
        FailCache = new FailCacheViewModel(this);
        _currentPage = Home;
        // B2: 后端进程 stdout/stderr/退出 → 日志链路(行前缀 [backend])。
        // ⚠ FaaProcessHost 三事件均在线程池线程触发(其注释已说明), 处理器内一律经 _uiDispatcher 调度回 UI 线程。
        Session.Host.OutputReceived += OnBackendOutputLine;
        Session.Host.ErrorReceived += OnBackendOutputLine;
        Session.Host.Exited += OnBackendExited;
    }

    // ==================== 导航(左侧栏) ====================

    [ObservableProperty]
    private object? _currentPage;

    [ObservableProperty]
    private bool _isNavHome = true;

    [ObservableProperty]
    private bool _isNavLog;

    [ObservableProperty]
    private bool _isNavSettings;

    [ObservableProperty]
    private bool _isNavDebug;

    [ObservableProperty]
    private bool _isNavFlow;

    [ObservableProperty]
    private bool _isNavAbout;

    partial void OnIsNavHomeChanged(bool value) { if (value) { SetPage(Home); } }
    partial void OnIsNavLogChanged(bool value) { if (value) { SetPage(Log); } }
    partial void OnIsNavSettingsChanged(bool value) { if (value) { SetPage(Settings); } }
    partial void OnIsNavDebugChanged(bool value) { if (value) { SetPage(Debug); } }
    partial void OnIsNavFlowChanged(bool value) { if (value) { SetPage(Flow); } }
    partial void OnIsNavAboutChanged(bool value) { if (value) { SetPage(About); } }

    private void SetPage(object page)
    {
        if (!ReferenceEquals(CurrentPage, page))
        {
            CurrentPage = page;
        }
        // 调试页可见性驱动其轮询暂停/恢复(后台/隐藏时暂停)
        Debug.OnPageVisibility(ReferenceEquals(page, Debug));
        if (ReferenceEquals(page, Debug))
        {
            Debug.OnNavigatedTo();
        }
        if (ReferenceEquals(page, Flow))
        {
            _ = Flow.LoadIfNeededAsync();   // 流程页首次进入懒加载 /api/flows + /api/kb
        }
    }

    /// <summary>程序化选页(--page 启动参数): 同步导航开关再设页。page: home|log|settings|debug|flow|about。</summary>
    public void NavigateTo(string page)
    {
        switch ((page ?? "").Trim().ToLowerInvariant())
        {
            case "log":
                SetOnlyNav(nameof(IsNavLog));
                break;
            case "settings":
                SetOnlyNav(nameof(IsNavSettings));
                break;
            case "debug":
                SetOnlyNav(nameof(IsNavDebug));
                break;
            case "flow":
                SetOnlyNav(nameof(IsNavFlow));
                break;
            case "about":   // C2: 「关于」页预选(截图取证 --page about 用)
                SetOnlyNav(nameof(IsNavAbout));
                break;
            default: // home(缺省, 含非法值回落)
                SetOnlyNav(nameof(IsNavHome));
                break;
        }
    }

    /// <summary>只点亮目标导航开关(其余熄灭; 最后置目标触发 OnChanged→SetPage)。</summary>
    private void SetOnlyNav(string target)
    {
        if (target != nameof(IsNavHome)) { IsNavHome = false; }
        if (target != nameof(IsNavLog)) { IsNavLog = false; }
        if (target != nameof(IsNavSettings)) { IsNavSettings = false; }
        if (target != nameof(IsNavDebug)) { IsNavDebug = false; }
        if (target != nameof(IsNavFlow)) { IsNavFlow = false; }
        if (target != nameof(IsNavAbout)) { IsNavAbout = false; }
        switch (target)
        {
            case nameof(IsNavHome): IsNavHome = true; break;
            case nameof(IsNavLog): IsNavLog = true; break;
            case nameof(IsNavSettings): IsNavSettings = true; break;
            case nameof(IsNavDebug): IsNavDebug = true; break;
            case nameof(IsNavFlow): IsNavFlow = true; break;
            case nameof(IsNavAbout): IsNavAbout = true; break;
        }
    }

    // ==================== 状态徽章 ====================

    [ObservableProperty]
    private string _connBadgeText = "连接状态: 探测中…";

    [ObservableProperty]
    private Brush _connDotBrush = UiBrushes.Warn;

    [ObservableProperty]
    private string _resolutionText = "待读取";

    [ObservableProperty]
    private string _runningText = "空闲";

    /// <summary>模式徽章(webui.html:464 mode-badge 同源 debug_click)。</summary>
    [ObservableProperty]
    private string _modeText = "使用模式";

    private void SetBadge(string text, Brush dot)
    {
        ConnBadgeText = text;
        ConnDotBrush = dot;
    }

    // ==================== 启动序列(契约5) ====================

    /// <summary>
    /// 启动三态探测(在 MainWindow.Loaded 里调, 不阻塞窗口显示):
    ///   other → 原生错误框 + 退出码 2(对齐 webui_app.py:399-404);
    ///   faa   → 连上现有实例, 不重起服务(webui_app.py:414-415);
    ///   free  → FaaProcessHost 自起服务并等就绪(webui_app.py:405-413; spawn 细节在 FaaProcessHost.StartAsync)。
    /// </summary>
    public async Task RunStartupSequenceAsync()
    {
        if (_startupDone)
        {
            return;
        }
        _startupDone = true;

        // --api-base 覆盖(批 21): 跳过三态探测/服务托管直连指定服务(调试/连 Mock 用)。
        // 连不上就让状态轮询/各页如实报错, 不代偿、不重起 —— 与 faa 模式同语义(绝不 spawn 服务)。
        if (Session.ApiBaseOverride is { } apiBase)
        {
            DebugTrace.Log($"startup: --api-base override -> {apiBase} (跳过探测/托管)");
            Session.Proxy = new FaaProxy(apiBase);
            Session.OwnsService = false;
            // 端口显示与 --api-base 对齐: 状态轮询按 Session.Port 重绘徽章, 原实现未同步
            // 导致 --api-base :8766 被显示成缺省 :8765(2026-11-16 实机发现)。
            if (Uri.TryCreate(Session.Proxy.BaseUrl, UriKind.Absolute, out var apiUri))
            {
                Session.Port = apiUri.Port;
            }
            SetBadge($"已连接 (--api-base :{Session.Port})", UiBrushes.Ok);
            await OnServiceReadyAsync("已按 --api-base 直连指定服务(调试模式: 不探测端口、不托管服务)");
            return;
        }

        var port = Session.Port;
        SetBadge($"探测 {port} 端口…", UiBrushes.Warn);
        DebugTrace.Log($"startup: probing :{port}");

        var state = await ProbeService.ProbeAsync(port);
        DebugTrace.Log($"startup: probe state={state}");
        switch (state)
        {
            case "faa":
                Session.Proxy = new FaaProxy($"http://127.0.0.1:{port}/");
                Session.OwnsService = false;
                SetBadge($"已连接现有实例 (:{port})", UiBrushes.Ok);
                await OnServiceReadyAsync("已连接现有 FAA 实例, 不重复起服务");
                break;

            case "other":
                SetBadge("端口被其他程序占用 (other)", UiBrushes.Err);
                await ShowFatalAndExitAsync(2,
                    $"端口 {port} 已被占用, 但未能识别为 FAA Web UI(可能正在启动, 或是别的程序)。\n\n" +
                    "请稍后重试, 或先关闭占用该端口的程序; 也可用 --port 指定其它端口。");
                break;

            default: // free
                SetBadge("端口空闲, 正在启动服务…(首次加载引擎模型需 10-30s)", UiBrushes.Warn);
                Session.OwnsService = true;
                var start = await Session.Host.StartAsync(port);
                if (!start.Success || start.Value is null)
                {
                    SetBadge("服务启动失败", UiBrushes.Err);
                    await ShowFatalAndExitAsync(3,
                        $"无法在端口 {port} 启动 Web 服务:\n{start.Error}\n\n" +
                        "(可先手动运行 webui.py 查看具体报错)");
                    break;
                }
                Session.Proxy = new FaaProxy(Session.Host.BaseUrl!);
                SetBadge($"已连接 (:{port}, 本窗口托管服务)", UiBrushes.Ok);
                await OnServiceReadyAsync("未发现运行中的实例, 已在本窗口托管启动服务");
                break;
        }
    }

    /// <summary>服务就绪(faa 或 free 自起成功)后的公共动作: 首拉数据 + 启动状态轮询。</summary>
    private async Task OnServiceReadyAsync(string readyNote)
    {
        DebugTrace.Log("serviceReady: begin");
        Home.StatusText = readyNote;
        _ = Home.LoadAsync();          // 任务列表(/api/daily), 失败会随状态轮询自动重试
        _ = Settings.LoadEchoAsync();  // 识别设置回显(/api/daily, 契约6 唯一来源)
        _ = Flow.LoadIfNeededAsync();  // 流程+知识库预载(--page flow 预选时页面 Loaded 早于服务就绪, 页面侧触发点会落空)
        _statusLoopCts = new CancellationTokenSource();
        _ = StatusLoopAsync(_statusLoopCts.Token);
        StartSse();                    // SSE 推送通道(日志/状态/失败), 断线自动回落轮询
        await RefreshStatusNowAsync();
        DebugTrace.Log("serviceReady: end");
    }

    // ==================== SSE 推送通道(NP-sse) ====================

    /// <summary>
    /// 启动 SSE(幂等): log→LogStore→日志页显示 / status→ApplyStatus(与 1.5s 轮询同路) /
    /// failures(批量)→失败浮层(批 21 修复) / failure(单数, 兼容保留)→失败浮层。
    /// 断线重连在 SseClient 内部(退避 2s/5s/10s); OnDisconnected 只把 IsSseUp 置假,
    /// 日志页据此恢复 800ms 轮询 —— 回落通道=契约4 原语义, 不需要额外降级逻辑。
    /// </summary>
    private void StartSse()
    {
        var proxy = Session.Proxy;
        if (proxy is null || _sse is not null)
        {
            return;   // 服务未就绪 / 已启动
        }
        var sse = new SseClient(proxy.BaseUrl);
        sse.OnLog += batch =>
        {
            if (!Session.Logs.Append(batch))
            {
                // SSE 游标倒退(服务端重启/缓冲被清): 以本事件重建游标账本(与日志页轮询重同步同款三动作),
                // 再通知日志页清显示 —— 否则 SSE 模式下轮询被跳过, 游标永远对不上。
                Session.Logs.Reset(0);
                Session.Logs.Append(batch);
                SseLogResynced?.Invoke();
                SseLogArrived?.Invoke(batch);
                return;
            }
            SseLogArrived?.Invoke(batch);
        };
        sse.OnConnected += () =>
        {
            IsSseUp = true;
            DebugTrace.Log("sse: connected (log/status/failure push)");
        };
        sse.OnDisconnected += reason =>
        {
            IsSseUp = false;   // → 日志页 800ms 轮询恢复(契约4 语义不变)
            DebugTrace.Log($"sse: down({reason}) -> fallback to 800ms polling");
        };
        sse.OnStatus += s =>
        {
            // SSE 事件在后台线程到达; ApplyStatus 触 UI 属性/集合 → 必须 marshal 回 UI 线程
            _uiDispatcher.BeginInvoke(() => ApplyStatus(s));
        };
        sse.OnFailures += page =>
        {
            // 失败批量事件 → 浮层(批 21: 服务端契约=复数 failures {items,next}; 失败清单为
            // ObservableCollection, 同样只在 UI 线程改)
            _uiDispatcher.BeginInvoke(() => Failures.OnSseFailures(page));
        };
        sse.OnFailure += f =>
        {
            // 失败单数事件 → 浮层(兼容保留; 现役服务端只推复数 failures)
            _uiDispatcher.BeginInvoke(() => Failures.OnSseFailure(f));
        };
        _sse = sse;
        sse.Start();
        DebugTrace.Log("sse: started");
    }

    // ==================== 后端进程输出接入(B2) ====================

    /// <summary>后端 stdout/stderr 行(两事件同型同处理, 行前缀 [backend])。⚠ 三事件均在线程池线程触发
    /// (FaaProcessHost 注释已说明), 一律经 _uiDispatcher 调度回 UI 线程再动共享状态/发通知。</summary>
    private void OnBackendOutputLine(string line)
        => _uiDispatcher.BeginInvoke(() => AppendBackendLine($"[backend] {line}"));

    /// <summary>后端进程退出(优雅停/被杀/崩溃都触发) → 日志页可见提示行(B2)。</summary>
    private void OnBackendExited(int? code)
        => _uiDispatcher.BeginInvoke(() =>
            AppendBackendLine($"[backend] 后端进程已退出(code={code?.ToString() ?? "未知"})"));

    /// <summary>
    /// 一行后端输出并入日志链路: ①LogStore 增量缓冲 —— Next 取当前游标, 只入本地缓冲(供离线导出)、
    /// **不推进游标**, 服务端 /api/log 增量语义不受影响(并发窗口由 LogStore.Append 的游标倒退守卫兜底);
    /// ②SseLogArrived 通知日志页显示 —— LogViewModel.OnSseLogArrived 自行 marshal(此处已在 UI 线程,
    /// 再 BeginInvoke 一次无害), 复用同一显示管道: 分片拆行/失败红显/底部自动滚动全兼容。
    /// 分片按 LogStore 契约自带换行, 该行立即完整可见。
    /// </summary>
    private void AppendBackendLine(string line)
    {
        var batch = new LogBatch(Session.Logs.Cursor, [line + "\n"]);
        Session.Logs.Append(batch);
        SseLogArrived?.Invoke(batch);
    }

    /// <summary>立即拉一次 /api/status 并应用(连接/保存日志等动作后主动刷新用)。</summary>
    public async Task RefreshStatusNowAsync()
    {
        try
        {
            await PollStatusAsync(CancellationToken.None);
        }
        catch
        {
            // PollStatusAsync 内部已兜底, 这里保底不向上抛
        }
    }

    /// <summary>状态轮询 1.5s(webui.html:868 同频); 服务未就绪时空转。</summary>
    private async Task StatusLoopAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                await Task.Delay(1500, ct);
                await PollStatusAsync(ct);
            }
            catch (OperationCanceledException)
            {
                break;
            }
            catch
            {
                // 单轮失败不打断轮询
            }
        }
    }

    private async Task PollStatusAsync(CancellationToken ct)
    {
        var proxy = Session.Proxy;
        if (proxy is null)
        {
            return;
        }
        var r = await proxy.GetStatusAsync(ct);
        if (!r.Success || r.Value is null)
        {
            DebugTrace.Log($"status poll FAIL: {r.Error}");
            // 连续失败才标红(单次抖动不闪徽章), 恢复后自动回绿 —— 如实反映不可达
            _statusFailStreak++;
            if (_statusFailStreak >= 2)
            {
                // 2026-11-19: 「重试中」只代表继续轮询 HTTP; 托管服务的真正恢复入口是
                // 「设置 → 重启后端」(服务不可达时保持可用)。外部服务只能等其恢复。
                SetBadge(Session.OwnsService
                    ? $"服务不可达, 可在「设置 → 重启后端」恢复 (:{Session.Port})"
                    : $"服务不可达, 等待外部服务恢复… (:{Session.Port})", UiBrushes.Err);
                IsServiceConnected = false;   // A3: 连续失败=已断开 → 「关闭服务」入口禁用
            }
            return;
        }
        _statusFailStreak = 0;
        SetBadge(Session.OwnsService
            ? $"已连接 (:{Session.Port}, 本窗口托管服务)"
            : Session.ApiBaseOverride is not null
                ? $"已连接 (--api-base :{Session.Port})"
                : $"已连接现有实例 (:{Session.Port})", UiBrushes.Ok);
        IsServiceConnected = true;   // A3: 服务可达 → 「关闭服务」入口可用
        ApplyStatus(r.Value);
    }

    /// <summary>应用状态快照: 徽章 + 会话字段 + 下发子页(契约1 的锁定数据源)。</summary>
    private void ApplyStatus(StatusSnapshot s)
    {
        Session.LastStatus = s;
        // confirm_page_close: webui.html:447 同款口径(非 false 即 true)
        Session.ConfirmPageClose = s.ConfirmPageClose;
        Session.MinimizeToTray = s.MinimizeToTray;
        ResolutionText = s.Screen is { Length: 2 }
            ? $"{s.Screen[0]}×{s.Screen[1]}"
            : "待读取";
        RunningText = s.Running
            ? $"运行中: {s.CurrentModule ?? "未知"}"
            : "空闲";
        ModeText = s.DebugClick ? "测试模式" : "使用模式";

        Home.OnStatusUpdated(s);
        Settings.OnStatusUpdated(s);
        Debug.OnStatusUpdated(s);
        FailCache.OnStatusUpdated(s);
        _ = Failures.PollAsync();   // 失败提醒随状态轮询顺带增量拉取(webui.html:498 同款)
        TrayQuickStateChanged?.Invoke(s.Running, Home.CanStart);   // 托盘快捷态同步(NP2 收尾)
    }

    /// <summary>托盘快捷态(开始/停止可用性)变化通知(TrayIconService 订阅, 手动同步 MenuItem)。</summary>
    public event Action<bool, bool>? TrayQuickStateChanged;

    // ==================== 关闭服务(A3: 托盘菜单/设置页连接卡片共用入口) ====================

    /// <summary>服务是否已连接(托管或外部实例就绪且最近状态可达) —— 「关闭服务」入口的可用判据。
    /// 置位: /api/status 轮询成功; 复位: 连续 2 轮失败(与徽章「服务不可达」同阈值, 防单次抖动闪断)。
    /// 托盘 MenuItem 与设置页命令均订阅本属性变化同步可用性(托盘不在可视树, 须手动同步)。</summary>
    [ObservableProperty]
    private bool _isServiceConnected;

    /// <summary>
    /// 关闭服务(A3): 仅已连接(托管或外部实例)时可用 → DialogService.Confirm 二次确认(批 C3; 默认按钮=取消,
    /// 防回车误触) → POST /api/shutdown(FaaProxy.ShutdownAsync, webui.py _shutdown 0.3s 后退出)
    /// → 成功后即刻置「未连接」并刷新状态(服务已停, 后续轮询如实转「服务不可达」)。失败如实弹框, 不静默。
    /// </summary>
    public async Task ShutdownServiceAsync()
    {
        var proxy = Session.Proxy;
        if (proxy is null || !IsServiceConnected)
        {
            DebugTrace.Log($"shutdown-service: SKIP (proxy={proxy is not null}, connected={IsServiceConnected})");
            return;
        }
        var tip = Session.OwnsService
            ? "服务由本窗口托管, 关闭后本窗口将显示「服务不可达」; 如需再次使用请重启本程序。"
            : "服务为外部实例, 关闭后如需再次使用请重新启动该实例。";
        if (!DialogService.Confirm(
                $"确定要关闭 FAA Web 服务吗?\n\n{tip}", "FAA 原生窗口", defaultCancel: true))
        {
            DebugTrace.Log("shutdown-service: 用户取消");
            return;
        }
        DebugTrace.Log("shutdown-service: 已确认 -> POST /api/shutdown");
        var r = await proxy.ShutdownAsync();
        if (r.Success && r.Value?.Ok == true)
        {
            IsServiceConnected = false;   // 入口即刻禁用(徽章随即转「服务已关闭」, 轮询失败 2 轮后转「服务不可达」)
            SetBadge("服务已关闭", UiBrushes.Err);
            await RefreshStatusNowAsync();   // 成功后状态刷新
        }
        else
        {
            DebugTrace.Log($"shutdown-service: FAIL {r.Error}");
            DialogService.Warn($"关闭服务失败:\n{r.Error}", "FAA 原生窗口");
        }
    }

    /// <summary>致命错误框 + 退出(webui_app.py _msgbox 0x10 错误图标同款; code: 2=端口冲突, 3=启动失败)。</summary>
    private async Task ShowFatalAndExitAsync(int exitCode, string text)
    {
        Session.ForceClose = true;   // 报错退出路径绕过契约2确认(对齐 webui_app.py 直接 return)
        DialogService.Error(text, "FAA 原生窗口");
        await Task.CompletedTask;
        System.Windows.Application.Current.Shutdown(exitCode);
    }

    /// <summary>停轮询 + 停日志页轮询 + 停 SSE; 进程级兜底杀树由 Dispose(App.OnExit) 负责。</summary>
    public void Stop()
    {
        _statusLoopCts?.Cancel();
        Log.StopPolling();
        var sse = _sse;
        if (sse is not null)
        {
            IsSseUp = false;
            _ = sse.StopAsync();   // 关窗路径: 火忘收尾即可(进程级资源由 Dispose 兜底)
        }
    }

    public void Dispose()
    {
        Stop();
        Session.Host.Dispose();
        GC.SuppressFinalize(this);
    }
}
