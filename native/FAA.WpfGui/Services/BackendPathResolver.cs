using System.IO;

namespace FAA.WpfGui.Services;

/// <summary>解析结果: 成功 = 两路径 + 来源诊断; 失败 = 中文报错(含已尝试路径清单)。
/// (原 FaaProcessHost 私有 record 随 N02 提纯升 internal; 字段语义零变化)</summary>
internal sealed record BackendResolution(
    string? VenvPython, string? WebUiScript, string? Error, string Diagnostics);

/// <summary>
/// 后端路径解析纯函数(N02 提纯自 FaaProcessHost.ResolveBackendPaths :48-144, batch-06 逐行等价迁移):
///   ①env 优先(已设置但无效即报错, 不静默回退发现链) ②exe 目录向上 ≤8 级发现 webui.py + 相邻 .venv
///   (venv 也可由 FAA_VENV_PY 提供) ③全部失败报中文错(含已尝试路径清单)。
/// 三个非纯依赖以参数注入(「env 以参数注入」口径, N02 方案表 #6): 进程级 env(FAA_BACKEND_DIR/
/// FAA_VENV_PY)、exe 所在目录(AppContext.BaseDirectory)、文件系统探针(File.Exists/Directory.Exists)。
/// FaaProcessHost 传真值(进程级 env/Lazy 缓存语义不变), 测试传桩 —— A2 探测三态语义可确定性单测。
/// </summary>
internal static class BackendPathResolver
{
    public static BackendResolution Resolve(
        string? envBackendDir, string? envVenvPy, string baseDirectory,
        Func<string, bool> fileExists, Func<string, bool> directoryExists)
    {
        var tried = new List<string>();   // 已尝试路径(报错清单)
        var notes = new List<string>();   // 各路径来源(成功诊断)

        // ① env FAA_BACKEND_DIR = 后端目录(含 webui.py)。已设置但无效 → 直接报错, 绝不静默回退发现链。
        string? webUiScript = null;
        var backendDir = envBackendDir;
        if (!string.IsNullOrWhiteSpace(backendDir))
        {
            var dir = Path.GetFullPath(backendDir.Trim());
            var script = Path.Combine(dir, "webui.py");
            tried.Add(script);
            if (fileExists(script))
            {
                webUiScript = script;
                notes.Add($"webui.py ← FAA_BACKEND_DIR={backendDir}");
            }
            else
            {
                return new BackendResolution(null, null,
                    $"环境变量 FAA_BACKEND_DIR 已设置但无效: 未找到 {script}"
                    + (directoryExists(dir) ? "(目录存在但缺 webui.py)" : "(该路径不存在或不是目录)")
                    + "\n按约定不回退自动发现链: 请修正 FAA_BACKEND_DIR, 或取消该环境变量后由程序自动查找。",
                    RenderTried(tried));
            }
        }

        // ① env FAA_VENV_PY = venv python.exe 全路径。同样: 已设置但无效即报错, 不静默回退。
        string? venvPython = null;
        var venvPy = envVenvPy;
        if (!string.IsNullOrWhiteSpace(venvPy))
        {
            var py = Path.GetFullPath(venvPy.Trim());
            tried.Add(py);
            if (fileExists(py))
            {
                venvPython = py;
                notes.Add($"venv python ← FAA_VENV_PY={venvPy}");
            }
            else
            {
                return new BackendResolution(null, null,
                    $"环境变量 FAA_VENV_PY 已设置但无效: 文件不存在 {py}"
                    + "\n按约定不回退自动发现链: 请修正 FAA_VENV_PY, 或取消该环境变量后由程序自动查找相邻 .venv。",
                    RenderTried(tried));
            }
        }

        // ② env 未提供后端脚本 → 从 exe 所在目录向上最多 8 级查找 FlowerAutoAssistant/webui.py
        if (webUiScript is null)
        {
            var exeDir = baseDirectory;
            var dir = new DirectoryInfo(exeDir);
            for (var level = 0; level <= 8 && dir is not null; level++, dir = dir.Parent)
            {
                var candidate = Path.Combine(dir.FullName, "FlowerAutoAssistant", "webui.py");
                tried.Add(candidate);
                if (fileExists(candidate))
                {
                    webUiScript = candidate;
                    notes.Add($"webui.py ← 自动发现(自 exe 目录 {exeDir} 向上 {level} 级): {candidate}");
                    break;
                }
            }
            if (webUiScript is null)
            {
                return new BackendResolution(null, null,
                    "未找到 FAA 后端脚本 webui.py: 已从 exe 所在目录向上最多 8 级查找 FlowerAutoAssistant/webui.py, 全部落空。\n"
                    + "已尝试路径:\n" + RenderTried(tried)
                    + "\n可设置环境变量 FAA_BACKEND_DIR 指向后端目录(含 webui.py)后重试。",
                    RenderTried(tried));
            }
        }

        // venv 校验: env 未提供时取 webui.py 相邻 .venv/Scripts/python.exe(引擎依赖 torch/onnx 等只在 venv 里)
        if (venvPython is null)
        {
            var backendRoot = Path.GetDirectoryName(Path.GetFullPath(webUiScript));
            var adjacent = Path.Combine(backendRoot ?? ".", ".venv", "Scripts", "python.exe");
            tried.Add(adjacent);
            if (fileExists(adjacent))
            {
                venvPython = adjacent;
                notes.Add($"venv python ← 相邻 .venv: {adjacent}");
            }
            else
            {
                return new BackendResolution(null, null,
                    $"已找到后端脚本 {webUiScript}, 但未找到 venv python(已尝试 {adjacent})。"
                    + "\n引擎依赖(torch/onnx 等)只在 venv 里; 可设置环境变量 FAA_VENV_PY 指向 python.exe 全路径后重试。",
                    RenderTried(tried));
            }
        }

        return new BackendResolution(venvPython, webUiScript, null, string.Join("; ", notes));
    }

    /// <summary>已尝试路径清单渲染(报错与诊断共用)。</summary>
    private static string RenderTried(List<string> tried)
        => tried.Count == 0 ? "(无)" : string.Join("\n", tried.Select(p => $"  {p}"));
}
