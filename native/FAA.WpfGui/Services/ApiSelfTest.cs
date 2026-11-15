using System.IO;
using System.Net.Http;
using System.Text.Json;
using FAA.WpfGui.Models;

namespace FAA.WpfGui.Services;

/// <summary>
/// --api-selftest 执行体: 经 FaaProxy 逐端点调用并断言响应形状。
///   all 模式      → 26 个端点全测(对 Mock 服务端, POST 无真实副作用);
///   get-only 模式 → 对真实实例只发 GET, 跳过全部变更类 POST(绝不调 /api/run /api/shutdown /api/click);
///                   首连即连接拒绝(实例未运行)时全部端点记 SKIP(instance-not-running) 且 exit 0(不算失败)。
/// 夹具契约与 _mock/mock_faa_api.py 现状对齐: /api/run 用 mock 真实流程名「开始启动」(_FLOWS[0]),
/// /api/tplt_load 用 _mock/debug/sample.png(该目录唯一文件)。
/// 输出文件每行「endpoint\tPASS|SKIP|FAIL\tdetail」+ 末行 SELFTEST PASS/FAIL; 退出码 0/1。
/// </summary>
public static class ApiSelfTest
{
    /// <summary>单个端点用例: name 输出名 / isPost 是否变更类 / 断言体(返回通过与否 + 明细)。</summary>
    private sealed record Case(string Name, bool IsPost, Func<FaaProxy, CancellationToken, Task<(bool Pass, string Detail)>> Run);

    /// <summary>
    /// 端点清单: GET 11 + POST 15 = 26 个唯一端点(含 GET /api/tplt_init, webui.py:646-647);
    /// 另有 2 条同端点分支用例: run_daily 缺 finish_action 键负例(A1 防再犯) + click abs 分支(D8), 计 28 用例。
    /// </summary>
    private static readonly Case[] Cases =
    [
        // ---------------- GET 11 ----------------
        new("GET /api/status", false, async (px, ct) =>
        {
            var r = await px.GetStatusAsync(ct);
            return r.Success && r.Value is not null
                ? (r.Value.FailCache is not null,
                   $"connected={r.Value.Connected} running={r.Value.Running} ui_build={Trunc(r.Value.UiBuild, 16)} fail_cache.mb={r.Value.FailCache?.Mb}")
                : (false, r.Error);
        }),
        new("GET /api/flows", false, async (px, ct) =>
        {
            var r = await px.GetFlowsAsync(ct);
            return r.Success && r.Value is not null
                ? (r.Value.Flows is not null, $"flows={r.Value.Flows?.Length ?? 0} 个")
                : (false, r.Error);
        }),
        new("GET /api/kb", false, async (px, ct) =>
        {
            var r = await px.GetKbAsync(ct);
            return r.Success && r.Value is not null
                ? (r.Value.ClickLog is not null && r.Value.CloseButtons is not null,
                   $"click_log 场景数={r.Value.ClickLog?.Count ?? 0} close_buttons={r.Value.CloseButtons?.Length ?? 0}")
                : (false, r.Error);
        }),
        new("GET /api/daily", false, async (px, ct) =>
        {
            var r = await px.GetDailyAsync(ct);
            if (!r.Success || r.Value is null)
            {
                return (false, r.Error);
            }
            var v = r.Value;
            return (v.Modules is not null && v.OcrThreads >= 0,
                   $"name={v.Name} modules={v.Modules?.Length ?? 0} ocr_threads={v.OcrThreads}");
        }),
        new("GET /api/screen", false, async (px, ct) =>
        {
            var r = await px.GetScreenAsync(ct);
            if (r.Success && r.Value is not null)
            {
                return (r.Value.Jpeg.Length > 0 && r.Value.W > 0 && r.Value.H > 0,
                        $"jpeg {r.Value.Jpeg.Length} b64字符, w={r.Value.W} h={r.Value.H}");
            }
            return Degrade(r.StatusCode, r.Error, r.RawBody, "未连接(503+error+status 属服务端设计内形状)");
        }),
        new("GET /api/ocr", false, async (px, ct) =>
        {
            var r = await px.GetOcrAsync(ct);
            if (r.Success && r.Value is not null)
            {
                return (r.Value.Boxes is not null, $"boxes={r.Value.Boxes?.Length ?? 0}");
            }
            return Degrade(r.StatusCode, r.Error, r.RawBody, "未连接(503 属设计内)");
        }),
        new("GET /api/failures", false, async (px, ct) =>
        {
            var r = await px.GetFailuresAsync(0, ct);
            return r.Success && r.Value is not null
                ? (r.Value.Items is not null && r.Value.Next >= 0,
                   $"items={r.Value.Items?.Length ?? 0} next={r.Value.Next}")
                : (false, r.Error);
        }),
        new("GET /api/log", false, async (px, ct) =>
        {
            var r = await px.GetLogAsync(0, ct);
            return r.Success && r.Value is not null
                ? (r.Value.Lines is not null && r.Value.Next >= 0,
                   $"lines={r.Value.Lines?.Length ?? 0} 分片, next={r.Value.Next}")
                : (false, r.Error);
        }),
        new("GET /api/log_download", false, async (px, ct) =>
        {
            var r = await px.DownloadLogAsync(ct);
            if (!r.Success || r.Value is null)
            {
                return (false, r.Error);
            }
            // 服务端导出头带 UTF-8 BOM + "# FlowerAutoAssistant 运行日志"(webui.py 1126/1139 行)
            var head = System.Text.Encoding.UTF8.GetString(r.Value, 0, Math.Min(80, r.Value.Length));
            return (r.Value.Length > 0 && head.Contains("运行日志"), $"{r.Value.Length} 字节, 头={Trunc(head, 40)}");
        }),
        new("GET /api/fail_cache_info", false, async (px, ct) =>
        {
            var r = await px.GetFailCacheInfoAsync(ct);
            if (r.Success && r.Value is not null)
            {
                return (r.Value.ThresholdMb > 0, $"mb={r.Value.Mb:F2} threshold={r.Value.ThresholdMb} exceed={r.Value.Exceed}");
            }
            // 真实服务端已知隐患: _fail_cache_stat 返回 files 为 Python set → json.dumps 500(webui.py 146/627 行)
            return (false, $"{r.Error} [服务端 files 字段为 set 序列化隐患, 如实记录]");
        }),
        new("GET /api/tplt_init", false, async (px, ct) =>
        {
            var r = await px.TpltInitAsync(ct);
            if (r.Success && r.Value is not null)
            {
                // 成功形状 {jpeg,w,h} 无 ok 键(webui.py 685-694)
                return (r.Value.Jpeg.Length > 0 && r.Value.W > 0 && r.Value.H > 0,
                        $"jpeg {r.Value.Jpeg.Length} b64字符, w={r.Value.W} h={r.Value.H}");
            }
            return Degrade(r.StatusCode, r.Error, r.RawBody, "未连接(503 属设计内)");
        }),

        // ---------------- POST 15 ----------------
        new("POST /api/connect", true, async (px, ct) =>
        {
            var r = await px.ConnectAsync(ct);
            return r.Success && r.Value is not null
                ? (r.Value.Ok, $"ok={r.Value.Ok} connected={r.Value.Connected}")
                : (false, r.Error);
        }),
        new("POST /api/set_mode", true, async (px, ct) =>
        {
            var r = await px.SetModeAsync("use", ct);
            return r.Success && r.Value is not null ? (r.Value.Ok, "mode=use") : (false, r.Error);
        }),
        new("POST /api/click", true, async (px, ct) =>
        {
            var r = await px.ClickRelAsync(0.5, 0.5, ct);
            return r.Success && r.Value is not null ? (r.Value.Ok, "rel=[0.5,0.5]") : (false, r.Error);
        }),
        new("POST /api/click abs 分支", true, async (px, ct) =>
        {
            // D8: 绝对坐标分支补测 —— abs 是同端点 /api/click 的 {x,y} 分支(主仓 webui.py:893-895
            // _click; 无独立 /api/click_abs 端点, POST 白名单仅 /api/click), mock 同分支已实现
            var r = await px.ClickAbsAsync(10, 20, ct);
            return r.Success && r.Value is not null ? (r.Value.Ok, "abs=[10,20]") : (false, r.Error);
        }),
        new("POST /api/run", true, async (px, ct) =>
        {
            // mock _FLOWS 全为中文名(mock_faa_api.py:111-130), 用真实存在的「开始启动」
            var r = await px.RunAsync("开始启动", "use", ct);
            return r.Success && r.Value is not null ? (r.Value.Ok, $"started={r.Value.Started}") : (false, r.Error);
        }),
        new("POST /api/run_daily", true, async (px, ct) =>
        {
            // 收尾方案 A1: body 键名 finish_action(对齐批 22 真后端 data["finish_action"]);
            // mock 含键 → 200 且响应回显该键 → 此处断言回显键值与请求值一致(防键名再犯)
            var r = await px.RunDailyAsync(["startup"], "use", "close_client", ct);
            if (!r.Success || r.Value is null)
            {
                return (false, r.Error);
            }
            string? echoed;
            try
            {
                using var doc = JsonDocument.Parse(r.RawBody);
                echoed = doc.RootElement.TryGetProperty("finish_action", out var fa)
                    && fa.ValueKind == JsonValueKind.String ? fa.GetString() : null;
            }
            catch (Exception ex)
            {
                return (false, $"响应体解析失败 {ex.GetType().Name}: {Trunc(r.RawBody, 60)}");
            }
            return r.Value.Ok && echoed == "close_client"
                ? (true, $"started={r.Value.Started} count={r.Value.Count} finish_action 回显={echoed}")
                : (false, $"ok={r.Value.Ok} finish_action 回显={echoed ?? "(响应无此键)"} (期望 close_client)");
        }),
        new("POST /api/run_daily 缺 finish_action 键负例", true, async (px, ct) =>
        {
            // 收尾方案 A1 负例: 裸 HttpClient(不经 FaaProxy)发不含 finish_action 的 run_daily
            // → mock 400 {"error":"缺少 finish_action"}(防键名回退: 旧客户端漏带该键须在此暴露)
            using var http = new HttpClient();
            using var content = new StringContent(
                """{"selected":["startup"],"mode":"use"}""",
                System.Text.Encoding.UTF8, "application/json");
            using var resp = await http.PostAsync(px.BaseUrl + "api/run_daily", content, ct);
            var body = await resp.Content.ReadAsStringAsync(ct);
            return (int)resp.StatusCode == 400 && body.Contains("finish_action")
                ? (true, $"400 {Trunc(body, 60)}")
                : (false, $"期望 400 + finish_action 错误体, 实际 {(int)resp.StatusCode} {Trunc(body, 60)}");
        }),
        new("POST /api/stop", true, async (px, ct) =>
        {
            var r = await px.StopAsync(ct);
            return r.Success && r.Value is not null ? (r.Value.Ok, Trunc(r.Value.Message, 30)) : (false, r.Error);
        }),
        new("POST /api/set_config", true, async (px, ct) =>
        {
            // 19 键白名单全量提交(mock 校验形状); ocr_threads 取合法范围 0-8
            var cfg = new Dictionary<string, object?>
            {
                ["enable_switch"] = false, ["target_tail"] = "12", ["claim_online"] = true,
                ["claim_party"] = true, ["claim_hb"] = false, ["enable_shine"] = false,
                ["enable_pollin"] = true, ["enable_like"] = false, ["enable_hot_sale"] = false,
                ["enable_baobao"] = false, ["enable_baobao_buy"] = true, ["log_click_pos"] = false,
                ["use_cache_pos"] = false, ["ocr_threads"] = 2, ["enable_mine"] = false,
                ["enable_rabbit"] = false, ["enable_water"] = true, ["confirm_page_close"] = true,
                ["fail_cache_prompt_mb"] = 100.0,
            };
            var r = await px.SetConfigAsync(cfg, ct);
            // 白名单现 22 键: 服务端 19 键 + finish_action(批 21 过渡) + ocr_execution_provider(OCR3 batch-08)
            // + use_angle_cls(OCR2 batch-10, bool 默认 true)。批 21 后的 20/21 旧钉子未随批 08 追平,
            // OCR2 批一并对齐到 22(引擎 API 变化与原生 UI 联动红线)。
            return r.Success && r.Value is not null
                ? (r.Value.Ok && FaaProxy.SetConfigKeys.Length == 22,
                   $"ok={r.Value.Ok} changed={r.Value.Changed} 白名单 {FaaProxy.SetConfigKeys.Length} 键(19 服务键+finish_action+ocr_execution_provider+use_angle_cls)")
                : (false, r.Error);
        }),
        new("POST /api/shutdown", true, async (px, ct) =>
        {
            var r = await px.ShutdownAsync(ct);
            return r.Success && r.Value is not null ? (r.Value.Ok, Trunc(r.Value.Message, 30)) : (false, r.Error);
        }),
        new("POST /api/failures_clear", true, async (px, ct) =>
        {
            var r = await px.FailuresClearAsync(ct);
            return r.Success && r.Value is not null ? (r.Value.Ok, "清空失败清单") : (false, r.Error);
        }),
        new("POST /api/log_clear", true, async (px, ct) =>
        {
            var r = await px.LogClearAsync(ct);
            return r.Success && r.Value is not null
                ? (r.Value.Ok && r.Value.Next == 0, $"ok={r.Value.Ok} next={r.Value.Next} (须回 0)")
                : (false, r.Error);
        }),
        new("POST /api/fail_cache_clean", true, async (px, ct) =>
        {
            var r = await px.FailCacheCleanAsync("all", ct: ct);
            return r.Success && r.Value is not null
                ? (r.Value.Ok, $"removed={r.Value.Removed} bytes={r.Value.Bytes} kept={r.Value.Kept}")
                : (false, r.Error);
        }),
        new("POST /api/fail_cache_open", true, async (px, ct) =>
        {
            var r = await px.FailCacheOpenAsync(ct);
            return r.Success && r.Value is not null ? (r.Value.Ok, Trunc(r.Value.Dir, 60)) : (false, r.Error);
        }),
        new("POST /api/tplt_load", true, async (px, ct) =>
        {
            // _mock/debug/ 下唯一文件是 sample.png(mock_faa_api.py 仅放行 debug/ 目录)
            var r = await px.TpltLoadAsync("debug/sample.png", ct);
            return r.Success && r.Value is not null
                ? (r.Value.Jpeg.Length > 0 && r.Value.W > 0, $"loaded={r.Value.Loaded} w={r.Value.W} h={r.Value.H}")
                : (false, r.Error);
        }),
        new("POST /api/tplt_submit", true, async (px, ct) =>
        {
            var r = await px.TpltSubmitAsync(new TpltSubmitRequest(1280, 720, "selftest-ann"), ct);
            return r.Success && r.Value is not null
                ? (r.Value.Ok, $"annotation_id={r.Value.AnnotationId}")
                : (false, r.Error);
        }),
        new("POST /api/tplt_contour", true, async (px, ct) =>
        {
            var r = await px.TpltContourAsync(10, 10, 300, 200, ct);
            return r.Success && r.Value is not null
                ? (r.Value.Ok && r.Value.Points is not null, $"n={r.Value.N} points={r.Value.Points?.Length ?? 0}")
                : (false, r.Error);
        }),
    ];

    /// <summary>执行自测, 返回进程退出码(0=PASS, 1=FAIL)。</summary>
    public static async Task<int> RunAsync(string baseUrl, string outFile, string mode, CancellationToken ct)
    {
        var all = mode.Equals("all", StringComparison.OrdinalIgnoreCase);
        var proxy = new FaaProxy(baseUrl);
        var lines = new List<string>();
        var failCount = 0;

        // —— 首连检测(仅 get-only): 连接层失败(StatusCode=0, 本机回环下即实例未运行) → 全部 SKIP, exit 0 ——
        if (!all)
        {
            var first = await proxy.GetStatusAsync(ct);
            if (!first.Success && first.StatusCode == 0)
            {
                foreach (var c in Cases)
                {
                    lines.Add($"{c.Name}\tSKIP\tinstance-not-running{(c.IsPost ? "+get-only" : "")}");
                }
                lines.Add("SELFTEST PASS");
                await WriteAsync(outFile, lines, ct);
                return 0;
            }
        }

        foreach (var c in Cases)
        {
            if (c.IsPost && !all)
            {
                // get-only: 跳过全部变更类 POST —— 对真实实例永不发
                lines.Add($"{c.Name}\tSKIP\tget-only(变更类 POST 跳过)");
                continue;
            }
            try
            {
                var (pass, detail) = await c.Run(proxy, ct);
                lines.Add($"{c.Name}\t{(pass ? "PASS" : "FAIL")}\t{detail}");
                if (!pass)
                {
                    failCount++;
                }
            }
            catch (Exception ex)
            {
                lines.Add($"{c.Name}\tFAIL\tcase 异常 {ex.GetType().Name}: {ex.Message}");
                failCount++;
            }
        }

        lines.Add(failCount == 0 ? "SELFTEST PASS" : $"SELFTEST FAIL ({failCount}/{Cases.Length} failed)");
        await WriteAsync(outFile, lines, ct);
        return failCount == 0 ? 0 : 1;
    }

    /// <summary>降级判定: 503 且响应体含 error 键(如"未连接") → 算通过但如实标注 degraded。</summary>
    private static (bool, string) Degrade(int statusCode, string err, string rawBody, string note)
    {
        if (statusCode == 503 && !string.IsNullOrEmpty(rawBody))
        {
            try
            {
                using var doc = JsonDocument.Parse(rawBody);
                if (doc.RootElement.ValueKind == JsonValueKind.Object && doc.RootElement.TryGetProperty("error", out _))
                {
                    return (true, $"degraded: 503 {Trunc(rawBody, 60)} —— {note}");
                }
            }
            catch
            {
                // 落到 FAIL
            }
        }
        return (false, err);
    }

    private static string Trunc(string s, int n) => string.IsNullOrEmpty(s) ? "" : s.Length <= n ? s : s[..n] + "…";

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
