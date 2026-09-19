@echo off
rem WeChat Ops Agent launcher: uses the system Python directly, no virtual environment needed.
setlocal EnableExtensions
cd /d "%~dp0"

title WeChat Ops Agent

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
echo Checking whether the local service is already running...
netstat -ano | findstr /C:":%PORT% " | findstr /C:"LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo An existing local service was found; opening the operations console.
    start "" "http://127.0.0.1:8000"
    exit /b 0
)

echo Starting the local service in this window...
echo The operations console will open in your default browser when ready.
echo Close this window to stop the service.
%PYCMD% -m app.cli serve --host 127.0.0.1 --port %PORT%
if errorlevel 1 (
    echo.
    echo [ERROR] The service failed to start. Share the error above for support.
    pause
)
exit /b %errorlevel%
