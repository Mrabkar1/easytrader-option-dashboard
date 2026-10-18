@echo off
title EasyTrader Option Dashboard - Uninstall

echo ============================================================
echo   Uninstalling EasyTrader Option Dashboard
echo ============================================================
echo.

echo   [1/3] Stopping server...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='python3.12.exe' OR Name='py.exe'\" | Where-Object { $_.CommandLine -like '*server.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>nul

echo   [2/3] Removing shortcuts...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$dt = [Environment]::GetFolderPath('Desktop');" ^
  "$sm = [Environment]::GetFolderPath('Programs');" ^
  "$su = [Environment]::GetFolderPath('Startup');" ^
  "Remove-Item (Join-Path $dt 'EasyTrader Dashboard.lnk') -ErrorAction SilentlyContinue;" ^
  "Remove-Item (Join-Path $sm 'EasyTrader Dashboard.lnk') -ErrorAction SilentlyContinue;" ^
  "Remove-Item (Join-Path $su 'EasyTrader Dashboard.lnk') -ErrorAction SilentlyContinue;"

echo   [3/3] Removing files (auth.json token is also removed)...
powershell -NoProfile -Command "Remove-Item \"$env:LOCALAPPDATA\EasyTraderDashboard\" -Recurse -Force -ErrorAction SilentlyContinue"

echo.
echo   Uninstallation complete.
echo.
pause
