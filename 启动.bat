@echo off
rem WeChat Ops Agent launcher. Runs the local service and opens the browser after health succeeds.
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "PYTHON=.venv\Scripts\python.exe"

title WeChat Ops Agent

if not exist "%PYTHON%" (
    echo [ERROR] Virtual environment Python was not found: %PYTHON%
    echo Run: .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
    echo Then copy .env.example to .env and configure local credentials.
    pause
    exit /b 1
)

echo Checking whether the local service is already running...
netstat -ano | findstr /C:":8000 " | findstr /C:"LISTENING" >nul 2>&1
if not errorlevel 1 goto open_existing_console

echo Starting the local service in this window...
echo The operations console will open in your default browser when ready.
"%PYTHON%" -m app.cli serve
exit /b %errorlevel%

:open_existing_console
echo An existing local service was found; opening the operations console.
start "" "http://127.0.0.1:8000"
exit /b 0
