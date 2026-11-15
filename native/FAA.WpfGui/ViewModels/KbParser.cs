using System.Text.Json;
using FAA.WpfGui.Models;

namespace FAA.WpfGui.ViewModels;

/// <summary>N02 提纯产物(batch-06): /api/kb 解析纯结果 —— ParseKb 的集合装配/状态文本副作用由此一次落地。</summary>
internal sealed class KbParseResult
{
    /// <summary>场景分组(两层嵌套模式按场景名排序; 旧扁平模式至多一个伪场景节点)。</summary>
    public List<KbSceneVm> Scenes { get; } = new();

    /// <summary>关闭按钮库行(两种模式共用同一段循环)。</summary>
    public List<KbCloseButtonVm> CloseButtons { get; } = new();

    /// <summary>汇总行文案(原 KbSummaryText 赋值)。</summary>
    public string SummaryText { get; internal set; } = "";

    /// <summary>加载状态文案(原 KbStatusText 赋值)。</summary>
    public string StatusText { get; internal set; } = "";
}

/// <summary>
/// 知识库解析纯函数(N02 提纯自 FlowViewModel.ParseKb ~135 行, batch-06 逐行等价迁移, 行为零变化):
/// 解析 /api/kb: click_log.scenes 两层嵌套 场景→按钮(场景名排序, webui.html:619);
/// 无 scenes 键时按旧扁平格式回退(634-643: 顶层键=按钮名, 值含 category/rel)。
/// 判据逐分支对照 webui.html:619-643:
///   kbRow(:615)  = b.name||键名; b.category||"其他"; JSON.stringify(b.rel||[]); sample_n&gt;1 显 " · 均N";
///   scenes 排序(:619) = Object.keys(scenes).sort()(string.CompareOrdinal 同序);
///   非对象按钮过滤 = filter(b =&gt; b &amp;&amp; typeof b === "object");
///   分类汇总(:627) = [...new Set(btns.map(b =&gt; b.category || "其他"))].join(" / ") ——
///     C# 侧用 SortedSet(Ordinal) 保持去重 + 有序(原实现如此, 与 webui 的首现序差异属既有形态);
///   旧扁平回退(:634-643) = 顶层键=按钮名, 只取对象值, scenes 键跳过;
///   关闭按钮行(:651) = b.name||"" / b.scene||"通用" / b.type||""。
/// VM 集合(ObservableCollection)仍归 FlowViewModel 所有; 本类只构建纯结果。
/// </summary>
internal static class KbParser
{
    public static KbParseResult Parse(KbData d)
    {
        var result = new KbParseResult();
        var total = 0;

        // 真实形状: click_log = {scenes: {场景: {按钮: {name,category,rel,sample_n,...}}}}
        // KbData.ClickLog 即 click_log 对象, 场景表在其 "scenes" 键下
        if (d.ClickLog.TryGetValue("scenes", out var scenesEl) && scenesEl.ValueKind == JsonValueKind.Object)
        {
            // webui: Object.keys(scenes).sort() —— 场景名排序
            var sceneProps = scenesEl.EnumerateObject().ToList();
            sceneProps.Sort((a, b) => string.CompareOrdinal(a.Name, b.Name));
            foreach (var scene in sceneProps)
            {
                if (scene.Value.ValueKind != JsonValueKind.Object)
                {
                    continue;
                }
                var buttons = new List<KbButtonVm>();
                var cats = new SortedSet<string>(StringComparer.Ordinal);
                foreach (var b in scene.Value.EnumerateObject())
                {
                    // webui kbRow: b.name||键名; b.category||"其他"; rel JSON; sample_n>1 显 " · 均N"
                    string name = b.Name;
                    string category = "其他";
                    string relJson = "[]";
                    int sampleN = 1;
                    if (b.Value.ValueKind == JsonValueKind.Object)
                    {
                        foreach (var f in b.Value.EnumerateObject())
                        {
                            switch (f.Name)
                            {
                                case "name" when f.Value.ValueKind == JsonValueKind.String:
                                    name = f.Value.GetString() ?? name;
                                    break;
                                case "category" when f.Value.ValueKind == JsonValueKind.String:
                                    category = f.Value.GetString() ?? "其他";
                                    break;
                                case "rel" when f.Value.ValueKind == JsonValueKind.Array:
                                    relJson = "[" + string.Join(",", f.Value.EnumerateArray()
                                        .Select(v => v.ValueKind == JsonValueKind.Number ? v.GetRawText() : "null")) + "]";
                                    break;
                                case "sample_n" when f.Value.ValueKind == JsonValueKind.Number:
                                    sampleN = f.Value.GetInt32();
                                    break;
                            }
                        }
                    }
                    else
                    {
                        continue;   // webui: filter(b => b && typeof b === "object")
                    }
                    cats.Add(category);
                    buttons.Add(new KbButtonVm(name, category, relJson, sampleN));
                }
                total += buttons.Count;
                result.Scenes.Add(new KbSceneVm
                {
                    Name = scene.Name,
                    ButtonCount = buttons.Count,
                    CategoriesSummary = string.Join(" / ", cats),
                    Buttons = buttons,
                    IsExpanded = true,
                });
            }
        }
        else
        {
            // 旧扁平格式回退(webui.html:634-643): 顶层键=按钮名, 值 {category, rel}
            var buttons = new List<KbButtonVm>();
            foreach (var kv in d.ClickLog)
            {
                if (kv.Value.ValueKind != JsonValueKind.Object || kv.Key == "scenes")
                {
                    continue;
                }
                string category = "其他";
                string relJson = "[]";
                foreach (var f in kv.Value.EnumerateObject())
                {
                    switch (f.Name)
                    {
                        case "category" when f.Value.ValueKind == JsonValueKind.String:
                            category = f.Value.GetString() ?? "其他";
                            break;
                        case "rel" when f.Value.ValueKind == JsonValueKind.Array:
                            relJson = "[" + string.Join(",", f.Value.EnumerateArray()
                                .Select(v => v.ValueKind == JsonValueKind.Number ? v.GetRawText() : "null")) + "]";
                            break;
                    }
                }
                buttons.Add(new KbButtonVm(kv.Key, category, relJson, 1));
            }
            total = buttons.Count;
            if (buttons.Count > 0)
            {
                result.Scenes.Add(new KbSceneVm
                {
                    Name = "知识库（旧版扁平格式）",
                    ButtonCount = buttons.Count,
                    CategoriesSummary = string.Join(" / ", buttons.Select(b => b.Category).Distinct()),
                    Buttons = buttons,
                    IsExpanded = true,
                });
            }
        }

        foreach (var cb in d.CloseButtons)
        {
            string name = "", scene = "通用", type = "";
            if (cb.ValueKind == JsonValueKind.Object)
            {
                foreach (var f in cb.EnumerateObject())
                {
                    switch (f.Name)
                    {
                        case "name" when f.Value.ValueKind == JsonValueKind.String:
                            name = f.Value.GetString() ?? "";
                            break;
                        case "scene" when f.Value.ValueKind == JsonValueKind.String:
                            scene = f.Value.GetString() ?? "通用";
                            break;
                        case "type" when f.Value.ValueKind == JsonValueKind.String:
                            type = f.Value.GetString() ?? "";
                            break;
                    }
                }
            }
            result.CloseButtons.Add(new KbCloseButtonVm(name, scene, type));
        }

        result.SummaryText = $"知识库共 {total} 个按钮 / {result.Scenes.Count} 个场景";
        result.StatusText = $"已加载: {result.Scenes.Count} 个场景 + 关闭按钮 {result.CloseButtons.Count} 条";
        return result;
    }
}
