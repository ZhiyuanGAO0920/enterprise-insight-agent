@echo off
REM =============================================================================
REM 启动V4服务.bat — 本地开发快速启动（Windows）
REM =============================================================================
REM 用于本地开发调试。生产环境请使用: deploy.bat
REM
REM 代理说明: llm.py 已通过 httpx.AsyncClient(trust_env=False) 处理代理隔离，
REM 无需在批处理中手动清除 HTTP_PROXY 环境变量。
REM =============================================================================
cd /d "%~dp0"

set PORT=8002
:check
netstat -ano | findstr ":%PORT% " >nul 2>&1
if %errorlevel% equ 0 (set /a PORT+=1 & goto check)

echo Starting V4 on http://localhost:%PORT%
python -m uvicorn app.api.main:app --host 0.0.0.0 --port %PORT% --reload
pause
