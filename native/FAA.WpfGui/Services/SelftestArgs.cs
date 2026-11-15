using System.IO;

namespace FAA.WpfGui.Services;

// ==================== 自测模式解析(N02 提纯, batch-06) ====================
// 提纯对象 = 原 App.xaml.cs 的私有 record 组 + ParseMode/ParseProbeMode(锚点 App.xaml.cs:217-289/
// :323-381, 批 21 加固代码)。逐行等价迁移, 行为零变化:
//   - 诊断字段/文案逐字保留(批 21 SELFTEST FAIL 链 :298 的输入由此而来);
//   - 唯一非纯依赖(exe 目录 AppContext.BaseDirectory, 仅 --probe-test 兜底 outfile 用)改为参数
//     注入 —— FaaProcessHost 同款「env 以参数注入」口径(N02 方案表 #6); App 调用点传 AppContext
//     真值, 测试传任意值。结果类型 record 本身即纯数据。
// 现状已知退化形态(--api-selftest / --sse-selftest 采到 0-1 段、--probe-test 无尾参时
// JoinOutfile 的 v[1..^1] 对空/单元素数组抛异常)按等价约束**原样保留**, 由用例锁定现状,
// 不属本批修复范围(行为零变化红线)。

/// <summary>自测模式(--probe-test)解析结果: 端口表 + 期望表 + 输出文件(原 App 私有 record 升 internal)。</summary>
internal sealed record ProbeMode(string OutFile, List<int> Ports, Dictionary<int, string>? Expect);

/// <summary>自测模式(--api-selftest)解析结果。</summary>
internal sealed record ApiMode(string BaseUrl, string OutFile, string Mode);

/// <summary>自测模式(--host-selftest)解析结果。</summary>
internal sealed record HostMode(int Port, string OutFile);

/// <summary>自测模式(--sse-selftest)解析结果。</summary>
internal sealed record SseMode(string BaseUrl, string OutFile, int Seconds);

/// <summary>自测参数解析失败(响亮失败: 落诊断文件 + exit 1, 绝不静默落入 GUI 模式; 处理链在 App)。</summary>
internal sealed record SelftestArgsError(string Flag, string Reason, string CandidateOutFile);

/// <summary>
/// 扫描启动参数, 返回匹配的自测模式记录; 无自测开关返回 null; 自测开关存在但解析不齐返回 SelftestArgsError。
/// 批 21 加固(实测事故: 统一脚本传未加引号的带空格 outfile「…/trae project/…」被拆成两个 argv token,
/// 旧 Take(n) 定数式解析把「E:/my_project/trae」当 outfile、路径后半段当尾参 → api 写到截断路径/sse 秒数
/// TryParse 失败静默落 GUI)。新语法按各 flag 的参数形状重建:
///   --api-selftest &lt;url&gt; &lt;outfile…(空格回拼)&gt; &lt;all|get-only&gt;
///   --sse-selftest &lt;url&gt; &lt;outfile…&gt; &lt;seconds&gt;
///   --host-selftest &lt;port&gt; &lt;outfile…&gt;
///   --probe-test &lt;outfile…&gt; [--probe-ports …] [--probe-expect …]
/// 尾参只认最后一段(模式名/秒数), 中段全部按空格回拼为 outfile —— 与原单 token 路径完全兼容。
/// N02: 原 App.ParseMode(217-289)/ParseProbeMode(323-381) 逐行等价迁入; 调用点单行替换, revert 即回旧实现。
/// </summary>
internal static class SelftestArgsParser
{
    /// <summary>解析启动参数为自测模式。<paramref name="baseDirectory"/> = exe 所在目录(原
    /// AppContext.BaseDirectory 真值注入; 仅 --probe-test 兜底 outfile 路径用到)。</summary>
    public static object? Parse(string[] args, string baseDirectory)
    {
        // 收集 "--flag" 之后到下一个 "--" 开关之间的全部 token(带空格路径被拆成的多段都收进来)
        static string[] Collect(string[] a, int idx)
        {
            var vals = new List<string>();
            for (var j = idx + 1; j < a.Length && !a[j].StartsWith("--"); j++)
            {
                vals.Add(a[j]);
            }
            return [.. vals];
        }

        // 中段(除首尾参外)按空格回拼成原始 outfile 路径
        static string JoinOutfile(string[] v) => string.Join(" ", v[1..^1]);

        for (var i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--probe-test":
                {
                    var v = Collect(args, i);
                    if (v.Length < 1)
                    {
                        return new SelftestArgsError("--probe-test", "缺 outfile", JoinOutfile(v));
                    }
                    return ParseProbeMode(args, i, [string.Join(" ", v)], baseDirectory);
                }
                case "--api-selftest":
                {
                    var v = Collect(args, i);
                    if (v.Length < 3)
                    {
                        return new SelftestArgsError("--api-selftest",
                            $"需 <url> <outfile> <all|get-only>, 实得 {v.Length} 段", JoinOutfile(v));
                    }
                    if (v[^1] is not ("all" or "get-only"))
                    {
                        return new SelftestArgsError("--api-selftest",
                            $"尾参须为 all|get-only, 实得「{v[^1]}」", JoinOutfile(v));
                    }
                    return new ApiMode(v[0], JoinOutfile(v), v[^1]);
                }
                case "--host-selftest":
                {
                    var v = Collect(args, i);
                    if (v.Length < 2 || !int.TryParse(v[0], out var port))
                    {
                        return new SelftestArgsError("--host-selftest",
                            $"需 <port> <outfile>, 实得 {v.Length} 段", v.Length > 1 ? string.Join(" ", v[1..]) : "");
                    }
                    return new HostMode(port, string.Join(" ", v[1..]));
                }
                case "--sse-selftest":
                {
                    var v = Collect(args, i);
                    if (v.Length < 3)
                    {
                        return new SelftestArgsError("--sse-selftest",
                            $"需 <url> <outfile> <seconds>, 实得 {v.Length} 段", JoinOutfile(v));
                    }
                    if (!int.TryParse(v[^1], out var seconds) || seconds <= 0)
                    {
                        return new SelftestArgsError("--sse-selftest",
                            $"尾参须为正整数秒, 实得「{v[^1]}」", JoinOutfile(v));
                    }
                    return new SseMode(v[0], JoinOutfile(v), seconds);
                }
            }
        }
        return null;
    }

    /// <summary>解析 --probe-test 模式(兼容旧契约: --probe-ports 8765,8798,8799 与 --probe-expect 8765=faa,…)。</summary>
    private static ProbeMode ParseProbeMode(string[] args, int idx, string[] taken, string baseDirectory)
    {
        var outFile = taken.Length > 0 ? taken[0] : "";
        var portsRaw = "";
        var expectRaw = "";
        for (var i = idx + 1; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--probe-ports" when i + 1 < args.Length:
                    portsRaw = args[++i];
                    break;
                case "--probe-expect" when i + 1 < args.Length:
                    expectRaw = args[++i];
                    break;
            }
        }

        // 端口表: 缺省或全非法 → 只探 8765(与 webui 启动口一致)
        var ports = new List<int>();
        foreach (var tok in portsRaw.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            if (int.TryParse(tok, out var p))
            {
                ports.Add(p);
            }
        }
        if (ports.Count == 0)
        {
            ports.Add(8765);
        }

        // 期望表: 空/全非法 → 不做比对
        Dictionary<int, string>? expect = null;
        if (expectRaw.Length > 0)
        {
            var dict = new Dictionary<int, string>();
            foreach (var tok in expectRaw.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
            {
                var kv = tok.Split('=', 2);
                if (kv.Length == 2 && int.TryParse(kv[0].Trim(), out var p))
                {
                    dict[p] = kv[1].Trim();
                }
            }
            if (dict.Count > 0)
            {
                expect = dict;
            }
        }

        // 输出文件缺失 → 兜底落到 exe 目录, 保证有文件可读(baseDirectory 参数注入, 原为 AppContext.BaseDirectory)
        if (outFile.Length == 0)
        {
            outFile = Path.Combine(baseDirectory, "probe-selftest.txt");
        }
        return new ProbeMode(outFile, ports, expect);
    }
}
