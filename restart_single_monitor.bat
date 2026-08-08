@echo off
taskkill /F /IM python.exe >nul 2>&1
timeout /t 2 /nobreak >nul
cd /d "C:\запрет"
start "" "C:\Users\Leonid\AppData\Local\Programs\Python\Python312\python.exe" monitor.py
exit
