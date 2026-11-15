using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;

namespace FAA.WpfGui.Services;

/// <summary>
/// 端口归属探测服务: 三态 "faa"(已有 FAA 实例) / "other"(被别的程序占用) / "free"(空闲)。
/// 语义逐条对照 FlowerAutoAssistant/webui_app.py 的 _probe(port, timeout=3.0) (56-71 行):
///   py  socket.create_connection(("127.0.0.1", port), timeout) 失败 → "free"
///       【这里: TcpClient.ConnectAsync 失败或 3s 超时 → "free"】
///   py  urllib.request.urlopen(_url(port) + "api/status") 读 JSON
///       【这里: 静态单例 HttpClient GET http://127.0.0.1:{port}/api/status, 3s 超时】
///   py  isinstance(data, dict) and "flow_dir" in data and "ui_build" in data → "faa"
///       【这里: JSON 根是 object 且同时含 flow_dir、ui_build 两键 → "faa"】
///   py  HTTP/JSON 任何异常或缺键 → "other"
///       【这里: 同语义, 一律 "other"】
/// </summary>
public static class ProbeService
{
    private const int TimeoutMs = 3000; // 对应 _probe 默认 timeout=3.0 秒

    /// <summary>静态单例 HttpClient: 复用连接池(每次 new 会耗尽本地端口); 3s 超时兜底。</summary>
    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromMilliseconds(TimeoutMs) };

    /// <summary>对外主入口: 返回三态字符串 "faa" / "other" / "free"。</summary>
    public static async Task<string> ProbeAsync(int port)
    {
        return (await ProbeCoreAsync(port, CancellationToken.None)).State;
    }

    /// <summary>核心探测: 返回 (三态, 明细)。自测输出行的 detail 列即取此明细。</summary>
    private static async Task<(string State, string Detail)> ProbeCoreAsync(int port, CancellationToken outer)
    {
        // —— 第 1 步: TCP 探测(对应 py socket.create_connection, with 块探完即关) ——
        using (var tcp = new TcpClient())
        {
            using var tcpTimeout = CancellationTokenSource.CreateLinkedTokenSource(outer);
            tcpTimeout.CancelAfter(TimeoutMs); // ConnectAsync 本身不带超时, 用 CTS 补 3s
            try
            {
                await tcp.ConnectAsync(IPAddress.Loopback, port, tcpTimeout.Token);
            }
            catch (Exception ex)
            {
                // 连不上(拒绝/超时/不可达)一律视为空闲, 对应 py except OSError → return "free"
                return ("free", $"tcp-connect-failed({ex.GetType().Name})");
            }
        } // using 出口: 探测完立即释放连接, 对应 py 的 with 自动 close

        // —— 第 2 步: GET /api/status(对应 py urlopen(_url(port) + "api/status")) ——
        using var httpTimeout = CancellationTokenSource.CreateLinkedTokenSource(outer);
        httpTimeout.CancelAfter(TimeoutMs);
        try
        {
            using var resp = await Http.GetAsync($"http://127.0.0.1:{port}/api/status", httpTimeout.Token);
            resp.EnsureSuccessStatusCode(); // py urlopen 对非 2xx 抛 HTTPError → other, 此处同语义

            await using var stream = await resp.Content.ReadAsStreamAsync(httpTimeout.Token);
            using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: httpTimeout.Token);

            // 对应 py: isinstance(data, dict) and "flow_dir" in data and "ui_build" in data
            // (只判断键是否存在, 不看值类型; 根不是 object 也走 other)
            if (doc.RootElement.ValueKind == JsonValueKind.Object
                && doc.RootElement.TryGetProperty("flow_dir", out _)
                && doc.RootElement.TryGetProperty("ui_build", out _))
            {
                return ("faa", $"http {(int)resp.StatusCode}, /api/status 含 flow_dir+ui_build");
            }

            // JSON 合法但缺 faa 独有键(或根不是 object) → other
            return ("other", $"http {(int)resp.StatusCode}, /api/status 缺 faa 独有键");
        }
        catch (Exception ex)
        {
            // 对应 py: except Exception: pass → return "other"
            return ("other", $"http-failed({ex.GetType().Name}: {ex.Message})");
        }
    }

    /// <summary>
    /// 自测入口(--probe-test): 逐端口探测, 输出文件每行 "port\tstate\tdetail";
    /// 给了 expect 则逐条比对, 末行写 "SELFTEST PASS" 或 "SELFTEST FAIL(...)"。
    /// </summary>
    public static async Task RunSelfTest(
        string outFile, IReadOnlyList<int> ports, IReadOnlyDictionary<int, string>? expect)
    {
        var lines = new List<string>();
        var mismatches = new List<string>();

        foreach (var port in ports)
        {
            var (state, detail) = await ProbeCoreAsync(port, CancellationToken.None);
            lines.Add($"{port}\t{state}\t{detail}");
            if (expect is not null && expect.TryGetValue(port, out var want) && want != state)
            {
                mismatches.Add($"{port}: 期望 {want}, 实得 {state}");
            }
        }

        // 末行自测结论; 不给 expect 就不写结论行
        if (expect is not null && expect.Count > 0)
        {
            lines.Add(mismatches.Count == 0
                ? "SELFTEST PASS"
                : "SELFTEST FAIL (" + string.Join("; ", mismatches) + ")");
        }

        // 确保输出目录存在; UTF-8 无 BOM, 便于 harness 直接读
        var dir = Path.GetDirectoryName(Path.GetFullPath(outFile));
        if (!string.IsNullOrEmpty(dir))
        {
            Directory.CreateDirectory(dir);
        }
        await File.WriteAllTextAsync(outFile, string.Join('\n', lines) + "\n", new UTF8Encoding(false));
    }
}
