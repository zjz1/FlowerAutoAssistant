@echo off
rem Start FAA native window shell (WebView2 / pywebview).
rem Double-click to run, or:  start_webui_app.bat [port]
rem Reuses a running instance on the same port; never opens the browser automatically.
cd /d "%~dp0"
chcp 65001 >nul

set PORT=%~1
if "%PORT%"=="" set PORT=8765

echo [FAA] Native window  http://127.0.0.1:%PORT%/
echo [FAA] An existing instance on this port will be reused (no duplicate server).
echo [FAA] Closing this window stops the shell.

if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe webui_app.py --port %PORT%
) else (
    python webui_app.py --port %PORT%
)

echo.
echo [FAA] Window closed.
timeout /t 3 >nul
