using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;
using FAA.WpfGui.ViewModels;

namespace FAA.WpfGui.Views;

/// <summary>
/// 调试页代码后置(纯视图职责):
///   ① 画面尺寸自适应: 按帧的宽高比把 ScreenHost 缩放进可视区(Image Stretch=Fill + Canvas 同尺寸 →
///      OCR 框与点击的像素映射精确);
///   ② OCR 框叠加: 订阅 VM.FrameArrived/BoxesUpdated, 按 2.5s 过期规则(webui.html:519)重绘 Canvas;
///   ③ 点击发送: 点击像素→rel→VM.ClickAtAsync→hit 圆点动效(800ms 后移除, webui.html:988-993);
///   ④ 模式下拉与 VM.IsTestMode 双向同步(SelectionChanged→set_mode 命令, 契约7)。
/// </summary>
public partial class DebugPage : UserControl
{
    private DebugViewModel? _vm;
    private bool _syncingMode;

    public DebugPage()
    {
        InitializeComponent();
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
    }

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        _vm = DataContext as DebugViewModel;
        if (_vm is null)
        {
            return;
        }
        _vm.FrameArrived += OnFrameArrived;
        _vm.BoxesUpdated += OnBoxesUpdated;
        _vm.PropertyChanged += OnVmPropertyChanged;
        SyncModeCombo();
    }

    private void OnUnloaded(object sender, RoutedEventArgs e)
    {
        if (_vm is not null)
        {
            _vm.FrameArrived -= OnFrameArrived;
            _vm.BoxesUpdated -= OnBoxesUpdated;
            _vm.PropertyChanged -= OnVmPropertyChanged;
            _vm.OnNavigatedFrom();
            _vm = null;
        }
    }

    // ==================== 模式切换(契约7) ====================

    private void OnVmPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(DebugViewModel.IsTestMode))
        {
            SyncModeCombo();
        }
    }

    /// <summary>VM 回显 → 下拉选中态(防重入)。</summary>
    private void SyncModeCombo()
    {
        if (_vm is null)
        {
            return;
        }
        _syncingMode = true;
        try
        {
            ModeCombo.SelectedIndex = _vm.IsTestMode ? 1 : 0;
        }
        finally
        {
            _syncingMode = false;
        }
    }

    private void OnModeSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_syncingMode || _vm is null)
        {
            return;
        }
        // index 1 = 测试(存点击图) → set_mode "test"; 0 = 使用 → "use"(契约7)
        _vm.SetModeCommand.Execute(ModeCombo.SelectedIndex == 1 ? "test" : "use");
    }

    // ==================== 画面尺寸自适应 ====================

    private void OnFrameArrived()
    {
        // 按帧宽高比缩放 ScreenHost(Image Stretch=Fill + Canvas 同尺寸 → 坐标映射精确)
        if (_vm?.ScreenImage is not { } bmp)
        {
            return;
        }
        double maxW = double.NaN, maxH = double.NaN;
        if (ScreenHost.Parent is FrameworkElement { } container)
        {
            maxW = container.ActualWidth > 20 ? container.ActualWidth - 16 : double.NaN;
            maxH = container.ActualHeight > 20 ? container.ActualHeight - 16 : double.NaN;
        }
        double w = bmp.PixelWidth, h = bmp.PixelHeight;
        var scale = 1.0;
        if (!double.IsNaN(maxW) && w > maxW)
        {
            scale = maxW / w;
        }
        if (!double.IsNaN(maxH) && h * scale > maxH)
        {
            scale = maxH / h;
        }
        ScreenHost.Width = Math.Max(320, w * scale);
        ScreenHost.Height = Math.Max(180, h * scale);
        RenderOverlay();
    }

    private void OnHostSizeChanged(object sender, SizeChangedEventArgs e)
    {
        OnFrameArrived();
    }

    // ==================== OCR 框叠加(2.5s 过期) ====================

    private void OnBoxesUpdated() => RenderOverlay();

    /// <summary>重绘 overlay: 框取回后 2.5s 内才叠加(webui.html:519 boxesStamp 过期规则);
    /// 框为相对矩形 box[0..1], 乘以宿主实际像素; 标签 = 文本 + rel 三位小数(webui.html:549)。</summary>
    private void RenderOverlay()
    {
        if (_vm is null)
        {
            return;
        }
        OcrCanvas.Children.Clear();
        if (!_vm.IsOcrEnabled || _vm.OcrStampTicks == 0)
        {
            return;
        }
        var ageMs = Environment.TickCount64 - _vm.OcrStampTicks;
        if (ageMs > 2500)
        {
            return;   // 框是 2.5s 前取的, 不再叠加(避免错位误导)
        }
        var w = ScreenHost.ActualWidth;
        var h = ScreenHost.ActualHeight;
        if (w <= 0 || h <= 0)
        {
            return;
        }
        foreach (var b in _vm.Boxes)
        {
            if (b.Box is not { Length: 4 })
            {
                continue;
            }
            var rect = new Rectangle
            {
                Stroke = new SolidColorBrush(Color.FromRgb(0x4C, 0xAF, 0x50)),
                StrokeThickness = 1,
                Fill = new SolidColorBrush(Color.FromArgb(0x28, 0x4C, 0xAF, 0x50)),
            };
            Canvas.SetLeft(rect, b.Box[0] * w);
            Canvas.SetTop(rect, b.Box[1] * h);
            rect.Width = Math.Max(2, (b.Box[2] - b.Box[0]) * w);
            rect.Height = Math.Max(2, (b.Box[3] - b.Box[1]) * h);
            OcrCanvas.Children.Add(rect);

            var label = new TextBlock
            {
                Text = $"{b.Text}  {b.Rel[0]:0.###},{b.Rel[1]:0.###}",
                FontSize = 10,
                FontFamily = new FontFamily("Consolas"),
                Foreground = Brushes.White,
                Background = new SolidColorBrush(Color.FromArgb(0xB0, 0x2E, 0x7D, 0x32)),
                Padding = new Thickness(2, 0, 2, 0),
            };
            Canvas.SetLeft(label, b.Box[0] * w);
            Canvas.SetTop(label, Math.Max(0, b.Box[1] * h - 14));
            OcrCanvas.Children.Add(label);
        }
    }

    // ==================== 点击发送 ====================

    private async void OnScreenClick(object sender, MouseButtonEventArgs e)
    {
        if (_vm is null)
        {
            return;
        }
        var pos = e.GetPosition(ScreenHost);
        var relX = pos.X / ScreenHost.ActualWidth;
        var relY = pos.Y / ScreenHost.ActualHeight;
        Services.DebugTrace.Log($"screen click: host={ScreenHost.ActualWidth:0}x{ScreenHost.ActualHeight:0} pos={pos.X:0},{pos.Y:0} rel=({relX:0.0000},{relY:0.0000})");
        var hitOk = await _vm.ClickAtAsync(relX, relY);
        if (hitOk)
        {
            ShowHit(pos);
        }
    }

    /// <summary>hit 动效: 点击处小圆点, 800ms 后移除(webui.html:988-993)。</summary>
    private void ShowHit(Point pos)
    {
        var hit = new Ellipse
        {
            Width = 10,
            Height = 10,
            Stroke = new SolidColorBrush(Color.FromRgb(0xFF, 0xD5, 0x4F)),
            StrokeThickness = 2,
            Fill = Brushes.Transparent,
        };
        Canvas.SetLeft(hit, pos.X - 5);
        Canvas.SetTop(hit, pos.Y - 5);
        OcrCanvas.Children.Add(hit);
        var timer = new System.Windows.Threading.DispatcherTimer { Interval = TimeSpan.FromMilliseconds(800) };
        timer.Tick += (_, _) =>
        {
            timer.Stop();
            OcrCanvas.Children.Remove(hit);
        };
        timer.Start();
    }
}
