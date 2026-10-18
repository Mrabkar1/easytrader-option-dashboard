@echo off
chcp 65001 >nul
title EasyTrader Option Dashboard
setlocal

echo ============================================
echo   EasyTrader Option - Local Dashboard
echo ============================================
echo.

REM ── اگر سرور قبلاً در حال اجراست، دوباره دان ست نمی کنیم ──
powershell -NoProfile -Command "$c = Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='python3.12.exe'\" | Where-Object { $_.CommandLine -like '*server.py*' }; if ($c) { Write-Host 'RUNNING' } else { Write-Host 'OK' }" > "%TEMP%\et_check.txt" 2>nul
findstr /C:"OK" "%TEMP%\et_check.txt" >nul 2>nul
if %errorlevel%==0 goto :start
echo سرور قبلاً در حال اجراست — باز کردن داشبورد...
timeout /t 2 /nobreak >nul
explorer http://127.0.0.1:8787
goto :end

:start
REM ── پیدا کردن Python ──
where python >nul 2>nul
if %errorlevel%==0 (
    start "EasyTrader Dash" /I python "%~dp0server.py"
    goto :end
)
where py >nul 2>nul
if %errorlevel%==0 (
    start "EasyTrader Dash" /I py "%~dp0server.py"
    goto :end
)

echo [خطا] Python پیدا نشد!
echo لطفاً Python 3 را از https://python.org نصب کنید.

:end
endlocal