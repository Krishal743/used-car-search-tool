@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Run scripts\setup_windows.cmd first.
  exit /b 1
)
if not exist "frontend\dist\index.html" (
  echo Run scripts\setup_windows.cmd first to build the dashboard.
  exit /b 1
)
echo Starting Motorwise at http://127.0.0.1:8000
start "" powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 40;$i++){try{$r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 1;if($r.StatusCode -eq 200){Start-Process 'http://127.0.0.1:8000';break}}catch{};Start-Sleep -Milliseconds 500}"
".venv\Scripts\python.exe" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
endlocal
