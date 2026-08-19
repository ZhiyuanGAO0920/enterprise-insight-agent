@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================================
echo   Enterprise Insight Agent 一键启动
echo   顺序：V3(8001) -^> V2(8000) -^> V4(8002) -^> React Web(5173)
echo   自动处理：Docker 容器、Ollama、清理旧进程、逐个启动
echo ============================================================
echo.

set "NO_PROXY=api.deepseek.com,localhost,127.0.0.1"
set "http_proxy="
set "https_proxy="
set "V2_DIR=D:\GaoZhiyuan\Enterprise Insight Agent V2"
set "V3_DIR=D:\GaoZhiyuan\Enterprise Insight Agent V3"
set "V4_DIR=D:\GaoZhiyuan\Enterprise Insight Agent V4"

REM ========== [1/5] Docker ==========
echo [1/5] 检查 Docker ...
docker info >nul 2>&1
if errorlevel 1 (
    echo       未运行，正在启动 Docker Desktop ...
    if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" (
        start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
    ) else (
        echo       [警告] 未找到 Docker Desktop，请手动打开后重跑本脚本
        powershell -NoProfile -Command "Start-Sleep -Seconds 10"
        exit /b 1
    )
    call :wait_cmd "docker info" 120
    if errorlevel 1 (
        echo       [失败] Docker 120 秒内未就绪
        powershell -NoProfile -Command "Start-Sleep -Seconds 10"
        exit /b 1
    )
)
echo       Docker 就绪

REM ========== [2/5] 容器 ==========
echo [2/5] 启动容器（PostgreSQL / Redis / n8n）...
docker start eia-postgres >nul 2>&1
if errorlevel 1 echo       [警告] eia-postgres 启动失败（容器可能不存在）
docker start 87d6472d9a83_eia-redis-v4-prod >/dev/null 2>&1
if errorlevel 1 echo       [警告] redis-v4 启动失败
docker start eia-n8n-v4-prod >nul 2>&1
if errorlevel 1 echo       [警告] eia-n8n-v4-prod 启动失败（不影响主功能）
call :wait_port 15432 "PostgreSQL" 60
call :wait_port 6381 "Redis" 30
call :wait_port 5680 "n8n" 60
echo       容器就绪

REM ========== [3/5] Ollama ==========
echo [3/5] 检查 Ollama（BGE-M3 嵌入）...
curl.exe -s --max-time 2 http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo       未运行，正在启动 Ollama ...
    if exist "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe" (
        start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
        call :wait_port 11434 "Ollama" 60
        if errorlevel 1 echo       [警告] Ollama 未在 60 秒内就绪
    ) else (
        echo       [警告] 未找到 Ollama，请手动启动（仅语义搜索受影响）
    )
)
echo       Ollama 就绪

REM ========== [4/5] 清理旧进程 ==========
echo [4/5] 清理 8000/8001/8002/5173 旧进程（只杀对应端口，不动其他 Python）...
powershell -NoProfile -Command "foreach($p in 8000,8001,8002,5173){try{$c=Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction Stop;Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue}catch{}}"
powershell -NoProfile -Command "Start-Sleep -Seconds 2"
echo       清理完成

REM ========== [5/5] 依次启动 ==========
echo [5/5] 依次启动四个服务（V3 -^> V2 -^> V4 -^> React Web）...
call :start_server "%V3_DIR%" "python" 8001 V3 90
call :start_server "%V2_DIR%" "%V2_DIR%\venv312\Scripts\python.exe" 8000 V2 90
call :start_server "%V4_DIR%" "python" 8002 V4 120
call :start_web 5173

echo.
echo ============================================================
echo   启动结果：
call :check_port 8000 V2
call :check_port 8001 V3
call :check_port 8002 V4
call :check_port 5173 "React Web"
echo ============================================================
echo   日志位置：各项目根目录 start.log / start.err.log（Web 见 web\vite.log）
echo.
powershell -NoProfile -Command "Start-Sleep -Seconds 10"
exit /b 0

REM ============ 子程序 ============

:start_web
set "_port=%~1"
echo       - 启动 React Web (端口 %_port%) ...
powershell -NoProfile -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','npm run dev' -WorkingDirectory '%V4_DIR%\web' -WindowStyle Hidden -RedirectStandardOutput '%V4_DIR%\web\vite.log' -RedirectStandardError '%V4_DIR%\web\vite.err.log'"
call :wait_port %_port% "React Web" 60
exit /b 0

:start_server
set "_dir=%~1"
set "_py=%~2"
set "_port=%~3"
set "_name=%~4"
set "_max=%~5"
echo       - 启动 %_name% (端口 %_port%) ...
powershell -NoProfile -Command "Start-Process -FilePath '%_py%' -ArgumentList '-m','uvicorn','app.api.main:app','--host','0.0.0.0','--port','%_port%' -WorkingDirectory '%_dir%' -WindowStyle Hidden -RedirectStandardOutput '%_dir%\start.log' -RedirectStandardError '%_dir%\start.err.log'"
call :wait_port %_port% "%_name%" %_max%
exit /b 0

:wait_port
set "_port=%~1"
set "_name=%~2"
set "_max=%~3"
set /a _n=0
:wait_port_loop
powershell -NoProfile -Command "try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',%_port%);$c.Close();exit 0}catch{};try{$c=New-Object Net.Sockets.TcpClient([Net.Sockets.AddressFamily]::InterNetworkV6);$c.Connect('::1',%_port%);$c.Close();exit 0}catch{};exit 1" >nul 2>&1
if not errorlevel 1 (
    echo         %_name% 就绪
    exit /b 0
)
set /a _n+=1
if !_n! geq %_max% (
    echo         [失败] %_name% 超时（%_max% 秒），请查看日志
    exit /b 1
)
powershell -NoProfile -Command "Start-Sleep -Seconds 1"
goto wait_port_loop

:wait_cmd
set "_cmd=%~1"
set "_max=%~2"
set /a _n=0
:wait_cmd_loop
%_cmd% >nul 2>&1
if not errorlevel 1 exit /b 0
set /a _n+=1
if !_n! geq %_max% exit /b 1
powershell -NoProfile -Command "Start-Sleep -Seconds 1"
goto wait_cmd_loop

:check_port
set "_port=%~1"
set "_name=%~2"
powershell -NoProfile -Command "try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',%_port%);$c.Close();exit 0}catch{};try{$c=New-Object Net.Sockets.TcpClient([Net.Sockets.AddressFamily]::InterNetworkV6);$c.Connect('::1',%_port%);$c.Close();exit 0}catch{};exit 1" >nul 2>&1
if not errorlevel 1 (
    echo    %_name%  http://localhost:%_port%  OK
    start "" "http://localhost:%_port%"
) else (
    echo    %_name%  http://localhost:%_port%  [失败] 请查 start.err.log
)
exit /b 0
