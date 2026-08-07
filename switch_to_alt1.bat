@echo off
taskkill /F /IM winws.exe >nul 2>&1
timeout /t 2 /nobreak >nul
call "C:\запрет\general (ALT).bat"