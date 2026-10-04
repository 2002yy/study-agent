@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-study-agent.ps1" %*
set "LAUNCH_EXIT=%ERRORLEVEL%"
endlocal & exit /b %LAUNCH_EXIT%
