# EIA V4 — 开机自启脚本（无窗口，不弹浏览器）
# 自动被添加到 Windows 启动项

$batPath = "D:\GaoZhiyuan\Enterprise Insight Agent V4\重启服务.bat"

# 等待 Docker 就绪（开机时 Docker 可能还没完全启动）
for ($i = 0; $i -lt 30; $i++) {
    try {
        $null = docker info 2>$null
        if ($LASTEXITCODE -eq 0) { break }
    } catch {}
    Start-Sleep -Seconds 2
}

# 启动服务（隐藏窗口）
Start-Process -FilePath $batPath -WindowStyle Hidden
