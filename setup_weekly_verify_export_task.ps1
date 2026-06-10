param(
    [string]$TaskName = "DouyinWeeklyVerifyRecordExport",
    [string]$RunAt = "09:00",
    [string]$PythonExe = "",
    [string]$SaveDir = ""
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ExportScript = Join-Path $ScriptDir "douyin_verify_record_export.py"
if (-not $SaveDir) {
    if ($env:DOUYIN_VERIFY_SAVE_DIR) {
        $SaveDir = $env:DOUYIN_VERIFY_SAVE_DIR
    } else {
        $SaveDir = Join-Path $ScriptDir "exports\verify"
    }
}
if (-not $PythonExe) {
    $BundledPython = $env:DY_DATA_PYTHON_EXE
    if (-not $BundledPython) {
        $BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    }
    if (Test-Path -LiteralPath $BundledPython) {
        $PythonExe = $BundledPython
    } else {
        $PythonExe = "python"
    }
}

if (-not (Test-Path -LiteralPath $ExportScript)) {
    throw "Export script not found: $ExportScript"
}

$missing = @()
foreach ($name in @("DOUYIN_APP_ID", "DOUYIN_APP_SECRET", "DOUYIN_ACCOUNT_ID")) {
    if (-not [Environment]::GetEnvironmentVariable($name, "User")) {
        $missing += $name
    }
}

if ($missing.Count -gt 0) {
    throw "Please set user environment variables first: $($missing -join ', ')"
}

[Environment]::SetEnvironmentVariable("DOUYIN_VERIFY_SAVE_DIR", $SaveDir, "User")

$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$ExportScript`"" `
    -WorkingDirectory $ScriptDir

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
