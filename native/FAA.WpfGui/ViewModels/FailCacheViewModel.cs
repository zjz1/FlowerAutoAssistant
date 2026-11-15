using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using FAA.WpfGui.Models;
using FAA.WpfGui.Services;

namespace FAA.WpfGui.ViewModels;

/// <summary>
/// 截图缓存(契约3 全条, 里程碑 94; 与 webui.html:473-492/773-820 对齐):
///   顶栏徽章常驻显示缓存 MB, exceed 时变红加粗(webui.html:481-483);
///   首次加载超阈值弹一次提醒模态(服务端 prompt 一次性标志, 刷新不重复弹, webui.html:414,491);
///   五选项: 全部/30天/7天/1天/暂不 → POST /api/fail_cache_clean; 清理只删像素,
///   index.jsonl 墓碑永留; 清理前 confirm、后反馈(removed/bytes/sessions/kept)。
/// </summary>
public partial class FailCacheViewModel : ObservableObject
{
    private readonly MainViewModel _main;

    /// <summary>模态是否已弹过(每应用运行一次; webui fcModalShown 页面生命周期同语义)。</summary>
    private bool _modalShown;

    public FailCacheViewModel(MainViewModel main)
    {
        _main = main;
    }

    // ==================== 顶栏徽章 ====================

    [ObservableProperty]
    private string _badgeText = "截图缓存 —";

    /// <summary>exceed: 超阈值 → 徽章变红加粗(webui.html:482-483)。</summary>
    [ObservableProperty]
    private bool _isExceed;

    /// <summary>徽章悬停提示(webui.html:484-487 同内容)。</summary>
    [ObservableProperty]
    private string _badgeTooltip = "故障存证截图缓存(出错时的全量OCR+截图, 供离线复核)";

    private double _mb;
    private int _count;

    // ==================== 提醒模态 ====================

    [ObservableProperty]
    private bool _isModalVisible;

    [ObservableProperty]
    private string _modalInfoText = "";

    /// <summary>每轮 /api/status 后调用: 徽章刷新 + 首载超阈值一次性弹模态。</summary>
    public void OnStatusUpdated(StatusSnapshot s)
    {
        var fc = s.FailCache;
        if (fc is null)
        {
            return;
        }
        _mb = fc.Mb;
        _count = fc.Count;
        BadgeText = $"截图缓存 {fc.Mb.ToString("0.0")}MB";
        IsExceed = fc.Exceed;
        var oldest = fc.Oldest is { Length: >= 8 }
            ? $"{fc.Oldest[..4]}-{fc.Oldest.Substring(4, 2)}-{fc.Oldest.Substring(6, 2)}"
            : fc.Oldest ?? "";
        BadgeTooltip = $"故障存证截图缓存 {fc.Mb.ToString("0.0")} MB / {fc.Count} 张 / {fc.Sessions} 个会话"
            + (fc.Oldest is not null ? $"，最早 {oldest}" : "")
            + $"（提醒阈值 {fc.ThresholdMb} MB）\n出错现场的全量 OCR + 截图（当场写盘, 不占运行内存; 跨重启保留）。";

        // 首载超阈值弹一次(服务端 _CACHE_PROMPT_PENDING 一次性标志; webui.html:491 fcModalShown)
        if (fc.Prompt && !_modalShown)
        {
            _modalShown = true;
            ModalInfoText = $"当前缓存: {fc.Mb.ToString("0.0")} MB / {fc.Count} 张 / {fc.Sessions} 个会话"
                + (fc.Oldest is not null ? $"，最早 {oldest}" : "")
                + $"（提醒阈值 {fc.ThresholdMb} MB）";
            IsModalVisible = true;
        }
    }

    // ==================== 清理(五选项) ====================

    /// <summary>mode: all|days; days: 30|7|1; none=暂不。按钮 CommandParameter 直接传 "all"/"30"/"7"/"1"/"none"。</summary>
    [RelayCommand]
    private async Task CleanAsync(string option)
    {
        if (option == "none")
        {
            IsModalVisible = false;   // 暂不清理
            return;
        }
        var mode = option == "all" ? "all" : "days";
        var days = option == "all" ? (int?)null : int.Parse(option);
        var label = option == "all" ? "全部" : $"{days} 天前";

        // D3: 确认文案改用**所选清理范围**的数字, 不再一律套整库数字+"中的一部分"(webui.html:795 原文
        // 也是整库数字, 属 webui 缺陷的照搬):
        //   全部 → 所选范围就是整库, 整库数字即删除量, 直接报数;
        //   N 天前 → 所选范围是子集, 客户端拿不到该范围的预清理数量(/api/status.fail_cache 与
        //   /api/fail_cache_info 都只有整库统计), 不虚构数字 —— 明示以服务端清理结果为准
        //   (清理完成提示会带回 removed/bytes/sessions/kept), 整库数字仅作上界参照。
        var scope = mode == "all"
            ? $"将删除缓存目录中的全部图片文件（约 {_mb.ToString("0.0")} MB / {_count} 张）。\n"
            : $"将删除缓存目录中 {days} 天前的图片文件（所选范围的具体数量以服务端清理结果为准；\n当前整库共 {_count} 张 / {_mb.ToString("0.0")} MB，仅作上界参照）。\n";
        var msg = $"确定清理缓存截图（{label}）？\n\n"
            + scope
            + "存证记录（时间/tag/全量OCR文本）会保留在 index.jsonl，清理动作也会写入运行日志。\n"
            + "不可恢复，如需留档请先点「保存日志」导出归档。";
        // C3: 二次确认/反馈统一走 DialogService(属主解析链=原 owner 兜底分支同款: 显式 owner > 可见主窗 > 无属主)
        if (!DialogService.Confirm(msg, "清理截图缓存", warning: true))
        {
            return;
        }

        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            DialogService.Warn("服务未就绪, 未清理。", "清理截图缓存");
            return;
        }
        var r = await proxy.FailCacheCleanAsync(mode, days);
        if (r.Success && r.Value?.Ok == true)
        {
            // 结果反馈(webui.html:800): 已清理 N 张 / X MB / S 个会话（保留 K 张）; 存证记录永留
            DialogService.Info(
                $"已清理 {r.Value.Removed} 张 / {(r.Value.Bytes / 1048576.0).ToString("0.0")} MB / {r.Value.Sessions} 个会话（保留 {r.Value.Kept} 张）。\n"
                + "存证记录仍保留在 index.jsonl。",
                "清理完成");
            IsModalVisible = false;
            await _main.RefreshStatusNowAsync();   // 徽章按清理后状态刷新
        }
        else
        {
            DialogService.Error($"清理失败: {r.Error}", "清理截图缓存");
        }
    }
}
