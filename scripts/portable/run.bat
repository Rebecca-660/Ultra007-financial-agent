@echo off
setlocal
pushd "%~dp0..\.." >nul 2>&1
if errorlevel 1 goto badroot
if not exist "streamlit_app.py" goto badroot
if exist ".venv\Scripts\python.exe" goto virtual
where py >nul 2>&1
if not errorlevel 1 goto launcher
where python >nul 2>&1
if not errorlevel 1 goto pythonpath
echo Python was not found.
echo Install 64-bit Python 3.11-3.14 from https://www.python.org/downloads/windows/
echo Enable the Python launcher or Add Python to PATH, then run this file again.
set "AIF_PORTABLE_EXIT=2"
goto finish

:virtual
".venv\Scripts\python.exe" "scripts\portable\portable_runtime.py" "%~1"
set "AIF_PORTABLE_EXIT=%errorlevel%"
goto finish

:launcher
py -3 "scripts\portable\portable_runtime.py" "%~1"
set "AIF_PORTABLE_EXIT=%errorlevel%"
goto finish

:pythonpath
python "scripts\portable\portable_runtime.py" "%~1"
set "AIF_PORTABLE_EXIT=%errorlevel%"
goto finish

:badroot
echo The complete extracted project could not be found.
echo Extract the ZIP first. Do not run files from inside the ZIP viewer.
set "AIF_PORTABLE_EXIT=2"

:finish
popd >nul 2>&1
echo.
pause
exit /b %AIF_PORTABLE_EXIT%
