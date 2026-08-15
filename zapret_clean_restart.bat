@echo off
chcp 65001 >nul
cd /d "%~dp0"
net file >nul 2>&1
if %errorlevel% NEQ 0 (
  echo Requesting administrator privileges...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
echo Stopping ZapretikWatchdog task...
schtasks /End /TN "ZapretikWatchdog" >nul 2>&1
timeout /t 2 >nul
echo Killing all pythonw (including elevated orphans)...
taskkill /F /IM pythonw.exe >nul 2>&1
timeout /t 2 >nul
echo Starting ZapretikWatchdog task fresh...
schtasks /Run /TN "ZapretikWatchdog" >nul 2>&1
timeout /t 6 >nul
echo Done. Press any key to close.
pause >nul
