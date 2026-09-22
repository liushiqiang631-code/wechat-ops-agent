@echo off
rem Stops only the background WeChat Ops Agent process recorded by the launcher.
setlocal EnableExtensions
cd /d "%~dp0"

set "PID_FILE=runtime\wechat-ops.pid"

if not exist "%PID_FILE%" (
    echo No service process recorded by this project. Nothing to stop.
    ping -n 3 127.0.0.1 >nul
    exit /b 0
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $pidPath = Join-Path $PWD 'runtime\wechat-ops.pid'; $raw = Get-Content -LiteralPath $pidPath -Raw; $targetPid = 0; if (-not [int]::TryParse($raw.Trim(), [ref]$targetPid)) { exit 2 }; $process = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $targetPid) -ErrorAction SilentlyContinue; if ($null -eq $process) { Remove-Item -LiteralPath $pidPath -Force; exit 0 }; if ($process.CommandLine -notmatch '(?i)-m\s+app\.cli\s+serve') { exit 3 }; Stop-Process -Id $targetPid -Force; Remove-Item -LiteralPath $pidPath -Force"
if errorlevel 3 (
    echo [ERROR] Refusing to stop the recorded PID because it is not this project's service.
    pause
    exit /b 1
)
if errorlevel 2 (
    echo [ERROR] The service PID file is invalid. Delete runtime\wechat-ops.pid after checking it.
    pause
    exit /b 1
)
if errorlevel 1 (
    echo [ERROR] Failed to stop the recorded service process.
    pause
    exit /b 1
)

echo The background service has been stopped.
ping -n 3 127.0.0.1 >nul
exit /b 0
