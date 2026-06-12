@echo off
chcp 65001 >nul 2>&1
REM =============================================================================
REM  Restart V4 dev server (Windows)
REM  Only kills uvicorn processes of this project.
REM  Production: docker compose -f docker-compose.prod.yml restart
REM =============================================================================
cd /d "%~dp0"

echo Stopping V4 uvicorn processes...
for /f "tokens=2" %%a in ('tasklist /fi "imagename eq python.exe" /fo list ^| findstr /c:"uvicorn" 2^>nul') do (
    echo   Terminating PID %%a
    taskkill /F /PID %%a >nul 2>&1
)

timeout /t 2 /nobreak >nul

set PORT=8002
:check
netstat -ano | findstr ":%PORT% " >nul 2>&1
if %errorlevel% equ 0 (set /a PORT+=1 & goto check)

echo Starting V4 on http://localhost:%PORT%
python -m uvicorn app.api.main:app --host 0.0.0.0 --port %PORT% --reload
pause
