@echo off
rem Register Zapretik watchdog as a Scheduled Task:
rem  - runs at user logon (ONLOGON)
rem  - with highest privileges (needed for zapret/winws service)
rem  - singleton lock in watchdog.py prevents duplicate care/monitor
rem Usage: install_watchdog_task.bat
setlocal
for /f "delims=" %%P in ('where pythonw.exe 2^>nul') do set "PY=%%P" & goto :found
echo pythonw.exe not found in PATH. Install Python or set path manually.
exit /b 1
:found
set "SCRIPT=%~dp0watchdog.py"
set "TASK=ZapretikWatchdog"
schtasks /Create /TN "%TASK%" /TR "\"%PY%\" \"%SCRIPT%\"" /SC ONLOGON /RL HIGHEST /RU "%USERDOMAIN%\%USERNAME%" /F
if %errorlevel%==0 (
    echo Task "%TASK%" registered: %PY% %SCRIPT%
    echo Runs at logon with admin rights. Duplicates prevented by singleton lock.
) else (
    echo Failed to create task (admin rights required).
)
endlocal
