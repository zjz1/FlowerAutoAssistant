using System.Diagnostics;
using System.IO;
using System.Text;

namespace FAA.WpfGui.Services;

/// <summary>
/// 环境检查(1.0 #14): 用与 FaaProcessHost 相同的后端路径解析, 以**一次性子进程**运行
/// `faa_webui.exe --check-env`(源码模式: venv python webui.py --check-env), 捕获 stdout。
/// 不启动服务、不占端口、不连游戏; 路径解析失败或进程异常也返回可读文本(由 UI 原样展示)。
/// 入口: 设置页「环境检查」按钮 + 首启服务启动失败时的自动诊断(错误框附带结果)。
/// </summary>
public static class EnvCheckService
{
    /// <summary>环境检查（`--check-env`）。</summary>
    public static Task<string> RunAsync(int timeoutSeconds = 60, CancellationToken ct = default)
        => RunBackendCommandAsync("--check-env", timeoutSeconds, ct);

    /// <summary>导出脱敏诊断包到指定路径（`--export-diag &lt;zip&gt;`）。</summary>
    public static Task<string> ExportDiagAsync(string outPath, int timeoutSeconds = 120,
        CancellationToken ct = default)
        => RunBackendCommandAsync($"--export-diag \"{outPath}\"", timeoutSeconds, ct);

    /// <summary>以一次性子进程运行后端 CLI（不启服务、不占端口），返回合并输出。</summary>
    public static async Task<string> RunBackendCommandAsync(string arguments, int timeoutSeconds,
        CancellationToken ct = default)
    {
        var pathError = FaaProcessHost.PathError;
        var backendExe = FaaProcessHost.BackendExe;
        var venvPython = FaaProcessHost.VenvPython;
        var webUiScript = FaaProcessHost.WebUiScript;
        if (pathError is not null || (backendExe is null && (venvPython is null || webUiScript is null)))
        {
            return $"后端路径解析失败, 无法执行命令:\n{pathError ?? "(未知原因)"}";
        }

        var psi = new ProcessStartInfo
        {
            FileName = backendExe ?? venvPython!,
            Arguments = backendExe is not null ? arguments : $"\"{webUiScript}\" {arguments}",
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
            CreateNoWindow = true,
            WorkingDirectory = backendExe is not null
                ? Path.GetDirectoryName(backendExe) ?? "."
                : Path.GetDirectoryName(webUiScript!) ?? ".",
        };
        psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";

        using var p = new Process { StartInfo = psi };
        var sb = new StringBuilder();
        var gate = new object();
        p.OutputDataReceived += (_, e) => { if (e.Data is not null) { lock (gate) sb.AppendLine(e.Data); } };
        p.ErrorDataReceived += (_, e) => { if (e.Data is not null) { lock (gate) sb.AppendLine("[stderr] " + e.Data); } };
        try
        {
            if (!p.Start())
            {
                return "环境检查失败: Process.Start 返回 false";
            }
        }
        catch (Exception ex)
        {
            return $"环境检查失败({ex.GetType().Name}): {ex.Message}";
        }
        p.BeginOutputReadLine();
        p.BeginErrorReadLine();

        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(TimeSpan.FromSeconds(timeoutSeconds));
        try
        {
            await p.WaitForExitAsync(cts.Token);
        }
        catch (OperationCanceledException)
        {
            try { p.Kill(entireProcessTree: true); } catch { /* 尽力而为 */ }
            lock (gate) sb.AppendLine($"[超时] 环境检查超过 {timeoutSeconds}s, 已终止。");
        }
        await Task.Delay(120, CancellationToken.None);   // 给管道尾行一点冲刷时间
        lock (gate)
        {
            var text = sb.ToString().TrimEnd();
            return text.Length > 0 ? text : "(环境检查无输出)";
        }
    }
}
