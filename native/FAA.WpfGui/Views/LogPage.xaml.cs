using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using FAA.WpfGui.ViewModels;

namespace FAA.WpfGui.Views;

/// <summary>
/// 运行日志页代码后置: 只做"底部吸附自动滚动"这一视图职责 ——
///   用户本就滚在底部 → 新日志到达自动贴底(webui.html:965,973 isBottom 同语义);
///   用户往上翻了 → 不打断阅读位置。数据/轮询/保存/清除全在 LogViewModel。
/// </summary>
public partial class LogPage : UserControl
{
    private LogViewModel? _vm;
    private ScrollViewer? _logScroll;
    private bool _pinned = true;

    public LogPage()
    {
        InitializeComponent();
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
    }

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        _vm = DataContext as LogViewModel;
        if (_vm is not null)
        {
            _vm.LinesAppended += OnLinesAppended;
        }
        _logScroll ??= FindScrollViewer(LogList);
        if (_logScroll is not null)
        {
            _logScroll.ScrollChanged += OnScrollChanged;
        }
    }

    private void OnUnloaded(object sender, RoutedEventArgs e)
    {
        if (_vm is not null)
        {
            _vm.LinesAppended -= OnLinesAppended;
            _vm = null;
        }
        if (_logScroll is not null)
        {
            _logScroll.ScrollChanged -= OnScrollChanged;
            _logScroll = null;
        }
    }

    private void OnScrollChanged(object sender, ScrollChangedEventArgs e)
    {
        if (_logScroll is null)
        {
            return;
        }
        // 距底 < 4px 视为贴底; 列表被清空时 extent≈0 也归为贴底
        _pinned = _logScroll.VerticalOffset + _logScroll.ViewportHeight >= _logScroll.ExtentHeight - 4;
    }

    private void OnLinesAppended()
    {
        if (_pinned && _logScroll is not null)
        {
            Dispatcher.BeginInvoke(() => _logScroll?.ScrollToEnd());
        }
    }

    /// <summary>视觉树递归找 ListBox 的 ScrollViewer(ListBox 内部模板件, 无公开属性)。</summary>
    private static ScrollViewer? FindScrollViewer(DependencyObject root)
    {
        if (root is ScrollViewer sv)
        {
            return sv;
        }
        for (var i = 0; i < VisualTreeHelper.GetChildrenCount(root); i++)
        {
            var found = FindScrollViewer(VisualTreeHelper.GetChild(root, i));
            if (found is not null)
            {
                return found;
            }
        }
        return null;
    }
}
