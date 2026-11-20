using System.Collections.ObjectModel;
using System.Collections.Specialized;
using System.ComponentModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using FAA.WpfGui.Models;
using FAA.WpfGui.Services;

namespace FAA.WpfGui.ViewModels;

/// <summary>模块设置面板里的一个控件行(switch/text, 形状=webui.py _daily 的 modules[].settings 元素)。</summary>
public partial class SettingVm : ObservableObject
{
    private readonly Func<SettingVm, Task> _save;

    public SettingVm(SettingItem src, Func<SettingVm, Task> save)
    {
        _save = save;
        Key = src.Key;
        Type = src.Type;
        Label = src.Label;
        Desc = src.Desc;
        if (Type == "switch")
        {
            _boolValue = src.Value.ValueKind == System.Text.Json.JsonValueKind.True
                         || (src.Value.ValueKind == System.Text.Json.JsonValueKind.String
                             && bool.TryParse(src.Value.GetString(), out var b) && b);
            _switchText = _boolValue ? "开" : "关";
        }
        else
        {
            // text 型: target_tail(string); JsonElement 兜底 ToString(字符串带引号时用 GetString)
            _textValue = src.Value.ValueKind == System.Text.Json.JsonValueKind.String
                ? src.Value.GetString() ?? ""
                : src.Value.ToString();
        }
    }

    public string Key { get; }
    public string Type { get; }
    public string Label { get; }
    public string Desc { get; }

    /// <summary>回显装载中: /api/daily 回显写入值时不触发保存(契约6: 回显只来自 /api/daily, 不回写)。</summary>
    public bool Loading { get; set; }

    [ObservableProperty]
    private bool _boolValue;

    partial void OnBoolValueChanged(bool value)
    {
        SwitchText = value ? "开" : "关";
        if (!Loading)
        {
            _ = _save(this);   // 改动即时保存(单键 set_config, webui.html:730-741 同语义)
        }
    }

    [ObservableProperty]
    private string _switchText = "关";

    [ObservableProperty]
    private string _textValue = "";

    partial void OnTextValueChanged(string value)
    {
        // 文本控件用 LostFocus 提交(对应 webui 的 change 事件): 不逐键保存
        if (!Loading && Type == "text")
        {
            _ = _save(this);
        }
    }
}

/// <summary>任务列表里的一行(/api/daily modules[] 元素 + 客户端勾选状态, 默认全勾=webui.html:662)。</summary>
public partial class HomeModuleVm : ObservableObject
{
    public HomeModuleVm(DailyModule m)
    {
        Id = m.Id;
        Name = m.Name;
        Flow = m.Flow ?? "";
        foreach (var s in m.Settings ?? [])
        {
            // 2026-11-20: 种植增强的选种/数量/购买键统一在「设置 → 种植」卡片配置,
            // 模块 ⚙ 面板不再重复渲染(避免 text 控件误展示 enum/int)。
            if (m.Id == "plant" && HiddenPlantKeys.Contains(s.Key))
            {
                continue;
            }
            Settings.Add(new SettingVm(s, Save));
        }
        HasSettings = Settings.Count > 0;
    }

    private static readonly HashSet<string> HiddenPlantKeys = new(StringComparer.Ordinal)
    {
        "plant_flower_type", "plant_seed_mode", "plant_seed_preset",
        "plant_count_mode", "plant_count", "plant_buy_missing", "plant_auto_buy",
    };

    public string Id { get; }
    public string Name { get; }
    public string Flow { get; }
    public bool HasSettings { get; }

    public ObservableCollection<SettingVm> Settings { get; } = new();

    /// <summary>保存回调由 HomeViewModel 注入(经构造后再接上, 这里用字段转交)。</summary>
    private Func<SettingVm, Task>? _saveSink;
    private Task Save(SettingVm s) => _saveSink?.Invoke(s) ?? Task.CompletedTask;
    internal void AttachSaveSink(Func<SettingVm, Task> sink) => _saveSink = sink;

    /// <summary>勾选状态(客户端持有; /api/daily 不回显勾选, 默认全勾)。</summary>
    [ObservableProperty]
    private bool _isChecked = true;

    /// <summary>契约1: 本模块正在运行 → 勾选与 ⚙ 锁定(/api/status current_module 比对模块 id)。</summary>
    [ObservableProperty]
    private bool _isRunningModule;

    /// <summary>勾选框可用性 = 非运行中(供绑定, 免转换器)。</summary>
    public bool CanToggle => !IsRunningModule;

    /// <summary>⚙ 可用性 = 非运行中(webui.html:681: 运行中 gear disabled; 无设置仍可点开看说明)。</summary>
    public bool GearEnabled => !IsRunningModule;

    /// <summary>⚙ 悬停说明(webui.html:681 title 三态: 运行中 / 设置 / 无独立设置)。</summary>
    public string GearTip => IsRunningModule
        ? " · 运行中, 设置已锁定"
        : HasSettings ? " · 设置" : " · 无独立设置(点击查看说明)";

    partial void OnIsRunningModuleChanged(bool value)
    {
        OnPropertyChanged(nameof(CanToggle));
        OnPropertyChanged(nameof(GearEnabled));
        OnPropertyChanged(nameof(GearTip));
    }
}

/// <summary>
/// 主页 ViewModel —— 对照 FlowerAutoAssistant/webui.html「使用界面」区块:
///   任务列表(/api/daily)勾选 + ⚙ 设置面板(改动即时 set_config) + 全选/清空/反选 +
///   开始一轮(/api/run_daily, body 带 finish_action=完成后动作) + 停止(/api/stop) + 连接设置组。
/// 契约1 —— current_module 运行中: 该模块勾选/⚙/面板锁定, 面板顶部锁定横幅。
/// 契约6 —— 面板回显唯一来源 /api/daily(modules[].settings); 保存走 /api/set_config 单键白名单。
/// 「完成后」下拉(批 21 复活原页死控件): none=无动作 / close_client=完成后关闭客户端;
///   开始一轮时随 body.finish_action 提交(旧后端忽略未知键=安全), 变更即时 set_config(finish_action)
///   持久化 —— 旧后端白名单无此键会被静默丢弃(引擎批 22 合并后生效, 见 PersistFinishActionAsync)。
/// </summary>
public partial class HomeViewModel : ObservableObject
{
    private readonly MainViewModel _main;
    private int _saveMsgSeq;   // 「已保存 ✓」2s 自动清空的序号(新消息作废旧定时)

    public HomeViewModel(MainViewModel main)
    {
        _main = main;
        PlantSettings = new PlantSettingsViewModel(main);
        Modules.CollectionChanged += OnModulesChanged;
    }

    /// <summary>种植模块聚合设置（2026-11-20：分组面板，仅 plant 模块显示）。</summary>
    public PlantSettingsViewModel PlantSettings { get; }

    public ObservableCollection<HomeModuleVm> Modules { get; } = new();

    [ObservableProperty]
    private HomeModuleVm? _selectedModule;

    [ObservableProperty]
    private string _statusText = "";

    /// <summary>⚙ 面板保存状态行("已保存 ✓" / "保存失败: …"), 2s 自动清空。</summary>
    [ObservableProperty]
    private string _saveStatusText = "";

    /// <summary>保存状态行是否为失败消息(供 XAML 换失败色: 成功=OkBrush, 失败=ErrBrush)。</summary>
    [ObservableProperty]
    private bool _saveStatusIsError;

    /// <summary>连接后首次装载 /api/daily; 失败留空并随状态轮询自动重试(LoadIfNeeded)。</summary>
    public bool Loaded { get; private set; }

    /// <summary>LoadAsync 在跑的标志: 状态轮询的 LoadIfNeeded 与手动重试不得并发重入(防 Clear/Add 交错重复行)。</summary>
    private bool _loadingDaily;

    // ---- 锁定横幅(契约1) ----

    public string LockBannerText => SelectedModule is { } m
        ? $"🔒 模块「{m.Name}」正在运行, 设置已锁定 —— 本次运行按启动时配置执行, 结束后自动解锁。"
        : "";

    partial void OnSelectedModuleChanged(HomeModuleVm? value)
    {
        OnPropertyChanged(nameof(LockBannerText));
        OnPropertyChanged(nameof(HasSelectedModule));
        OnPropertyChanged(nameof(IsPlantModule));
    }

    public bool HasSelectedModule => SelectedModule is not null;

    /// <summary>当前选中模块是否为种植（控制分组设置面板可见性）。</summary>
    public bool IsPlantModule => SelectedModule?.Id == "plant";

    // ---- 连接设置组(静态展示值与 webui.html:218-224 一致; 状态值来自 /api/status 轮询) ----

    public string ConnConfig => "MuMu 模拟器";
    public string AdbPath => "D:\\Program Files\\Netease\\MuMu";
    public string ConnectAddr => "127.0.0.1:16384";

    /// <summary>连接按钮文案(webui.html:493-497: 已连接→primary 文案)。</summary>
    [ObservableProperty]
    private string _connectButtonText = "连接";

    /// <summary>分辨率展示(状态徽章同源; webui.html:466-467)。</summary>
    [ObservableProperty]
    private string _resolutionText = "待读取";

    // ---- 数据装载 ----

    public async Task LoadAsync()
    {
        if (_loadingDaily)
        {
            return;   // 已有装载在跑(上一轮还没回来), 不重入
        }
        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            DebugTrace.Log("home.load: proxy null, skip");
            return;
        }
        _loadingDaily = true;
        try
        {
            var r = await proxy.GetDailyAsync();
            DebugTrace.Log($"home.load: success={r.Success} err={(r.Success ? "" : r.Error)}");
            if (!r.Success || r.Value is null)
            {
                StatusText = $"加载任务列表失败: {Trunc(r.Error)}(将在状态轮询后自动重试)";
                return;
            }
            Modules.Clear();
            foreach (var m in r.Value.Modules)
            {
                var vm = new HomeModuleVm(m);
                vm.AttachSaveSink(SaveSettingAsync);
                Modules.Add(vm);
            }
            Loaded = true;
            StatusText = $"已载入编排「{r.Value.Name}」: {Modules.Count} 个任务";
            await PlantSettings.LoadAsync(proxy, r.Value);
            RefreshRunningLock();
            StartCommand.NotifyCanExecuteChanged();
        }
        finally
        {
            _loadingDaily = false;
        }
    }

    /// <summary>未装载成功时随每轮状态轮询重试(服务端短暂不可达的兜底)。</summary>
    public void LoadIfNeeded()
    {
        if (!Loaded)
        {
            _ = LoadAsync();
        }
    }

    /// <summary>每轮 /api/status 后调用: 刷新契约1 锁定态与开始按钮可用性 + 连接组展示。</summary>
    public void OnStatusUpdated(StatusSnapshot s)
    {
        ConnectButtonText = s.Connected ? "已连接" : "连接";
        ResolutionText = s.Screen is { Length: 2 } ? $"{s.Screen[0]}×{s.Screen[1]}" : "待读取";
        RefreshRunningLock();
        StartCommand.NotifyCanExecuteChanged();
        LoadIfNeeded();
    }

    /// <summary>契约1: current_module === 模块 id(引擎 run_daily 维护, ocr_engine.py:4308)。</summary>
    private void RefreshRunningLock()
    {
        var runningId = _main.Session.RunningModule;
        foreach (var m in Modules)
        {
            m.IsRunningModule = runningId is not null && m.Id == runningId;
        }
        OnPropertyChanged(nameof(LockBannerText));
        OnPropertyChanged(nameof(AnyModuleRunning));
        OnPropertyChanged(nameof(NotRunning));
        // B5: 全选/清空/反选三命令随运行态灰显/恢复(CanExecute 守卫见 NotRunning)
        SelectAllCommand.NotifyCanExecuteChanged();
        ClearAllCommand.NotifyCanExecuteChanged();
        InvertSelectionCommand.NotifyCanExecuteChanged();
    }

    // ---- 勾选批量操作(webui.html:743-745) ----

    /// <summary>B5 守卫: 有模块运行中(契约1, 即任一 HomeModuleVm.IsRunningModule 的数据源
    /// Session.RunningModule 非空)时全选/清空/反选一律灰显 —— 运行中批量改勾选会造成
    /// 列表展示与本轮实跑错位, 故运行中禁改(经 CanExecute 灰显; 用 RunningModule 而非
    /// Modules.Any(IsRunningModule), 防 current_module 为列表外 id 时漏判)。</summary>
    public bool AnyModuleRunning => _main.Session.RunningModule is not null;

    /// <summary>CanExecute 用正向条件：空闲才允许批量改勾选（RelayCommand 不能直接取反）。</summary>
    public bool NotRunning => !AnyModuleRunning;

    [RelayCommand(CanExecute = nameof(NotRunning))]
    private void SelectAll()
    {
        foreach (var m in Modules)
        {
            m.IsChecked = true;
        }
    }

    [RelayCommand(CanExecute = nameof(NotRunning))]
    private void ClearAll()
    {
        foreach (var m in Modules)
        {
            m.IsChecked = false;
        }
    }

    [RelayCommand(CanExecute = nameof(NotRunning))]
    private void InvertSelection()
    {
        foreach (var m in Modules)
        {
            m.IsChecked = !m.IsChecked;
        }
    }

    // ---- ⚙ 面板 ----

    [RelayCommand]
    private void OpenModule(HomeModuleVm? module)
    {
        if (module is not null)
        {
            SelectedModule = module;
        }
    }

    /// <summary>⚙ 面板控件改动 → 单键 /api/set_config(契约6: 19 键白名单在 FaaProxy 内过滤)。</summary>
    private async Task SaveSettingAsync(SettingVm s)
    {
        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            SaveStatusText = "服务未就绪, 未保存";
            return;
        }
        object? value = s.Type == "switch" ? s.BoolValue : s.TextValue;
        var r = await proxy.SetConfigAsync(new Dictionary<string, object?> { [s.Key] = value });
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

    // ---- 完成后动作(批 21) ----

    /// <summary>
    /// 完成后动作: none=无动作(缺省) / close_client=完成后关闭客户端。
    /// 「开始一轮」时随 POST /api/run_daily body.finish_action 提交; 变更即时经 /api/set_config(finish_action) 持久化。
    /// ⚠ 旧后端 set_config 白名单无此键 → 保存请求被静默丢弃且仍回 ok:true(无法在客户端辨识),
    ///   即持久化暂不保证落地(如实降级); body.finish_action 每轮照带, 引擎批 22 合并后两端一齐生效。
    /// </summary>
    [ObservableProperty]
    private string _finishAction = "none";

    partial void OnFinishActionChanged(string value)
    {
        if (value is not ("none" or "close_client"))
        {
            return;   // 只认两档(防御); 非法值不持久化不提交
        }
        _ = PersistFinishActionAsync(value);
    }

    /// <summary>finish_action 持久化(单键 set_config; 旧后端静默丢弃=仅随请求携带, 注释见 FinishAction)。</summary>
    private async Task PersistFinishActionAsync(string value)
    {
        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            DebugTrace.Log($"home.finish: proxy null, {value} 只在会话内生效");
            return;   // 服务未就绪: 会话内仍生效, 落盘等连接后用户再改动时补
        }
        var r = await proxy.SetConfigAsync(new Dictionary<string, object?> { ["finish_action"] = value });
        DebugTrace.Log($"home.finish: persist finish_action={value} success={r.Success} err={(r.Success ? "" : r.Error)}");
        if (!r.Success)
        {
            // 只有传输层失败可见(旧后端对未知键回 ok:true); 本轮开始仍会照带 body.finish_action
            StatusText = $"完成后动作保存失败: {Trunc(r.Error)}(不影响本轮提交)";
        }
    }

    // ---- 开始 / 停止 ----

    public bool CanStart => !_main.Session.IsRunning && !_starting && Modules.Any(m => m.IsChecked);

    /// <summary>提交中标志: run_daily 的 await 期间 Session.IsRunning 尚未翻转, 用它挡住快速双击的第二个 POST(409)。</summary>
    private bool _starting;

    [RelayCommand(CanExecute = nameof(CanStart))]
    private async Task StartAsync()
    {
        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            return;
        }
        var sel = Modules.Where(m => m.IsChecked).Select(m => m.Id).ToArray();
        if (sel.Length == 0)
        {
            StatusText = "请至少勾选一个任务";
            return;
        }
        // 2026-11-20: 运行前统一确认（一个窗口汇总 开启/关闭/风险；替代原稀有单独确认）
        var pf = await proxy.GetPreflightAsync(sel);
        if (pf.Success && pf.Value is not null)
        {
            if (!DialogService.ConfirmPreflight(pf.Value.Text))
            {
                StatusText = "已取消运行";
                return;
            }
        }
        else if (!DialogService.Confirm(
                     $"无法获取运行前确认信息（{Trunc(pf.Error)}），是否继续？",
                     "提示", warning: true))
        {
            StatusText = "已取消运行";
            return;
        }
        _starting = true;                    // 提交瞬间即禁用按钮(webui.html:825 同语义)
        StartCommand.NotifyCanExecuteChanged();
        StatusText = $"已提交 {sel.Length} 个任务, 后台运行中…";
        try
        {
            // body.finish_action=完成后动作(收尾方案 A1 键名对齐批 22): 旧后端忽略未知键=安全; 引擎批 22 合并后按此执行收尾
            var r = await proxy.RunDailyAsync(sel, "use", FinishAction);
            if (r.Success && r.Value?.Ok == true)
            {
                StatusText = $"开始: {r.Value.Started} ({r.Value.Count} 个任务)。查看运行日志请切到「运行日志」页。";
            }
            else
            {
                StatusText = $"无法运行: {Trunc(r.Error)}";
            }
            await _main.RefreshStatusNowAsync();
        }
        finally
        {
            _starting = false;
            StartCommand.NotifyCanExecuteChanged();
        }
    }

    [RelayCommand]
    private async Task StopAsync()
    {
        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            return;
        }
        StatusText = "正在请求停止当前流程…";
        var r = await proxy.StopAsync();
        if (r.Success && r.Value?.Ok == true)
        {
            StatusText = "已请求停止。当前流程会在最近一个安全点中断, 服务保持运行, 可重新「开始一轮」。";
        }
        else
        {
            StatusText = $"停止请求失败: {Trunc(r.Error)}";
        }
        await _main.RefreshStatusNowAsync();
    }

    // ---- 连接(webui.html:844-849 maa-connect) ----

    [RelayCommand]
    private async Task ConnectAsync()
    {
        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            StatusText = "服务未就绪";
            return;
        }
        StatusText = "正在连接设备…";
        var r = await proxy.ConnectAsync();
        StatusText = r.Success && r.Value?.Ok == true
            ? "连接成功(ADB 已连上模拟器)"
            : $"连接失败: {Trunc(r.Error)}";
        await _main.RefreshStatusNowAsync();
    }

    // ---- 杂项 ----

    private void OnModulesChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        if (e.NewItems is not null)
        {
            foreach (HomeModuleVm m in e.NewItems)
            {
                m.PropertyChanged += OnModulePropertyChanged;
            }
        }
        OnPropertyChanged(nameof(CanStart));
        StartCommand.NotifyCanExecuteChanged();
    }

    private void OnModulePropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(HomeModuleVm.IsChecked))
        {
            StartCommand.NotifyCanExecuteChanged();
        }
    }

    private static string Trunc(string s) => s.Length > 160 ? s[..160] : s;
}
