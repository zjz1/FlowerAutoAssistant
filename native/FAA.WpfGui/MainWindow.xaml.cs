using System.ComponentModel;
using System.Windows;
using FAA.WpfGui.Services;
using FAA.WpfGui.ViewModels;

namespace FAA.WpfGui;

/// <summary>
/// 主窗口 = 左侧导航 + ContentControl 六页壳(主页/运行日志/设置/调试/流程/关于), MVVM: 交互全在 ViewModel。
/// 职责:
///   ① 启动序列(契约5): Loaded 后台跑 MainViewModel.RunStartupSequenceAsync —— 三态探测
///      (faa=连上不重起 / other=报错退出 / free=自起服务), 期间窗口先显示"探测中/启动中"徽章;
///      --api-base 给定时跳过探测/托管直连指定服务(批 21, 调试/连 Mock 用)。
///   ② 关窗确认(契约2): confirm_page_close(缺省 true)开确认; 流程运行中即使关了提醒仍强制确认;
///      统一走 DialogService.Confirm(批 C3; 底层 WPF MessageBox/user32, 文案对齐 webui_app.py:316-326)。
///      托盘「退出」也走本路径(RequestExit → Show → Close), 全应用只有这一条确认逻辑。
///   ③ 托盘(NP2 收尾): 最小化 → 隐藏到托盘; 托盘左键恢复; 右键菜单(显示主窗/开始/停止快捷态/退出)。
///   ④ 退出清理: 若服务为本窗口托管(free 自起), 关窗时优雅停(POST /api/shutdown → 超时杀树)
///      —— 批 21 起改异步收尾: 不再在 UI 线程同步 Wait(8s), 后台任务跑优雅停 + 8s 超时看护,
///      结果异常照常观测(原 ContinueWith 竞态修复语义保留), 进程级兜底杀树仍由 App.OnExit→Dispose 负责。
/// </summary>
public partial class MainWindow : Window
{
    private readonly MainViewModel _vm;
    private TrayIconService? _tray;
    private bool _closeConfirmed;   // 用户已在确认框点过"确定"(Close 重入时直接放行)
    private bool _asking;           // 确认框已弹出(防叠弹)

    public MainWindow(string initialPage = "home", int? port = null, string? apiBase = null)
    {
        InitializeComponent();
        _vm = new MainViewModel();
        if (port is not null)
        {
            _vm.Session.Port = port.Value;
        }
        if (!string.IsNullOrWhiteSpace(apiBase))
        {
            _vm.Session.ApiBaseOverride = apiBase;   // --api-base: 跳过三态探测/托管, 直连指定服务(调试/连 Mock)
        }
        DataContext = _vm;
        _vm.NavigateTo(initialPage);   // --page home|log|settings|debug|flow|about 预选页(缺省 home)
        StateChanged += OnStateChanged;
        _tray = new TrayIconService(_vm, RequestExit);
        _vm.TrayQuickStateChanged += (isRunning, canStart) => _tray?.UpdateQuickState(canStart, isRunning);
    }

    /// <summary>托盘「退出」入口: 与点 X 同一条契约2 路径 —— 先把窗口带回来再 Close()。</summary>
    public void RequestExit()
    {
        RestoreFromTray();
        Close();
    }

    /// <summary>从托盘/单实例激活恢复主窗: 显示 + 正常态 + 前台。</summary>
    public void RestoreFromTray()
    {
        Services.DebugTrace.Log("tray: restore requested");
        if (!IsVisible)
        {
            Show();
        }
        WindowState = WindowState.Normal;
        Activate();
    }

    /// <summary>最小化 → 隐藏到托盘(MAA 式; 隐藏不是关闭, 不触发契约2 确认)。
    /// 2026-11-19: 仅当托盘图标确认创建(IsAvailable)才隐藏; 否则保持最小化在任务栏,
    /// 避免图标未注册时窗口彻底失踪、无任何入口。</summary>
    private void OnStateChanged(object? sender, EventArgs e)
    {
        if (WindowState == WindowState.Minimized)
        {
            if (_tray?.IsAvailable == true)
            {
                Hide();
                Services.DebugTrace.Log("tray: minimized -> hidden to tray");
            }
            else
            {
                Services.DebugTrace.Log("tray: minimized but icon unavailable -> keep in taskbar");
            }
        }
    }

    /// <summary>启动序列放 Loaded 后台跑: 窗口先显示(徽章=探测中), 探测/自起服务不冻结 UI。</summary>
    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        await _vm.RunStartupSequenceAsync();
    }

    // ==================== 契约2: 关窗确认 ====================

    private void OnClosing(object? sender, CancelEventArgs e)
    {
        // 报错退出路径(端口 other/自起失败)与已确认重入: 直接放行
        if (_closeConfirmed || _vm.Session.ForceClose)
        {
            return;
        }

        // 判定与 webui_app.py:316 一致: 确认框出现条件 = 流程运行中 OR confirm_page_close 开启
        var running = _vm.Session.IsRunning;
        var confirmEnabled = _vm.Session.ConfirmPageClose;   // 首个状态到达前按 true(安全侧)
        if (!running && !confirmEnabled)
        {
            return;   // 无需确认, 放行(托管服务在 OnClosed 停)
        }

        // 已有确认框在弹(消息泵期间第二次 WM_CLOSE 重入): 拦下本次, 不叠弹
        if (_asking)
        {
            e.Cancel = true;
            return;
        }

        // 先弹框、后决定是否取消本次关闭 —— 绝不在 e.Cancel=true 之后调用 Close()
        // (窗口关闭期间 Close()/Show() 会抛 InvalidOperationException, 见 faa_gui_error.log 04:10:07 事故;
        //  用户点确定 → 不设 e.Cancel, 本次关闭自然放行, 无需重入 Close)
        _asking = true;
        var text = running
            ? "流程正在运行中, 关闭窗口将失去实时监控。"
            : "确定要关闭 FAA 窗口吗?";
        if (_vm.Session.OwnsService)
        {
            text += "\n\n关闭窗口会同时停止本窗口托管的 Web 服务。";
        }
        var rc = DialogService.Confirm(text, "FAA 原生窗口", this, warning: running);
        _asking = false;
        if (rc)
        {
            _closeConfirmed = true;   // 本次关闭自然放行; OnClosed 停托管服务
        }
        else
        {
            e.Cancel = true;          // 取消: 窗口原样保留
        }
    }

    /// <summary>
    /// 关窗后清理: 停轮询 + 移除托盘图标; 本窗口托管的服务优雅停改为**异步收尾**(批 21)。
    /// 原 UI 线程 stop.Wait(8s) 同步等待会冻结消息泵(退出口径不优雅), 改为后台任务跑完整优雅停
    /// (StopAsync: POST /api/shutdown → 等退出 ≤15s → 超时杀树, 带上限语义不变) + 8s 超时看护。
    /// </summary>
    protected override void OnClosed(EventArgs e)
    {
        _vm.Stop();
        _tray?.Dispose();
        _tray = null;
        if (_vm.Session.OwnsService)
        {
            // 后台收尾: StopAsync 在首个 await 前同步发出 shutdown 请求, 之后全部在后台跑 ——
            // UI 线程零等待。看护与观测见 WatchShutdownAsync; 优雅停失败时由 App.OnExit → Host.Dispose() 兜底杀树。
            var stop = _vm.Session.Host.StopAsync();
            _ = WatchShutdownAsync(stop);
        }
        base.OnClosed(e);
    }

    /// <summary>
    /// 停服后台看护: 8s 内未确认完成则记诊断(后台任务继续等/杀树兜底, 不阻塞也不放弃);
    /// 无论哪条路径, StopAsync 的最终结果/异常都必须被观测 —— App.OnExit→Dispose() 会与后台停服任务
    /// 并发操作同一 Process, 不观测会产生未观察异常(原 Wait(8s)+ContinueWith 竞态修复的语义保留)。
    /// </summary>
    private static async Task WatchShutdownAsync(Task stop)
    {
        try
        {
            var finished = await Task.WhenAny(stop, Task.Delay(TimeSpan.FromSeconds(8)));
            if (finished != stop)
            {
                DebugTrace.Log("shutdown-watchdog: 优雅停 8s 内未确认完成, 后台任务继续等待/超时杀树兜底");
            }
            await stop;   // 已完成则直取结果; 未完成则继续看到底 —— 异常在此被观测, 不外抛
        }
        catch
        {
            // 停服失败/与 Dispose 并发的对象释放异常: 观测即修复, 兜底杀树由 App.OnExit 负责
        }
    }
}
