using FAA.WpfGui.Services;
using Xunit;

namespace FAA.WpfGui.Tests;

/// <summary>
/// 后端路径解析用例(N02, batch-06; FaaProcessHost.ResolveBackendPaths 提纯对象 BackendPathResolver.Resolve)。
/// A2 三态语义: ①env 优先(已设置但无效**直接报错, 绝不静默回退发现链**) ②exe 目录向上 ≤8 级发现
/// webui.py + 相邻 .venv(venv 未由 env 提供时, 无论 webui.py 来自 env 还是发现都校验相邻 .venv)
/// ③全失败给中文报错(含已尝试路径清单)。env/exe 目录/文件系统探针全参数注入(用例传桩, 生产传真值)。
/// </summary>
public sealed class BackendPathResolverTests
{
    // 假 exe 目录: C:\fake\bin\Release\net8.0-windows\ (向上链: Release → bin → fake → C:\)
    private const string BaseDir = @"C:\fake\bin\Release\net8.0-windows\";
    private const string WebUiAtFakeRoot = @"C:\fake\FlowerAutoAssistant\webui.py";
    private const string AdjacentVenv = @"C:\fake\FlowerAutoAssistant\.venv\Scripts\python.exe";

    /// <summary>文件系统桩: 仅认给定路径集存在。</summary>
    private static Func<string, bool> Fs(params string[] existing)
    {
        var set = new HashSet<string>(existing, StringComparer.OrdinalIgnoreCase);
        return p => set.Contains(p);
    }

    private static BackendResolution Resolve(
        string? backendDir = null, string? venvPy = null, string? backendExe = null,
        Func<string, bool>? fileExists = null, Func<string, bool>? directoryExists = null)
        => BackendPathResolver.Resolve(backendDir, venvPy, backendExe, BaseDir,
            fileExists ?? Fs(), directoryExists ?? (_ => false));

    [Fact]
    public void EnvBackendDir_Valid_TakesPrecedence_WithAdjacentVenvCheck()
    {
        var r = Resolve(backendDir: @"C:\backend\",
            fileExists: Fs(@"C:\backend\webui.py", @"C:\backend\.venv\Scripts\python.exe"));
        Assert.Null(r.Error);
        Assert.Equal(@"C:\backend\webui.py", r.WebUiScript);   // GetFullPath 去尾斜杠后拼接
        Assert.Equal(@"C:\backend\.venv\Scripts\python.exe", r.VenvPython);   // venv 未提供 → 相邻 .venv 校验
        Assert.Contains("FAA_BACKEND_DIR", r.Diagnostics);
    }

    [Fact]
    public void EnvBackendDir_Invalid_HardError_NoSilentFallback()
    {
        // env 已设置但无效 → 直接报错, 即使自动发现链能命中也绝不回退(A2 红线)
        var r = Resolve(backendDir: @"C:\missing\",
            fileExists: p => p == WebUiAtFakeRoot || p == AdjacentVenv);
        Assert.NotNull(r.Error);
        Assert.Contains("FAA_BACKEND_DIR 已设置但无效", r.Error);
        Assert.Contains(@"C:\missing\webui.py", r.Error);
        Assert.Null(r.WebUiScript);
        Assert.Null(r.VenvPython);
    }

    [Fact]
    public void EnvBackendDir_DirExistsButMissingScript_ErrorMessageNamesIt()
    {
        var r = Resolve(backendDir: @"C:\backend\", directoryExists: _ => true);
        Assert.NotNull(r.Error);
        Assert.Contains("(目录存在但缺 webui.py)", r.Error);
    }

    [Fact]
    public void EnvVenvPy_Invalid_HardError_EvenWhenAdjacentVenvExists()
    {
        var r = Resolve(backendDir: @"C:\backend\",   // 后端由 env 提供, 但 venv 指了个不存在的文件
            venvPy: @"C:\nowhere\python.exe",
            fileExists: p => p == @"C:\backend\webui.py" || p == AdjacentVenv);
        Assert.NotNull(r.Error);
        Assert.Contains("FAA_VENV_PY 已设置但无效", r.Error);
        Assert.Contains(@"C:\nowhere\python.exe", r.Error);
    }

    [Fact]
    public void EnvVenvPy_Valid_UsedDirectly()
    {
        var r = Resolve(backendDir: @"C:\backend\",
            venvPy: @"C:\myvenv\python.exe",
            fileExists: p => p == @"C:\backend\webui.py" || p == @"C:\myvenv\python.exe");
        Assert.Null(r.Error);
        Assert.Equal(@"C:\myvenv\python.exe", r.VenvPython);   // env 优先, 不查相邻 .venv
        Assert.Contains("FAA_VENV_PY", r.Diagnostics);
    }

    [Fact]
    public void Discovery_FindsWebuiByWalkingUp_ThenAdjacentVenv()
    {
        // 无 env: 自 exe 目录向上 ≤8 级发现 fake\FlowerAutoAssistant\webui.py(3 级) + 相邻 .venv
        var r = Resolve(fileExists: p => p == WebUiAtFakeRoot || p == AdjacentVenv);
        Assert.Null(r.Error);
        Assert.Equal(WebUiAtFakeRoot, r.WebUiScript);
        Assert.Equal(AdjacentVenv, r.VenvPython);
        Assert.Contains("向上 3 级", r.Diagnostics);
        Assert.Contains("相邻 .venv", r.Diagnostics);
    }

    [Fact]
    public void Discovery_WebuiFound_ButNoAdjacentVenv_HardError()
    {
        var r = Resolve(fileExists: p => p == WebUiAtFakeRoot);
        Assert.NotNull(r.Error);
        Assert.Contains("已找到后端脚本", r.Error);
        Assert.Contains("未找到 venv python", r.Error);
        Assert.Contains("已尝试", r.Error);
        Assert.Contains(AdjacentVenv, r.Error);       // 报错清单含相邻 venv 候选路径
    }

    [Fact]
    public void Discovery_AllLevelsMiss_HardErrorWithTriedList()
    {
        var r = Resolve(fileExists: _ => false);
        Assert.NotNull(r.Error);
        Assert.Contains("未找到 FAA 后端", r.Error);
        Assert.Contains("向上最多 8 级", r.Error);
        Assert.Contains("FAA_BACKEND_DIR", r.Error);  // 指引设置 env
        // 假 exe 目录链 0-4 级共 5 个候选全部入已尝试清单
        Assert.Contains(@"C:\fake\bin\Release\net8.0-windows\FlowerAutoAssistant\webui.py", r.Error);
        Assert.Contains(@"C:\fake\bin\Release\FlowerAutoAssistant\webui.py", r.Error);
        Assert.Contains(@"C:\fake\bin\FlowerAutoAssistant\webui.py", r.Error);
        Assert.Contains(@"C:\fake\FlowerAutoAssistant\webui.py", r.Error);
        Assert.Contains(@"C:\FlowerAutoAssistant\webui.py", r.Error);
    }

    [Fact]
    public void EnvWhitespace_Only_IsTreatedAsUnset()
    {
        // env 为空白 → 视同未设置(NullOrWhiteSpace 守卫), 走自动发现
        var r = Resolve(backendDir: "   ",
            fileExists: p => p == WebUiAtFakeRoot || p == AdjacentVenv);
        Assert.Null(r.Error);
        Assert.Equal(WebUiAtFakeRoot, r.WebUiScript);
    }

    [Fact]
    public void EnvBackendDir_TrailingSpace_TrimmedForProbe()
    {
        // env 带首尾空白: 探测用 Trim 后路径, 诊断保留 env 原文
        var r = Resolve(backendDir: @"C:\backend  ",
            fileExists: Fs(@"C:\backend\webui.py", @"C:\backend\.venv\Scripts\python.exe"));
        Assert.Null(r.Error);
        Assert.Equal(@"C:\backend\webui.py", r.WebUiScript);
        Assert.Contains(@"C:\backend  ", r.Diagnostics);   // 诊断记 env 原文
    }

    // ==================== Phase 2: 打包后端(faa_webui.exe) ====================

    private const string PackagedExe = @"C:\fake\bin\Release\net8.0-windows\backend\faa_webui.exe";

    [Fact]
    public void PackagedLayout_Discovered_WhenNoSourceEnv()
    {
        // 便携包: <exe 目录>/backend/faa_webui.exe 命中 → 无需 venv/webui.py
        var r = Resolve(fileExists: p => p == PackagedExe);
        Assert.Null(r.Error);
        Assert.Equal(PackagedExe, r.BackendExe);
        Assert.Null(r.VenvPython);
        Assert.Null(r.WebUiScript);
        Assert.Contains("便携包布局", r.Diagnostics);
    }

    [Fact]
    public void EnvBackendExe_Valid_TakesPrecedence_AndSkipsVenv()
    {
        var r = Resolve(backendExe: @"C:\pkg\faa_webui.exe",
            fileExists: p => p == @"C:\pkg\faa_webui.exe" || p == PackagedExe);
        Assert.Null(r.Error);
        Assert.Equal(@"C:\pkg\faa_webui.exe", r.BackendExe);
        Assert.Contains("FAA_BACKEND_EXE", r.Diagnostics);
    }

    [Fact]
    public void EnvBackendExe_Invalid_HardError_NoSilentFallback()
    {
        // env 已设置但无效 → 直接报错, 即使便携包布局能命中也绝不回退(A2 红线)
        var r = Resolve(backendExe: @"C:\missing\faa_webui.exe",
            fileExists: p => p == PackagedExe || p == WebUiAtFakeRoot || p == AdjacentVenv);
        Assert.NotNull(r.Error);
        Assert.Contains("FAA_BACKEND_EXE 已设置但无效", r.Error);
        Assert.Null(r.BackendExe);
    }

    [Fact]
    public void SourceEnv_Valid_BeatsPackagedLayout()
    {
        // 源码 env 显式提供时, 便携包布局不介入(env 优先)
        var r = Resolve(backendDir: @"C:\backend\",
            fileExists: p => p == @"C:\backend\webui.py" || p == @"C:\backend\.venv\Scripts\python.exe"
                || p == PackagedExe);
        Assert.Null(r.Error);
        Assert.Null(r.BackendExe);
        Assert.Equal(@"C:\backend\webui.py", r.WebUiScript);
    }

    [Fact]
    public void PackagedLayout_Missing_AndNoSource_FallsThroughToError()
    {
        // 便携包缺 backend/faa_webui.exe, 且向上发现全部落空 → 报错含两类指引
        var r = Resolve(fileExists: _ => false);
        Assert.NotNull(r.Error);
        Assert.Contains("FAA_BACKEND_EXE", r.Error);
        Assert.Contains("FAA_BACKEND_DIR", r.Error);
        Assert.Contains("backend", r.Error);
    }
}
