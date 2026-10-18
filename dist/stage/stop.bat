@echo off
chcp 65001 >nul
title EasyTrader Dashboard — Stop
echo متوقف کردن سرور محلی...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='python3.12.exe'\" | Where-Object { $_.CommandLine -like '*server.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo انجام شد.
timeout /t 1 /nobreak >nul