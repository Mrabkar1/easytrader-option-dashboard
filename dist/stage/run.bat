@echo off
title EasyTrader Option Dashboard - FastAPI

cd /d "%~dp0"

REM ---- Single instance: stop any running api_server / legacy server ----
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='python3.12.exe' OR Name='py.exe'\" | Where-Object { $_.CommandLine -like '*api_server.py*' -or $_.CommandLine -like '*server.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>nul
ping -n 2 127.0.0.1 >nul

REM ---- Find Python ----
set "PYEXE="
where python >nul 2>nul && set "PYEXE=python"
if not defined PYEXE where py >nul 2>nul && set "PYEXE=py"
if not defined PYEXE (
    echo [ERROR] Python not found. Install from python.org first.
    pause
    exit /b 1
)

echo ============================================
echo   EasyTrader Option Dashboard (FastAPI)
echo   http://127.0.0.1:8787
echo   Swagger: http://127.0.0.1:8787/docs
echo ============================================
echo.

start "EasyTrader Dash" /I %PYEXE% "%~dp0api_server.py"

REM ---- Wait for server to be ready (up to ~10s), then open browser ----
for /l %%i in (1,1,12) do (
    python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health')" >nul 2>nul
    if not errorlevel 1 goto :opened
    ping -n 2 127.0.0.1 >nul
)
:opened
explorer http://127.0.0.1:8787