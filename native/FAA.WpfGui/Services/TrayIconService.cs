using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using H.NotifyIcon;
using FAA.WpfGui.ViewModels;

namespace FAA.WpfGui.Services;

/// <summary>
/// 托盘图标服务(H.NotifyIcon.Wpf) —— MAA 式系统集成:
///   最小化到托盘(MainWindow.StateChanged 触发 Hide)/左键恢复主窗/右键菜单:
///     显示主窗 · 开始一轮(快捷, 随运行态禁用) · ⏹ 停止(快捷, 随运行态启停) ·
///     ⏻ 关闭服务(A3, 随连接态禁用) · 退出。
///   退出走契约2 同一关窗确认逻辑: RequestExit → 主窗 Show 后 Close() → Window.Closing 的
///   确认判定(流程运行中 OR confirm_page_close)原样生效, 不另设第二条确认路径。
/// </summary>
public sealed class TrayIconService : IDisposable
{
    private readonly TaskbarIcon _icon;
    private readonly MainViewModel _main;
    private readonly Action _requestExit;
    private readonly MenuItem _startItem;
    private readonly MenuItem _stopItem;
    private readonly MenuItem _shutdownItem;

    public TrayIconService(MainViewModel main, Action requestExit)
    {
        _main = main;
        _requestExit = requestExit;

        _startItem = new MenuItem { Header = "▶ 开始一轮(快捷)", ToolTip = "以当前勾选的任务开始每日编排(主页可改勾选)" };
        _startItem.Click += (_, _) => _main.Home.StartCommand.Execute(null);

        _stopItem = new MenuItem { Header = "⏹ 停止当前流程", ToolTip = "请求停止当前流程(服务保持运行)" };
        _stopItem.Click += (_, _) => _main.Home.StopCommand.Execute(null);

        // A3: 关闭服务(与设置页连接卡片共用 MainViewModel.ShutdownServiceAsync 的 确认→shutdown→刷新 链路)
        _shutdownItem = new MenuItem
        {
            Header = "⏻ 关闭服务",
            ToolTip = "POST /api/shutdown 关闭 Web 服务(需二次确认; 仅已连接托管/外部实例时可用)",
        };
        _shutdownItem.Click += async (_, _) => await _main.ShutdownServiceAsync();
        _shutdownItem.IsEnabled = _main.IsServiceConnected;   // 初始同步(启动早期服务未就绪=禁用)
        _main.PropertyChanged += OnMainPropertyChanged;

        var showItem = new MenuItem { Header = "显示主窗" };
        showItem.Click += (_, _) => ShowMainWindow();

        var exitItem = new MenuItem { Header = "退出" };
        exitItem.Click += (_, _) => _requestExit();

        var menu = new ContextMenu();
        menu.Items.Add(showItem);
        menu.Items.Add(new Separator());
        menu.Items.Add(_startItem);
        menu.Items.Add(_stopItem);
        menu.Items.Add(_shutdownItem);
        menu.Items.Add(new Separator());
        menu.Items.Add(exitItem);

        _icon = new TaskbarIcon
        {
            ToolTipText = "FAA 小花仙挂机助手(原生窗口)",
            IconSource = new System.Windows.Media.Imaging.BitmapImage(
                new Uri("pack://application:,,,/Assets/app.ico")),
            ContextMenu = menu,
            Visibility = Visibility.Visible,
        };
        // 左键恢复主窗(单击; MAA 同款)
        _icon.TrayLeftMouseUp += (_, _) => ShowMainWindow();
        _icon.TrayLeftMouseDown += (_, _) => ShowMainWindow();

        UpdateQuickState(canStart: false, isRunning: false);
    }

    /// <summary>恢复主窗: 显示 + 正常态 + 前台。</summary>
    public void ShowMainWindow()
    {
        var win = Application.Current?.MainWindow;
        if (win is null)
        {
            return;
        }
        win.Show();
        win.WindowState = WindowState.Normal;
        win.Activate();
    }

    /// <summary>快捷态刷新(每轮 /api/status 后由 MainViewModel 调; 托盘不在可视树, 手动同步 IsEnabled)。</summary>
    public void UpdateQuickState(bool canStart, bool isRunning)
    {
        _startItem.IsEnabled = canStart;
        _startItem.Header = isRunning ? "▶ 开始一轮(运行中, 不可用)" : "▶ 开始一轮(快捷)";
        _stopItem.IsEnabled = isRunning;
    }

    /// <summary>A3: 服务连接态变化 → 同步「关闭服务」菜单项(托盘不在可视树, 手动同步 IsEnabled, 与快捷态同款)。</summary>
    private void OnMainPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(MainViewModel.IsServiceConnected))
        {
            _shutdownItem.IsEnabled = _main.IsServiceConnected;
        }
    }

    public void Dispose()
    {
        _main.PropertyChanged -= OnMainPropertyChanged;
        _icon.Dispose();
    }
}
