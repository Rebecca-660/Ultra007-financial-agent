@echo off
if exist "%~dp0run.bat" goto nested
call "%~dp0scripts\portable\run.bat" install
exit /b %errorlevel%
:nested
call "%~dp0run.bat" install
exit /b %errorlevel%
