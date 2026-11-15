using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using FAA.WpfGui.Models;
using FAA.WpfGui.Services;

/// <summary>失败提醒浮层 VM —— 契约8(与 webui.html:555-587 逐条对齐):
///   /api/failures 增量游标(失败 id > after), 有新失败即弹出;
///   ✕ 关闭只是收起(不清游标不清列表), 新失败会再次弹出; 「已知悉」调 failures_clear。</summary>
namespace FAA.WpfGui.ViewModels;

public partial class FailuresViewModel : ObservableObject
{
    private readonly MainViewModel _main;
    private long _cursor;                       // 已提示到的失败 id 游标(webui failSeen)
    private bool _polling;

    public FailuresViewModel(MainViewModel main)
    {
        _main = main;
    }

    public ObservableCollection<FailureItem> Items { get; } = new();

    /// <summary>浮层可见(新失败即 true; ✕ 收起为 false; 已知悉清空并收起)。</summary>
    [ObservableProperty]
    private bool _isVisible;

    public string CountText => Items.Count.ToString();

    /// <summary>增量拉取(挂在状态轮询之后, webui.html:498 refreshFailures 同款); 防重入。</summary>
    public async Task PollAsync()
    {
        if (_polling)
        {
            return;
        }
        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            return;
        }
        _polling = true;
        try
        {
            var r = await proxy.GetFailuresAsync(_cursor);
            if (!r.Success || r.Value is null)
            {
                return;   // 服务不可达: 游标保留(webui 同语义)
            }
            _cursor = r.Value.Next;
            if (r.Value.Items is { Length: > 0 })
            {
                foreach (var it in r.Value.Items)
                {
                    Items.Add(it);
                }
                OnPropertyChanged(nameof(CountText));
                IsVisible = true;   // 新失败即弹(收起过也会再弹)
            }
        }
        finally
        {
            _polling = false;
        }
    }

    /// <summary>
    /// SSE failures 批量事件直达浮层(批 21 修复; 与 PollAsync 并存)。
    /// data={items,next} 与 GET /api/failures 同形: 逐条入列(沿用 id 游标去重), 游标推进到服务端 next
    /// (next ≥ 末条 id: 服务端 _FAIL_SEQ 全局序号, 含已被 clear 的空档 —— 以 next 为准防重放)。
    /// </summary>
    public void OnSseFailures(FailuresPage page)
    {
        foreach (var it in page.Items)
        {
            AddSseFailure(it);
        }
        if (page.Next > _cursor)
        {
            _cursor = page.Next;   // 与 /api/failures 的 id 游标同一账本(空档/清空后不重放旧 id)
        }
        OnPropertyChanged(nameof(CountText));
    }

    /// <summary>
    /// SSE failure 单数事件直达浮层(兼容保留; 与 PollAsync 并存)。
    /// 去重: 轮询可能先把同一 id 拉进来(状态轮询 1.5s 与 SSE 推送竞争), id 不大于已提示游标即忽略。
    /// </summary>
    public void OnSseFailure(FailureItem f) => AddSseFailure(f);

    /// <summary>单条入列: id 游标去重 → 推进游标 → 入列 → 弹浮层。批量/单数两入口共用同一账本。</summary>
    private void AddSseFailure(FailureItem f)
    {
        if (f.Id <= _cursor)
        {
            return;   // 已提示过(轮询先到), 不重复弹
        }
        _cursor = f.Id;          // SSE 推送同样推进游标(与 /api/failures 的 id 游标同一账本)
        Items.Add(f);
        OnPropertyChanged(nameof(CountText));
        IsVisible = true;        // 新失败即弹
    }

    /// <summary>✕ 关闭 = 只收起(webui.html:582: fail-pop hidden, 不清列表/游标)。</summary>
    [RelayCommand]
    private void Collapse()
    {
        IsVisible = false;
    }

    /// <summary>「已知悉，清空列表」→ POST /api/failures_clear + 清列表收起(webui.html:583-587)。</summary>
    [RelayCommand]
    private async Task AcknowledgeAsync()
    {
        var proxy = _main.Session.Proxy;
        if (proxy is not null)
        {
            await proxy.FailuresClearAsync();   // 服务端清空; 游标不回退(mock/真实一致)
        }
        Items.Clear();
        OnPropertyChanged(nameof(CountText));
        IsVisible = false;
    }
}
