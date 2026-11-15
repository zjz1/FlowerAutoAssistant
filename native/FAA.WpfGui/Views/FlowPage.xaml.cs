using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using FAA.WpfGui.ViewModels;

namespace FAA.WpfGui.Views;

/// <summary>流程页代码后置: 仅做「首次进入懒加载」——数据/命令全在 FlowViewModel。</summary>
public partial class FlowPage : UserControl
{
    private bool _loadHooked;

    public FlowPage()
    {
        InitializeComponent();
        DataContextChanged += OnDataContextChanged;
        Loaded += OnLoaded;
    }

    private void OnDataContextChanged(object? sender, System.Windows.DependencyPropertyChangedEventArgs e)
    {
        _loadHooked = false;   // 换 VM 后重新挂首次装载
    }

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        if (_loadHooked || DataContext is not FlowViewModel vm)
        {
            return;
        }
        _loadHooked = true;
        _ = vm.LoadIfNeededAsync();   // 首次导航到本页才拉 /api/flows + /api/kb
    }
}
