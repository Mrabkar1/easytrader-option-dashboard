@echo off
title EasyTrader Option Dashboard - Installer
cd /d "%~dp0"

echo ============================================================
echo   EasyTrader Option Dashboard - Installer
echo   (read-only - never places orders)
echo ============================================================
echo.

REM ---- Install folder (no admin rights needed) ----
set "APPDIR=%LOCALAPPDATA%\EasyTraderDashboard"

REM ---- Check Python (required) ----
set "PYEXE="
where python >nul 2>nul && set "PYEXE=python"
if not defined PYEXE where py >nul 2>nul && set "PYEXE=py"
if not defined PYEXE (
    echo   [ERROR] Python 3 was not found!
    echo.
    echo   Please install Python from: https://www.python.org/downloads/
    echo   Check "Add Python to PATH" during setup,
    echo   then run this installer again.
    echo.
    start "" https://www.python.org/downloads/
    pause
    exit /b 1
)
echo   [1/5] Python found: %PYEXE%

REM ---- Stop any previous instance ----
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='python3.12.exe' OR Name='py.exe'\" | Where-Object { $_.CommandLine -like '*.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>nul
echo   [2/6] Previous instances stopped.

REM ---- Install Python dependencies (FastAPI + Uvicorn) ----
echo   [3/6] Installing FastAPI + Uvicorn (via pip)...
%PYEXE% -m pip install -r "%~dp0requirements.txt" --quiet --disable-pip-version-check >nul 2>&1
%PYEXE% -c "import fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
    echo   [WARN] pip install failed - fastapi not available.
    echo   Try manually:  %PYEXE% -m pip install fastapi uvicorn
) else (
    echo         dependencies OK.
)

REM ---- Copy files ----
if not exist "%APPDIR%" mkdir "%APPDIR%"
if not exist "%APPDIR%\static" mkdir "%APPDIR%\static"
copy /y "server.py" "%APPDIR%\" >nul
copy /y "dashboard.html" "%APPDIR%\" >nul
copy /y "get-token.html" "%APPDIR%\" >nul
copy /y "save-token.html" "%APPDIR%\" >nul
copy /y "run.bat" "%APPDIR%\" >nul
copy /y "stop.bat" "%APPDIR%\" >nul
copy /y "README.md" "%APPDIR%\" >nul
copy /y "static\app.js" "%APPDIR%\static\" >nul
copy /y "static\style.css" "%APPDIR%\static\" >nul
if exist "%APPDIR%\auth.json" echo   (previous session token preserved)
echo   [4/6] Files installed to %APPDIR%

REM ---- Shortcuts: Desktop + Start Menu + Startup ----
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$dt = [Environment]::GetFolderPath('Desktop');" ^
  "$sm = [Environment]::GetFolderPath('Programs');" ^
  "$su = [Environment]::GetFolderPath('Startup');" ^
  "$L1 = $ws.CreateShortcut((Join-Path $dt 'EasyTrader Dashboard.lnk')); $L1.TargetPath='%APPDIR%\run.bat'; $L1.WorkingDirectory='%APPDIR%'; $L1.Description='EasyTrader Option Dashboard + API'; $L1.WindowStyle=7; $L1.Save();" ^
  "$L2 = $ws.CreateShortcut((Join-Path $sm 'EasyTrader Dashboard.lnk')); $L2.TargetPath='%APPDIR%\run.bat'; $L2.WorkingDirectory='%APPDIR%'; $L2.Save();" ^
  "$L3 = $ws.CreateShortcut((Join-Path $su 'EasyTrader Dashboard.lnk')); $L3.TargetPath='%APPDIR%\run.bat'; $L3.WorkingDirectory='%APPDIR%'; $L3.Description='Auto-start EasyTrader Dashboard'; $L3.WindowStyle=7; $L3.Save();"
echo   [5/6] Shortcuts created (Desktop / Start Menu / auto-start on boot)

REM ---- First launch ----
echo   [6/6] Starting dashboard + API server...
cd /d "%APPDIR%"
start "EasyTrader Dash" /I %PYEXE% "%APPDIR%\api_server.py"
timeout /t 3 /nobreak >nul
start "" http://127.0.0.1:8787/get-token

echo.
echo ============================================================
echo   Installation complete!
echo   Dashboard URL:  http://127.0.0.1:8787
echo   Uninstall:      uninstall.bat (in this package)
echo ============================================================
echo.
echo Note: Do not close the Python window (minimize it instead).
echo       Closing that window stops the dashboard.
pause
