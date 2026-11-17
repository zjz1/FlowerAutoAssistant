using System.Diagnostics;
using System.IO;
using System.Text;

namespace FAA.WpfGui.Services;

/// <summary>
/// FAA WebUI 服务进程托管:
///   路径解析(A2, 见 ResolveBackendPaths) → 探测(复用 ProbeService 三态语义) →
///   free 时 spawn venv python webui.py --port → stdout/stderr 管道回调 →
///   优雅停(POST /api/shutdown → 等退出 → 超时杀进程树) → 可重启。
/// 后端路径解析链(A2 去硬编码; 命中的主项目路径只读引用, 运行属程序自身行为):
///   ① env FAA_BACKEND_DIR(后端目录, 含 webui.py)/FAA_VENV_PY(python.exe 全路径)优先 ——
///      env 已设置但无效时**直接报错, 绝不静默回退发现链**(防止配错却悄悄换后端);
///   ② env 未提供时从 exe 所在目录向上最多 8 级查找 FlowerAutoAssistant/webui.py,
///      找到后校验相邻 .venv/Scripts/python.exe(venv 也可由 FAA_VENV_PY 提供);
///   ③ 全部失败给出明确中文报错(含已尝试路径清单, 见 PathError)。
/// ⚠ webui.py 每次启动按自身设计清空 data/webui_runtime_log.txt(_log_reset_history,
///   webui.py:99-113) —— 属程序正常启动行为。
/// </summary>
public sealed class FaaProcessHost : IDisposable
{
    // ==================== 后端路径解析(A2 去硬编码) ====================

    // N02(batch-06) 提纯随迁: 原 private record BackendResolution 移至 BackendPathResolver.cs(升 internal), 字段语义零变化。

    /// <summary>解析一次性缓存(进程内首访问解析一次; env 属进程级配置, 无需重复解析)。</summary>
    private static readonly Lazy<BackendResolution> _backend = new(ResolveBackendPaths);

    /// <summary>venv python 全路径(引擎依赖 torch/onnx 等只在 venv 里); 解析失败为 null(原因见 PathError)。</summary>
    public static string? VenvPython => _backend.Value.VenvPython;

    /// <summary>服务脚本全路径(webui.py 自身用 BASE=脚本目录 定位资源); 解析失败为 null(原因见 PathError)。</summary>
    public static string? WebUiScript => _backend.Value.WebUiScript;

    /// <summary>路径解析失败原因(中文, 含已尝试路径清单); null = 解析成功。</summary>
    public static string? PathError => _backend.Value.Error;

    /// <summary>路径解析诊断(各路径来源; 解析成功时也有值, 供自测输出)。</summary>
    public static string PathDiagnostics => _backend.Value.Diagnostics;

    /// <summary>
    /// 后端路径解析(A2)适配器(N02, batch-06): 纯函数逐行等价迁至 BackendPathResolver.Resolve,
    /// 此处只注入进程级真值 —— env(FAA_BACKEND_DIR/FAA_VENV_PY)、exe 目录(AppContext.BaseDirectory)、
    /// 真文件系统探针。Lazy 单次缓存语义与调用方(StartAsync/HostSelfTest)零变化。
    /// </summary>
    private static BackendResolution ResolveBackendPaths()
        => BackendPathResolver.Resolve(
            Environment.GetEnvironmentVariable("FAA_BACKEND_DIR"),
            Environment.GetEnvironmentVariable("FAA_VENV_PY"),
            AppContext.BaseDirectory,
            static p => File.Exists(p),
            static p => Directory.Exists(p));

    /// <summary>当前托管端口; 未运行为 null。</summary>
    public int? Port { get; private set; }

    /// <summary>子进程句柄; 退出后仍保留(供 ExitCode 检查), Dispose 才置 null。</summary>
    public Process? Process { get; private set; }

    /// <summary>stdout 行回调(webui.py 的启动横幅/日志 print 走这里)。
    /// ⚠ 线程语义: 在线程池线程触发(非 UI 线程) —— GUI 订阅方必须自行 Dispatcher.BeginInvoke 调度。</summary>
    public event Action<string>? OutputReceived;

    /// <summary>stderr 行回调。⚠ 线程语义同 OutputReceived: 线程池线程, GUI 订阅方须自行调度到 UI 线程。</summary>
    public event Action<string>? ErrorReceived;

    /// <summary>进程退出回调(优雅停/被杀/崩溃都触发)。⚠ 线程语义同上: 线程池线程; 依赖 EnableRaisingEvents=true(StartAsync 已设)。</summary>
    public event Action<int?>? Exited;

    /// <summary>BaseUrl(未运行时 null)。</summary>
    public string? BaseUrl => Port is null ? null : $"http://127.0.0.1:{Port}/";

    /// <summary>端口三态探测(契约与 ProbeService/webui_app.py _probe 完全一致)。</summary>
    public Task<string> ProbeAsync(int port, CancellationToken ct = default)
    {
        return ProbeService.ProbeAsync(port);
    }

    /// <summary>
    /// 启动服务: 解析后端路径(env 优先/向上发现, 失败即报错) → 探测须为 free → spawn →
    /// 轮询 /api/status 直到 faa(引擎首建加载模型需 10-30s, 默认等待上限 120s) → 返回结果。
    /// 失败不抛异常, 一律转 ProxyResult。
    /// </summary>
    public async Task<ProxyResult<string>> StartAsync(
        int port, int waitSeconds = 120, CancellationToken ct = default)
    {
        if (Process is not null && !Process.HasExited)
        {
            return new ProxyResult<string>(false, 0, null, $"已有托管进程在运行(port={Port}), 先 Stop 再 Start", "");
        }

        // 第 1 步: 解析后端路径(A2): env 优先/向上发现, 全失败给中文报错(含已尝试路径) —— 解析失败绝不 spawn
        // (先落局部变量再判空: 属性访问不被可空流分析跟踪, 局部变量守卫后即知非空, 免掉 FileName 处的可空警告)
        var pathError = PathError;
        var venvPython = VenvPython;
        var webUiScript = WebUiScript;
        if (pathError is not null || venvPython is null || webUiScript is null)
        {
            return new ProxyResult<string>(false, 0, null,
                $"后端路径解析失败, 无法启动服务:\n{pathError ?? "(未知原因)"}", "");
        }

        // 第 2 步: 探测必须 free —— 被占(faa/other)绝不 spawn, 避免端口冲突
        var probe0 = await ProbeService.ProbeAsync(port);
        if (probe0 != "free")
        {
            return new ProxyResult<string>(false, 0, null, $"端口 {port} 非空闲(探测结果 {probe0}), 拒绝启动", "");
        }

        // 解析时已校验存在, 这里兜底(解析与 spawn 之间文件被删等极端情况)
        if (!File.Exists(venvPython))
        {
            return new ProxyResult<string>(false, 0, null, $"venv python 不存在: {venvPython}", "");
        }
        if (!File.Exists(webUiScript))
        {
            return new ProxyResult<string>(false, 0, null, $"服务脚本不存在: {webUiScript}", "");
        }

        // 第 3 步: spawn(工作目录=脚本目录; 输出管道回调)
        // 编码契约: python 管道输出编码随宿主环境漂移(实测: PYTHONUTF8=1 时 utf-8, 否则 gbk),
        // 这里显式钉死 PYTHONIOENCODING=utf-8 + .NET 按 UTF-8 解码 —— 两种宿主环境下中文都不乱码。
        var psi = new ProcessStartInfo
        {
            FileName = venvPython,
            // Stage 4: --parent-pid 让服务在壳被强杀时随父进程退出(不留孤儿监听端口)
            Arguments = $"\"{webUiScript}\" --port {port} --parent-pid {Environment.ProcessId}",
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
            CreateNoWindow = true,
            WorkingDirectory = Path.GetDirectoryName(webUiScript) ?? ".",
        };
        psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        var p = new Process { StartInfo = psi };
        p.OutputDataReceived += (_, e) => { if (e.Data is not null) { Remember(e.Data); OutputReceived?.Invoke(e.Data); } };
        p.ErrorDataReceived += (_, e) => { if (e.Data is not null) { Remember(e.Data); ErrorReceived?.Invoke(e.Data); } };
        p.Exited += (_, _) => Exited?.Invoke(Port is null ? null : p.HasExited ? p.ExitCode : null);
        // Exited 事件模型必需: 不置 true 则 Exited 永不触发(.NET Process 默认不启用退出通知)
        p.EnableRaisingEvents = true;
        try
        {
            if (!p.Start())
            {
                return new ProxyResult<string>(false, 0, null, "Process.Start 返回 false", "");
            }
        }
        catch (Exception ex)
        {
            return new ProxyResult<string>(false, 0, null, $"spawn 失败({ex.GetType().Name}: {ex.Message})", "");
        }
        p.BeginOutputReadLine();
        p.BeginErrorReadLine();
        Port = port;
        Process = p;

        // 第 4 步: 轮询等 /api/status 可达(语义=ProbeService 探得 faa)
        var sw = System.Diagnostics.Stopwatch.StartNew();
        while (sw.Elapsed.TotalSeconds < waitSeconds)
        {
            ct.ThrowIfCancellationRequested();
            if (p.HasExited)
            {
                await FlushOutputAsync();
                return new ProxyResult<string>(false, 0, null,
                    $"进程提前退出(code={p.ExitCode}), 等待 {sw.Elapsed.TotalSeconds:F1}s", CollectTail());
            }
            var state = await ProbeService.ProbeAsync(port);
            if (state == "faa")
            {
                return ProxyResult<string>.Ok(200,
                    $"服务就绪: http://127.0.0.1:{port}/ (等待 {sw.Elapsed.TotalSeconds:F1}s)", "");
            }
            await Task.Delay(1000, ct);
        }
        await FlushOutputAsync();
        return new ProxyResult<string>(false, 0, null,
            $"等待 /api/status 超时({waitSeconds}s), 进程{(p.HasExited ? "已退出" : "仍在运行")}", CollectTail());
    }

    /// <summary>
    /// 优雅停: POST /api/shutdown(服务端 0.3s 后退出, webui.py 1180 行) → 等进程退出(默认上限 15s) →
    /// 超时则 Kill 整棵进程树兜底。返回值描述走了哪条路径。
    /// </summary>
    public async Task<ProxyResult<string>> StopAsync(int gracefulWaitSeconds = 15, CancellationToken ct = default)
    {
        var p = Process;
        if (p is null || p.HasExited)
        {
            return ProxyResult<string>.Ok(0, "无运行中的托管进程", "");
        }
        var port = Port ?? 0;

        // 第 1 步: 优雅停请求(失败也继续等/杀 —— 停进程是硬保证)
        var proxy = new FaaProxy($"http://127.0.0.1:{port}/");
        var shutdown = await proxy.ShutdownAsync(ct);

        // 第 2 步: 等退出
        var exited = false;
        try
        {
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
            cts.CancelAfter(TimeSpan.FromSeconds(gracefulWaitSeconds));
            await p.WaitForExitAsync(cts.Token);
            exited = true;
        }
        catch (OperationCanceledException)
        {
            exited = false;
        }

        // 第 3 步: 超时兜底杀进程树(python 引擎可能有子线程/子进程)
        var killed = false;
        if (!exited && !p.HasExited)
        {
            try
            {
                p.Kill(entireProcessTree: true);
                killed = true;
                await p.WaitForExitAsync(ct);
            }
            catch (Exception ex)
            {
                return new ProxyResult<string>(false, 0, null,
                    $"Kill 失败({ex.GetType().Name}: {ex.Message}); shutdown 请求 {(shutdown.Success ? "已送达" : "未送达")}", "");
            }
        }
        var how = exited
            ? $"优雅退出(POST /api/shutdown {(shutdown.Success ? "成功" : "未确认")})"
            : killed ? "等待超时后强杀进程树" : "等待超时但进程恰好已自行退出(竞态), 未强杀";
        return ProxyResult<string>.Ok(0, $"进程已停({how}; code={p.ExitCode})", "");
    }

    /// <summary>重启 = 优雅停 → 用同端口再 Start(StartAsync 内部重新探测 free)。</summary>
    public async Task<ProxyResult<string>> RestartAsync(
        int? port = null, int waitSeconds = 120, int gracefulWaitSeconds = 15, CancellationToken ct = default)
    {
        var stop = await StopAsync(gracefulWaitSeconds, ct);
        if (!stop.Success)
        {
            return new ProxyResult<string>(false, 0, null, $"重启时停止失败: {stop.Error}", stop.RawBody);
        }
        var target = port ?? Port ?? throw new InvalidOperationException("无可用端口");
        Port = null; // 让 Start 重新走完整探测
        Process = null;
        return await StartAsync(target, waitSeconds, ct);
    }

    /// <summary>收集最近输出尾部(诊断用)。TakeLast 对不足 8 行/空列表安全(旧 _outTail[^8..] 在行数少于 8 时
    /// 以负下标调 List.GetRange 抛 ArgumentOutOfRangeException, 修复前只要进程早退/等待超时即 100% 崩溃)。</summary>
    private string CollectTail()
    {
        lock (_outLock)
        {
            return string.Join(" | ", _outTail.TakeLast(8));
        }
    }

    private readonly object _outLock = new();
    private readonly List<string> _outTail = new();

    private void Remember(string line)
    {
        lock (_outLock)
        {
            _outTail.Add(line);
            if (_outTail.Count > 40)
            {
                _outTail.RemoveAt(0);
            }
        }
    }

    /// <summary>给管道一点时间把残余输出冲完(诊断信息补全, 不阻塞主流程)。</summary>
    private async Task FlushOutputAsync()
    {
        await Task.Delay(300);
    }

    public void Dispose()
    {
        var p = Process;
        Process = null;
        Port = null;
        if (p is not null && !p.HasExited)
        {
            try
            {
                p.Kill(entireProcessTree: true);
            }
            catch
            {
                // Dispose 时尽力而为
            }
        }
        p?.Dispose();
        GC.SuppressFinalize(this);
    }
}
