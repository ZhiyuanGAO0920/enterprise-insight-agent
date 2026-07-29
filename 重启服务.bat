@echo off
cd /d "%~dp0"

echo EIA V4 — Quick Start
echo.

REM Start Docker
echo [1/3] Starting Docker...
docker compose up -d redis-v4 postgres-v4 >nul 2>&1
echo OK

REM Kill old process
echo [2/3] Stopping old server...
powershell -NoProfile -Command "& {try{$p=Get-NetTCPConnection -LocalPort 8002 -State Listen -ErrorAction Stop; Stop-Process -Id $p.OwningProcess -Force}catch{}}"
timeout /t 2 /nobreak >nul
echo OK

REM Start server and open browser
echo [3/3] Starting server on http://localhost:8002
set NO_PROXY=api.deepseek.com,localhost,127.0.0.1
set http_proxy=
set https_proxy=

start http://localhost:8002
python -m uvicorn app.api.main:app --host 0.0.0.0 --port 8002
pause
