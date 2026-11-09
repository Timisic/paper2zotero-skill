@echo off
call "%~dp0setup.cmd" -Modules %*
set "setup_result=%errorlevel%"
pause
exit /b %setup_result%
