using System.Text.Json;
using FAA.WpfGui.Models;
using FAA.WpfGui.ViewModels;
using Xunit;

namespace FAA.WpfGui.Tests;

/// <summary>
/// 知识库解析用例(N02, batch-06; FlowViewModel.ParseKb 提纯对象 KbParser.Parse)。
/// 逐分支对照 webui.html:619-643: kbRow(:615)/场景名排序(:619)/非对象过滤/rel JSON 归一/sample_n
/// 「 · 均N」/旧扁平回退(:634-643)/关闭按钮行(:651)。
/// </summary>
public sealed class KbParserTests
{
    private static KbData ParseData(string json)
        => JsonSerializer.Deserialize<KbData>(json) ?? throw new InvalidOperationException("KbData 反序列化失败");

    [Fact]
    public void ScenesMode_SortedBySceneName_Ordinal()
    {
        var d = ParseData(
            "{\"click_log\":{\"scenes\":{\"场景B\":{\"b2\":{\"category\":\"作业\",\"rel\":[1,2],\"sample_n\":1}}," +
            "\"场景A\":{\"b1\":{\"category\":\"导航\",\"rel\":[0.5,0.25],\"sample_n\":3}}}},\"close_buttons\":[]}");
        var r = KbParser.Parse(d);
        Assert.Equal(2, r.Scenes.Count);
        Assert.Equal("场景A", r.Scenes[0].Name);      // Object.keys(scenes).sort() 同序
        Assert.Equal("场景B", r.Scenes[1].Name);
        Assert.Equal("导航", r.Scenes[0].Buttons[0].Category);
        Assert.Equal("作业", r.Scenes[1].Buttons[0].Category);
        Assert.Contains("2 个按钮", r.SummaryText);
        Assert.Contains("2 个场景", r.SummaryText);
    }

    [Fact]
    public void ScenesMode_ButtonDefaults_NameFromKey_CategoryOthers()
    {
        var d = ParseData(
            "{\"click_log\":{\"scenes\":{\"弹窗\":{\"btnKey\":{}}}},\"close_buttons\":[]}");
        var r = KbParser.Parse(d);
        var b = Assert.Single(r.Scenes[0].Buttons);
        Assert.Equal("btnKey", b.Name);               // b.name||键名(缺 name 用键名)
        Assert.Equal("其他", b.Category);             // b.category||"其他"
        Assert.Equal("[]", b.RelJson);                // JSON.stringify(b.rel||[])
        Assert.Equal(1, b.SampleN);
        Assert.Equal("其他", r.Scenes[0].CategoriesSummary);
        Assert.Equal(1, r.Scenes[0].ButtonCount);
        Assert.True(r.Scenes[0].IsExpanded);          // webui 初始 ▾ 展开
    }

    [Fact]
    public void ScenesMode_RelJsonNormalization_NonNumbersBecomeNull()
    {
        // rel 数组元素: 数字保原样(GetRawText), 非数字 → "null"(webui JSON.stringify 同形)
        var d = ParseData(
            "{\"click_log\":{\"scenes\":{\"s\":{\"b\":{\"rel\":[1,0.5,\"x\",null,true]}}}},\"close_buttons\":[]}");
        var r = KbParser.Parse(d);
        var b = Assert.Single(r.Scenes[0].Buttons);
        Assert.Equal("[1,0.5,null,null,null]", b.RelJson);
    }

    [Fact]
    public void ScenesMode_SampleNOverOne_AppendsMeanSuffix()
    {
        var d = ParseData(
            "{\"click_log\":{\"scenes\":{\"s\":{\"b\":{\"rel\":[1,2],\"sample_n\":3}}}},\"close_buttons\":[]}");
        var r = KbParser.Parse(d);
        var b = Assert.Single(r.Scenes[0].Buttons);
        Assert.Equal("[1,2] · 均3", b.RelText);       // RelJson 前缀 + sample_n > 1 显 " · 均N"(webui kbRow)
    }

    [Fact]
    public void ScenesMode_NonObjectButton_Skipped()
    {
        // webui filter(b => b && typeof b === "object"): 字符串值按钮被过滤
        var d = ParseData(
            "{\"click_log\":{\"scenes\":{\"s\":{\"real\":{\"category\":\"作业\"},\"junk\":\"not-an-object\"}}},\"close_buttons\":[]}");
        var r = KbParser.Parse(d);
        var b = Assert.Single(r.Scenes[0].Buttons);
        Assert.Equal("real", b.Name);
        Assert.Equal(1, r.Scenes[0].ButtonCount);
        Assert.Contains("1 个按钮", r.SummaryText);
    }

    [Fact]
    public void ScenesMode_CategorySummary_SortedOrdinalDistinct()
    {
        var d = ParseData(
            "{\"click_log\":{\"scenes\":{\"s\":{\"b1\":{\"category\":\"作业\"},\"b2\":{\"category\":\"导航\"},\"b3\":{\"category\":\"作业\"}}}},\"close_buttons\":[]}");
        var r = KbParser.Parse(d);
        Assert.Equal("作业 / 导航", r.Scenes[0].CategoriesSummary);   // SortedSet(Ordinal): 作(U+4F5C)<导(U+5BFC)
    }

    [Fact]
    public void ScenesMode_NonObjectScene_Skipped()
    {
        var d = ParseData(
            "{\"click_log\":{\"scenes\":{\"goodScene\":{\"b\":{}},\"badScene\":\"no\"}},\"close_buttons\":[]}");
        var r = KbParser.Parse(d);
        var scene = Assert.Single(r.Scenes);
        Assert.Equal("goodScene", scene.Name);
    }

    [Fact]
    public void FlatFallback_LegacyShape()
    {
        // 旧扁平格式(webui.html:634-643): 顶层键=按钮名, 值 {category, rel}
        var d = ParseData(
            "{\"click_log\":{\"btnA\":{\"category\":\"导航\",\"rel\":[0.5,0.5]},\"btnB\":{\"rel\":[]}},\"close_buttons\":[]}");
        var r = KbParser.Parse(d);
        var scene = Assert.Single(r.Scenes);
        Assert.Equal("知识库（旧版扁平格式）", scene.Name);
        Assert.Equal(2, scene.ButtonCount);
        Assert.Equal("导航", scene.Buttons[0].Category);
        Assert.Equal("[0.5,0.5]", scene.Buttons[0].RelJson);
        Assert.Equal("其他", scene.Buttons[1].Category);   // 旧格式缺 category → 默认
        Assert.Equal(1, scene.Buttons[0].SampleN);         // 旧格式无 sample_n → 1
        Assert.Contains("2 个按钮 / 1 个场景", r.SummaryText);
    }

    [Fact]
    public void FlatFallback_ScenesKeyNotObject_GoesToLegacyBranch()
    {
        // scenes 键存在但非对象(如字符串) → 落旧扁平分支, 且旧分支跳过 scenes 键
        var d = ParseData(
            "{\"click_log\":{\"scenes\":\"broken\",\"btn\":{\"category\":\"作业\"}},\"close_buttons\":[]}");
        var r = KbParser.Parse(d);
        var scene = Assert.Single(r.Scenes);
        var b = Assert.Single(scene.Buttons);
        Assert.Equal("btn", b.Name);
    }

    [Fact]
    public void EmptyClickLog_ZeroScenes()
    {
        var d = ParseData("{\"click_log\":{},\"close_buttons\":[]}");
        var r = KbParser.Parse(d);
        Assert.Empty(r.Scenes);
        Assert.Equal("知识库共 0 个按钮 / 0 个场景", r.SummaryText);
        Assert.Equal("已加载: 0 个场景 + 关闭按钮 0 条", r.StatusText);
    }

    [Fact]
    public void CloseButtons_ParsedWithDefaults()
    {
        var d = ParseData(
            "{\"click_log\":{\"scenes\":{\"s\":{\"b\":{}}}},\"close_buttons\":[" +
            "{\"name\":\"关闭\",\"scene\":\"弹窗\",\"type\":\"click\"},{\"name\":\"X\"},1]}");
        var r = KbParser.Parse(d);
        Assert.Equal(3, r.CloseButtons.Count);
        Assert.Equal(("关闭", "弹窗", "click"), (r.CloseButtons[0].Name, r.CloseButtons[0].Scene, r.CloseButtons[0].Type));
        Assert.Equal(("X", "通用", ""), (r.CloseButtons[1].Name, r.CloseButtons[1].Scene, r.CloseButtons[1].Type));   // scene||"通用"
        Assert.Equal(("", "通用", ""), (r.CloseButtons[2].Name, r.CloseButtons[2].Scene, r.CloseButtons[2].Type));   // 非对象 → 全默认
        Assert.Contains("关闭按钮 3 条", r.StatusText);
    }
}
