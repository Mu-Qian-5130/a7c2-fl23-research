@echo off
call "%~dp0dev\windows\bootstrap.cmd" looks %*
exit /b %errorlevel%
