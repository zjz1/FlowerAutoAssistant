using System.Windows.Controls;
using FAA.WpfGui.ViewModels;

namespace FAA.WpfGui.Views;

/// <summary>种植模块设置面板（2026-11-20）：失焦提交数量/种子名，校验与回退在 VM。</summary>
public partial class PlantSettingsPanel : UserControl
{
    public PlantSettingsPanel()
    {
        InitializeComponent();
        PlantFlowerBox.LostFocus += (_, _) => (DataContext as PlantSettingsViewModel)?.CommitPlantFlowerType();
        PlantCountBox.LostFocus += (_, _) => (DataContext as PlantSettingsViewModel)?.CommitPlantCount();
    }
}
