using System.Collections.ObjectModel;
using System.Text.Json;
using CommunityToolkit.Mvvm.ComponentModel;
using FAA.WpfGui.Models;
using FAA.WpfGui.Services;

namespace FAA.WpfGui.ViewModels;

/// <summary>
/// 种植模块设置面板（2026-11-20）：选种 / 数量与购买 / 收获保护 三组。
/// 回显 = GET /api/daily（modules[plant].settings + 顶层 plant_harvest_allowed），
/// 保存 = POST /api/set_config 单键；稀有种子规则与引擎一致（购买强制关闭、不可加入收获允许列表）。
/// </summary>
public partial class PlantSettingsViewModel : ObservableObject
{
    private readonly MainViewModel _main;
    private bool _loadingEcho;
    private bool _rebuilding;
    private bool _suppressSave;
    private bool _rareConfirm = true;
    private PlantPresetsDoc? _presets;
    private int _lastPlantCount = 1;
    private string _lastPresetSeed = "白色桃花";
    private string _lastPlantFlowerType = "桃花";
    private int _saveMsgSeq;

    public PlantSettingsViewModel(MainViewModel main)
    {
        _main = main;
    }

    public ObservableCollection<string> PlantFlowers { get; } = new();
    public ObservableCollection<PlantColorOption> PlantColors { get; } = new();
    public ObservableCollection<HarvestFlowerVm> HarvestFlowers { get; } = new();

    [ObservableProperty] private int _plantSeedModeIndex;
    [ObservableProperty] private int _plantCountModeIndex;
    [ObservableProperty] private string _plantFlowerTypeText = "桃花";
    [ObservableProperty] private string _plantCountText = "1";
    [ObservableProperty] private bool _plantBuyMissing;
    [ObservableProperty] private bool _plantAutoBuy;
    [ObservableProperty] private string _plantSeedLabel = "白色桃花";
    [ObservableProperty] private string? _plantFlower;
    [ObservableProperty] private PlantColorOption? _plantColor;
    [ObservableProperty] private string _saveStatusText = "";
    [ObservableProperty] private bool _saveStatusIsError;

    public bool IsPlantManual => PlantSeedModeIndex == 0;
    public bool IsPlantPreset => PlantSeedModeIndex == 1;
    public bool IsPlantCountFixed => PlantCountModeIndex == 0;
    public bool IsPlantCountAuto => PlantCountModeIndex == 1;

    partial void OnPlantSeedModeIndexChanged(int value)
    {
        OnPropertyChanged(nameof(IsPlantManual));
        OnPropertyChanged(nameof(IsPlantPreset));
        if (!_loadingEcho)
        {
            _ = SaveKeyAsync("plant_seed_mode", value == 0 ? "manual" : "preset");
        }
    }

    partial void OnPlantCountModeIndexChanged(int value)
    {
        OnPropertyChanged(nameof(IsPlantCountFixed));
        OnPropertyChanged(nameof(IsPlantCountAuto));
        if (!_loadingEcho)
        {
            _ = SaveKeyAsync("plant_count_mode", value == 0 ? "fixed" : "auto");
        }
    }

    partial void OnPlantBuyMissingChanged(bool value)
    {
        if (!_suppressSave)
        {
            SaveIfNotEchoing("plant_buy_missing", value);
        }
    }

    partial void OnPlantAutoBuyChanged(bool value)
    {
        if (!_suppressSave)
        {
            SaveIfNotEchoing("plant_auto_buy", value);
        }
    }

    partial void OnPlantFlowerChanged(string? value) => RebuildPlantColors(null);

    partial void OnPlantColorChanged(PlantColorOption? value) => OnPlantColorPicked();

    private PlantColor? FindColor(string? seed)
        => seed is null ? null : _presets?.Flowers.SelectMany(f => f.Colors)
            .FirstOrDefault(c => c.Seed == seed);

    private string RareLabel(string seed)
    {
        var flower = _presets?.Flowers.FirstOrDefault(f => f.Colors.Any(c => c.Seed == seed))?.Name;
        var color = FindColor(seed)?.Name;
        var s = $"{color} {flower}".Trim();
        return s.Length > 0 ? s : seed;
    }

    private string? ResolveManualSeed(string raw)
    {
        if (_presets is null)
        {
            return null;   // 数据库未加载: 交由服务端校验
        }
        var s = raw.Trim();
        foreach (var suf in new[] { "种子", "花种" })
        {
            if (s.EndsWith(suf) && s.Length > suf.Length)
            {
                s = s[..^suf.Length];
            }
        }
        if (s.Length == 0 || s == "桃花")
        {
            s = "白色桃花";
        }
        return _presets.Flowers.SelectMany(f => f.Colors).Any(c => c.Seed == s) ? s : null;
    }

    public async void CommitPlantFlowerType()
    {
        if (_loadingEcho)
        {
            return;
        }
        var raw = PlantFlowerTypeText.Trim();
        if (raw == _lastPlantFlowerType)
        {
            return;
        }
        var seed = ResolveManualSeed(raw);
        if (seed is not null && FindColor(seed)?.Rare == true && _rareConfirm
            && !DialogService.Confirm($"选中的 {RareLabel(seed)} 种子为稀有种子，请确认", "稀有种子确认"))
        {
            PlantFlowerTypeText = _lastPlantFlowerType;
            return;
        }
        if (!await SaveKeyResultAsync("plant_flower_type", raw))
        {
            PlantFlowerTypeText = _lastPlantFlowerType;
            DialogService.Warn($"种子名保存失败（可能不是小花仙种子）：{raw}\n可选项见 data/plant_presets.json", "种植设置");
            return;
        }
        _lastPlantFlowerType = raw;
    }

    public async void CommitPlantCount()
    {
        if (_loadingEcho)
        {
            return;
        }
        if (!int.TryParse(PlantCountText.Trim(), out var n) || n < 1 || n > 360)
        {
            PlantCountText = _lastPlantCount.ToString();
            DialogService.Warn("种植数量须在 1~360 之间", "种植设置");
            return;
        }
        if (n == _lastPlantCount)
        {
            PlantCountText = n.ToString();
            return;
        }
        if (!await SaveKeyResultAsync("plant_count", n))
        {
            PlantCountText = _lastPlantCount.ToString();
            DialogService.Warn("种植数量保存失败（须在 1~360 之间）", "种植设置");
            return;
        }
        _lastPlantCount = n;
        PlantCountText = n.ToString();
    }

    private void RebuildPlantColors(string? preserveSeed)
    {
        if (_presets is null)
        {
            return;
        }
        var flower = _presets.Flowers.FirstOrDefault(f => f.Name == PlantFlower);
        _rebuilding = true;
        try
        {
            PlantColors.Clear();
            foreach (var c in flower?.Colors ?? Array.Empty<PlantColor>())
            {
                PlantColors.Add(new PlantColorOption(c.Name, c.Seed, c.Rare));
            }
            PlantColor = PlantColors.FirstOrDefault(x => x.Seed == preserveSeed) ?? PlantColors.FirstOrDefault();
        }
        finally
        {
            _rebuilding = false;
        }
        UpdatePlantSeedLabel();
    }

    private async void OnPlantColorPicked()
    {
        if (_loadingEcho || _rebuilding || PlantColor is null)
        {
            return;
        }
        var seed = PlantColor.Seed;
        if (seed == _lastPresetSeed)
        {
            UpdatePlantSeedLabel();
            return;
        }
        if (PlantColor.Rare && _rareConfirm
            && !DialogService.Confirm($"选中的 {PlantColor.Name} {PlantFlower} 种子为稀有种子，请确认", "稀有种子确认"))
        {
            RevertPlantPreset();
            return;
        }
        if (!await SaveKeyResultAsync("plant_seed_preset", seed))
        {
            RevertPlantPreset();
            DialogService.Warn("预设种子保存失败", "种植设置");
            return;
        }
        _lastPresetSeed = seed;
        UpdatePlantSeedLabel();
    }

    private void UpdatePlantSeedLabel()
    {
        var seed = PlantColor?.Seed ?? _lastPresetSeed;
        var rare = PlantColor?.Rare == true || FindColor(seed)?.Rare == true;
        PlantSeedLabel = seed + (rare ? "（稀有，不可购买）" : "");
        if (!rare)
        {
            return;
        }
        // 稀有种子不可购买：仅视觉强制关闭，不改写已保存值（引擎运行时会再次强制）
        _suppressSave = true;
        try
        {
            PlantBuyMissing = false;
            PlantAutoBuy = false;
        }
        finally
        {
            _suppressSave = false;
        }
    }

    private void RevertPlantPreset()
    {
        var seed = _lastPresetSeed;
        var flower = _presets?.Flowers.FirstOrDefault(f => f.Colors.Any(c => c.Seed == seed));
        if (flower is not null)
        {
            _rebuilding = true;
            try
            {
                PlantFlower = flower.Name;
                PlantColors.Clear();
                foreach (var c in flower.Colors)
                {
                    PlantColors.Add(new PlantColorOption(c.Name, c.Seed, c.Rare));
                }
                PlantColor = PlantColors.FirstOrDefault(x => x.Seed == seed) ?? PlantColors.FirstOrDefault();
            }
            finally
            {
                _rebuilding = false;
            }
        }
        UpdatePlantSeedLabel();
    }

    /// <summary>收获保护勾选变化 → 保存允许不授粉收获的种子数组（稀有项永不进入）。</summary>
    internal void NotifyHarvestChanged()
    {
        if (_loadingEcho || _rebuilding)
        {
            return;
        }
        var allowed = HarvestFlowers.SelectMany(f => f.Colors)
            .Where(c => c is { Rare: false, IsAllowed: true })
            .Select(c => c.Seed).Distinct().ToArray();
        SaveIfNotEchoing("plant_harvest_allowed", allowed);
    }

    private async Task EnsurePresetsAsync(FaaProxy proxy)
    {
        if (_presets is not null)
        {
            return;
        }
        var r = await proxy.GetPlantPresetsAsync();
        if (r.Success && r.Value is not null)
        {
            _presets = r.Value;
        }
    }

    /// <summary>回显（HomeViewModel.LoadAsync 调用）；_loadingEcho 由调用方管理。</summary>
    public async Task LoadAsync(FaaProxy proxy, DailyPlan d)
    {
        _loadingEcho = true;
        try
        {
            await EnsurePresetsAsync(proxy);
            LoadPlantEcho(d);
        }
        finally
        {
            _loadingEcho = false;
        }
    }

    private void LoadPlantEcho(DailyPlan d)
    {
        var ps = d.Modules.FirstOrDefault(m => m.Id == "plant")?.Settings ?? Array.Empty<SettingItem>();
        string Txt(string key, string def)
        {
            var s = ps.FirstOrDefault(x => x.Key == key);
            if (s is null)
            {
                return def;
            }
            return s.Value.ValueKind == JsonValueKind.String ? (s.Value.GetString() ?? def) : s.Value.ToString();
        }
        bool Bl(string key, bool def)
        {
            var s = ps.FirstOrDefault(x => x.Key == key);
            if (s is null)
            {
                return def;
            }
            return s.Value.ValueKind == JsonValueKind.True
                   || (s.Value.ValueKind == JsonValueKind.String
                       && bool.TryParse(s.Value.GetString(), out var b) && b);
        }

        _rareConfirm = d.PlantRareConfirm;
        PlantSeedModeIndex = Txt("plant_seed_mode", "manual") == "preset" ? 1 : 0;
        PlantCountModeIndex = Txt("plant_count_mode", "fixed") == "auto" ? 1 : 0;
        _lastPlantFlowerType = Txt("plant_flower_type", "桃花");
        PlantFlowerTypeText = _lastPlantFlowerType;
        _lastPlantCount = int.TryParse(Txt("plant_count", "1"), out var n) ? Math.Clamp(n, 1, 360) : 1;
        PlantCountText = _lastPlantCount.ToString();
        PlantBuyMissing = Bl("plant_buy_missing", false);
        PlantAutoBuy = Bl("plant_auto_buy", false);
        _lastPresetSeed = Txt("plant_seed_preset", "白色桃花");

        PlantFlowers.Clear();
        foreach (var f in _presets?.Flowers ?? Array.Empty<PlantFlower>())
        {
            PlantFlowers.Add(f.Name);
        }
        var savedFlower = _presets?.Flowers.FirstOrDefault(f => f.Colors.Any(c => c.Seed == _lastPresetSeed))?.Name
                          ?? PlantFlowers.FirstOrDefault();
        if (savedFlower is not null)
        {
            PlantFlower = savedFlower;
            RebuildPlantColors(_lastPresetSeed);
        }

        // 收获保护：花名一级 → 颜色二级；稀有强制保护且不可勾选
        var allowed = new HashSet<string>(d.PlantHarvestAllowed
                                          ?? new[] { "白色桃花", "粉色桃花" });
        _rebuilding = true;
        try
        {
            HarvestFlowers.Clear();
            foreach (var f in _presets?.Flowers ?? Array.Empty<PlantFlower>())
            {
                var flowerVm = new HarvestFlowerVm(f.Name);
                foreach (var c in f.Colors)
                {
                    flowerVm.Colors.Add(new HarvestColorVm(this, c.Name, c.Seed, c.Rare,
                        !c.Rare && allowed.Contains(c.Seed)));
                }
                HarvestFlowers.Add(flowerVm);
            }
        }
        finally
        {
            _rebuilding = false;
        }
        UpdatePlantSeedLabel();
    }

    private void SaveIfNotEchoing(string key, object? value)
    {
        if (!_loadingEcho)
        {
            _ = SaveKeyAsync(key, value);
        }
    }

    private async Task SaveKeyAsync(string key, object? value)
    {
        await SaveKeyResultAsync(key, value);
    }

    private async Task<bool> SaveKeyResultAsync(string key, object? value)
    {
        var proxy = _main.Session.Proxy;
        if (proxy is null)
        {
            SaveStatusText = "服务未就绪, 未保存";
            SaveStatusIsError = true;
            return false;
        }
        var r = await proxy.SetConfigAsync(new Dictionary<string, object?> { [key] = value });
        var ok = r.Success && r.Value?.Ok == true;
        if (ok)
        {
            SaveStatusText = "已保存 ✓";
            SaveStatusIsError = false;
        }
        else
        {
            SaveStatusText = $"保存失败: {(r.Error.Length > 160 ? r.Error[..160] : r.Error)}";
            SaveStatusIsError = true;
        }
        var seq = ++_saveMsgSeq;
        _ = ClearSaveStatusAfterDelayAsync(seq);
        return ok;
    }

    private async Task ClearSaveStatusAfterDelayAsync(int seq)
    {
        await Task.Delay(2000);
        if (seq == _saveMsgSeq)
        {
            SaveStatusText = "";
        }
    }
}

/// <summary>收获保护：花名一级条目。</summary>
public sealed class HarvestFlowerVm
{
    public HarvestFlowerVm(string name)
    {
        Name = name;
    }

    public string Name { get; }
    public ObservableCollection<HarvestColorVm> Colors { get; } = new();
}

/// <summary>收获保护：颜色二级条目（稀有=false 才可勾选）。</summary>
public sealed partial class HarvestColorVm : ObservableObject
{
    private readonly PlantSettingsViewModel _owner;
    private readonly bool _suppress;

    public HarvestColorVm(PlantSettingsViewModel owner, string name, string seed, bool rare, bool isAllowed)
    {
        _owner = owner;
        _suppress = true;
        Name = name;
        Seed = seed;
        Rare = rare;
        IsAllowed = isAllowed;
        _suppress = false;
        IsEnabled = !rare;
    }

    public string Name { get; }
    public string Seed { get; }
    public bool Rare { get; }
    public bool IsEnabled { get; }
    public string Display => Rare ? $"{Name}（稀有·强制保护）" : Name;

    [ObservableProperty] private bool _isAllowed;

    partial void OnIsAllowedChanged(bool value)
    {
        if (!_suppress)
        {
            _owner.NotifyHarvestChanged();
        }
    }
}

/// <summary>预设颜色下拉项（Display 带稀有标记）。</summary>
public sealed record PlantColorOption(string Name, string Seed, bool Rare)
{
    public string Display => Rare ? $"{Name} (稀有)" : Name;
}
