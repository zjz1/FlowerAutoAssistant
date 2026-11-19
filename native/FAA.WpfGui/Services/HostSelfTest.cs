using System.IO;

namespace FAA.WpfGui.Services;

/// <summary>
/// --host-selftest 执行体: FaaProcessHost 全链实测。
///   探测(应 free) → spawn venv python webui.py --port(引擎首建加载模型需 10-30s, 上限 120s) →
///   复探测(应 faa) → POST /api/shutdown 优雅停 → 等进程退出 → 复探测(应 free) → 断言写 outfile。
/// 输出每行「step\tPASS|SKIP|FAIL\tdetail」+ 末行 SELFTEST PASS/FAIL; 退出码 0/1。
/// ⚠ 只用 8793 等非 8765 端口; 绝不调 /api/connect、不碰 ADB; spawn 会按 webui.py 自身设计
///   清空其 data/webui_runtime_log.txt(属程序正常启动行为, 如实记录)。
/// </summary>
public static class HostSelfTest
{
    /// <summary>执行全链自测, 返回进程退出码(0=PASS, 1=FAIL)。失败步骤之后的依赖步骤记 SKIP。</summary>
    public static async Task<int> RunAsync(int port, string outFile, CancellationToken ct)
    {
        var lines = new List<string>();
        var failCount = 0;
        var outputTail = new List<string>(); // 服务进程 stdout/stderr 尾部(诊断)

        void Add(string step, bool pass, string detail)
        {
            lines.Add($"{step}\t{(pass ? "PASS" : "FAIL")}\t{detail}");
            if (!pass)
            {
                failCount++;
            }
        }

        using var host = new FaaProcessHost();
        host.OutputReceived += s => { lock (outputTail) { outputTail.Add($"[out] {s}"); } };
        host.ErrorReceived += s => { lock (outputTail) { outputTail.Add($"[err] {s}"); } };

        // 步骤 0: 后端路径解析检查(A2, 原 venv-check): 输出解析结果(路径+来源诊断)而非裸 File.Exists ——
        // env 指向错路径等解析失败时, detail 直接给出 PathError 的中文报错(含已尝试路径清单)。
        // Phase 2: 打包模式只需 BackendExe; 源码模式需 VenvPython + WebUiScript。
        var venvOk = FaaProcessHost.PathError is null
            && (FaaProcessHost.BackendExe is not null
                || (FaaProcessHost.VenvPython is not null && FaaProcessHost.WebUiScript is not null));
        Add("venv-check", venvOk, venvOk
            ? $"解析成功: BackendExe={FaaProcessHost.BackendExe ?? "(源码模式)"}; VenvPython={FaaProcessHost.VenvPython}; WebUiScript={FaaProcessHost.WebUiScript}; 诊断: {FaaProcessHost.PathDiagnostics}"
            : $"解析失败: {FaaProcessHost.PathError ?? "(PathError 为空但路径仍为 null, 异常状态)"}");

        // 步骤 1: 首探测应 free
        var probe0 = venvOk ? await host.ProbeAsync(port) : "skipped";
        var free0 = probe0 == "free";
        Add($"probe@{port}(before)", free0, $"探测结果 = {probe0} (应 free)");

        // 步骤 2: spawn + 等 /api/status(上限 120s; 引擎首建加载模型 10-30s 属正常)
        var start = venvOk && free0
            ? await host.StartAsync(port, waitSeconds: 120, ct)
            : new ProxyResult<string>(false, 0, null, "前置步骤失败, 跳过", "");
        var spawnOk = start.Success;
        Add("spawn", spawnOk, spawnOk ? start.Value ?? "" : start.Error);

        // 步骤 3: 复探测应 faa
        var probe1 = spawnOk ? await host.ProbeAsync(port) : "skipped";
        Add($"probe@{port}(after-spawn)", probe1 == "faa", $"探测结果 = {probe1} (应 faa)");

        // 步骤 4: POST /api/shutdown 优雅停(FaaProcessHost.StopAsync 内部完成 停请求→等退出→超时杀)
        var stop = spawnOk
            ? await host.StopAsync(gracefulWaitSeconds: 15, ct)
            : new ProxyResult<string>(false, 0, null, "spawn 未成功, 跳过", "");
        Add("shutdown-graceful", stop.Success, stop.Success ? stop.Value ?? "" : stop.Error);

        // 步骤 5: 复探测应 free(端口释放稍滞后于进程退出, 轮询最多 10s)
        var free1 = false;
        if (spawnOk)
        {
            for (var i = 0; i < 10 && !free1; i++)
            {
                await Task.Delay(1000, ct);
                free1 = await host.ProbeAsync(port) == "free";
            }
        }
        Add($"probe@{port}(after-stop)", free1, spawnOk
            ? $"探测结果 = {(free1 ? "free" : "仍被占")} (应 free)"
            : "spawn 未成功, 跳过");

        lines.Add(failCount == 0 ? "SELFTEST PASS" : $"SELFTEST FAIL ({failCount} steps failed)");
        // 附注: spawn 会按 webui.py 自身设计清空 data/webui_runtime_log.txt(_log_reset_history)
        lines.Add($"# 注: webui.py 启动按自身设计清空 data/webui_runtime_log.txt; 服务进程输出尾部: " +
                  (outputTail.Count == 0 ? "(无)" : string.Join(" | ", outputTail.TakeLast(6))));
        await WriteAsync(outFile, lines, ct);
        return failCount == 0 ? 0 : 1;
    }

    private static async Task WriteAsync(string outFile, List<string> lines, CancellationToken ct)
    {
        var dir = Path.GetDirectoryName(Path.GetFullPath(outFile));
        if (!string.IsNullOrEmpty(dir))
        {
            Directory.CreateDirectory(dir);
        }
        await File.WriteAllTextAsync(outFile, string.Join('\n', lines) + "\n",
            new System.Text.UTF8Encoding(false), ct);
    }
}
