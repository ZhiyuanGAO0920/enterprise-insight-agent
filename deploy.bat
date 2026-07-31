@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
REM =============================================================================
REM deploy.bat - Enterprise Insight Agent V4 一键部署 (Windows)
REM =============================================================================
REM Usage: deploy.bat
REM =============================================================================

cd /d "%~dp0"

echo ========================================
echo  Enterprise Insight Agent V4 - 一键部署
echo ========================================
echo.

REM ---- 1. Check Docker ----
where docker >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Docker is not installed.
    echo   Download: https://docs.docker.com/desktop/install/windows-install/
    pause
    exit /b 1
)

docker compose version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set DOCKER_COMPOSE=docker compose
) else (
    echo [WARN] docker compose not found, trying docker-compose...
    where docker-compose >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        set DOCKER_COMPOSE=docker-compose
    ) else (
        echo [ERROR] Neither docker compose nor docker-compose found.
        pause
        exit /b 1
    )
)
echo [OK] Docker detected

REM ---- 2. Create .env if missing ----
if not exist .env (
    echo.
    echo [INFO] No .env file found. Creating from template...
    copy .env.production.example .env
    echo.
    echo ========================================
    echo  Please edit .env and fill in:
    echo    DEEPSEEK_API_KEY   - your DeepSeek API key
    echo    JWT_SECRET_KEY     - a random string
    echo    POSTGRES_PASSWORD  - a strong database password
    echo ========================================
    echo.
    echo After editing, re-run: deploy.bat
    pause
    exit /b 0
)
echo [OK] .env file found

REM ---- 3. Check model ----
if not exist "ollama-models\bge-m3.tar.gz" (
    echo.
    echo [WARN] Pre-packaged BGE-M3 model not found.
    echo   Ollama will download on first start (may be slow).
    echo.
    set /p answer="Continue without model? [y/N] "
    if /i not "%answer%"=="y" exit /b 1
) else (
    echo [OK] BGE-M3 model package found
)

REM ---- 4. Start services ----
echo.
echo Starting services...
%DOCKER_COMPOSE% -f docker-compose.prod.yml up -d

REM ---- 5. Wait for health check ----
echo.
echo Waiting for application to be ready...
for /l %%i in (1,1,30) do (
    curl -s http://localhost:8002/health >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        echo.
        echo ========================================
        echo  Deploy successful!
        echo.
        echo  Access URL:  http://localhost:8002
        echo  Username:    admin
        echo  Password:    admin123
        echo.
        echo  Next: Login and connect your business database.
        echo ========================================
        pause
        exit /b 0
    )
    <nul set /p =.
    timeout /t 2 >nul
)

echo.
echo [INFO] Startup taking longer than expected.
echo  Check logs: %DOCKER_COMPOSE% -f docker-compose.prod.yml logs
pause
