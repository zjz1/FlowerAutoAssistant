using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;

namespace FAA.WpfGui.Services;

/// <summary>
/// 统一对话框服务(批 C3) —— 全应用弹框唯一出口, 替换各页内联 MessageBox.Show:
///   Confirm  = 确定取消二次确认(图标可选 警告/提问, 默认按钮可选 OK/Cancel —— 与原 MessageBox 调用点逐一对应);
///   Warn / Info / Error = 单按钮提示(图标如实区分, 标题/文案/按钮语义与原 MessageBox 一致);
///   ShowProgress = 最小可用进度窗(不定时长任务用: 非模态、无取消按钮, Report 改文案 / Close 收尾;
///                  现无调用点, 为下批可能的「重启后端」等长动作预留)。
/// 属主解析链(与原各调用点的 owner 兜底分支同语义): 显式 owner > 可见的主窗(Application.Current.MainWindow)
/// > 无属主 —— 主窗隐藏到托盘时保持无属主, 托盘路径(如「关闭服务」)的弹框行为不变;
/// 主窗可见时弹框带属主(居中于主窗、不被主窗压住), 交互语义与原无属主弹框一致。
/// 所有方法须在 UI 线程调用(与原 MessageBox.Show 调用点一致; 底层仍是 WPF MessageBox, user32 封装)。
/// </summary>
public static class DialogService
{
    private const string DefaultTitle = "FAA 原生窗口";

    /// <summary>
    /// 确认框(确定/取消): 确定=true。warning=false 用提问图标(契约2 关窗确认的空闲分支),
    /// true 用警告图标(危险动作确认); defaultCancel=true 时默认按钮为取消(回车不误触, 关闭服务二次确认用)。
    /// </summary>
    public static bool Confirm(string message, string title = DefaultTitle, Window? owner = null,
        bool warning = false, bool defaultCancel = false)
    {
        var rc = Show(owner, message, title, MessageBoxButton.OKCancel,
            warning ? MessageBoxImage.Warning : MessageBoxImage.Question,
            defaultCancel ? MessageBoxResult.Cancel : MessageBoxResult.OK);
        return rc == MessageBoxResult.OK;
    }

    /// <summary>警告提示框(单按钮, ⚠ 图标): 失败/不可达等需要用户知情但不致命的场景。</summary>
    public static void Warn(string message, string title = DefaultTitle, Window? owner = null)
        => Show(owner, message, title, MessageBoxButton.OK, MessageBoxImage.Warning, MessageBoxResult.OK);

    /// <summary>信息提示框(单按钮, ℹ 图标): 完成反馈等普通告知。</summary>
    public static void Info(string message, string title = DefaultTitle, Window? owner = null)
        => Show(owner, message, title, MessageBoxButton.OK, MessageBoxImage.Information, MessageBoxResult.OK);

    /// <summary>
    /// 运行前统一确认框（2026-11-20）：一个窗口展示 开启/关闭/风险 三段文本，确认=true。
    /// 文本由 POST /api/preflight 生成，本方法只负责展示与确认。
    /// </summary>
    public static bool ConfirmPreflight(string text, string title = "提示", Window? owner = null)
    {
        var body = new TextBlock
        {
            Text = text,
            TextWrapping = TextWrapping.Wrap,
            LineHeight = 21,
            Foreground = AppBrush("TextBrush") ?? new SolidColorBrush(Color.FromRgb(0xE8, 0xEA, 0xED)),
        };
        var scroll = new ScrollViewer
        {
            Content = body,
            MaxHeight = 460,
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
        };
        var ok = new Button { Content = "确认", Width = 88, IsDefault = true, Margin = new Thickness(0, 0, 8, 0) };
        var cancel = new Button { Content = "取消", Width = 88, IsCancel = true };
        var buttons = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            HorizontalAlignment = HorizontalAlignment.Right,
            Margin = new Thickness(0, 14, 0, 0),
        };
        buttons.Children.Add(ok);
        buttons.Children.Add(cancel);
        var panel = new StackPanel();
        panel.Children.Add(scroll);
        panel.Children.Add(buttons);
        var win = new Window
        {
            Title = title,
            Content = panel,
            Width = 620,
            MaxHeight = 620,
            SizeToContent = SizeToContent.Height,
            WindowStartupLocation = WindowStartupLocation.CenterScreen,
            ResizeMode = ResizeMode.NoResize,
            ShowInTaskbar = false,
            Background = AppBrush("PanelBrush") ?? new SolidColorBrush(Color.FromRgb(0x26, 0x28, 0x2D)),
        };
        var own = owner ?? Application.Current?.MainWindow;
        if (own is { IsVisible: true })
        {
            win.Owner = own;
            win.WindowStartupLocation = WindowStartupLocation.CenterOwner;
        }
        ok.Click += (_, _) => win.DialogResult = true;
        return win.ShowDialog() == true;
    }

    /// <summary>错误提示框(单按钮, ✖ 图标): 写盘失败等明确出错; 致命错误(端口冲突/服务自起失败)也走这里。</summary>
    public static void Error(string message, string title = DefaultTitle, Window? owner = null)
        => Show(owner, message, title, MessageBoxButton.OK, MessageBoxImage.Error, MessageBoxResult.OK);

    /// <summary>统一弹框: 属主解析链见类注释; 三分支与原调用点的 owner 兜底写法一一对应。</summary>
    private static MessageBoxResult Show(Window? owner, string message, string title,
        MessageBoxButton buttons, MessageBoxImage icon, MessageBoxResult defaultResult)
    {
        return owner is not null
            ? MessageBox.Show(owner, message, title, buttons, icon, defaultResult)
            : Application.Current?.MainWindow is { IsVisible: true } main
                ? MessageBox.Show(main, message, title, buttons, icon, defaultResult)
                : MessageBox.Show(message, title, buttons, icon, defaultResult);
    }

    // ==================== 进度窗(最小可用) ====================

    /// <summary>
    /// 弹出进度窗(非模态, 不定时长任务用): 不定态进度条 + 文案, 返回句柄 —— Report 改文案 / Close 收尾。
    /// 须在 UI 线程调用(窗口在调用线程创建); Report/Close 可在任意线程调(经创建线程 Dispatcher 调度)。
    /// 关闭路径幂等: 窗被用户 Alt+F4 关掉后再 Close/Report 均为无害空操作。
    /// </summary>
    public static ProgressHandle ShowProgress(string message, string title = DefaultTitle, Window? owner = null)
    {
        var text = new TextBlock
        {
            Text = message,
            TextWrapping = TextWrapping.Wrap,
            MaxWidth = 360,
            Foreground = AppBrush("TextBrush") ?? new SolidColorBrush(Color.FromRgb(0xE8, 0xEA, 0xED)),
        };
        var bar = new ProgressBar
        {
            IsIndeterminate = true,
            Height = 4,
            Margin = new Thickness(0, 12, 0, 0),
        };
        var panel = new StackPanel();
        panel.Children.Add(text);
        panel.Children.Add(bar);
        var border = new Border
        {
            Child = panel,
            Padding = new Thickness(18, 16, 18, 16),
            CornerRadius = new CornerRadius(6),
            Background = AppBrush("PanelBrush") ?? new SolidColorBrush(Color.FromRgb(0x26, 0x28, 0x2D)),
            BorderBrush = AppBrush("LineBrush") ?? new SolidColorBrush(Color.FromRgb(0x3A, 0x3D, 0x44)),
            BorderThickness = new Thickness(1),
        };
        var win = new Window
        {
            Title = title,
            Content = border,
            SizeToContent = SizeToContent.WidthAndHeight,
            Width = 420,
            WindowStartupLocation = WindowStartupLocation.CenterScreen,
            ResizeMode = ResizeMode.NoResize,
            ShowInTaskbar = false,
        };
        // 属主仅在主窗可见时挂(隐藏到托盘时不挂, 避免进度窗随隐藏属主一起不可见)
        var own = owner ?? Application.Current?.MainWindow;
        if (own is { IsVisible: true })
        {
            win.Owner = own;
            win.WindowStartupLocation = WindowStartupLocation.CenterOwner;
        }
        win.Show();
        return new ProgressHandle(win, text);
    }

    /// <summary>应用级资源画刷(DialogService 自建进度窗用): 取不到时由调用处给同色兜底值。</summary>
    private static Brush? AppBrush(string key) => Application.Current?.TryFindResource(key) as Brush;

    /// <summary>进度窗句柄: Report 改文案 / Close 收尾(Dispose 等价 Close); 经创建线程 Dispatcher 调度, 线程安全。</summary>
    public sealed class ProgressHandle : IDisposable
    {
        private readonly Dispatcher _dispatcher;
        private Window? _window;
        private TextBlock? _text;

        internal ProgressHandle(Window window, TextBlock text)
        {
            _dispatcher = window.Dispatcher;
            _window = window;
            _text = text;
            // 用户直接关掉进度窗(Alt+F4): 清引用, 后续 Report/Close 变空操作
            window.Closed += (_, _) =>
            {
                _window = null;
                _text = null;
            };
        }

        /// <summary>更新进度文案(不定态进度条无百分比可报)。</summary>
        public void Report(string message) => Run(() =>
        {
            if (_text is not null)
            {
                _text.Text = message;
            }
        });

        /// <summary>关闭进度窗; 未弹出/已关闭时为空操作。</summary>
        public void Close() => Run(() => _window?.Close());

        public void Dispose() => Close();

        private void Run(Action action)
        {
            if (_dispatcher.CheckAccess())
            {
                action();
            }
            else
            {
                _dispatcher.BeginInvoke(action);
            }
        }
    }
}
