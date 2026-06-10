$ErrorActionPreference = "Stop"

$runId = Get-Date -Format "yyyyMMdd_HHmmss"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$runRoot = $env:DY_DATA_RUN_ROOT
if (-not $runRoot) {
    $runRoot = Join-Path $scriptDir "runs"
}
$runDir = Join-Path $runRoot $runId
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

if (-not $env:DOUYIN_APP_ID) { throw "Missing env var: DOUYIN_APP_ID" }
if (-not $env:DOUYIN_APP_SECRET) { throw "Missing env var: DOUYIN_APP_SECRET" }
if (-not $env:DOUYIN_ACCOUNT_ID) { throw "Missing env var: DOUYIN_ACCOUNT_ID" }
$env:DOUYIN_SAVE_DIR = $runDir
$env:DOUYIN_START_YEAR = "2025"
$env:DOUYIN_START_MONTH = "5"
$env:DOUYIN_START_DAY = "13"
$env:DOUYIN_END_YEAR = "2026"
$env:DOUYIN_END_MONTH = "5"
$env:DOUYIN_PAGE_SIZE = "100"

$python = $env:DY_DATA_PYTHON_EXE
if (-not $python) {
    $venvPython = Join-Path $scriptDir ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        $python = $venvPython
    } else {
        $python = "python"
    }
}
$rawScript = Join-Path $scriptDir "export_raw_orders.py"
$backfillScript = Join-Path $scriptDir "backfill_coupon_status.py"
$logPath = Join-Path $runDir "workflow.log"

Start-Transcript -Path $logPath -Force | Out-Null

Write-Host "Run directory: $runDir"
Write-Host "Step 1: export raw orders"
& $python $rawScript

$rawTotalCsv = Join-Path $runDir "抖音订单_2025年05月到2026年05月_总表.csv"
$filledTotalCsv = Join-Path $runDir "抖音订单_2025年05月到2026年05月_总表_含券状态.csv"
$filledTotalJson = Join-Path $runDir "抖音订单_2025年05月到2026年05月_总表_含券状态.json"

$env:BACKFILL_INPUT_CSV = $rawTotalCsv
$env:BACKFILL_OUTPUT_CSV = $filledTotalCsv
$env:BACKFILL_OUTPUT_JSON = $filledTotalJson

Write-Host "Step 2: backfill coupon status"
& $python $backfillScript

Write-Host "Completed. Output directory: $runDir"
Stop-Transcript | Out-Null
