using FAA.WpfGui.ViewModels;
using Xunit;

namespace FAA.WpfGui.Tests;

/// <summary>
/// OCR 线程数钳制用例(N02, batch-06)。语义 = webui.html:758-764 Math.max(0, Math.min(8, parseInt(v,10) || 0)):
/// 非数字/负数钳 0、&gt;8 钳 8、边界 0/8 保留。(SettingsViewModel.CommitOcrThreads 提纯对象)
/// </summary>
public sealed class SettingsClampsTests
{
    [Theory]
    [InlineData("2", 2, 2, true)]      // 常态
    [InlineData("0", 0, 0, true)]      // 下界
    [InlineData("8", 8, 8, true)]      // 上界
    [InlineData("9", 8, 9, true)]      // 超上界 → 钳 8(clamped != v → 回写输入框)
    [InlineData("-3", 0, -3, true)]    // 负数 → 钳 0(clamped != v → 回写输入框)
    [InlineData("abc", 0, 0, false)]   // 非数字 → 0 且 Numeric=false(回写 "0")
    [InlineData("", 0, 0, false)]      // 空 → 非数字
    [InlineData(" 3 ", 3, 3, true)]    // 首尾空白 Trim 后解析
    [InlineData("12", 8, 12, true)]    // 大值钳 8
    [InlineData("+4", 4, 4, true)]     // int.TryParse 接受符号位
    public void OcrThreads_ClampSemantics(string input, int clamped, int parsed, bool numeric)
    {
        var (c, p, n) = SettingsClamps.OcrThreads(input);
        Assert.Equal(clamped, c);
        Assert.Equal(parsed, p);
        Assert.Equal(numeric, n);
    }

    [Fact]
    public void OcrThreads_NullInput_TreatedAsNonNumeric()
    {
        var (c, p, n) = SettingsClamps.OcrThreads(null);
        Assert.Equal(0, c);
        Assert.Equal(0, p);
        Assert.False(n);
    }
}
