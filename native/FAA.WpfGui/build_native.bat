@echo off
setlocal
rem ============================================================
rem  NP4 定版发布脚本 —— FAA.WpfGui self-contained 单文件发布
rem
rem  产物   : dist\FAA.WpfGui.exe（self-contained 单文件，零 .NET 运行时依赖）
rem  落位   : dist 取「本脚本上一级目录」下的 dist，两种布局同一相对规则：
rem           主仓库合并后  = FlowerAutoAssistant\native\dist
rem           zcode 工作空间 = _coagent\FAA_basis-zcode\_nativeui\dist
rem  口径   : 产物 dist 目录不入库，本脚本入库；主管线 join 后统一执行并校验产物。
rem           脚本内不设 pause，双击运行结束后窗口自动关闭（避免挂起自动化调用）。
rem  失败   : errorlevel = 1，错误行以 [错误] 前缀打印。
rem  维护   : 本文件须保存为 UTF-8（无 BOM）+ CRLF；中文依赖首部 chcp 65001。
rem ============================================================
chcp 65001 >nul

rem ---- 0. 锚定到工程目录（本脚本与 FAA.WpfGui.csproj 同目录）----
cd /d "%~dp0"
if not exist "FAA.WpfGui.csproj" (
    echo [错误] 未找到 FAA.WpfGui.csproj，本脚本须放在工程目录内运行。
    exit /b 1
)

rem ---- 1. dotnet 自举：先探测 PATH，探测不到再退回用户级安装目录 ----
set "DOTNET_EXE="
set "DOTNET_ROOT="
where dotnet >nul 2>&1
if not errorlevel 1 set "DOTNET_EXE=dotnet"
if not defined DOTNET_EXE if exist "%LOCALAPPDATA%\Microsoft\dotnet\dotnet.exe" (
    set "DOTNET_EXE=%LOCALAPPDATA%\Microsoft\dotnet\dotnet.exe"
    set "DOTNET_ROOT=%LOCALAPPDATA%\Microsoft\dotnet"
)
if not defined DOTNET_EXE (
    echo [错误] 未找到 dotnet：PATH 探测失败，且 %LOCALAPPDATA%\Microsoft\dotnet\dotnet.exe 不存在。
    echo        请安装 .NET 8 SDK（https://aka.ms/dotnet/download）后重试。
    exit /b 1
)
echo [信息] dotnet      : %DOTNET_EXE%
if defined DOTNET_ROOT echo [信息] DOTNET_ROOT : %DOTNET_ROOT%
if not defined DOTNET_ROOT echo [信息] DOTNET_ROOT : 未设置（dotnet 取自 PATH，运行时解析交由系统）

rem ---- 2. 单元测试（N02, batch-06: Tests 工程 dotnet test；失败即终止发布）----
rem 测试工程 FAA.WpfGui.Tests 与主工程目录互为同级（sln 内 ..\FAA.WpfGui.Tests\ 引用），同解 net8.0-windows。
if not exist "..\FAA.WpfGui.Tests\FAA.WpfGui.Tests.csproj" (
    echo [错误] 未找到测试工程 ..\FAA.WpfGui.Tests\FAA.WpfGui.Tests.csproj（N02 测试基建残缺）。
    exit /b 1
)
echo [执行] dotnet test FAA.WpfGui.Tests（单元测试未全绿则发布终止）
"%DOTNET_EXE%" test "..\FAA.WpfGui.Tests\FAA.WpfGui.Tests.csproj" -nologo -v q
if errorlevel 1 (
    echo [错误] dotnet test 失败（单元测试未全绿）。发布终止。
    exit /b 1
)

rem ---- 3. dist 输出目录 = 本脚本上一级（即 native 目录）下的 dist ----
for %%I in ("..") do set "NATIVE_DIR=%%~fI"
set "DIST_DIR=%NATIVE_DIR%\dist"
echo [信息] dist 输出   : %DIST_DIR%

rem ---- 4. 清空重建 dist（保证产物只来自本次发布）----
if exist "%DIST_DIR%" rd /s /q "%DIST_DIR%"
if not exist "%DIST_DIR%" mkdir "%DIST_DIR%"

rem ---- 5. self-contained 单文件发布（win-x64）----
rem 注意：WPF 不支持裁剪，本命令不得追加 PublishTrimmed。
echo [执行] dotnet publish -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -o "%DIST_DIR%"
"%DOTNET_EXE%" publish "FAA.WpfGui.csproj" -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -o "%DIST_DIR%"
if errorlevel 1 (
    echo [错误] dotnet publish 失败。dist 目录保留现场（可能含半成品）供排查。
    exit /b 1
)

rem ---- 6. 校验产物并打印路径与大小 ----
set "EXE_PATH=%DIST_DIR%\FAA.WpfGui.exe"
if not exist "%EXE_PATH%" (
    echo [错误] 产物缺失：%EXE_PATH%
    exit /b 1
)
for %%F in ("%EXE_PATH%") do set "EXE_BYTES=%%~zF"
set /a EXE_MB=%EXE_BYTES% / 1048576
echo.
echo ==================== 发布完成 ====================
echo  产物路径 : %EXE_PATH%
echo  产物大小 : %EXE_BYTES% 字节（约 %EXE_MB% MB）
echo --------------------------------------------------
echo  dist 目录内容（单文件发布模式可能伴随少量 WPF 原生 DLL，属正常现象）：
dir /b /a:-d "%DIST_DIR%"
echo ==================================================
exit /b 0
