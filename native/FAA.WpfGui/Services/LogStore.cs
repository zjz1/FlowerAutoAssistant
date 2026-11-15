using FAA.WpfGui.Models;

namespace FAA.WpfGui.Services;

/// <summary>
/// 运行日志增量缓冲(线程安全)。
/// 游标语义与服务端 /api/log 完全一致(webui.py _log 1101-1109 行):
///   after=N → 服务端返回 {"next": N+len(lines), "lines": [...]} —— next = 已下发分片总数;
///   本类持有 Cursor(=本地已吸收的 next), 下一次轮询 GET /api/log?after=Cursor。
/// 保留原始分片(≠行: 一次 write 一个分片, print 的正文与换行是两次 write), 供离线导出按序 join。
/// </summary>
public sealed class LogStore
{
    private readonly object _lock = new();
    private readonly List<string> _chunks = new();   // 原始分片, 按到达顺序
    private long _cursor;                             // 已吸收到的服务端 next

    /// <summary>当前游标(= 已吸收的服务端 next; 下一次增量拉取的 after 值)。</summary>
    public long Cursor
    {
        get { lock (_lock) { return _cursor; } }
    }

    /// <summary>已缓冲分片数。</summary>
    public int ChunkCount
    {
        get { lock (_lock) { return _chunks.Count; } }
    }

    /// <summary>
    /// 游标守卫纯函数(N02, batch-06 提纯): incomingNext &lt; currentCursor = 服务端游标倒退
    /// (重启/被外部清空, 增量语义已破坏 —— 调用方应显式 Reset 后重拉, 不静默吞; webui.py:1102-1104
    /// 防负对账的客户端侧)。轮询侧同判序的三支决策见 ViewModels.LogLines.Plan(① 支同此式)。
    /// </summary>
    internal static bool IsCursorRegression(long incomingNext, long currentCursor)
        => incomingNext < currentCursor;

    /// <summary>
    /// 追加一个增量分片(GET /api/log?after=Cursor 的响应)。
    /// 返回 false = 游标倒退(服务端重启/被外部清空), 调用方应显式 Reset 后重拉 —— 不会静默吞。
    /// 空轮询(lines 空, next 不变)视为成功返回 true。
    /// </summary>
    public bool Append(LogBatch batch)
    {
        ArgumentNullException.ThrowIfNull(batch);
        lock (_lock)
        {
            if (IsCursorRegression(batch.Next, _cursor))
            {
                return false; // 服务端游标倒退: 需调用方 Reset, 增量语义已破坏
            }
            if (batch.Lines.Length > 0)
            {
                _chunks.AddRange(batch.Lines);
            }
            _cursor = batch.Next;
            return true;
        }
    }

    /// <summary>复位游标并清空缓冲(POST /api/log_clear 回 next=0 后调用; webui.py 1154-1155 行要求前端同步复位)。</summary>
    public void Reset(long next = 0)
    {
        lock (_lock)
        {
            _chunks.Clear();
            _cursor = next;
        }
    }

    /// <summary>原始分片快照(按序副本)。</summary>
    public string[] SnapshotChunks()
    {
        lock (_lock)
        {
            return [.. _chunks];
        }
    }

    /// <summary>全量拼接文本(离线导出用; 分片已自带换行, 直接 Concat 不加分隔符)。</summary>
    public string ExportText()
    {
        lock (_lock)
        {
            return string.Concat(_chunks);
        }
    }
}
