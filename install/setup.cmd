@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
set "setup_result=%errorlevel%"
if "%~1"=="" pause
exit /b %setup_result%
