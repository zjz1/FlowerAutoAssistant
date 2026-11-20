using System.Windows;
using System.Windows.Controls;
using FAA.WpfGui.ViewModels;

namespace FAA.WpfGui.Views;

/// <summary>
/// 设置页代码后置: 只做两个文本框的"编辑中"标记 ——
///   状态轮询的回显不得覆盖用户正在输入的内容(webui.html:490 activeElement 同款防抢);
///   失焦即提交(LostFocus=webui change 语义), 解析/钳制/保存都在 SettingsViewModel。
/// D1: 焦点事件改为**构造期一次性订阅** —— 原实现挂在 OnLoaded 里每次装载都 += 匿名委托, 页面装载 N 次
///   就重复注册 N 份 → 失焦提交/回显防抢逻辑翻倍触发(重复提交缺陷)。构造期每实例只挂一份, 多次
///   Loaded/Unloaded 不再叠加; DataContext 在事件触发时解析(构造时尚未挂上), 不捕获空引用。
/// </summary>
public partial class SettingsPage : UserControl
{
    public SettingsPage()
    {
        InitializeComponent();
        ThreadsBox.GotFocus += (_, _) => (DataContext as SettingsViewModel)?.OnThreadsEditingChanged(true);
        ThreadsBox.LostFocus += (_, _) => (DataContext as SettingsViewModel)?.OnThreadsEditingChanged(false);
        ThresholdBox.GotFocus += (_, _) => (DataContext as SettingsViewModel)?.OnThresholdEditingChanged(true);
        ThresholdBox.LostFocus += (_, _) => (DataContext as SettingsViewModel)?.OnThresholdEditingChanged(false);
        // 种植卡片(2026-11-20): 失焦提交(数量/种子名), 校验与回退在 VM
        PlantFlowerBox.LostFocus += (_, _) => (DataContext as SettingsViewModel)?.CommitPlantFlowerType();
        PlantCountBox.LostFocus += (_, _) => (DataContext as SettingsViewModel)?.CommitPlantCount();
        Unloaded += OnUnloaded;
    }

    private void OnUnloaded(object sender, RoutedEventArgs e)
    {
        // 控件卸载时若还挂着焦点标记, 一并复位(防下次装载后回显被误判"编辑中")
        if (DataContext is SettingsViewModel vm)
        {
            vm.OnThreadsEditingChanged(false);
            vm.OnThresholdEditingChanged(false);
        }
    }
}
