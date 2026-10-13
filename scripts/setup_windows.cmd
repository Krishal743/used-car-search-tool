@echo off
setlocal
cd /d "%~dp0.."
where py >nul 2>nul
if errorlevel 1 (
  echo Python 3.12 or newer is required. Install it from python.org and rerun this script.
  exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
  echo Node.js 20.19 or newer is required. Install the current LTS release and rerun this script.
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 echo Chromium download failed. The app can still try direct public-page retrieval.
call npm --prefix frontend install --no-package-lock
if errorlevel 1 exit /b 1
call npm --prefix frontend run build
if errorlevel 1 exit /b 1
if not exist ".env" copy ".env.example" ".env" >nul
echo.
echo Setup complete. Run scripts\run_windows.cmd to open Motorwise.
endlocal
