# run_selftest.ps1 - FAA.WpfGui 自测启动器(批 21; N02/batch-06 增 -RunUnitTests 分支)。
# 用途: 统一脚本可改调本启动器跑自测 —— 自动补 DOTNET_ROOT(本机 dotnet 为用户级安装
#       C:\Users\zjz1\AppData\Local\Microsoft\dotnet, 无全局安装; exe 是框架依赖 WinExe,
#       apphost 靠 DOTNET_ROOT 找 hostfxr, 不设则卡「缺少运行时」且无任何输出)。
#       透传真实退出码(SELFTEST PASS=0 / FAIL=1)。
# 用法: powershell -NoProfile -ExecutionPolicy Bypass -File run_selftest.ps1 --api-selftest <url> <outfile> <all|get-only>
#       powershell -NoProfile -ExecutionPolicy Bypass -File run_selftest.ps1 --sse-selftest <url> <outfile> <seconds>
#       powershell -NoProfile -ExecutionPolicy Bypass -File run_selftest.ps1 -RunUnitTests
#         (N02, batch-06: 第五条链 —— C# 纯函数单元测试 dotnet test FAA.WpfGui.Tests, 透传退出码)
# 说明: 带空格的 outfile 即使被外层 shell 拆成多个 token, exe 端(批 21 C# 修复)也会按
#       自测语法把中段 token 回拼为原路径, 故本启动器只做逐元素引号包裹, 不做拼接假设。
$ErrorActionPreference = "Stop"
if (-not $env:DOTNET_ROOT) {
    $env:DOTNET_ROOT = 'C:\Users\zjz1\AppData\Local\Microsoft\dotnet'
}
# N02(batch-06): -RunUnitTests → dotnet test Tests 工程(与四条 exe 自测链并列, 结果只看退出码)
if ($args.Count -gt 0 -and $args[0] -eq '-RunUnitTests') {
    # 2026-11-18: 测试工程与 FAA.WpfGui 同级（native\FAA.WpfGui.Tests），不是子目录。
    # PowerShell 5.1 下 -File 调用时 $PSScriptRoot 偶发为空，退回 $MyInvocation 定位脚本目录。
    $scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
    $testsProj = Join-Path (Split-Path $scriptDir -Parent) 'FAA.WpfGui.Tests\FAA.WpfGui.Tests.csproj'
    if (-not (Test-Path $testsProj)) {
        Write-Error "未找到测试工程: $testsProj"
        exit 1
    }
    $dotnet = Get-Command dotnet -ErrorAction SilentlyContinue
    $dotnetExe = if ($dotnet) { $dotnet.Source } else { Join-Path $env:DOTNET_ROOT 'dotnet.exe' }
    & $dotnetExe test $testsProj -nologo -v q
    exit $LASTEXITCODE
}
$exe = Join-Path $PSScriptRoot 'bin\Release\net8.0-windows\FAA.WpfGui.exe'
$quoted = $args | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }
$p = Start-Process -FilePath $exe -ArgumentList $quoted -PassThru -Wait -WindowStyle Hidden
exit $p.ExitCode
