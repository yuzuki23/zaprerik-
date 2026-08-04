@echo off
taskkill /F /IM python.exe >nul 2>&1
timeout /t 1 /nobreak >nul
cd /d "C:\запрет"
start "monitor" python monitor.py
exit
