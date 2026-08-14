@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=C:\Users\Leonid\AppData\Local\Programs\Python\Python312\python.exe
net file >nul 2>&1
if %errorlevel% NEQ 0 (
  echo Requesting administrator privileges...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
echo Reinstalling zapret service from general.bat... > reinstall_log.txt
"%PY%" reinstall_service.py >> reinstall_log.txt 2>&1
echo. >> reinstall_log.txt
echo --- zapret service state --- >> reinstall_log.txt
sc query zapret | findstr STATE >> reinstall_log.txt
type reinstall_log.txt
echo.
echo Done. Press any key to close.
pause >nul
