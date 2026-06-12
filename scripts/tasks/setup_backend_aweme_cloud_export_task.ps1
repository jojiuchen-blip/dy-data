param(
    [string]$TaskName = "DouyinBackendAwemeCloudExport",
    [string]$RunAt = "08:30",
    [string]$PythonExe = "",
    [string]$DatabaseUrl = ""
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$RepoRoot = Split-Path -Parent $ScriptDir
. (Join-Path $RepoRoot "scripts\dy_data_runtime.ps1")

$ExportScript = Join-Path $RepoRoot "scripts\exports\auto_export_backend_aweme_edge.py"
if (-not (Test-Path -LiteralPath $ExportScript)) {
    throw "Export script not found: $ExportScript"
}

if (-not $PythonExe) {
    $PythonExe = Initialize-DyDataRuntime -Root $RepoRoot
}

if ($DatabaseUrl) {
    [Environment]::SetEnvironmentVariable("DY_DATA_DATABASE_URL", $DatabaseUrl, "User")
}

[Environment]::SetEnvironmentVariable("DY_DATA_IMPORT_BACKEND_AWEME_TO_DB", "1", "User")
[Environment]::SetEnvironmentVariable("DY_DATA_DELETE_BACKEND_AWEME_FILES_AFTER_DB", "1", "User")

$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$ExportScript`" --import-db --delete-local-after-db" `
    -WorkingDirectory $RepoRoot

$trigger = New-ScheduledTaskTrigger `
    -Daily `
    -At ([DateTime]::ParseExact($RunAt, "HH:mm", $null))

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Export Douyin Laike backend aweme detail through Edge automation and import rows into database" `
    -Force | Out-Null

Write-Host "Scheduled task created: $TaskName"
Write-Host "Schedule: every day $RunAt"
Write-Host "Command: $PythonExe `"$ExportScript`" --import-db --delete-local-after-db"
Write-Host "Database URL configured: $([bool]([Environment]::GetEnvironmentVariable("DY_DATA_DATABASE_URL", "User")))"
