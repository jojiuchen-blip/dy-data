param(
    [string]$TaskName = "DouyinWeeklyVerifyRecordExport",
    [string]$RunAt = "09:00",
    [string]$PythonExe = "",
    [string]$SaveDir = ""
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $ScriptDir "..\..")).Path
. (Join-Path $RepoRoot "scripts\dy_data_runtime.ps1")
$ExportScript = Join-Path $RepoRoot "scripts\exports\douyin_verify_record_export.py"
if (-not $SaveDir) {
    if ($env:DOUYIN_VERIFY_SAVE_DIR) {
        $SaveDir = $env:DOUYIN_VERIFY_SAVE_DIR
    } else {
        $SaveDir = Join-Path $RepoRoot "exports\verify"
    }
}
if (-not $PythonExe) {
    $PythonExe = Initialize-DyDataRuntime -Root $RepoRoot
}

if (-not (Test-Path -LiteralPath $ExportScript)) {
    throw "Export script not found: $ExportScript"
}

[Environment]::SetEnvironmentVariable("DOUYIN_VERIFY_SAVE_DIR", $SaveDir, "User")

$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$ExportScript`"" `
    -WorkingDirectory $RepoRoot

$trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday `
    -At ([DateTime]::ParseExact($RunAt, "HH:mm", $null))

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Export Douyin weekly verify records every Monday" `
    -Force | Out-Null

Write-Host "Scheduled task created: $TaskName"
Write-Host "Schedule: every Monday $RunAt"
Write-Host "Export directory: $SaveDir"
Write-Host "Manual test command:"
Write-Host "python `"$ExportScript`""
