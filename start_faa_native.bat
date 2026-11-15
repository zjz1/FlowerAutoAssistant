@echo off
setlocal
rem ============================================================
rem  FAA 双入口之一 —— 启动原生窗口(native UI 版, 批 C4)
rem
rem  行为   : 优先启动 native\dist\FAA.WpfGui.exe(存在才启动);
rem           exe 缺失(原生版尚未发布)时打印中文提示, 并回退提示改用 start_webui.bat。
rem  布局   : 本脚本须放在仓库根目录(与 start_webui.bat / start_webui_app.bat 同级,
rem           native 为其子目录); native\FAA.WpfGui\build_native.bat 的发布产物即落在 native\dist。
rem  口径   : start_webui.bat / start_webui_app.bat 原样保留(webui 回退入口, 拍板 #2), 本脚本不改动它们。
rem  维护   : 本文件须保存为 UTF-8(无 BOM) + CRLF; 中文依赖首部 chcp 65001(同 build_native.bat 口径)。
rem ============================================================
chcp 65001 >nul

rem ---- 锚定到仓库根(本脚本所在目录) ----
cd /d "%~dp0"

set "EXE_PATH=%~dp0native\dist\FAA.WpfGui.exe"

if not exist "%EXE_PATH%" (
    echo [FAA] 未找到 native\dist\FAA.WpfGui.exe —— 原生窗口尚未发布。
    echo [FAA] 请先运行 native\FAA.WpfGui\build_native.bat 生成发布产物后再试。
    echo [FAA] 回退方案: 可继续使用浏览器版入口 start_webui.bat
    exit /b 1
)

echo [FAA] 启动原生窗口: %EXE_PATH%
echo [FAA] 浏览器版入口 start_webui.bat / start_webui_app.bat 仍可用(双轨并存)。
rem /D 让 exe 的工作目录落在 dist(路径解析基于 exe 所在目录向上发现后端, 不依赖双击位置)
start "" /D "%~dp0native\dist" "%EXE_PATH%"
exit /b 0
