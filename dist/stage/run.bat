@echo off
chcp 65001 >nul
title EasyTrader Option Dashboard

setlocal
cd /d "%~dp0"

REM ---- Single instance check ----
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='python3.12.exe' OR Name='py.exe'\" | Where-Object { $_.CommandLine -like '*server.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>nul

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
echo   EasyTrader Option Dashboard
echo   http://127.0.0.1:8787
echo ============================================
echo.

start "EasyTrader Dash" /I %PYEXE% "%~dp0server.py"
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8787
