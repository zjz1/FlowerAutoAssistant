using System.IO;
using System.Threading;
using System.Windows;
using FAA.WpfGui.Services;

namespace FAA.WpfGui;

/// <summary>
/// 应用入口。五种启动模式:
///   默认: --page home|log|settings|debug|flow|about 预选页(缺省 home), --port N 指定服务端口(缺省 8765, 供联调用);
///         --api-base &lt;url&gt; 覆盖默认 base url(批 21: 直连指定服务, 跳过探测/托管, 调试/连 Mock 用);
///         手动创建 MainWindow 显示(三态探测/服务托管在 MainWindow.Loaded 后台进行, 不阻塞窗口显示)。
///   --probe-test &lt;outfile&gt; [--probe-ports ...] [--probe-expect ...]
///       NP1a 端口三态探测自测, 写文件后 exit 0。
///   --api-selftest &lt;baseurl&gt; &lt;outfile&gt; &lt;all|get-only&gt;
///       NP1b FaaProxy 26 端点形状自测, 写文件, exit 0/1。
///       get-only 对真实实例永不发 POST(绝不调 /api/run /api/shutdown /api/click)。
///   --host-selftest &lt;port&gt; &lt;outfile&gt;
///       NP1b FaaProcessHost 全链自测(spawn venv python webui.py → 优雅停), exit 0/1。
///   --sse-selftest &lt;baseurl&gt; &lt;outfile&gt; &lt;seconds&gt;
///       SSE 流读取自测(只对 Mock 用), 连 /api/stream 读 N 秒断言事件与重连, exit 0/1。
/// 自测模式均不显示窗口(WinExe 无控制台, 结果只落文件)。
/// </summary>
public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        // 全局兜底: WPF 无控制台, 未处理异常只落文件, 不静默吞(async void / async void Tick 事件里抛的也算)
        DispatcherUnhandledException += (_, ex) =>
        {
            LogFatal("DispatcherUnhandledException", ex.Exception);
            ex.Handled = true;   // 保命: 记录后不让进程直接崩, 用户能看到窗口状态
        };
        AppDomain.CurrentDomain.UnhandledException += (_, ex) =>
            LogFatal("AppDomain.UnhandledException", ex.ExceptionObject as Exception);

        // N02(batch-06): 参数解析提纯为 Services.SelftestArgsParser(逐行等价迁移, exe 目录参数注入);
        // 模式记录组(ProbeMode/ApiMode/HostMode/SseMode/SelftestArgsError)随迁 internal 化。
        switch (Services.SelftestArgsParser.Parse(e.Args, AppContext.BaseDirectory))
        {
            case ProbeMode plan when plan != null:
                // NP1a 端口探测自测(结果恒 exit 0)
                RunAsyncThenExitAsync(async () =>
                {
                    await Services.ProbeService.RunSelfTest(plan.OutFile, plan.Ports, plan.Expect);
                    return 0;
                }, plan.OutFile);
                return;
            case ApiMode api when api != null:
                RunAsyncThenExitAsync(() => Services.ApiSelfTest.RunAsync(api.BaseUrl, api.OutFile, api.Mode, default),
                    api.OutFile);
                return;
            case HostMode host when host != null:
                RunAsyncThenExitAsync(() => Services.HostSelfTest.RunAsync(host.Port, host.OutFile, default),
                    host.OutFile);
                return;
            case SseMode sse when sse != null:
                RunAsyncThenExitAsync(() => Services.SseSelfTest.RunAsync(sse.BaseUrl, sse.OutFile, sse.Seconds, default),
                    sse.OutFile);
                return;
            case SelftestArgsError err:
                // 批 21: 自测开关存在但参数解析不齐 —— 响亮失败(落诊断文件)后 exit 1, 绝不静默落 GUI
                Services.DebugTrace.Log($"selftest args error: {err.Flag} {err.Reason}");
                ReportSelftestArgsError(err, e.Args);
                Shutdown(1);
                return;
            default:
                // 正常 GUI 启动: 先单实例互斥(NP2 收尾) —— 已有 FAAgui 进程则激活既有窗口后退出
                if (!AcquireSingleInstanceMutex())
                {
                    ActivateExistingInstance();
                    Shutdown(0);
                    return;
                }
                // 解析 --page / --port / --api-base → 手动建窗(--api-base 批 21: 直连指定服务, 调试/连 Mock)
                var page = ParsePage(e.Args);
                var port = ParsePort(e.Args);
                var apiBase = ParseApiBase(e.Args);
                var win = new MainWindow(page, port, apiBase);
                MainWindow = win;
                win.Show();
                StartActivateListener();   // 2026-11-19: 托盘隐藏后二次启动可恢复
                return;
        }
    }

    // ==================== 单实例互斥(NP2 收尾) ====================

    private Mutex? _singleInstanceMutex;
    private const string MutexName = "Local\\FAA.WpfGui.SingleInstance";

    // 2026-11-19: 托盘隐藏(Hide)后, 二次启动不能只靠 Win32 ShowWindow 恢复 ——
    // WPF 的 Visibility 仍是 Hidden。用命名事件让既有实例自己 RestoreFromTray()。
    private const string ActivateEventName = "Local\\FAA.WpfGui.Activate";
    private EventWaitHandle? _activateEvent;
    private volatile bool _exiting;

    /// <summary>尝试持有单实例互斥; false=已有实例在跑(本进程不应再开窗)。仅 GUI 模式调用(自测模式不参与互斥)。</summary>
    private bool AcquireSingleInstanceMutex()
    {
        _singleInstanceMutex = new Mutex(initiallyOwned: true, MutexName, out var createdNew);
        if (createdNew)
        {
            Services.DebugTrace.Log("single-instance: mutex acquired (first instance)");
            return true;
        }
        Services.DebugTrace.Log("single-instance: mutex held by another instance -> activate existing");
        return false;
    }

    /// <summary>首个实例监听「激活」命名事件; 第二个实例 Set 后由本线程恢复主窗。</summary>
    private void StartActivateListener()
    {
        try
        {
            _activateEvent = new EventWaitHandle(false, EventResetMode.AutoReset, ActivateEventName);
        }
        catch (Exception ex)
        {
            Services.DebugTrace.Log($"single-instance: create activate event failed {ex.GetType().Name}: {ex.Message}");
            return;
        }

        Task.Run(() =>
        {
            try
            {
                while (!_exiting && _activateEvent.WaitOne())
                {
                    Dispatcher.Invoke(() => (MainWindow as MainWindow)?.RestoreFromTray());
                }
            }
            catch (ObjectDisposedException)
            {
                // 退出时事件已释放
            }
            catch (Exception ex)
            {
                Services.DebugTrace.Log($"single-instance: activate listener failed {ex.GetType().Name}: {ex.Message}");
            }
        });
    }

    /// <summary>激活既有实例的主窗(标题精确匹配「FAA 原生窗口」): 还原 + 前台; 找不到窗口时兜底枚举进程。</summary>
    private static void ActivateExistingInstance()
    {
        // 2026-11-19: 优先命名事件 —— 既有实例自己 Show/Normal/Activate;
        // WPF Hide() 的窗口仅靠 Win32 ShowWindow 不会恢复(Visibility 仍 Hidden)。
        try
        {
            using var ev = EventWaitHandle.OpenExisting(ActivateEventName);
            ev.Set();
            Services.DebugTrace.Log("single-instance: signaled activate event");
            return;
        }
        catch (WaitHandleCannotBeOpenedException)
        {
            // 旧版本实例/事件尚未创建 -> 回退 Win32
        }
        catch (Exception ex)
        {
            Services.DebugTrace.Log($"single-instance: signal activate event failed {ex.GetType().Name}: {ex.Message}");
        }

        try
        {
            var hwnd = NativeMethods.FindWindowW(null, "FAA 原生窗口");
            if (hwnd == IntPtr.Zero)
            {
                // 主窗可能在托盘里被隐藏(标题仍在)或标题不匹配: 兜底按进程名取 MainWindowHandle
                foreach (var proc in System.Diagnostics.Process.GetProcessesByName("FAA.WpfGui"))
                {
                    if (proc.MainWindowHandle != IntPtr.Zero)
                    {
                        hwnd = proc.MainWindowHandle;
                        break;
                    }
                }
            }
            if (hwnd != IntPtr.Zero)
            {
                NativeMethods.ShowWindow(hwnd, NativeMethods.SW_RESTORE);      // 托盘隐藏态 → 还原
                NativeMethods.SetForegroundWindow(hwnd);
                Services.DebugTrace.Log($"single-instance: activated existing window hwnd=0x{hwnd.ToInt64():X}");
            }
            else
            {
                Services.DebugTrace.Log("single-instance: existing instance window not found (may be starting)");
            }
        }
        catch (Exception ex)
        {
            // 激活失败不致命: 用户手动从任务栏/托盘找回即可
            Services.DebugTrace.Log($"single-instance: activate failed {ex.GetType().Name}: {ex.Message}");
        }
    }

    protected override void OnExit(ExitEventArgs e)
    {
        // 2026-11-19: 先停激活监听线程(Set 唤醒 -> _exiting 让循环退出), 再释放事件
        _exiting = true;
        try
        {
            _activateEvent?.Set();
        }
        catch
        {
            // 事件可能已释放
        }
        try
        {
            _activateEvent?.Dispose();
        }
        catch
        {
            // 释放失败不影响进程退出
        }
        _activateEvent = null;

        // 兜底: 停轮询 + 杀掉可能残留的托管服务进程树(优雅停在 MainWindow.OnClosed 已做过)
        (MainWindow?.DataContext as ViewModels.MainViewModel)?.Dispose();
        try
        {
            _singleInstanceMutex?.ReleaseMutex();
        }
        catch
        {
            // 非 owning 线程释放会抛 —— 互斥体随进程退出由系统回收
        }
        _singleInstanceMutex?.Dispose();
        base.OnExit(e);
    }

    /// <summary>未处理异常落文件(诊断用; WinExe 无控制台)。</summary>
    private static void LogFatal(string source, Exception? ex)
    {
        try
        {
            var line = $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {source}: {ex?.GetType().Name}: {ex?.Message}\n{ex?.StackTrace}\n\n";
            File.AppendAllText(Path.Combine(AppContext.BaseDirectory, "faa_gui_error.log"), line);
        }
        catch
        {
            // 日志写不进就算了, 不能再抛
        }
    }

    /// <summary>自测执行体: 任何异常也落一个可诊断的文件(无控制台可打印), 最后按返回码 Shutdown。</summary>
    private static async void RunAsyncThenExitAsync(Func<Task<int>> work, string outFile)
    {
        var code = 1;
        try
        {
            code = await work();
        }
        catch (Exception ex)
        {
            try
            {
                // 先确保输出目录存在(HostSelfTest.WriteAsync 有建目录, 这里补齐同语义 —— 防止异常
                // 诊断文件因目录缺失而丢失, 复现为「输出文件未落盘」)
                var dir = Path.GetDirectoryName(Path.GetFullPath(outFile));
                if (!string.IsNullOrEmpty(dir))
                {
                    Directory.CreateDirectory(dir);
                }
                await File.WriteAllTextAsync(outFile,
                    $"SELFTEST FAIL\t未捕获异常 {ex.GetType().Name}: {ex.Message}\n");
            }
            catch
            {
                // 连输出文件都写不进去时已无处可报, 只能带码退出
            }
            code = 1;
        }
        Application.Current.Shutdown(code); // Shutdown 是实例方法, 静态方法里须经 Current
    }

    /// <summary>
    /// 自测参数解析失败的处理(批 21: 响亮失败, 替代旧的静默落入 GUI):
    /// 诊断写两处 —— ① 猜测的 outfile 路径(统一脚本在等的位置能看到 SELFTEST FAIL);
    /// ② exe 目录 selftest_args_error.txt(无 outfile 线索时的兜底, WinExe 无控制台)。
    /// </summary>
    private static void ReportSelftestArgsError(SelftestArgsError err, string[] args)
    {
        var line = $"SELFTEST FAIL\t{err.Flag}\t参数解析失败: {err.Reason}\targs={string.Join(' ', args)}\n";
        var targets = new List<string>();
        if (err.CandidateOutFile.Length > 0)
        {
            targets.Add(err.CandidateOutFile);   // 统一脚本等文件的位置
        }
        targets.Add(System.IO.Path.Combine(AppContext.BaseDirectory, "selftest_args_error.txt"));
        foreach (var t in targets.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            try
            {
                var dir = System.IO.Path.GetDirectoryName(System.IO.Path.GetFullPath(t));
                if (!string.IsNullOrEmpty(dir))
                {
                    Directory.CreateDirectory(dir);
                }
                File.WriteAllText(t, line);
            }
            catch
            {
                // 连诊断都写不进时已无处可报, 只能带码退出
            }
        }
    }

    /// <summary>
    /// 解析 --page home|log|settings|debug|flow|about(预选页; 非法/缺省回落 home)。
    /// 支持 "--page log" 与 "--page=log" 两种写法。
    /// </summary>
    private static string ParsePage(string[] args)
    {
        for (var i = 0; i < args.Length; i++)
        {
            if (args[i].StartsWith("--page", StringComparison.OrdinalIgnoreCase))
            {
                var value = args[i].Contains('=') ? args[i][(args[i].IndexOf('=') + 1)..] : null;
                if (value is null && i + 1 < args.Length && !args[i + 1].StartsWith("--"))
                {
                    value = args[i + 1];
                }
                if (value is not null)
                {
                    var v = value.Trim().ToLowerInvariant();
                    if (v is "home" or "log" or "settings" or "debug" or "flow" or "about")
                    {
                        return v;
                    }
                }
            }
        }
        return "home";
    }

    /// <summary>解析 --port N(服务端口, 缺省 8765 与 webui_app.py DEFAULT_PORT 一致; 非法忽略)。支持 --port=N。</summary>
    private static int? ParsePort(string[] args)
    {
        for (var i = 0; i < args.Length; i++)
        {
            var a = args[i];
            var isPortFlag = a.Equals("--port", StringComparison.OrdinalIgnoreCase)
                             || a.StartsWith("--port=", StringComparison.OrdinalIgnoreCase);
            if (isPortFlag)
            {
                var value = a.Contains('=') ? a[(a.IndexOf('=') + 1)..] : null;
                if (value is null && i + 1 < args.Length && !args[i + 1].StartsWith("--"))
                {
                    value = args[i + 1];
                }
                if (value is not null && int.TryParse(value.Trim(), out var p) && p is > 0 and < 65536)
                {
                    return p;
                }
            }
        }
        return null;
    }

    /// <summary>
    /// 解析 --api-base &lt;url&gt;(批 21): 覆盖默认 base url —— 直连指定服务, 跳过三态探测/服务托管
    /// (调试/连 Mock 用; 与 --page/--port 共存, 此模式下 --port 不参与连接)。支持 --api-base=&lt;url&gt;。
    /// 仅认 http(s):// 开头的 URL; 非法/缺省返回 null 走原三态流程。
    /// </summary>
    private static string? ParseApiBase(string[] args)
    {
        for (var i = 0; i < args.Length; i++)
        {
            var a = args[i];
            var isFlag = a.Equals("--api-base", StringComparison.OrdinalIgnoreCase)
                         || a.StartsWith("--api-base=", StringComparison.OrdinalIgnoreCase);
            if (isFlag)
            {
                var value = a.Contains('=') ? a[(a.IndexOf('=') + 1)..] : null;
                if (value is null && i + 1 < args.Length && !args[i + 1].StartsWith("--"))
                {
                    value = args[i + 1];
                }
                var v = value?.Trim();
                if (!string.IsNullOrEmpty(v)
                    && (v.StartsWith("http://", StringComparison.OrdinalIgnoreCase)
                        || v.StartsWith("https://", StringComparison.OrdinalIgnoreCase)))
                {
                    return v;
                }
            }
        }
        return null;
    }
}

/// <summary>单实例激活用的最小 Win32 互操作(NP2 收尾)。</summary>
internal static class NativeMethods
{
    public const int SW_RESTORE = 9;

    [System.Runtime.InteropServices.DllImport("user32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
    public static extern IntPtr FindWindowW(string? lpClassName, string lpWindowName);

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
}
