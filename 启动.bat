@echo off
rem WeChat Ops Agent launcher: starts the local service as a hidden background
rem process (no console window stays open), then opens the operations console.
rem Use the stop script in this folder to stop the background service.
setlocal EnableExtensions
cd /d "%~dp0"

set "PORT=8000"

rem ---- Locate a suitable Python (project requires >=3.12,<3.14) ----
set "PYCMD="
py -3.13 -c "import sys" >nul 2>&1 && set "PYCMD=py -3.13"
if not defined PYCMD py -3.12 -c "import sys" >nul 2>&1 && set "PYCMD=py -3.12"
if not defined PYCMD python -c "import sys" >nul 2>&1 && set "PYCMD=python"

if not defined PYCMD (
    echo [ERROR] No usable Python was found.
    echo Install Python 3.12 or 3.13 and enable "Add python.exe to PATH" during setup.
    pause
    exit /b 1
)

%PYCMD% -c "import sys; sys.exit(0 if sys.version_info>=(3,12) and sys.version_info<(3,14) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] The detected Python version is not supported. Python 3.12 or 3.13 is required:
    %PYCMD% --version
    pause
    exit /b 1
)

rem ---- Install dependencies on first run ----
%PYCMD% -c "import fastapi, uvicorn, sqlalchemy, langgraph, alembic, apscheduler, jinja2, pydantic_settings" >nul 2>&1
if errorlevel 1 (
    echo First run: installing dependencies, this needs network access. Please wait...
    %PYCMD% -m pip install -e ".[dev]"
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed. Check the network and try again.
        pause
        exit /b 1
    )
)

rem ---- Reuse an already running service ----
netstat -ano | findstr /C:":%PORT% " | findstr /C:"LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo An existing local service was found; opening the operations console.
    start "" "http://127.0.0.1:%PORT%"
    ping -n 3 127.0.0.1 >nul
    exit /b 0
)

rem ---- Start the service as a hidden background process ----
rem Logs are written to runtime\uvicorn.out.log and runtime\uvicorn.err.log.
set "NO_PROXY=api.weixin.qq.com,api.deepseek.com,127.0.0.1,localhost"
if not exist runtime mkdir runtime
set "PYEXE="
for /f "delims=" %%F in ('%PYCMD% -c "import sys; print(sys.executable)"') do set "PYEXE=%%F"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $process = Start-Process -PassThru -WindowStyle Hidden -FilePath $env:PYEXE -ArgumentList @('-m','app.cli','serve','--host','127.0.0.1','--port','%PORT%','--no-reload') -WorkingDirectory $PWD -RedirectStandardOutput (Join-Path $PWD 'runtime\uvicorn.out.log') -RedirectStandardError (Join-Path $PWD 'runtime\uvicorn.err.log'); Set-Content -LiteralPath (Join-Path $PWD 'runtime\wechat-ops.pid') -Value $process.Id -Encoding ascii"
if errorlevel 1 (
    echo [ERROR] Failed to start the background service. Check runtime\uvicorn.err.log
    pause
    exit /b 1
)

echo The local service is starting in the background.
echo The operations console will open in your default browser when ready.
echo To stop it, double-click the stop script in this folder.
ping -n 4 127.0.0.1 >nul
exit /b 0
