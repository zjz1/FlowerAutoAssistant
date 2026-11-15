using System.Text;
using FAA.WpfGui.Models;
using FAA.WpfGui.Services;
using FAA.WpfGui.ViewModels;
using Xunit;

namespace FAA.WpfGui.Tests;

/// <summary>
/// 运行日志纯逻辑用例(N02, batch-06): 分片→整行拆分(LogLines.CompleteLines) + 失败行判红(MakeLine,
/// webui.html:970 判据 /异常|失败|错误/) + 轮询游标状态机(LogLines.Plan 判序)。
/// 分片≠行: print 的正文与换行是两次 write(webui.py:1128-1129)。
/// </summary>
public sealed class LogLinesTests
{
    private static List<LogLineVm> Split(StringBuilder pending, params string[] chunks)
        => LogLines.CompleteLines(chunks, pending);

    [Fact]
    public void ChunksAcrossWrites_AreJoinedIntoLines()
    {
        var pending = new StringBuilder();
        var lines = Split(pending, "ab", "c\n", "d\ne\n");
        Assert.Equal(new[] { "abc", "d", "e" }, lines.Select(l => l.Text));
        Assert.Equal("", pending.ToString());   // "d\ne\n" 自带两行, 全部消费完
    }

    [Fact]
    public void PartialLine_RemainsInPending()
    {
        var pending = new StringBuilder();
        var lines = Split(pending, "abc", "de");      // 无换行: 全留在缓冲
        Assert.Empty(lines);
        Assert.Equal("abcde", pending.ToString());
    }

    [Fact]
    public void Crlf_IsStrippedFromLineEnd()
    {
        var pending = new StringBuilder();
        var lines = Split(pending, "line1\r\n", "line2\r\n");
        Assert.Equal(new[] { "line1", "line2" }, lines.Select(l => l.Text));
        Assert.Equal("", pending.ToString());
    }

    [Fact]
    public void EmptyLines_AreDropped()
    {
        var pending = new StringBuilder();
        var lines = Split(pending, "\n\n");
        Assert.Empty(lines);
        Assert.Equal("", pending.ToString());
    }

    [Fact]
    public void Pending_CarriesAcrossCalls()
    {
        var pending = new StringBuilder();
        Assert.Empty(Split(pending, "abc"));            // 无换行: 无整行产出
        var lines = Split(pending, "def\n");            // 换行到达: 跨 chunk 拼成整行
        Assert.Equal(new[] { "abcdef" }, lines.Select(l => l.Text));
    }

    [Fact]
    public void MakeLine_FailRedJudging_MatchesWebui()
    {
        Assert.True(LogLines.MakeLine("xxx 失败").IsFail);
        Assert.True(LogLines.MakeLine("发生异常").IsFail);
        Assert.True(LogLines.MakeLine("错误: oops").IsFail);
        Assert.False(LogLines.MakeLine("[OCR统计] n=3").IsFail);
        Assert.False(LogLines.MakeLine("").IsFail);
    }

    [Fact]
    public void MakeLine_TrailingCarriageReturn_StrippedBeforeJudging()
    {
        var vm = LogLines.MakeLine("done\r");
        Assert.Equal("done", vm.Text);
        Assert.False(vm.IsFail);
        var fail = LogLines.MakeLine("失败\r");
        Assert.Equal("失败", fail.Text);              // \r 先剥再判红(不因孤 \r 丢判)
        Assert.True(fail.IsFail);
    }

    [Fact]
    public void Plan_ResyncHasHighestPrecedence_OverEmpty()
    {
        // 游标倒退优先于一切(空批也重同步 —— 原 PollTickAsync 判序第①支)
        Assert.Equal(LogPollPlan.Resync, LogLines.Plan(batchNext: 2, storeCursor: 5, batchLineCount: 0));
        Assert.Equal(LogPollPlan.Resync, LogLines.Plan(batchNext: 2, storeCursor: 5, batchLineCount: 3));
    }

    [Fact]
    public void Plan_EmptyPoll_AndNormalAppend()
    {
        Assert.Equal(LogPollPlan.Empty, LogLines.Plan(batchNext: 5, storeCursor: 5, batchLineCount: 0));
        Assert.Equal(LogPollPlan.Empty, LogLines.Plan(batchNext: 9, storeCursor: 5, batchLineCount: 0));
        Assert.Equal(LogPollPlan.Normal, LogLines.Plan(batchNext: 9, storeCursor: 5, batchLineCount: 2));
        Assert.Equal(LogPollPlan.Normal, LogLines.Plan(batchNext: 5, storeCursor: 5, batchLineCount: 2));
        // LogStore.Append 接受 Next ≥ cursor, next == cursor 且有行走正常追加(与原实现一致)
        Assert.Equal(LogPollPlan.Normal, LogLines.Plan(batchNext: 3, storeCursor: 0, batchLineCount: 3));
    }
}

/// <summary>
/// LogStore 游标守卫/重同步用例(N02, batch-06)。游标语义与服务端 /api/log 完全一致
/// (webui.py _log 1101-1109 行: next = 已下发分片总数; 防负对账 webui.py:1102-1104)。
/// 拒绝倒退 → 调用方 Reset 后重拉(重同步), 全链不静默吞。
/// </summary>
public sealed class LogStoreTests
{
    private static LogBatch Batch(long next, params string[] lines)
        => new(next, lines);

    [Fact]
    public void Append_FreshStore_AcceptsAndAdvancesCursor()
    {
        var store = new LogStore();
        Assert.Equal(0, store.Cursor);
        Assert.True(store.Append(Batch(3, "a\n", "b\n")));
        Assert.Equal(3, store.Cursor);
        Assert.Equal(2, store.ChunkCount);
        Assert.Equal("a\nb\n", store.ExportText());
    }

    [Fact]
    public void Append_CursorRegression_RejectedWithoutSilentSwallow()
    {
        var store = new LogStore();
        Assert.True(store.Append(Batch(3, "a\n", "b\n", "c\n")));
        Assert.False(store.Append(Batch(2, "x\n")));    // 倒退: 拒绝, 返回 false
        Assert.Equal(3, store.Cursor);                  // 游标不后退
        Assert.Equal(3, store.ChunkCount);              // 分片镜像不动
        Assert.Equal("a\nb\nc\n", store.ExportText());
    }

    [Fact]
    public void ResyncFlow_ResetThenAppend_RebuildsFromServerState()
    {
        // 轮询回落分支重同步序(原 PollTickAsync Resync 支): Reset(倒退到的 next) → 重新 Append
        var store = new LogStore();
        Assert.True(store.Append(Batch(3, "a\n", "b\n", "c\n")));
        store.Reset(2);                                  // 以服务端为准重同步
        Assert.Equal(2, store.Cursor);
        Assert.Empty(store.SnapshotChunks());
        Assert.True(store.Append(Batch(2, "new\n")));
        Assert.Equal(2, store.Cursor);
        Assert.Equal("new\n", store.ExportText());      // 旧镜像不残留
    }

    [Fact]
    public void Append_EmptyPoll_IsSuccessWithoutChunkGrowth()
    {
        var store = new LogStore();
        Assert.True(store.Append(Batch(3, "a\n")));
        Assert.True(store.Append(Batch(3)));            // lines 空, next 不变
        Assert.Equal(3, store.Cursor);
        Assert.Equal(1, store.ChunkCount);
    }

    [Fact]
    public void Append_SameCursorWithLines_Accepted()
    {
        // next == cursor 不属倒退(IsCursorRegression 严格小于), 与 Append 原/新行为一致
        var store = new LogStore();
        Assert.True(store.Append(Batch(3, "a\n")));
        Assert.True(store.Append(Batch(3, "b\n")));
        Assert.Equal(3, store.Cursor);
        Assert.Equal(2, store.ChunkCount);
    }

    [Fact]
    public void Reset_WithPositiveNext_SetsCursor()
    {
        var store = new LogStore();
        Assert.True(store.Append(Batch(3, "a\n")));
        store.Reset(7);
        Assert.Equal(7, store.Cursor);
        Assert.Equal(0, store.ChunkCount);
    }

    [Fact]
    public void IsCursorRegression_PureGuardSemantics()
    {
        Assert.True(LogStore.IsCursorRegression(2, 3));    // 倒退
        Assert.False(LogStore.IsCursorRegression(3, 3));   // 相等: 非倒退
        Assert.False(LogStore.IsCursorRegression(4, 3));   // 前进
        Assert.False(LogStore.IsCursorRegression(0, 0));
        Assert.True(LogStore.IsCursorRegression(-1, 0));   // 负 next(对账防负, webui.py:1102-1104 同源)
    }

    [Fact]
    public void Append_NullBatch_Throws()
    {
        var store = new LogStore();
        Assert.Throws<ArgumentNullException>(() => store.Append(null!));
    }
}
