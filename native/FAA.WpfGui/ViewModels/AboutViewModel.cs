using System.Reflection;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using FAA.WpfGui.Services;

namespace FAA.WpfGui.ViewModels;

/// <summary>
/// 「关于」页 ViewModel(批 C2): 版本读自程序集(优先 InformationalVersion —— csproj &lt;Version&gt;0.5.0&lt;/Version&gt;
/// 即其来源; 缺失回落 Assembly.GetName().Version), 说明/链接/致谢为静态内容。
/// 链接为实际地址(项目文档目录 / GitHub 仓库), 打开走系统默认浏览器(与设置页 OpenTplTool 同款
/// UseShellExecute 口径), 打不开原生框如实报错。
/// </summary>
public partial class AboutViewModel : ObservableObject
{
    /// <summary>应用版本(csproj Version → 程序集 InformationalVersion; 当前 0.5.0)。</summary>
    public string VersionText { get; }

    /// <summary>程序集版本(Assembly.GetName().Version, 形如 0.5.0.0; 与应用版本同源, 供核对)。</summary>
    public string AssemblyVersionText { get; }

    /// <summary>应用一句话说明(与壳的实际能力一致: 六页导航/服务托管/托盘/单实例)。</summary>
    public string AppIntro { get; } =
        "本程序是 FlowerAutoAssistant（FAA）每日挂机助手的 Windows 原生桌面壳（WPF, 无浏览器依赖）。\n" +
        "启动时自动探测本机 FAA Web 服务: 已在运行则直连复用, 未运行则托管启动; 也可用 --api-base 直连指定服务。\n" +
        "提供 主页 / 运行日志 / 设置 / 调试 / 流程 / 关于 六个页面, 支持最小化到托盘与单实例互斥。";

    /// <summary>项目文档目录(流程手册 / 架构路线 / API 契约)。</summary>
    public string DocsUrl { get; } = "https://github.com/zjz1/FlowerAutoAssistant/tree/main/docs";

    /// <summary>GitHub 仓库。</summary>
    public string GithubUrl { get; } = "https://github.com/zjz1/FlowerAutoAssistant";

    /// <summary>致谢文案(只谢代码里实际用到的: MAA 风格参考 + 两个 NuGet 依赖 + 服务端项目本体)。</summary>
    public string Thanks { get; } =
        "界面与交互风格参考开源项目 MaaAssistantArknights（MAA）的深色主题。\n" +
        "感谢开源库 CommunityToolkit.Mvvm（MVVM 工具链）与 H.NotifyIcon.Wpf（系统托盘）。\n" +
        "识别与服务端能力来自 FlowerAutoAssistant 项目本体（Python: webui.py + OCR 引擎）。\n" +
        "以及一切被本程序引用的开源组件作者。";

    public AboutViewModel()
    {
        var asm = Assembly.GetExecutingAssembly();
        VersionText = asm.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion
            ?? asm.GetName().Version?.ToString() ?? "未知";
        AssemblyVersionText = asm.GetName().Version?.ToString() ?? "未知";
    }

    /// <summary>打开外部链接(XAML Hyperlink.Command 调用, CommandParameter=URL): 失败原生框如实报, 不静默。</summary>
    [RelayCommand]
    private void OpenLink(string? url)
    {
        if (string.IsNullOrWhiteSpace(url))
        {
            return;
        }
        try
        {
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(url)
            {
                UseShellExecute = true,   // URL 必须走 shell: 由系统按默认浏览器分发
            });
            Services.DebugTrace.Log($"about.openlink: opened {url}");
        }
        catch (Exception ex)
        {
            Services.DebugTrace.Log($"about.openlink: FAIL {ex.GetType().Name}: {ex.Message}");
            DialogService.Warn(
                $"无法在系统浏览器中打开链接:\n{url}\n\n{ex.GetType().Name}: {ex.Message}",
                "FAA 原生窗口");
        }
    }
}
