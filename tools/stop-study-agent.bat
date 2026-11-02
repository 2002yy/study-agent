@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-study-agent.ps1" %*
