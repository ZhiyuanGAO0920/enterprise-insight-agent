@echo off
cd /d "%~dp0web"

echo EIA V4 Web (React) 快速启动
echo.
echo 启动 Vite dev server: http://localhost:5173

REM 首次运行自动安装依赖
if not exist node_modules (
    echo 首次运行，安装依赖中...
    call npm install
)

REM 后台守护：Vite 就绪后自动打开浏览器（避免"无法访问此网页"）
start "" /b powershell -NoProfile -Command "$ok=0; for($i=0;$i -lt 30;$i++){curl.exe -s -o NUL --max-time 2 http://localhost:5173/; if($LASTEXITCODE -eq 0){$ok=1; break}; Start-Sleep -Seconds 1}; if($ok){Start-Process 'http://localhost:5173'}"

npm run dev
pause
