namespace FAA.WpfGui.ViewModels;

/// <summary>
/// 设置页输入钳制纯函数(N02 提纯, batch-06): 解析/钳制计算与 VM 提交副作用分离, 语义可确定性单测。
/// 钳制语义以 webui 前端为准(08/05 笔记 :147-166 钳制对照)。
/// </summary>
internal static class SettingsClamps
{
    /// <summary>
    /// OCR 线程数解析钳制(D2, webui.html:758-764 实读核对):
    /// 服务端/前端语义 = Math.max(0, Math.min(8, parseInt(v,10) || 0)) —— 非数字/负数钳 0、&gt;8 钳 8。
    /// 返回 (Clamped 钳制值, Parsed 原始解析值[非数字=0], Numeric 是否解析为数字) ——
    /// Parsed/Numeric 供调用方复现「非法输入回写 0 / 钳制后回写输入框」的原判序(clamped != v)。
    /// </summary>
    public static (int Clamped, int Parsed, bool Numeric) OcrThreads(string? text)
    {
        var numeric = int.TryParse(text?.Trim(), out var v);
        if (!numeric)
        {
            v = 0;   // 非数字: webui parseInt → NaN → ||0
        }
        var clamped = Math.Max(0, Math.Min(8, v));
        return (clamped, v, numeric);
    }
}
