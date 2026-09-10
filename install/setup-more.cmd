@echo off
call "%~dp0setup.cmd" -Advanced %*
set "setup_result=%errorlevel%"
pause
exit /b %setup_result%
