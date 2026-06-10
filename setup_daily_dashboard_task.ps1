$ErrorActionPreference = "Stop"

$taskName = "抖音来客看板每日更新推送"
$scriptPath = Join-Path $PSScriptRoot "run_daily_dashboard_workflow.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -Command `"& '$scriptPath'`""
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "10:00"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 4)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "工作日10点更新抖音来客看板基础表、刷新看板、截图并推送机器人；当天关机则不补跑" -Force | Out-Null
Write-Host "已创建/更新定时任务：$taskName，工作日 10:00 运行。"



