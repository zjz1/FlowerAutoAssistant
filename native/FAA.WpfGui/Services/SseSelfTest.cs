using System.IO;
using System.Text;
using FAA.WpfGui.Models;

namespace FAA.WpfGui.Services;

/// <summary>
/// --sse-selftest 执行体: 连 SSE 读 N 秒, 断言事件流与分发链路。
/// ⚠ 只对 Mock 用(真实 webui.py 目前无 /api/stream, 会 404 退避重连 → 判 FAIL 属预期)。
/// 断言: 建连≥1、重连≥1(Mock 首连被掐断 → 验证退避重连真生效)、log 事件≥5 且 LogStore 游标推进、
/// status 事件≥2、failure-events≥1(批 21 修复: 服务端契约=复数 failures {items,next} 批量事件,
/// 检查行键沿用批 19 的「failure-events」token 供统一脚本取数; 批 19 及之前只分发单数 failure →
/// 全落解析错误)、批量条目逐条进账本≥1、frames≥1(B1: 同一连接订阅 ?frames=1 —— 与既有 cutfirst
/// 查询串拼接为 &frames=1, mock 每 3s 推 canned 帧; 顺带实证「与既有查询参数正确拼接」)、解析错误=0。
/// 输出每行「check\tPASS|FAIL\tdetail」+ 末行 SELFTEST PASS/FAIL; 退出码 0/1。
/// detail 内嵌机器可读 token「failure-events=N / frames=N / parse-errors=N」(真实计数值, FAIL 时如实为 0/非零)
/// —— 统一脚本闸门按 /failure-events=(\d+)/、/frames=(\d+)/、/parse-errors=(\d+)/ 从本文件取数(NP4 dwf.ts:204-205),
/// 批 21 实测: 表格键是制表符分隔, 等号 token 缺失时正则永不匹配 → 闸门恒假空转(parse-errors=? 问号实证)。
/// </summary>
public static class SseSelfTest
{
    /// <summary>执行自测, 返回进程退出码(0=PASS, 1=FAIL)。</summary>
    public static async Task<int> RunAsync(string baseUrl, string outFile, int seconds, CancellationToken ct)
    {
        var store = new LogStore();
        // cutfirst=<token>: 让 mock 把本运行的首条连接在首轮事件推送后掐断 —— 退避重连断言的前提。
        // token 每次运行唯一(2026-11-10 二修): mock 对每个 token 只掐一次, 进程级一次性原实现会让
        // 同一 Mock 进程的第二次 --sse-selftest 拿不到掐断 → reconnect 恒 FAIL(可重复复测修复)。
        // 不带标志的连接(契约自测/GUI)不受影响; 真实服务端忽略未知查询参数。
        // B1: 同一连接追加 frames=1 订阅帧推送 —— URL 既有 cutfirst 查询串, SseClient 须以
        // "&frames=1" 正确拼接(mock 每 3s 推 canned 帧; 掐断首连后重连的连接同样续推 frame)。
        var cutToken = $"sse{DateTime.UtcNow.Ticks:X}";
        var client = new SseClient(baseUrl, $"api/stream?cutfirst={cutToken}", frames: true);
        var cnt = new Counters();
        client.OnConnected += () => Interlocked.Increment(ref cnt.Connected);
        client.OnLog += batch =>
        {
            Interlocked.Increment(ref cnt.LogBatches);
            if (!store.Append(batch))
            {
                Interlocked.Increment(ref cnt.CursorRegress); // 游标倒退被 LogStore 拒绝, 如实计数
            }
        };
        client.OnStatus += _ => Interlocked.Increment(ref cnt.Status);
        client.OnFrame += _ => Interlocked.Increment(ref cnt.Frames);   // B1: frame 事件计数(?frames=1 订阅)
        client.OnFailures += page =>
        {
            Interlocked.Increment(ref cnt.FailuresBatch);
            Interlocked.Add(ref cnt.FailureItems, page.Items.Length);   // 逐条进浮层的账本(批 21 链路)
        };
        client.OnFailure += _ => Interlocked.Increment(ref cnt.Failure);   // 单数兼容分支(现役服务端不推)
        client.OnParseError += (_, _) => Interlocked.Increment(ref cnt.ParseErrors);

        client.Start();
        try
        {
            await Task.Delay(TimeSpan.FromSeconds(seconds), ct);
        }
        catch (OperationCanceledException)
        {
            // 外层取消: 仍输出已收集结果
        }
        await client.StopAsync();

        var lines = new List<string>
        {
            $"connect\t{(cnt.Connected >= 1 ? "PASS" : "FAIL")}\t建连次数={cnt.Connected} (应≥1)",
            $"reconnect\t{(client.ReconnectCount >= 1 ? "PASS" : "FAIL")}\t断线后重连/重试={client.ReconnectCount} (Mock 首连被掐断, 应≥1)",
            $"log-events\t{(cnt.LogBatches >= 5 ? "PASS" : "FAIL")}\tlog 事件={cnt.LogBatches} (应≥5)",
            $"logstore-cursor\t{(store.Cursor > 0 ? "PASS" : "FAIL")}\t游标={store.Cursor} 分片={store.ChunkCount} 倒退拒绝={cnt.CursorRegress}",
            $"status-events\t{(cnt.Status >= 2 ? "PASS" : "FAIL")}\tstatus 事件={cnt.Status} (应≥2)",
            $"frames\t{(cnt.Frames >= 1 ? "PASS" : "FAIL")}\tframes={cnt.Frames} frame 事件={cnt.Frames} (应≥1; B1 帧指纹推送: ?frames=1 订阅, 与 cutfirst 查询串以 & 拼接, mock 每 3s 推 canned 帧)",
            $"failure-events\t{(cnt.FailuresBatch >= 1 && cnt.FailureItems >= 1 ? "PASS" : "FAIL")}\tfailure-events={cnt.FailuresBatch} failures 批量事件={cnt.FailuresBatch} 条目={cnt.FailureItems} 单数failure={cnt.Failure} (批量≥1且条目≥1; 服务端契约=复数 failures {{items,next}}, 检查行键沿用批19 token; 单数分支兼容保留)",
            $"parse-errors\t{(cnt.ParseErrors == 0 ? "PASS" : "FAIL")}\tparse-errors={cnt.ParseErrors} 解析错误={cnt.ParseErrors} (应=0)",
        };
        var failCount = lines.Count(l => l.Contains("\tFAIL\t"));
        lines.Add(failCount == 0 ? "SELFTEST PASS" : $"SELFTEST FAIL ({failCount} checks failed)");

        var dir = Path.GetDirectoryName(Path.GetFullPath(outFile));
        if (!string.IsNullOrEmpty(dir))
        {
            Directory.CreateDirectory(dir);
        }
        await File.WriteAllTextAsync(outFile, string.Join('\n', lines) + "\n", new UTF8Encoding(false), ct);
        return failCount == 0 ? 0 : 1;
    }

    private sealed class Counters
    {
        public int Connected;
        public int LogBatches;
        public int Status;
        public int Frames;          // frame 事件数(B1: ?frames=1 订阅; mock 每 3s 推 canned 帧)
        public int FailuresBatch;   // failures 批量事件数(服务端契约=复数)
        public int FailureItems;    // 批量事件累计条目数(逐条进浮层账本)
        public int Failure;         // failure 单数事件数(兼容保留, 现役服务端不推)
        public int ParseErrors;
        public int CursorRegress;
    }
}
