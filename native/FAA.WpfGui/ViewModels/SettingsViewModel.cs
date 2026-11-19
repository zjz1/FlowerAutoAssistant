using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using FAA.WpfGui.Models;
using FAA.WpfGui.Services;

namespace FAA.WpfGui.ViewModels;

/// <summary>
/// 设置页 ViewModel —— 连接 / 识别 / 界面 三组卡片(对照 webui.html 右栏「连接设置/识别设置/界面设置」面板)。
/// 契约6(W1 口径): 识别设置的回显**唯一来源** = GET /api/daily(log_click_pos/use_cache_pos/ocr_threads,
/// webui.py:994-996; W1 已删 /api/config 死端点); 保存走 POST /api/set_config 单键(19 键白名单过滤在 FaaProxy)。
/// 界面卡片三项(confirm_page_close / minimize_to_tray / fail_cache_prompt_mb)的回显来自 /api/status —— 与 webui.html:447,490
/// 同口径(/api/daily 不含这两键); 保存同走 set_config 白名单。
/// 每控件改动即时保存并显示「已保存 ✓」(2s 自动清空)。
/// </summary>
public partial class SettingsViewModel : ObservableObject
{
    private readonly MainViewModel _main;
    private int _saveMsgSeq;

    /// <summary>回显装载中: /api/daily 或 /api/status 回显写入时不触发保存(契约6: 回显不回写)。</summary>
    private bool _loadingEcho;

    /// <summary>用户正在文本框里编辑(状态轮询的回显不得覆盖输入中内容; webui.html:490,666 activeElement 同款防抢)。</summary>
    private bool _threadsEditing;
    private bool _thresholdEditing;

    public SettingsViewModel(MainViewModel main)
    {
        _main = main;
        // A3/B3: 服务连接态变化 → 刷新「关闭服务」与「重启后端」入口可用性(按钮随命令 CanExecute 自动禁用/启用)
        _main.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(MainViewModel.IsServiceConnected))
            {
                ShutdownServiceCommand.NotifyCanExecuteChanged();
                RestartBackendCommand.NotifyCanExecuteChanged();
            }
        };
    }

    // ==================== 卡片一: 连接 ====================

    [ObservableProperty]
    private string _connStateText = "未连接";

    [ObservableProperty]
    private string _resolutionText = "待读取";

    /// <summary>连接卡片静态展示(与 webui.html:218-224 一致, ADB 路径/连接地址为固定展示值)。</summary>
    public string ConnConfig => "MuMu 模拟器";
    public string AdbPath => "D:\\Program Files\\Netease\\MuMu";
    public string ConnectAddr => "127.0.0.1:16384";

    [RelayCommand]
    private async Task ConnectAsync()
    {
        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            SaveStatusText = "服务未就绪";
            return;
        }
        ConnStateText = "连接中…";
        var r = await proxy.ConnectAsync();
        ConnStateText = r.Success && r.Value?.Ok == true ? "已连接" : $"连接失败: {Trunc(r.Error)}";
        await _main.RefreshStatusNowAsync();
    }

    /// <summary>
    /// 打开模板标注工具(批 21): 用系统默认浏览器开 &lt;当前baseurl&gt;tpltool(tpltool 过渡期方案 ——
    /// 原生标注页未建, 过渡期沿用服务端 web 页)。服务未就绪时兜底 http://127.0.0.1:8765/tpltool(缺省口)。
    /// UseShellExecute=true → 按 URL 协议交给系统默认浏览器; 打不开(无浏览器关联等)原生框如实报。
    /// </summary>
    [RelayCommand]
    private void OpenTplTool()
    {
        var baseUrl = _main.Session.Proxy?.BaseUrl ?? "http://127.0.0.1:8765/";
        var url = baseUrl + "tpltool";
        try
        {
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(url)
            {
                UseShellExecute = true,   // URL 必须走 shell: 由系统按默认浏览器分发
            });
            Services.DebugTrace.Log($"settings.tpltool: opened {url}");
        }
        catch (Exception ex)
        {
            Services.DebugTrace.Log($"settings.tpltool: FAIL {ex.GetType().Name}: {ex.Message}");
            DialogService.Warn(
                $"无法在系统浏览器中打开模板标注工具:\n{url}\n\n{ex.GetType().Name}: {ex.Message}",
                "FAA 原生窗口");
        }
    }

    /// <summary>「关闭服务」入口可用性(A3): 仅服务已连接(托管或外部实例)时可用, 判据在 MainViewModel。</summary>
    public bool CanShutdownService => _main.IsServiceConnected;

    /// <summary>关闭服务(A3): 二次确认/调用/刷新在 MainViewModel.ShutdownServiceAsync(与托盘菜单共用同一入口)。</summary>
    [RelayCommand(CanExecute = nameof(CanShutdownService))]
    private Task ShutdownServiceAsync() => _main.ShutdownServiceAsync();

    /// <summary>「重启后端」可用性(B3): 仅服务由本窗口托管(free 自起)时可用 —— 外部实例不受本程序
    /// 托管(Host 无进程句柄), 无从重启(强起会同端口撞车)。**不再要求已连接** —— 服务不可达
    /// 正是需要重启的时候; 重启执行中禁用防连点。</summary>
    public bool CanRestartBackend => _main.Session.OwnsService && !_restarting;

    private bool _restarting;

    /// <summary>重启后端(B3): 调此前零调用的 FaaProcessHost.RestartAsync(优雅停 → 同端口重探测自起;
    /// 引擎重载需 10-30s) → 成功后状态刷新(轮询恢复, 徽章/按钮自动回到可用态); 失败弹框如实报错。
    /// 2026-11-19: 服务不可达时也可点(这是恢复入口); 仅执行期间禁用, 防连点。</summary>
    [RelayCommand(CanExecute = nameof(CanRestartBackend))]
    private async Task RestartBackendAsync()
    {
        _restarting = true;
        RestartBackendCommand.NotifyCanExecuteChanged();
        ConnStateText = "重启中…(引擎重载需 10-30s)";
        Services.DebugTrace.Log("settings.restart-backend: begin");
        try
        {
            var r = await _main.Session.Host.RestartAsync();
            Services.DebugTrace.Log($"settings.restart-backend: success={r.Success} err={(r.Success ? "" : r.Error)}");
            if (!r.Success)
            {
                ConnStateText = "重启失败";
                DialogService.Warn($"重启后端失败:\n{r.Error}", "FAA 原生窗口");
                return;
            }
            await _main.RefreshStatusNowAsync();   // 完成后状态刷新
        }
        finally
        {
            _restarting = false;
            RestartBackendCommand.NotifyCanExecuteChanged();
        }
    }

    // ==================== 环境检查(1.0 #14) ====================

    private bool _envChecking;

    /// <summary>环境检查执行中禁用按钮(防连点); 不依赖服务连接态(它自己起一次性子进程)。</summary>
    public bool CanCheckEnv => !_envChecking;

    /// <summary>环境检查: 起一次 `--check-env` 子进程并展示结果(不启服务/不占端口)。</summary>
    [RelayCommand(CanExecute = nameof(CanCheckEnv))]
    private async Task CheckEnvAsync()
    {
        _envChecking = true;
        CheckEnvCommand.NotifyCanExecuteChanged();
        try
        {
            var text = await EnvCheckService.RunAsync();
            DialogService.Info(text, "环境检查");
        }
        finally
        {
            _envChecking = false;
            CheckEnvCommand.NotifyCanExecuteChanged();
        }
    }

    // ==================== 诊断包导出(1.0 #16) ====================

    private bool _diagExporting;

    public bool CanExportDiag => !_diagExporting;

    /// <summary>导出脱敏诊断包(1.0 #16): 另存为 zip → 调后端 --export-diag → 完成后定位文件。</summary>
    [RelayCommand(CanExecute = nameof(CanExportDiag))]
    private async Task ExportDiagAsync()
    {
        var dlg = new Microsoft.Win32.SaveFileDialog
        {
            Title = "导出脱敏诊断包",
            FileName = $"FAA-diag-{DateTime.Now:yyyyMMdd-HHmmss}.zip",
            Filter = "Zip (*.zip)|*.zip",
            DefaultExt = ".zip",
            AddExtension = true,
        };
        if (dlg.ShowDialog() != true)
        {
            return;
        }
        _diagExporting = true;
        ExportDiagCommand.NotifyCanExecuteChanged();
        try
        {
            var text = await EnvCheckService.ExportDiagAsync(dlg.FileName);
            DebugTrace.Log($"settings.export-diag: {text}");
            DialogService.Info(text + "\n\n包内不含截图；账号尾号/绝对路径/ADB 路径已脱敏。",
                "导出诊断包");
            if (File.Exists(dlg.FileName))
            {
                try { Process.Start("explorer.exe", $"/select,\"{dlg.FileName}\""); } catch { /* 定位失败不影响导出 */ }
            }
        }
        finally
        {
            _diagExporting = false;
            ExportDiagCommand.NotifyCanExecuteChanged();
        }
    }

    // ==================== 卡片二: 识别(契约6 唯一回显来源 /api/daily) ====================
    [ObservableProperty]
    private bool _logClickPos;

    partial void OnLogClickPosChanged(bool value) => SaveIfNotEchoing("log_click_pos", value);

    [ObservableProperty]
    private bool _useCachePos;

    partial void OnUseCachePosChanged(bool value) => SaveIfNotEchoing("use_cache_pos", value);

    [ObservableProperty]
    private string _ocrThreadsText = "2";

    /// <summary>OCR 线程数提交(TextBox LostFocus 调用)。D2 对齐 webui(webui.html:758-764 实读核对):
    ///   服务端/前端语义 = Math.max(0, Math.min(8, parseInt(v,10) || 0)) —— 非数字/负数钳 0、&gt;8 钳 8,
    ///   回写输入框并照常提交服务端; 不再本地回退旧值(2026-11-10 评审登记的「非法输入不通知服务端」偏差就此修正)。
    ///   LoadingEcho 守卫保留(回显不回写, 契约6); 与服务端现值一致时免提交(no-op, 等价 webui change 事件只在值变时触发)。
    ///   N02(batch-06): 解析/钳制计算提纯为 SettingsClamps.OcrThreads(等价迁移; 提交判序与回写行为逐支保留)。</summary>
    public void CommitOcrThreads()
    {
        _threadsEditing = false;
        var (clamped, v, numeric) = SettingsClamps.OcrThreads(OcrThreadsText);
        if (!numeric)
        {
            OcrThreadsText = "0";
        }
        if (clamped != v)
        {
            OcrThreadsText = clamped.ToString();   // 钳制后回写输入框(webui 同款 ev.target.value = v)
        }
        if (LoadingEcho || clamped == _lastThreads)
        {
            return;   // 回显装载中不回写; 与现值一致免提交
        }
        _lastThreads = clamped;
        SaveIfNotEchoing("ocr_threads", clamped);
    }

    public void OnThreadsEditingChanged(bool editing)
    {
        _threadsEditing = editing;
        if (!editing)
        {
            CommitOcrThreads();
        }
    }

    private int _lastThreads = 2;

    // ==================== 卡片三: 界面(回显来自 /api/status, webui 同口径) ====================

    [ObservableProperty]
    private bool _confirmPageClose = true;

    partial void OnConfirmPageCloseChanged(bool value) => SaveIfNotEchoing("confirm_page_close", value);

    /// <summary>最小化自动收进托盘(默认关闭; 关闭时最小化保留在任务栏)。</summary>
    [ObservableProperty]
    private bool _minimizeToTray;

    partial void OnMinimizeToTrayChanged(bool value)
    {
        // 立即生效, 不等下一轮 /api/status; 回显装载时 SaveIfNotEchoing 会跳过回写。
        _main.Session.MinimizeToTray = value;
        SaveIfNotEchoing("minimize_to_tray", value);
    }

    [ObservableProperty]
    private string _thresholdText = "100";

    /// <summary>缓存提醒阈值提交(LostFocus): 非法或 <1 回退(webui.html:817 同规则; 服务端再钳 ≥1.0)。</summary>
    public void CommitThreshold()
    {
        _thresholdEditing = false;
        if (!double.TryParse(ThresholdText.Trim(), out var v) || v < 1.0)
        {
            RevertThreshold();
            return;
        }
        if (LoadingEcho || Math.Abs(v - _lastThreshold) < 0.001)
        {
            return;
        }
        _lastThreshold = v;
        ThresholdText = v.ToString("0.##");
        SaveIfNotEchoing("fail_cache_prompt_mb", v);
    }

    public void OnThresholdEditingChanged(bool editing)
    {
        _thresholdEditing = editing;
        if (!editing)
        {
            CommitThreshold();
        }
    }

    private double _lastThreshold = 100;

    private void RevertThreshold() => ThresholdText = _lastThreshold.ToString("0.##");

    // ==================== 保存与回显 ====================

    [ObservableProperty]
    private string _saveStatusText = "";

    /// <summary>保存状态行是否为失败消息(供 XAML 换失败色: 成功=OkBrush, 失败=ErrBrush)。</summary>
    [ObservableProperty]
    private bool _saveStatusIsError;

    /// <summary>识别卡片注释(webui.html:247-252 浓缩)。</summary>
    public string RecogNote =>
        "两项默认关闭。关闭时只认本次实时识别(OCR/模板/锚点/颜色), 认不到就如实失败, 绝不用知识库历史坐标盲点。\n" +
        "「使用缓存位置」只管自动学到的历史坐标; 流程里人工写死的兜底坐标仍生效。改动即时保存, 下次「开始一轮」生效。\n" +
        "「OCR 线程数」为每 ONNX 会话推理线程数(默认 2; 0=不限制即吃满全部物理核), 改后需重启服务生效(会话在引擎启动时创建)。";

    /// <summary>界面卡片注释(webui.html:261,266 浓缩)。</summary>
    public string UiNote =>
        "开启后, 关闭窗口会弹原生确认框防误触; 关掉后不再提醒。流程运行中即使设了不再提醒仍会强制确认(契约2)。\n" +
        "出错时的全量 OCR + 截图缓存在 data/fail_cache/(当场写盘, 跨服务重启保留), 系统不会自动删除; 只有打开时若\n" +
        "缓存 ≥ 本阈值才弹提醒由你选清理范围。清理只删图片, 存证记录永久保留在 index.jsonl。";

    private void SaveIfNotEchoing(string key, object? value)
    {
        Services.DebugTrace.Log($"settings.saveIfNotEchoing: key={key} loadingEcho={_loadingEcho}");
        if (_loadingEcho)
        {
            return;
        }
        _ = SaveKeyAsync(key, value);
    }

    private async Task SaveKeyAsync(string key, object? value)
    {
        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            Services.DebugTrace.Log("settings.save: proxy null");
            SaveStatusText = "服务未就绪, 未保存";
            return;
        }
        var r = await proxy.SetConfigAsync(new Dictionary<string, object?> { [key] = value });
        Services.DebugTrace.Log($"settings.save: key={key} success={r.Success} err={(r.Success ? "" : r.Error)}");
        if (r.Success && r.Value?.Ok == true)
        {
            SaveStatusText = "已保存 ✓";
            SaveStatusIsError = false;
        }
        else
        {
            SaveStatusText = $"保存失败: {Trunc(r.Error)}";
            SaveStatusIsError = true;
        }
        var seq = ++_saveMsgSeq;
        _ = ClearSaveStatusAfterDelayAsync(seq);
    }

    private async Task ClearSaveStatusAfterDelayAsync(int seq)
    {
        await Task.Delay(2000);
        if (seq == _saveMsgSeq)
        {
            SaveStatusText = "";
        }
    }

    /// <summary>识别设置回显(契约6 唯一来源 /api/daily); 服务就绪后调一次, 失败随状态轮询重试。</summary>
    public bool LoadingEcho => _loadingEcho;
    public bool EchoLoaded { get; private set; }

    public async Task LoadEchoAsync()
    {
        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            return;
        }
        var r = await proxy.GetDailyAsync();
        if (!r.Success || r.Value is null)
        {
            return;   // 下轮状态轮询重试(LoadEchoIfNeeded)
        }
        var d = r.Value;
        _loadingEcho = true;
        try
        {
            LogClickPos = d.LogClickPos;
            UseCachePos = d.UseCachePos;
            _lastThreads = d.OcrThreads;
            if (!_threadsEditing)
            {
                OcrThreadsText = d.OcrThreads.ToString();
            }
        }
        finally
        {
            _loadingEcho = false;
        }
        EchoLoaded = true;
    }

    public void LoadEchoIfNeeded()
    {
        if (!EchoLoaded)
        {
            _ = LoadEchoAsync();
        }
    }

    /// <summary>每轮 /api/status 后调用: 界面卡片回显 + 连接卡片展示 + 重试未完成的识别回显。</summary>
    public void OnStatusUpdated(StatusSnapshot s)
    {
        ConnStateText = s.Connected ? "已连接" : "未连接";
        ResolutionText = s.Screen is { Length: 2 } ? $"{s.Screen[0]}×{s.Screen[1]}" : "待读取";
        _loadingEcho = true;
        try
        {
            // confirm_page_close: /api/status 唯一回显源(webui.html:447,456 同款)
            ConfirmPageClose = s.ConfirmPageClose;
            MinimizeToTray = s.MinimizeToTray;
            if (!_thresholdEditing)
            {
                var thr = s.FailCache?.ThresholdMb ?? 100;
                _lastThreshold = thr;
                ThresholdText = thr.ToString("0.##");
            }
        }
        finally
        {
            _loadingEcho = false;
        }
        LoadEchoIfNeeded();
    }

    private static string Trunc(string s) => s.Length > 160 ? s[..160] : s;
}
