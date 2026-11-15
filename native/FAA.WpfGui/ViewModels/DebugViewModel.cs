using System.ComponentModel;
using System.IO;
using System.Windows.Media.Imaging;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using FAA.WpfGui.Models;
using FAA.WpfGui.Services;

namespace FAA.WpfGui.ViewModels;

/// <summary>OCR 文字框(展示用): text/score + box 相对矩形[0..1]×4 + rel 相对中心。</summary>
public sealed record OcrBoxVm(string Text, double Score, double[] Box, double[] Rel);

/// <summary>
/// 调试页 ViewModel —— 对照 webui.html「测试界面」:
///   实时画面: SSE frame 推送优先(B1: 独立 ?frames=1 订阅, 页面可见才开; 推送帧即时上屏),
///   推送断流回落 /api/screen 1.5s 轮询兜底(webui autoTimer 同频), 页面不可见/窗口最小化时暂停;
///   OCR 标注按需: 勾选才调 /api/ocr(webui.html:527), 框 2.5s 过期不再叠加(webui.html:519);
///   点击发送: 点击坐标→rel→POST /api/click(webui.html:995)+hit 动效+点后刷新画面与框;
///   模式切换 test/use → POST /api/set_mode(契约7; webui.html:859-862; test=每步存点击截图);
///   连接(A4): POST /api/connect 连接设备 —— 与主页/设置页连接同语义(复用 FaaProxy.ConnectAsync),
///   设备未连时 /api/screen 返回 503 无画面; 连接成功即强制取一帧, 分辨率在底栏 ScreenStatusText 回显;
///   帧解码(D6): 图像源校验 + 失败灰图占位, 不让解码异常逃逸(轮询与推送共用一解码器)。
/// </summary>
public partial class DebugViewModel : ObservableObject
{
    private readonly MainViewModel _main;
    private readonly System.Windows.Threading.DispatcherTimer _timer;
    private readonly System.Windows.Threading.Dispatcher _uiDispatcher;
    private bool _screenPolling;
    private bool _boxesPolling;

    /// <summary>OCR 框取框时刻(本地); 2.5s 过期由视图判定不再叠加(webui boxesStamp 语义)。</summary>
    public long OcrStampTicks { get; private set; }

    public DebugViewModel(MainViewModel main)
    {
        _main = main;
        _uiDispatcher = System.Windows.Threading.Dispatcher.CurrentDispatcher;   // VM 在 UI 线程构造(MainViewModel 组合根)
        _timer = new System.Windows.Threading.DispatcherTimer(
            System.Windows.Threading.DispatcherPriority.Background)
        {
            Interval = TimeSpan.FromMilliseconds(1500),   // webui autoTimer 1500ms 同频
        };
        _timer.Tick += async (_, _) => await PollScreenTickAsync();
    }

    // ==================== 实时画面 ====================

    /// <summary>当前帧(冻结的 BitmapImage, 跨线程赋值安全)。</summary>
    [ObservableProperty]
    private BitmapSource? _screenImage;

    [ObservableProperty]
    private string _screenStatusText = "服务就绪后开始取画面";

    /// <summary>自动刷新开关(默认开; 对应 webui auto-chk)。</summary>
    [ObservableProperty]
    private bool _isAutoRefresh = true;

    partial void OnIsAutoRefreshChanged(bool value)
    {
        UpdateTimerState();
        if (value)
        {
            EnsureFrameSse();   // B1: 重开自动刷新 → 帧推送一并恢复(懒建, 代理未就绪则随 tick 自愈)
        }
        else
        {
            StopFrameSse();     // 手动模式 → 推送一并停(画面只在点「刷新」时更新)
        }
    }

    // ==================== OCR 框(按需) ====================

    /// <summary>OCR 标注开关: 勾选时才取文字框(按需 OCR; webui.html:527 同语义)。</summary>
    [ObservableProperty]
    private bool _isOcrEnabled;

    partial void OnIsOcrEnabledChanged(bool value)
    {
        if (value)
        {
            _ = PollBoxesAsync();   // 勾选瞬间取一次框
        }
        else
        {
            Boxes = [];
            OcrStampTicks = 0;
            RaiseBoxesUpdated();
        }
    }

    /// <summary>最近一次取到的框(视图订阅 BoxesUpdated 重绘)。</summary>
    public IReadOnlyList<OcrBoxVm> Boxes { get; private set; } = [];

    /// <summary>框集更新通知(视图重绘 overlay)。</summary>
    public event Action? BoxesUpdated;

    private void RaiseBoxesUpdated()
    {
        BoxesUpdated?.Invoke();
    }

    [RelayCommand]
    private async Task RefreshAsync()
    {
        await PollScreenTickAsync(force: true);
        if (IsOcrEnabled)
        {
            await PollBoxesAsync();   // 手动刷新连带重取框(webui.html:863)
        }
    }

    // ==================== 模式切换(契约7) ====================

    /// <summary>当前是否测试模式(回显自 /api/status.debug_click; webui mode-badge 同源)。</summary>
    [ObservableProperty]
    private bool _isTestMode;

    [RelayCommand]
    private async Task SetModeAsync(string mode)
    {
        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            ModeStatusText = "服务未就绪";
            return;
        }
        var m = mode == "test" ? "test" : "use";
        var r = await proxy.SetModeAsync(m);
        if (r.Success && r.Value?.Ok == true)
        {
            // 契约7: test=每步存点击截图(click_debug/), use=正常
            ModeStatusText = m == "test" ? "已切换: 测试模式(每步存点击截图)" : "已切换: 使用模式";
            IsTestMode = m == "test";
        }
        else
        {
            ModeStatusText = $"切换失败: {Trunc(r.Error)}";
        }
        await _main.RefreshStatusNowAsync();
    }

    [ObservableProperty]
    private string _modeStatusText = "";

    // ==================== 连接(A4: 顶栏连接按钮) ====================

    /// <summary>连接按钮文案: /api/status.connected 回显(webui.html:493-497 同源, 主页连接组同款)。</summary>
    [ObservableProperty]
    private string _connectButtonText = "连接";

    /// <summary>连接动作结果回显(按钮右侧); 常态连接态由按钮文案随状态轮询回显, 分辨率在底栏。</summary>
    [ObservableProperty]
    private string _connectStatusText = "";

    /// <summary>
    /// 「连接」命令(A4): POST /api/connect 连接设备(ADB 连模拟器; webui.py _connect 829 行) ——
    /// 与主页/设置页的连接按钮同语义, 复用 FaaProxy.ConnectAsync。设备未连时 /api/screen 返回 503(未连接),
    /// 调试页无画面可取; 连接成功即强制取一帧 → 底栏 ScreenStatusText 回显分辨率(W×H · 更新时间),
    /// 并 RefreshStatusNowAsync 让徽章/连接文案/模式全链回显(与 SettingsViewModel.ConnectAsync 同款收尾)。
    /// </summary>
    [RelayCommand]
    private async Task ConnectAsync()
    {
        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            ConnectStatusText = "服务未就绪";
            return;
        }
        ConnectStatusText = "正在连接设备…";
        var r = await proxy.ConnectAsync();
        var ok = r.Success && r.Value?.Ok == true;
        ConnectStatusText = ok ? "已连接(ADB)" : $"连接失败: {Trunc(r.Error)}";
        await _main.RefreshStatusNowAsync();
        if (ok)
        {
            await PollScreenTickAsync(force: true);   // 连接后立即取一帧(不等 1.5s 轮询), 分辨率随帧回显
            if (IsOcrEnabled)
            {
                await PollBoxesAsync();               // OCR 开着则连带重取框(与 RefreshAsync 同语义)
            }
        }
    }

    // ==================== 页面可见性 ====================

    /// <summary>导航进入/离开调试页时调用: 离开即停轮询与帧推送(后台/隐藏时暂停)。</summary>
    public void OnPageVisibility(bool visible)
    {
        UpdateTimerState();
        if (visible)
        {
            EnsureFrameSse();
        }
        else
        {
            StopFrameSse();
            ScreenStatusText = "已暂停(页面不可见)——切回本页自动恢复";
        }
    }

    private void UpdateTimerState()
    {
        var shouldRun = IsAutoRefresh && _isPageVisible;
        if (shouldRun && !_timer.IsEnabled)
        {
            _timer.Start();
        }
        else if (!shouldRun && _timer.IsEnabled)
        {
            _timer.Stop();
        }
    }

    private bool _isPageVisible;

    // ==================== 轮询 ====================

    private async Task PollScreenTickAsync(bool force = false)
    {
        EnsureFrameSse();   // B1: 帧推送连接懒建(页面可见+自动刷新开+代理就绪才建; 代理晚就绪随 tick 自愈)
        if (_screenPolling)
        {
            return;
        }
        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            return;
        }
        // B1 推送优先: 推送通道活着(PushFreshMs 内有 frame 事件, ≥3 个轮询周期)则本轮轮询退避跳过 ——
        // 画面由推送即时更新, 轮询次数随之下降; 推送断流/未建连接时恢复 1.5s 轮询兜底(原 autoTimer 语义)。
        // force(手动「刷新」/连接后取帧/点后取帧)不受退避约束 —— 显式动作永远取实时帧。
        if (!force && Environment.TickCount64 - _lastFramePushTicks < PushFreshMs)
        {
            return;
        }
        // 窗口最小化时跳过(后台/隐藏时暂停; DecodePixels 无意义)
        var win = System.Windows.Application.Current?.MainWindow;
        if (!force && win is not null && win.WindowState == System.Windows.WindowState.Minimized)
        {
            return;
        }
        _screenPolling = true;
        try
        {
            var r = await proxy.GetScreenAsync();
            if (!r.Success || r.Value is null)
            {
                // 未连接 503 / 截图失败 500: 如实显示, 不刷旧帧(语义不变; 解码失败才走 D6 占位)
                ScreenStatusText = $"截图失败: {Trunc(r.Error)}";
                return;
            }
            var dr = await System.Threading.Tasks.Task.Run(() => DecodeJpeg(r.Value.Jpeg));
            if (!dr.Ok)
            {
                // D6: 图像源校验/解码失败 → 灰图占位 + 文案, 绝不让异常逐 tick 逃逸成
                // DispatcherUnhandledException 刷屏(faa_gui_error.log 05:16 事故教训)
                ScreenStatusText = $"画面数据异常: {dr.Error}";
                ScreenImage = dr.Bmp;
                return;
            }
            ScreenImage = dr.Bmp;
            ScreenStatusText = $"{r.Value.W}×{r.Value.H} · 更新于 {DateTime.Now:HH:mm:ss}";
            RaiseFrameArrived();
        }
        finally
        {
            _screenPolling = false;
        }
    }

    /// <summary>新帧到达通知(视图据此按 2.5s 过期规则重绘框)。</summary>
    public event Action? FrameArrived;

    private void RaiseFrameArrived() => FrameArrived?.Invoke();

    // ==================== 帧解码(D6: 图像源校验 + 失败占位) ====================

    /// <summary>失败占位帧: 1×1 深灰像素(冻结; Image Stretch=Fill 拉伸即整块灰底, 视图侧最小 320×180)。</summary>
    private static readonly BitmapSource ScreenPlaceholder = CreatePlaceholder();

    private static BitmapSource CreatePlaceholder()
    {
        var bmp = BitmapSource.Create(1, 1, 96, 96, System.Windows.Media.PixelFormats.Gray8, null, new byte[] { 0x30 }, 1);
        bmp.Freeze();   // 冻结后跨线程只读安全
        return bmp;
    }

    /// <summary>解码结果: Ok=真帧; 失败时 Bmp=灰图占位、Error=原因(供底栏文案)。</summary>
    private sealed record DecodeResult(bool Ok, BitmapSource Bmp, string Error);

    /// <summary>
    /// JPEG 帧解码(1.5s 轮询与 B1 推送共用): 图像源校验在前 —— 空/base64 非法/非 JPEG 魔数(FF D8)
    /// 一律拒收不喂解码器; 解码失败(FileFormatException 等)返回灰图占位 + 原因,
    /// 绝不让异常逃逸成 DispatcherUnhandledException 刷屏(faa_gui_error.log 05:16 事故教训)。
    /// </summary>
    private static DecodeResult DecodeJpeg(string? jpegB64)
    {
        if (string.IsNullOrEmpty(jpegB64))
        {
            return new DecodeResult(false, ScreenPlaceholder, "空帧数据");
        }
        byte[] data;
        try
        {
            data = Convert.FromBase64String(jpegB64);
        }
        catch (FormatException ex)
        {
            return new DecodeResult(false, ScreenPlaceholder, $"base64 非法: {Trunc(ex.Message)}");
        }
        if (data.Length < 3 || data[0] != 0xFF || data[1] != 0xD8)
        {
            // JPEG SOI 魔数校验: 拒收明显不是 JPEG 的载荷(错误页 HTML/JSON 被塞进 jpeg 字段等)
            return new DecodeResult(false, ScreenPlaceholder, $"非 JPEG 数据({data.Length}B)");
        }
        try
        {
            var img = new BitmapImage();
            using var ms = new MemoryStream(data);
            img.BeginInit();
            img.CacheOption = BitmapCacheOption.OnLoad;
            img.StreamSource = ms;
            img.EndInit();
            img.Freeze();   // 冻结后可跨线程交给 UI
            return new DecodeResult(true, img, "");
        }
        catch (Exception ex)
        {
            return new DecodeResult(false, ScreenPlaceholder, $"{ex.GetType().Name}: {Trunc(ex.Message)}");
        }
    }

    // ==================== 帧推送(B1: SSE frame 事件, 推送优先/轮询兜底) ====================

    private SseClient? _frameSse;

    /// <summary>最近一次推送帧到达时刻(TickCount64); 轮询退避的依据(推送活 → 轮询跳过)。</summary>
    private long _lastFramePushTicks;

    /// <summary>推送存活判定窗(毫秒): ≥3 个轮询周期内有 frame 事件即视为推送活着, 轮询退避跳过。</summary>
    private const int PushFreshMs = 4500;

    /// <summary>
    /// 确保帧推送连接就绪(幂等): 页面可见 + 自动刷新开 + 服务代理就绪才建, 代理晚就绪随轮询 tick 自愈。
    /// 独立于 MainViewModel 的 log/status 流 —— 其 SseClient 为私有无法复用, 且帧流仅需调试页可见时
    /// 开启(离开即停, 不常占连接); 帧事件契约与真实副本 webui.py:1200 一致(仅 ?frames=1 才推)。
    /// </summary>
    private void EnsureFrameSse()
    {
        if (_frameSse is not null || !IsAutoRefresh || !_isPageVisible)
        {
            return;
        }
        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            return;
        }
        var sse = new SseClient(proxy.BaseUrl, frames: true);   // B1: 订阅 URL 追加 ?frames=1(SseClient 正确拼接)
        sse.OnFrame += OnFramePushed;
        sse.OnConnected += () => Services.DebugTrace.Log("frame sse: connected (?frames=1)");
        sse.OnDisconnected += r => Services.DebugTrace.Log($"frame sse: down({r}) -> 1.5s 轮询兜底");
        _frameSse = sse;
        sse.Start();
        Services.DebugTrace.Log("frame sse: started");
    }

    /// <summary>停帧推送连接(离开页面/关自动刷新时); 推送停后轮询自然恢复兜底(1.5s autoTimer 语义)。</summary>
    private void StopFrameSse()
    {
        var sse = _frameSse;
        _frameSse = null;
        _lastFramePushTicks = 0;
        if (sse is not null)
        {
            _ = sse.StopAsync();   // 火忘收尾(与 MainViewModel.Stop 同款)
        }
    }

    /// <summary>SSE frame 事件到达(后台线程): 解码放后台(Task.Run), 结果 marshal 回 UI 线程 ——
    /// SSE 回调触 UI 属性必须过调度器(MainViewModel.StartSse 同款纪律), 解码也不占 UI 线程。</summary>
    private void OnFramePushed(FramePush f)
    {
        _ = System.Threading.Tasks.Task.Run(() =>
        {
            var dr = DecodeJpeg(f.Jpeg);
            _uiDispatcher.BeginInvoke(() => ApplyFramePush(dr));
        });
    }

    /// <summary>应用推送帧: 推送到达即计时(轮询退避依据); 真帧上屏 + 底栏回显(带「推送」标记),
    /// 非法帧灰图占位(D6)不崩。</summary>
    private void ApplyFramePush(DecodeResult dr)
    {
        _lastFramePushTicks = Environment.TickCount64;
        if (!dr.Ok)
        {
            ScreenStatusText = $"推送帧异常: {dr.Error}";
            ScreenImage = dr.Bmp;
            return;
        }
        ScreenImage = dr.Bmp;
        ScreenStatusText = $"{dr.Bmp.PixelWidth}×{dr.Bmp.PixelHeight} · 更新于 {DateTime.Now:HH:mm:ss} (推送)";
        Services.DebugTrace.Log($"frame push: {dr.Bmp.PixelWidth}×{dr.Bmp.PixelHeight}");
        RaiseFrameArrived();
    }

    private async Task PollBoxesAsync()
    {
        if (_boxesPolling)
        {
            return;
        }
        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            return;
        }
        _boxesPolling = true;
        try
        {
            var r = await proxy.GetOcrAsync();
            if (!r.Success || r.Value is null)
            {
                ScreenStatusText = $"取文字框失败: {Trunc(r.Error)}";
                return;
            }
            Boxes = (r.Value.Boxes ?? [])
                .Select(b => new OcrBoxVm(b.Text, b.Score, b.Box, b.Rel))
                .ToList();
            OcrStampTicks = Environment.TickCount64;   // webui boxesStamp = Date.now()
            RaiseBoxesUpdated();
        }
        finally
        {
            _boxesPolling = false;
        }
    }

    // ==================== 点击发送 ====================

    /// <summary>画面点击 → POST /api/click {rel} → 点后刷新画面与框(webui.html:979-999)。
    /// 由视图把点击像素换算成 rel 后调用; 返回是否发送成功(供 hit 动效与否)。</summary>
    public async Task<bool> ClickAtAsync(double relX, double relY)
    {
        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            return false;
        }
        var rx = Math.Round(relX, 4);   // webui +rx.toFixed(4)
        var ry = Math.Round(relY, 4);
        if (rx is < 0 or > 1 || ry is < 0 or > 1)
        {
            return false;   // 画面外
        }
        var r = await proxy.ClickRelAsync(rx, ry);
        if (r.Success && r.Value?.Ok == true)
        {
            // 点后画面已变: 刷新一帧; OCR 开着则连带重取框(webui.html:996-997)
            _ = PollScreenTickAsync(force: true);
            if (IsOcrEnabled)
            {
                _ = PollBoxesAsync();
            }
            return true;
        }
        ScreenStatusText = $"点击失败: {Trunc(r.Error)}";
        return false;
    }

    // ==================== 状态回显 ====================

    /// <summary>每轮 /api/status 后调用: 模式回显(webui mode-badge 同源 debug_click) + 连接按钮文案回显。</summary>
    public void OnStatusUpdated(StatusSnapshot s)
    {
        IsTestMode = s.DebugClick;
        ConnectButtonText = s.Connected ? "已连接" : "连接";   // 连接组文案随状态回显(webui.html:493-497)
    }

    /// <summary>导航进入调试页(首次进入即开轮询与帧推送)。</summary>
    public void OnNavigatedTo()
    {
        _isPageVisible = true;
        UpdateTimerState();
        EnsureFrameSse();
    }

    /// <summary>离开调试页(停轮询与帧推送)。</summary>
    public void OnNavigatedFrom()
    {
        _isPageVisible = false;
        UpdateTimerState();
        StopFrameSse();
    }

    private static string Trunc(string s) => s.Length > 160 ? s[..160] : s;
}
