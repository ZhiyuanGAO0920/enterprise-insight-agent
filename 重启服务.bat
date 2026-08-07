@echo off
cd /d "%~dp0"

echo EIA V4 - Quick Start
echo.

REM Start Docker
echo [1/3] Starting Docker...
REM 数据库：V4 实际复用 eia-postgres（15432，V2 创建的容器，数据卷 enterpriseinsightagentv2_postgres_data，V4 的 .env DATABASE_URL 指向它）
docker start eia-postgres >nul 2>&1
REM Redis：6381 由 eia-redis-v4 提供。只 up 单个 redis-v4 服务——勿与 postgres-v4 一起 up（其 15432 端口与 eia-postgres 冲突，永远失败）
docker compose up -d redis-v4 >nul 2>&1
REM 确保 n8n 定时任务容器在跑（workflow 存在 prod 数据卷，直接 start 幂等；勿用 compose up，prod 依赖容器名被残留容器占用）
docker start eia-n8n-v4-prod >nul 2>&1
echo OK

REM Kill old process
echo [2/3] Stopping old server...
powershell -NoProfile -Command "& {try{$p=Get-NetTCPConnection -LocalPort 8002 -State Listen -ErrorAction Stop; Stop-Process -Id $p.OwningProcess -Force}catch{}}"
timeout /t 2 /nobreak >nul
echo OK

REM Start server and open browser once the server is ready
echo [3/3] Starting server on http://localhost:8002 (��̨��פ���ش���ͣ)
set NO_PROXY=api.deepseek.com,localhost,127.0.0.1
set http_proxy=
set https_proxy=

REM Start uvicorn as a detached background process (survives terminal close).
REM Logs go to server_restart.log / server_restart.err.log in the project root.
powershell -NoProfile -Command "Start-Process -FilePath 'python' -ArgumentList '-m','uvicorn','app.api.main:app','--host','0.0.0.0','--port','8002' -WorkingDirectory '%~dp0' -WindowStyle Hidden -RedirectStandardOutput '%~dp0server_restart.log' -RedirectStandardError '%~dp0server_restart.err.log'"

REM Background watcher: poll until the server responds, then open the browser.
REM Avoids the "can't reach this page" tab that appears when the browser opens too early.
start "" /b powershell -NoProfile -Command "$ok=0; for($i=0;$i -lt 60;$i++){curl.exe -s -o NUL --max-time 2 http://localhost:8002/; if($LASTEXITCODE -eq 0){$ok=1; break}; Start-Sleep -Seconds 1}; if($ok){Start-Process 'http://localhost:8002'}"

echo ������ɣ��������ں�̨���С��رձ����ڲ�Ӱ�����
pause
