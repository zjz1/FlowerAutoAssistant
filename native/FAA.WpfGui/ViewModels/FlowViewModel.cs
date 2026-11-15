using System.Collections.ObjectModel;
using System.Text.Json;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using FAA.WpfGui.Models;
using FAA.WpfGui.Services;

namespace FAA.WpfGui.ViewModels;

/// <summary>流程下拉项(name + [编排] 后缀 = webui.html:596)。</summary>
public sealed record FlowItemVm(string Name, string File, bool HasModules)
{
    public string Display => Name + (HasModules ? " [编排]" : "");
}

/// <summary>知识库按钮行(name + 分类 tag + rel JSON + 均值样本; webui.html:615 kbRow)。</summary>
public sealed record KbButtonVm(string Name, string Category, string RelJson, int SampleN)
{
    public string RelText => RelJson + (SampleN > 1 ? " · 均" + SampleN : "");
}

/// <summary>知识库场景分组(折叠树节点; webui.html:625-627)。</summary>
public sealed class KbSceneVm
{
    public string Name { get; init; } = "";
    public int ButtonCount { get; init; }
    public string CategoriesSummary { get; init; } = "";
    public IReadOnlyList<KbButtonVm> Buttons { get; init; } = [];
    public bool IsExpanded { get; set; } = true;   // webui 初始 ▾ 展开, 点击折叠
}

/// <summary>关闭按钮库行(webui.html:630: name + 关闭按钮 tag + scene(通用) + type)。</summary>
public sealed record KbCloseButtonVm(string Name, string Scene, string Type);

/// <summary>
/// 流程页 ViewModel —— 对照 webui.html「测试界面」运行区 + 流程表 + 知识库:
///   流程下拉(/api/flows) + 运行单流程 POST /api/run {flow, mode:"use"}(webui.html:870-878) +
///   流程表(流程名/文件, webui.html:599-603) + 知识库面板(/api/kb 场景分组折叠树 + 分类 tag + 关闭按钮库, 607-650)。
/// </summary>
public partial class FlowViewModel : ObservableObject
{
    private readonly MainViewModel _main;

    public FlowViewModel(MainViewModel main)
    {
        _main = main;
    }

    // ==================== 流程下拉与运行 ====================

    public ObservableCollection<FlowItemVm> Flows { get; } = new();

    [ObservableProperty]
    private FlowItemVm? _selectedFlow;

    [ObservableProperty]
    private string _runStatusText = "";

    /// <summary>运行提交中(防双击第二个 /api/run)。</summary>
    private bool _runningFlow;

    public bool CanRun => SelectedFlow is not null && !_runningFlow;

    partial void OnSelectedFlowChanged(FlowItemVm? value) => StartCommand.NotifyCanExecuteChanged();

    [RelayCommand(CanExecute = nameof(CanRun))]
    private async Task StartAsync()
    {
        var proxy = _main.Session.Proxy;
        var flow = SelectedFlow;
        if (proxy is null || flow is null)
        {
            return;
        }
        _runningFlow = true;
        StartCommand.NotifyCanExecuteChanged();
        RunStatusText = $"正在提交运行「{flow.Name}」…";
        try
        {
            // webui.html:875 同语义: mode 固定 "use"
            var r = await proxy.RunAsync(flow.Name, "use");
            if (r.Success && r.Value?.Ok == true)
            {
                RunStatusText = $"已开始: {r.Value.Started}。运行日志见「运行日志」页。";
            }
            else
            {
                RunStatusText = $"无法运行: {Trunc(r.Error)}";
            }
            await _main.RefreshStatusNowAsync();
        }
        finally
        {
            _runningFlow = false;
            StartCommand.NotifyCanExecuteChanged();
        }
    }

    // ==================== 流程表 ====================

    public ObservableCollection<FlowItemVm> FlowTable { get; } = new();

    // ==================== 知识库 ====================

    public ObservableCollection<KbSceneVm> KbScenes { get; } = new();

    public ObservableCollection<KbCloseButtonVm> KbCloseButtons { get; } = new();

    [ObservableProperty]
    private string _kbSummaryText = "";

    [ObservableProperty]
    private string _kbStatusText = "尚未加载";

    // ==================== 装载 ====================

    public bool Loaded { get; private set; }

    private bool _loading;

    /// <summary>首次导航到本页时装载 flows + kb; 失败可重试(LoadIfNeeded)。</summary>
    public async Task LoadIfNeededAsync()
    {
        if (Loaded || _loading)
        {
            return;
        }
        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            return;
        }
        _loading = true;
        try
        {
            var flowsTask = proxy.GetFlowsAsync();
            var kbTask = proxy.GetKbAsync();
            await System.Threading.Tasks.Task.WhenAll(flowsTask, kbTask);

            var rf = flowsTask.Result;
            if (rf.Success && rf.Value?.Flows is not null)
            {
                Flows.Clear();
                FlowTable.Clear();
                foreach (var f in rf.Value.Flows)
                {
                    var vm = new FlowItemVm(f.Name ?? "", f.File ?? "", f.Modules is { Length: > 0 });
                    Flows.Add(vm);
                    FlowTable.Add(vm);
                }
                if (SelectedFlow is null && Flows.Count > 0)
                {
                    SelectedFlow = Flows[0];   // webui 默认选中第一项
                }
            }
            else
            {
                RunStatusText = $"加载流程列表失败: {Trunc(rf.Error)}";
            }

            var rk = kbTask.Result;
            if (rk.Success && rk.Value is not null)
            {
                ParseKb(rk.Value);
            }
            else
            {
                KbStatusText = $"加载知识库失败: {Trunc(rk.Error)}";
            }

            Loaded = Flows.Count > 0 || KbScenes.Count > 0;
        }
        finally
        {
            _loading = false;
        }
    }

    /// <summary>解析 /api/kb 并落地展示(两层嵌套 场景→按钮(场景名排序, webui.html:619);
    /// 无 scenes 键时按旧扁平格式回退(634-643: 顶层键=按钮名, 值含 category/rel))。
    /// N02(batch-06): 解析提纯为 KbParser.Parse(逐行等价迁移, 逐分支对照 webui.html:619-643);
    /// 本方法只保留集合装配与状态文本副作用 —— 先算后清, 解析异常路径下不清旧展示(解析全 ValueKind
    /// 守卫, 异常不可达; 原实现为「先清后算」)。</summary>
    private void ParseKb(KbData d)
    {
        var r = KbParser.Parse(d);
        KbScenes.Clear();
        foreach (var s in r.Scenes)
        {
            KbScenes.Add(s);
        }
        KbCloseButtons.Clear();
        foreach (var cb in r.CloseButtons)
        {
            KbCloseButtons.Add(cb);
        }
        KbSummaryText = r.SummaryText;
        KbStatusText = r.StatusText;
    }

    private static string Trunc(string s) => s.Length > 160 ? s[..160] : s;
}
