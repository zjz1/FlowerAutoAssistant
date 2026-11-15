using System.Windows.Controls;

namespace FAA.WpfGui.Views;

/// <summary>
/// 「关于」页(批 C2): 静态信息页 —— 版本/说明/链接(占位)/致谢, 无轮询无服务依赖;
/// 打开链接交互在 AboutViewModel.OpenLinkCommand, 本页无代码后置逻辑。
/// </summary>
public partial class AboutPage : UserControl
{
    public AboutPage()
    {
        InitializeComponent();
    }
}
