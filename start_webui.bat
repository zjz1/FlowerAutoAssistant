@echo off
rem Start FAA Web UI (self-test / usage mode).
rem Double-click to run, or:  start_webui.bat [port]
cd /d "%~dp0"

set PORT=%~1
if "%PORT%"=="" set PORT=8765

echo [FAA] Starting Web UI  http://127.0.0.1:%PORT%/
echo [FAA] Press Ctrl+C to exit
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe webui.py --port %PORT%
) else (
    python webui.py --port %PORT%
)
pause