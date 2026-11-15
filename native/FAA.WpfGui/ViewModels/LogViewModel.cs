using System.Collections.ObjectModel;
using System.IO;
using System.Text;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using FAA.WpfGui.Models;
using FAA.WpfGui.Services;

namespace FAA.WpfGui.ViewModels;

/// <summary>日志展示行: 失败行红显(判据与 webui.html:970 一致: /异常|失败|错误/)。</summary>
public sealed record LogLineVm(string Text, bool IsFail);

/// <summary>
/// 运行日志页 ViewModel —— 契约4「日志三同步」:
///   ① SSE 优先(NP-sse): MainViewModel 的 SseClient 推 log 事件 → LogStore 吸收 → 本页显示行拆分;
///      SSE 断线/不可用时自动回落 800ms 增量轮询(webui.html pollLog 同频):
///      GET /api/log?after=游标 → LogStore 吸收(游标语义与 SSE 通道完全一致, 回落不降级)。
///      游标防负: 拉取前 after=max(0, cursor), 且 LogStore 拒绝游标倒退(倒退=服务端被外部清空, 走重同步)。
///      定时器随本页可见性启停(D5): 页不可见停、切回自动恢复(模式对齐 DebugViewModel.OnPageVisibility)。
///   ② 保存日志 = GET /api/log_download 服务端**全量**导出(含本页打开前历史; 服务端同时归档截图缓存+manifest)
///      → SaveFileDialog 落盘。导出失败(异常/非 200)时离线快照兜底(B4, 对齐 webui.html saveLog):
///      把 LogStore 本地已缓存分片导出到用户 Downloads(时间戳文件名, 重名加序号)。
///   ③ 清除日志 = confirm(文案按 fail_cache/archived 三分支) → POST /api/log_clear → 服务端回 next=0 →
///      LogStore 游标复位 + 本页显示清空, 三处一起动; 失败则游标不复位、服务端缓冲与 LogStore 镜像不动,
///      本页显示仍清空并刷新状态(对齐 webui.html clearLog 失败语义, D4)。
/// </summary>
public partial class LogViewModel : ObservableObject
{
    private readonly MainViewModel _main;
    private readonly System.Windows.Threading.DispatcherTimer _timer;
    private readonly StringBuilder _pending = new();   // 尚未凑成整行的分片尾部
    private bool _polling;

    /// <summary>UI 线程调度器(VM 在 UI 线程构造; SSE 事件在后台线程到达, 改展示集合须经此)。</summary>
    private readonly System.Windows.Threading.Dispatcher _uiDispatcher;

    public LogViewModel(MainViewModel main)
    {
        _main = main;
        _uiDispatcher = System.Windows.Threading.Dispatcher.CurrentDispatcher;
        // 订阅 SSE 推送(SSE 在线时本页数据来自推送; 断线由 800ms 轮询兜底, 语义一致)
        _main.SseLogArrived += OnSseLogArrived;
        _main.SseLogResynced += OnSseLogResynced;
        // UI 线程定时器(VM 在 UI 线程构造); 800ms 与 webui.html:976 setTimeout(pollLog, 800) 同频。
        // D5: 不再构造即常开 —— 初始(首页非本页)保持停止, 由 OnPageVisibility 随导航启停(省 CPU)。
        _timer = new System.Windows.Threading.DispatcherTimer(
            System.Windows.Threading.DispatcherPriority.Background)
        {
            Interval = TimeSpan.FromMilliseconds(800),
        };
        _timer.Tick += async (_, _) => await PollTickAsync();
        // D5 可见性接线: SetPage 对 Debug 页是直接调用(MainViewModel.SetPage 内), 本文件白名单不动
        // MainViewModel, 故订阅 CurrentPage 属性通知 —— SetPage 赋值即触发; 构造期 _currentPage=Home
        // 是直接字段赋值不经属性, 不触发(初始不可见, 定时器保持停止, 语义正确)。
        _main.PropertyChanged += OnMainPropertyChanged;
    }

    // ==================== SSE 推送接入(NP-sse) ====================

    /// <summary>SSE log 事件 → 展示行(已在 MainViewModel 入 LogStore; 这里只管显示, marshal 到 UI 线程)。</summary>
    private void OnSseLogArrived(LogBatch batch)
    {
        _uiDispatcher.BeginInvoke(() =>
        {
            AppendLines(batch.Lines);
            UpdateLineInfo();
        });
    }

    /// <summary>SSE 游标倒退(MainViewModel 已重同步 LogStore) → 本页显示随之重置(游标/显示/服务端三同步)。</summary>
    private void OnSseLogResynced()
    {
        _uiDispatcher.BeginInvoke(ClearDisplay);
    }

    public ObservableCollection<LogLineVm> Lines { get; } = new();

    /// <summary>工具行反馈(保存/清除结果), 不自动清空(让用户有时间读到路径)。</summary>
    [ObservableProperty]
    private string _statusText = "";

    [ObservableProperty]
    private string _lineInfoText = "0 行 · 游标 0";

    /// <summary>展示行有追加时通知视图自动滚动(仅当用户本就停在底部)。</summary>
    public event Action? LinesAppended;

    public void StopPolling() => _timer.Stop();

    // ==================== 页面可见性(D5) ====================

    /// <summary>
    /// 页面可见性驱动的轮询启停(模式对齐 DebugViewModel.OnPageVisibility: 页不可见停, 切回恢复)。
    /// SSE 推送不在此停 —— 推送入 LogStore 在 MainViewModel 侧, 与页面可见无关, 本页只是不再主动轮询。
    /// 不动 StatusText: 那是保存/清除的结果反馈, 不被导航动作覆盖。
    /// </summary>
    public void OnPageVisibility(bool visible)
    {
        if (visible && !_timer.IsEnabled)
        {
            _timer.Start();
        }
        else if (!visible && _timer.IsEnabled)
        {
            _timer.Stop();
        }
    }

    /// <summary>导航切页(MainViewModel.SetPage 赋 CurrentPage) → 本页是否可见。</summary>
    private void OnMainPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(MainViewModel.CurrentPage))
        {
            OnPageVisibility(ReferenceEquals(_main.CurrentPage, this));
        }
    }

    // ==================== 增量轮询 ====================

    private async Task PollTickAsync()
    {
        if (_polling)
        {
            return;   // 上一轮还没回来(网络慢), 跳过本轮防堆叠
        }
        if (_main.IsSseUp)
        {
            return;   // SSE 在线: 推送通道供数, 800ms 轮询让路(SseClient 断线后自动回落到这里)
        }
        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            return;   // 服务未就绪(探测/自起中), 空转
        }
        _polling = true;
        try
        {
            var store = _main.Session.Logs;
            var after = Math.Max(0, store.Cursor);   // 契约4 防负: 负游标会让服务端负切片错乱(webui.py:1102-1104)
            var r = await proxy.GetLogAsync(after);
            DebugTrace.Log($"log.poll: after={after} success={r.Success} lines={(r.Value?.Lines.Length ?? -1)} next={r.Value?.Next}");
            if (!r.Success || r.Value is null)
            {
                return;   // 服务不可达: 静默保留游标, 下轮再拉(webui 同语义)
            }
            var batch = r.Value;
            // N02(batch-06): 游标状态机决策提纯为 LogLines.Plan(判序逐支等价迁移) ——
            // Resync=游标倒退(以服务端为准重同步, 不静默吞) / Empty=空轮询 / Normal=正常追加
            switch (LogLines.Plan(batch.Next, store.Cursor, batch.Lines.Length))
            {
                case LogPollPlan.Resync:
                    store.Reset(batch.Next);
                    ClearDisplay();
                    store.Append(batch);
                    AppendLines(batch.Lines);
                    UpdateLineInfo();
                    return;
                case LogPollPlan.Empty:
                    return;   // 空轮询
            }
            store.Append(batch);
            AppendLines(batch.Lines);
            UpdateLineInfo();
        }
        finally
        {
            _polling = false;
        }
    }

    /// <summary>把分片拆成整行入展示集(分片≠行: print 的正文与换行是两次 write, webui.py:1128-1129)。
    /// N02(batch-06): 拆分纯逻辑迁 LogLines.CompleteLines(等价迁移; pending 缓冲仍由本类持有)。</summary>
    private void AppendLines(IEnumerable<string> chunks)
    {
        var fresh = LogLines.CompleteLines(chunks, _pending);
        if (fresh.Count == 0)
        {
            return;
        }
        foreach (var l in fresh)
        {
            Lines.Add(l);
        }
        LinesAppended?.Invoke();
    }

    private void ClearDisplay()
    {
        Lines.Clear();
        _pending.Clear();
        UpdateLineInfo();
    }

    private void UpdateLineInfo()
        => LineInfoText = $"{Lines.Count} 行 · 游标 {_main.Session.Logs.Cursor}";

    // ==================== 保存日志 ====================

    [RelayCommand]
    private async Task SaveLogAsync()
    {
        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            // 服务未就绪/已停: log_download 发不出去 → 与导出失败同走离线快照兜底(B4; webui saveLog
            // 对"服务端不可达"正是落页面快照)。本地无缓存时如实提示, 不落空文件。
            await ExportLocalSnapshotAsync("服务端不可达(尚未就绪或已停止)");
            return;
        }
        var dlg = new Microsoft.Win32.SaveFileDialog
        {
            FileName = $"faa_log_{DateTime.Now:yyyyMMdd_HHmmss}.txt",
            Filter = "文本文件 (*.txt)|*.txt|所有文件 (*.*)|*.*",
            Title = "保存运行日志(服务端全量导出)",
        };
        if (dlg.ShowDialog() != true)
        {
            StatusText = "已取消保存";
            return;
        }
        var r = await proxy.DownloadLogAsync();
        if (!r.Success || r.Value is null)
        {
            // B4: log_download 失败(异常/非 200) → 离线快照兜底(对齐 webui.html saveLog 的 fetch 失败分支:
            // 服务端全量拿不到时, 导出本地已缓存日志, 离线也有保存能力)
            await ExportLocalSnapshotAsync($"log_download 失败: {r.Error}");
            return;
        }
        try
        {
            await File.WriteAllBytesAsync(dlg.FileName, r.Value);
            StatusText = $"已保存: {dlg.FileName}";
        }
        catch (Exception ex)
        {
            DialogService.Error($"写入文件失败: {ex.Message}", "保存日志");
            StatusText = $"保存失败: {ex.Message}";
            return;
        }
        // 服务端保存动作已完成截图归档 → 立即刷新状态(webui.html:942 同语义, 供「清除日志」文案用)
        await _main.RefreshStatusNowAsync();
    }

    // ==================== 离线快照兜底(B4) ====================

    /// <summary>
    /// 离线快照兜底(B4; webui.html saveLog 930-953 行同构): 服务端全量导出不可用时, 把 LogStore
    /// 已缓存的原始分片(SSE/增量轮询累积所得; ExportText 按序拼接, 分片自带换行)导出到用户
    /// Downloads, 文件名 faa_log_snapshot_yyyyMMdd_HHmmss.txt, 重名追加 _N 序号。
    /// 头部带 BOM(webui 同款, 防 Windows 记事本按 ANSI 打开中文乱码)。本地无任何缓存分片时不落盘。
    /// 与服务端导出的差别: 快照只含本页打开以来已缓存的日志, 不含服务端更早历史, 也不触发截图归档。
    /// </summary>
    private async Task ExportLocalSnapshotAsync(string reason)
    {
        var store = _main.Session.Logs;
        if (store.ChunkCount == 0)
        {
            DialogService.Warn(
                $"保存失败: {reason}。\n本地也没有已缓存的日志分片, 无内容可导出快照。",
                "保存日志");
            StatusText = "保存失败: 服务不可达且本地无缓存日志";
            return;
        }
        var text = store.ExportText();
        var lineCount = 0;
        foreach (var ch in text)
        {
            if (ch == '\n')
            {
                lineCount++;   // 行数= 换行数(webui saveLog 统计同口径: text.match(/\n/g).length)
            }
        }
        var head = "# FlowerAutoAssistant 本地快照日志\n"
                 + $"# 导出时间: {DateTime.Now:yyyy/MM/dd HH:mm:ss}\n"
                 + $"# {reason}, 以下为本地已缓存的日志(增量轮询/SSE 累积所得, 可能不含服务端更早历史)\n"
                 + $"# 总行数: {lineCount}\n"
                 + new string('-', 40) + "\n";
        var path = NextSnapshotPath();
        try
        {
            // BOM 头(\ufeff): 与 webui 快照一致, 让记事本按 UTF-8 识别
            await File.WriteAllTextAsync(path, "\ufeff" + head + text, new UTF8Encoding(true));
        }
        catch (Exception ex)
        {
            DialogService.Error($"写入本地快照失败: {ex.Message}\n目标位置: {path}", "保存日志");
            StatusText = $"本地快照写入失败: {ex.Message}";
            return;
        }
        DialogService.Warn(
            $"服务端全量导出不可用({reason}), 已导出本地快照:\n{path}\n\n" +
            "内容为本页打开以来已缓存的日志; 服务恢复后重新「保存日志」可取得服务端全量导出(含截图归档)。",
            "保存日志(离线快照)");
        StatusText = $"已导出本地快照: {path}";
    }

    /// <summary>快照落盘路径: 用户 Downloads(不存在时回退「我的文档」), 时间戳文件名, 重名追加 _N 序号。</summary>
    private static string NextSnapshotPath()
    {
        var dir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads");
        if (!Directory.Exists(dir))
        {
            dir = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
        }
        var stamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
        var path = Path.Combine(dir, $"faa_log_snapshot_{stamp}.txt");
        for (var i = 1; File.Exists(path); i++)
        {
            path = Path.Combine(dir, $"faa_log_snapshot_{stamp}_{i}.txt");
        }
        return path;
    }

    // ==================== 浏览截图(NP2 承接落地) ====================

    [RelayCommand]
    private async Task BrowseShotsAsync()
    {
        // webui.html:807-812 log-browse-shots: 在服务端机器打开缓存目录(POST /api/fail_cache_open)
        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            StatusText = "服务尚未就绪, 无法打开缓存目录";
            return;
        }
        var r = await proxy.FailCacheOpenAsync();
        if (r.Success && r.Value?.Ok == true)
        {
            StatusText = $"已打开缓存目录: {r.Value.Dir}";
        }
        else
        {
            StatusText = $"打开目录失败: {r.Error}";
        }
    }

    // ==================== 清除日志 ====================

    [RelayCommand]
    private async Task ClearLogAsync()
    {
        // 文案三分支(契约4, 与 webui.html clearLog 892-908 逐行对齐): 数据源=/api/status.fail_cache
        var fc = _main.Session.LastStatus?.FailCache;
        var n = fc?.Count ?? 0;
        var mb = (fc?.Mb ?? 0).ToString("0.0");
        var arch = fc?.Archived;
        var msg = "确定清除日志？\n\n将清空服务端日志缓冲与磁盘备份, 本页显示也一并清空。\n";
        if (n > 0 && arch is not null && arch.All)
        {
            msg += $"\n截图缓存 {n} 张 / {mb} MB 已归档到 data/fail_archives/{arch.Ts}(归档 {arch.Count} 张)。\n" +
                   "本次只删除缓存副本, 归档副本不受影响。\n";
        }
        else if (n > 0)
        {
            msg += $"\n同时删除截图缓存 {n} 张 / {mb} MB(截图存证记录仍保留在 index.jsonl)。\n";
            if (arch is not null)
            {
                msg += $"最近一次归档 {arch.Ts}({arch.Count} 张)之后新增的截图尚未归档。\n";
            }
            msg += "不可恢复, 如需留档请先点「保存日志」(保存会同时归档截图)。\n";
        }
        else
        {
            msg += "\n当前无截图缓存。\n";
        }

        // C3: 二次确认统一走 DialogService(属主解析链=原 owner 兜底分支同款)
        if (!DialogService.Confirm(msg, "清除日志", warning: true))
        {
            return;
        }

        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            StatusText = "服务尚未就绪, 未清除(服务端缓冲与本页显示保持不变)";
            return;
        }
        var r = await proxy.LogClearAsync();
        if (r.Success && r.Value?.Ok == true)
        {
            // 三同步: 服务端已清(缓冲+磁盘+缓存像素) → 回 next=0 → 游标复位 + 本页显示清空
            _main.Session.Logs.Reset(r.Value.Next);
            ClearDisplay();
            StatusText = $"已清除服务端日志缓冲与磁盘备份(next={r.Value.Next}), 本页显示一并清空。";
            await _main.RefreshStatusNowAsync();   // 清空后缓存/归档状态已变, 顶栏按新状态刷新
        }
        else
        {
            // 失败(D4 对齐 webui.html clearLog 892-928): 游标不复位(服务端下标未归零), 服务端缓冲与
            // LogStore 镜像保持不变 —— LogStore 是服务端缓冲的本地镜像, 服务端未清镜像亦不清;
            // 但本页显示仍清空 + 状态照常刷新(webui 在 try/catch 外无条件清显示并 await refreshStatus,
            // 提示语即"(服务端缓冲保持不变, 本页显示仍将清空)"; webui 的 logChunks 兼任显示缓冲故一并清空,
            // 原生显示(Lines)与缓冲(LogStore)分离, 各随其源)。
            StatusText = $"清除服务端日志失败: {r.Error}(服务端缓冲保持不变, 本页显示仍将清空)";
            ClearDisplay();
            await _main.RefreshStatusNowAsync();
        }
    }
}
