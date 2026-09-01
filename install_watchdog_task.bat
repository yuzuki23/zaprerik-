@echo off
rem Register Zapretik watchdog as a Scheduled Task:
rem  - runs at user logon AND at system boot (ONSTART)
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
set "XML=%TEMP%\zapretik_watchdog.xml"

rem Create XML task definition
(
echo ^<?xml version="1.0" encoding="UTF-16"?^>
echo ^<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"^>
echo   ^<RegistrationInfo^>
echo     ^<Author^>%USERDOMAIN%\%USERNAME%^</Author^>
echo     ^<URI^>\ZapretikWatchdog^</URI^>
echo   ^</RegistrationInfo^>
echo   ^<Principals^>
echo     ^<Principal id="Author"^>
echo       ^<LogonType^>InteractiveToken^</LogonType^>
echo       ^<RunLevel^>HighestAvailable^</RunLevel^>
echo     ^</Principal^>
echo   ^</Principals^>
echo   ^<Settings^>
echo     ^<DisallowStartIfOnBatteries^>false^</DisallowStartIfOnBatteries^>
echo     ^<StopIfGoingOnBatteries^>false^</StopIfGoingOnBatteries^>
echo     ^<MultipleInstancesPolicy^>IgnoreNew^</MultipleInstancesPolicy^>
echo     ^<StartWhenAvailable^>true^</StartWhenAvailable^>
echo     ^<IdleSettings^>
echo       ^<StopOnIdleEnd^>false^</StopOnIdleEnd^>
echo     ^</IdleSettings^>
echo   ^</Settings^>
echo   ^<Triggers^>
echo     ^<LogonTrigger^>
echo       ^<Enabled^>true^</Enabled^>
echo     ^</LogonTrigger^>
echo     ^<BootTrigger^>
echo       ^<Enabled^>true^</Enabled^>
echo       ^<Delay^>PT30S^</Delay^>
echo     ^</BootTrigger^>
echo   ^</Triggers^>
echo   ^<Actions Context="Author"^>
echo     ^<Exec^>
echo       ^<Command^>"%PY%"^</Command^>
echo       ^<Arguments^>"%SCRIPT%"^</Arguments^>
echo     ^</Exec^>
echo   ^</Actions^>
echo ^</Task^>
) > "%XML%"

schtasks /Delete /TN "%TASK%" /F >nul 2>nul
schtasks /Create /TN "%TASK%" /XML "%XML%" /F
if %errorlevel%==0 (
    echo Task "%TASK%" registered: %PY% %SCRIPT%
    echo Triggers: logon + boot (30s delay). Admin rights. Works on battery.
) else (
    echo Failed to create task (admin rights required).
)
del "%XML%" >nul 2>nul
endlocal
