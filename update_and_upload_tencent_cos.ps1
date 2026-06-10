$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$python = $env:DY_DATA_PYTHON_EXE
if (-not $python) {
    $venvPython = Join-Path $root ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        $python = $venvPython
    } else {
        $python = "python"
    }
}

if (-not $env:TENCENT_SECRET_ID) { throw "Missing env var: TENCENT_SECRET_ID" }
if (-not $env:TENCENT_SECRET_KEY) { throw "Missing env var: TENCENT_SECRET_KEY" }
if (-not $env:TENCENT_COS_REGION) { $env:TENCENT_COS_REGION = "ap-guangzhou" }
if (-not $env:TENCENT_COS_BUCKET) { throw "Missing env var: TENCENT_COS_BUCKET" }
if (-not $env:TENCENT_COS_KEY) { $env:TENCENT_COS_KEY = "index.html" }

& $python (Join-Path $root "build_sales_dashboard.py")
& $python (Join-Path $root "upload_dashboard_to_tencent_cos.py")

Write-Host "Done: dashboard generated and uploaded to Tencent COS."
