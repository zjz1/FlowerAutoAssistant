using System.IO;
using FAA.WpfGui.Services;
using Xunit;

namespace FAA.WpfGui.Tests;

/// <summary>
/// 自测启动参数解析用例(N02, batch-06)。核心覆盖:
///   ① 批 21 事故形态: 未加引号的带空格 outfile 被外层 shell 拆成多 token, 中段须空格回拼为原路径;
///   ② 各 flag 尾参校验(模式名/秒数/端口) + 错误记录(SelftestArgsError 文案逐字);
///   ③ 退化形态现状锁定(0-1 段时 JoinOutfile 的 v[1..^1] 抛异常 —— 等价迁移原样保留, 非本批修复项)。
/// baseDirectory 参数注入(原 AppContext.BaseDirectory), 用例传固定假值。
/// </summary>
public sealed class ParseModeTests
{
    private const string FakeBaseDir = @"C:\fake\bin\Release\net8.0-windows\";

    [Fact]
    public void ApiSelftest_SpacedOutfile_TokensRejoined_Batch21AccidentShape()
    {
        // 批 21 实测事故形态: outfile「…/trae project/…」未加引号被拆成两个 argv token。
        var result = SelftestArgsParser.Parse(
            new[] { "--api-selftest", "http://127.0.0.1:8765/", "E:/my_project/trae", "project/FAA_basis/out.txt", "all" },
            FakeBaseDir);
        var api = Assert.IsType<ApiMode>(result);
        Assert.Equal("http://127.0.0.1:8765/", api.BaseUrl);
        Assert.Equal("E:/my_project/trae project/FAA_basis/out.txt", api.OutFile);   // 中段空格回拼
        Assert.Equal("all", api.Mode);
    }

    [Fact]
    public void ApiSelftest_SingleTokenOutfile_LegacyContractCompatible()
    {
        var result = SelftestArgsParser.Parse(
            new[] { "--api-selftest", "http://u/", "o.txt", "get-only" }, FakeBaseDir);
        var api = Assert.IsType<ApiMode>(result);
        Assert.Equal("o.txt", api.OutFile);
        Assert.Equal("get-only", api.Mode);
    }

    [Fact]
    public void ApiSelftest_WrongTailMode_ReturnsError()
    {
        var result = SelftestArgsParser.Parse(
            new[] { "--api-selftest", "http://u/", "o.txt", "post-everything" }, FakeBaseDir);
        var err = Assert.IsType<SelftestArgsError>(result);
        Assert.Equal("--api-selftest", err.Flag);
        Assert.Equal("尾参须为 all|get-only, 实得「post-everything」", err.Reason);
        Assert.Equal("o.txt", err.CandidateOutFile);
    }

    [Fact]
    public void SseSelftest_SpacedOutfile_Rejoined_AndSecondsParsed()
    {
        // 「a b/c.txt」被拆成 ["a","b/c.txt"], 中段回拼; 尾参秒数认最后一段。
        var result = SelftestArgsParser.Parse(
            new[] { "--sse-selftest", "http://u/", "a", "b/c.txt", "30" }, FakeBaseDir);
        var sse = Assert.IsType<SseMode>(result);
        Assert.Equal("http://u/", sse.BaseUrl);
        Assert.Equal("a b/c.txt", sse.OutFile);
        Assert.Equal(30, sse.Seconds);
    }

    [Fact]
    public void SseSelftest_NonPositiveSeconds_ReturnsError()
    {
        var result = SelftestArgsParser.Parse(
            new[] { "--sse-selftest", "http://u/", "o.txt", "0" }, FakeBaseDir);
        var err = Assert.IsType<SelftestArgsError>(result);
        Assert.Equal("--sse-selftest", err.Flag);
        Assert.Equal("尾参须为正整数秒, 实得「0」", err.Reason);
    }

    [Fact]
    public void HostSelftest_SpacedOutfile_Rejoined_AndPortParsed()
    {
        var result = SelftestArgsParser.Parse(
            new[] { "--host-selftest", "8765", "E:/my", "project/x.txt" }, FakeBaseDir);
        var host = Assert.IsType<HostMode>(result);
        Assert.Equal(8765, host.Port);
        Assert.Equal("E:/my project/x.txt", host.OutFile);
    }

    [Fact]
    public void HostSelftest_BadPort_ReturnsErrorWithOutfileCandidate()
    {
        var result = SelftestArgsParser.Parse(
            new[] { "--host-selftest", "notaport", "o.txt" }, FakeBaseDir);
        var err = Assert.IsType<SelftestArgsError>(result);
        Assert.Equal("--host-selftest", err.Flag);
        Assert.Equal("o.txt", err.CandidateOutFile);
    }

    [Fact]
    public void HostSelftest_TooFewSegments_ReturnsEmptyCandidate_NoThrow()
    {
        // host 分支错误路径不用 JoinOutfile(v.Length>1 三元守卫), 0-1 段不抛异常。
        var result = SelftestArgsParser.Parse(new[] { "--host-selftest", "8765" }, FakeBaseDir);
        var err = Assert.IsType<SelftestArgsError>(result);
        Assert.Equal("", err.CandidateOutFile);
    }

    [Fact]
    public void ProbeTest_SpacedOutfile_PortsAndExpectParsed()
    {
        var result = SelftestArgsParser.Parse(
            new[] { "--probe-test", "E:/my", "dir/probe.txt", "--probe-ports", "8765,8798,8799", "--probe-expect", "8765=faa,8798=other" },
            FakeBaseDir);
        var probe = Assert.IsType<ProbeMode>(result);
        Assert.Equal("E:/my dir/probe.txt", probe.OutFile);
        Assert.Equal(new[] { 8765, 8798, 8799 }, probe.Ports);
        Assert.NotNull(probe.Expect);
        Assert.Equal("faa", probe.Expect![8765]);
        Assert.Equal("other", probe.Expect![8798]);
    }

    [Fact]
    public void ProbeTest_AllPortsInvalid_FallsBackTo8765()
    {
        var result = SelftestArgsParser.Parse(
            new[] { "--probe-test", "o.txt", "--probe-ports", "x,y" }, FakeBaseDir);
        var probe = Assert.IsType<ProbeMode>(result);
        Assert.Equal(new[] { 8765 }, probe.Ports);   // 缺省或全非法 → 只探 8765
        Assert.Null(probe.Expect);                    // 空/全非法 → 不做比对
    }

    [Fact]
    public void ProbeTest_EmptyOutfileToken_FallsBackToBaseDirectory()
    {
        // outfile 为空 token(taken[0]="" → outFile.Length==0) → 兜底 baseDirectory/probe-selftest.txt(参数注入)。
        var result = SelftestArgsParser.Parse(
            new[] { "--probe-test", "", "--probe-ports", "8765" }, FakeBaseDir);
        var probe = Assert.IsType<ProbeMode>(result);
        Assert.Equal(Path.Combine(FakeBaseDir, "probe-selftest.txt"), probe.OutFile);
        Assert.Equal(new[] { 8765 }, probe.Ports);
    }

    [Fact]
    public void NoSelftestFlags_ReturnsNull()
    {
        Assert.Null(SelftestArgsParser.Parse(new string[] { }, FakeBaseDir));
        Assert.Null(SelftestArgsParser.Parse(new[] { "--page", "log", "--port", "9999" }, FakeBaseDir));
        Assert.Null(SelftestArgsParser.Parse(new[] { "--api-base", "http://127.0.0.1:9999/" }, FakeBaseDir));
    }

    [Fact]
    public void ApiSelftest_NextSwitchStopsCollection_ReturnsError()
    {
        // 采段遇下一个 "--" 开关即停: 只采到 2 段 → 报错且段数如实计数。
        var result = SelftestArgsParser.Parse(
            new[] { "--api-selftest", "http://u/", "o.txt", "--port", "1234" }, FakeBaseDir);
        var err = Assert.IsType<SelftestArgsError>(result);
        Assert.Contains("实得 2 段", err.Reason);
    }

    // ---- 退化形态现状锁定(等价迁移原样保留: JoinOutfile 的 v[1..^1] 对 0/1 段数组抛异常) ----

    [Fact]
    public void ApiSelftest_ZeroSegments_DegenerateForm_ThrowsAsLegacy()
    {
        // 现状锁定(非修复项): --api-selftest 后无任何 token, 错误路径 JoinOutfile(v[0 段]) → v[1..^1]
        // 起止越界抛异常(与原 App.ParseMode 逐行为等价 —— 等价重构含此退化形态)。
        Assert.ThrowsAny<Exception>(() =>
            SelftestArgsParser.Parse(new[] { "--api-selftest" }, FakeBaseDir));
    }

    [Fact]
    public void ApiSelftest_OneSegment_DegenerateForm_ThrowsAsLegacy()
    {
        // 现状锁定(非修复项): 1 段时 v[1..^1] 产生负长度切片抛异常(原实现同)。
        Assert.ThrowsAny<Exception>(() =>
            SelftestArgsParser.Parse(new[] { "--api-selftest", "http://u/" }, FakeBaseDir));
    }

    [Fact]
    public void ProbeTest_ZeroSegments_DegenerateForm_ThrowsAsLegacy()
    {
        // 现状锁定(非修复项): --probe-test 无尾参(含只带 --probe-ports 选项)时, 「缺 outfile」错误路径
        // 自身经 JoinOutfile(v[0 段]) 抛异常(原实现同; 带选项形态由本用例第 2 断言覆盖)。
        Assert.ThrowsAny<Exception>(() =>
            SelftestArgsParser.Parse(new[] { "--probe-test" }, FakeBaseDir));
        Assert.ThrowsAny<Exception>(() =>
            SelftestArgsParser.Parse(new[] { "--probe-test", "--probe-ports", "8765" }, FakeBaseDir));
    }
}
