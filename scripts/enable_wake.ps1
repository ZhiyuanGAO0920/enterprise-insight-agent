try {
    $task = Get-ScheduledTask -TaskName "EIA_DailyDemoFeed" -ErrorAction Stop
    $task.Settings.WakeToRun = $true
    $task.Settings.RunOnlyIfIdle = $false
    $task.Settings.IdleSettings.StopOnIdleEnd = $false
    Set-ScheduledTask -TaskName "EIA_DailyDemoFeed" -Settings $task.Settings
    Write-Host "Done: WakeToRun enabled for EIA_DailyDemoFeed"
} catch {
    Write-Host "Error: Scheduled task 'EIA_DailyDemoFeed' not found. Create it first." -ForegroundColor Red
    exit 1
}
