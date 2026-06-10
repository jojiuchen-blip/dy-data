$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
. (Join-Path $root "scripts\dy_data_runtime.ps1")
$python = Initialize-DyDataRuntime -Root $root

& $python (Join-Path $root "build_sales_dashboard.py")
& $python (Join-Path $root "upload_dashboard_to_tencent_cos.py")

Write-Host "Done: dashboard generated and uploaded to Tencent COS."
