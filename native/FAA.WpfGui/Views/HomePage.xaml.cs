using System.Windows.Controls;

namespace FAA.WpfGui.Views;

/// <summary>主页(每日挂机任务 + 模块设置面板 + 连接设置)。交互全部走绑定与命令, 代码后置仅承载 XAML。</summary>
public partial class HomePage : UserControl
{
    public HomePage()
    {
        InitializeComponent();
    }
}
