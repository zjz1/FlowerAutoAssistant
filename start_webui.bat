@echo off
rem Start FAA Web UI (self-test / usage mode).
rem Double-click to run, or:  start_webui.bat [port] [adb_address]
cd /d "%~dp0"

set PORT=%~1
if "%PORT%"=="" set PORT=8765

echo [FAA] Starting Web UI  http://127.0.0.1:%PORT%/
echo [FAA] The browser will open automatically.
echo [FAA] Close the service via the web page button, or press Ctrl+C here to exit.

rem Open browser briefly after server starts.
start "" /b powershell -NoProfile -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:%PORT%/'"

if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe webui.py --port %PORT% %2 %3 %4
) else (
    python webui.py --port %PORT% %2 %3 %4
)

echo.
echo [FAA] Web UI has stopped. This window will close.
timeout /t 3 >nul