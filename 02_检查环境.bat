@echo off
if exist "%~dp0run.bat" goto nested
call "%~dp0scripts\portable\run.bat" check
exit /b %errorlevel%
:nested
call "%~dp0run.bat" check
exit /b %errorlevel%
