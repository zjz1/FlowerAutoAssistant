using System.IO;

namespace FAA.WpfGui.Services;

/// <summary>
/// VM 执行轨迹(诊断用): 设环境变量 FAA_TRACE=1 时, 关键流转一行一条落
/// %TEMP%/faa_vm_trace.txt; 未设时零开销。WinExe 无控制台, 异常/时序问题靠它取证。
/// </summary>
public static class DebugTrace
{
    private static readonly string? Path = Environment.GetEnvironmentVariable("FAA_TRACE") == "1"
        ? System.IO.Path.Combine(PathObj(), "faa_vm_trace.txt")
        : null;
    private static readonly object Lock = new();

    private static string PathObj() => System.IO.Path.GetTempPath();

    public static void Log(string line)
    {
        if (Path is null)
        {
            return;
        }
        try
        {
            lock (Lock)
            {
                File.AppendAllText(Path, $"[{DateTime.Now:HH:mm:ss.fff}] {line}\n");
            }
        }
        catch
        {
            // 追踪写失败不影响业务
        }
    }
}
