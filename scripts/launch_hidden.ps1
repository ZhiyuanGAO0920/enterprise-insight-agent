# EIA V4 — 无窗口启动器
# 被桌面快捷方式调用，自身不弹出任何窗口

$batPath = "D:\GaoZhiyuan\Enterprise Insight Agent V4\重启服务.bat"

# 1. 后台启动服务（完全隐藏）
Start-Process -FilePath $batPath -WindowStyle Hidden -PassThru | Out-Null

# 2. 等待服务就绪（最长 25 秒）
$ready = $false
for ($i = 0; $i -lt 25; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:8002/health" -TimeoutSec 2 -UseBasicParsing
        if ($resp.Content -match "ok") { $ready = $true; break }
    } catch {}
    Start-Sleep -Seconds 1
}

# 3. 打开浏览器
if ($ready) {
    Start-Process "http://localhost:8002"
}
