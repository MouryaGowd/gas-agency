@echo off
rem ============================================================
rem  Commercial Gas Agency - double-click this file to start.
rem  First run: installs everything, asks for your secret key and
rem  dealer login, then opens the site in your browser.
rem ============================================================
setlocal
cd /d "%~dp0"
title Commercial Gas Agency

if not defined PORT set "PORT=8000"

rem ---- 1. find Python 3.10+ ------------------------------------------------
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo.
    echo  Python 3.10 or newer was not found.
    echo  Install it from https://www.python.org/downloads/windows/
    echo  and tick "Add python.exe to PATH" in the installer, then run this file again.
    echo.
    pause
    exit /b 1
)

rem ---- 2. create the virtual environment and install packages (first run only) ----
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    %PY% -m venv .venv
    if errorlevel 1 goto :fail
)
if not exist ".venv\.deps_ok" (
    echo Installing packages. This takes a few minutes the first time...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :fail
    echo ok> ".venv\.deps_ok"
)

rem ---- 3. first-run setup: secret key + dealer login ---------------------------
".venv\Scripts\python.exe" setup_env.py
if errorlevel 1 goto :fail

rem ---- 4. open the browser once the server is ready, then start the server ----
echo.
echo  Starting server on http://127.0.0.1:%PORT%/
echo  The first start also creates demo data and trains the model (about a minute).
echo  Keep this window open while you use the site. Close it or press Ctrl+C to stop.
echo.
start "" /b ".venv\Scripts\python.exe" open_browser.py "http://127.0.0.1:%PORT%/"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%
echo.
echo  The server stopped. If you saw "address already in use", another program is using port %PORT%.
echo  Set a different port with:  set PORT=8001   and run this file again.
pause
exit /b 0

:fail
echo.
echo  Something went wrong. Read the messages above, fix the problem and run this file again.
echo  If package installation failed, delete the ".venv" folder and try again.
pause
exit /b 1
