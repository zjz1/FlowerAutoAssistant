using System.Text;

namespace FAA.WpfGui.ViewModels;

/// <summary>轮询批次决策(LogLines.Plan 返回值; N02 提纯自 LogViewModel.PollTickAsync :148-161 判序)。</summary>
internal enum LogPollPlan
{
    /// <summary>游标倒退 = 服务端缓冲被外部清空/重启: 以服务端为准重同步(本地显示随之重置, 不静默吞)。</summary>
    Resync,

    /// <summary>空轮询: 本批无行, 直接返回。</summary>
    Empty,

    /// <summary>正常增量追加。</summary>
    Normal,
}

/// <summary>
/// 运行日志纯逻辑(N02 提纯, batch-06): 分片→整行拆分(原 LogViewModel.AppendLines :173-222 主体) +
/// 失败行判红(:218-222 MakeLine) + 轮询游标状态机决策(:148-161 判序)。逐行等价迁移, 行为零变化。
/// UI 集合(Lines)与游标存储(LogStore)仍归 LogViewModel/LogStore 所有 —— 本类只做无状态计算,
/// 分片尾部缓冲(StringBuilder pending)由调用方持有并传入(跨调用状态)。
/// SSE 契约注释原样保留: 游标语义与 SSE 通道一致(webui.py:1102-1104 防负对账)。
/// </summary>
internal static class LogLines
{
    /// <summary>把分片拆成整行(分片≠行: print 的正文与换行是两次 write, webui.py:1128-1129)。
    /// 整行入返回值; 不满一行留在 <paramref name="pending"/>。空行丢弃(原实现 line.Length>0 守卫)。</summary>
    public static List<LogLineVm> CompleteLines(IEnumerable<string> chunks, StringBuilder pending)
    {
        var fresh = new List<LogLineVm>();
        foreach (var chunk in chunks)
        {
            pending.Append(chunk);
            while (true)
            {
                var idx = IndexOfNewline(pending);
                if (idx < 0)
                {
                    break;
                }
                var line = pending.ToString(0, idx);
                pending.Remove(0, idx + 1);
                if (line.Length > 0)
                {
                    fresh.Add(MakeLine(line));
                }
            }
        }
        return fresh;
    }

    /// <summary>找 pending 里第一个换行(兼容 \r\n —— 连 \r 一起剥)。</summary>
    private static int IndexOfNewline(StringBuilder pending)
    {
        for (var i = 0; i < pending.Length; i++)
        {
            if (pending[i] == '\n')
            {
                return i;
            }
        }
        return -1;
    }

    /// <summary>行构造: 失败行红显(判据与 webui.html:970 一致: /异常|失败|错误/), 行尾孤 \r 剥除。</summary>
    public static LogLineVm MakeLine(string line)
    {
        line = line.EndsWith('\r') ? line[..^1] : line;
        return new LogLineVm(line, line.Contains("异常") || line.Contains("失败") || line.Contains("错误"));
    }

    /// <summary>
    /// 轮询批次决策(等价原 PollTickAsync 判序, 顺序逐支一致):
    ///   ① batch.Next &lt; store.Cursor → Resync(游标倒退优先于一切, 空批也重同步);
    ///   ② 本批 0 行 → Empty(空轮询);
    ///   ③ 其余 → Normal(正常追加; next == cursor 且有行也走此支, LogStore.Append 接受 Next ≥ cursor)。
    /// </summary>
    public static LogPollPlan Plan(long batchNext, long storeCursor, int batchLineCount)
        => batchNext < storeCursor ? LogPollPlan.Resync
         : batchLineCount == 0 ? LogPollPlan.Empty
         : LogPollPlan.Normal;
}
