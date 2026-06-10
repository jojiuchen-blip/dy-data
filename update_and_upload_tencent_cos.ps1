$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$pythonItem = Get-ChildItem -Path "D:\app" -Recurse -Filter "python.exe" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -like "*runtime*python*python.exe" } |
    Select-Object -First 1

if (-not $pythonItem) {
    throw "Python runtime not found under D:\app"
}

$python = $pythonItem.FullName

if (-not $env:TENCENT_SECRET_ID) { throw "Missing env var: TENCENT_SECRET_ID" }
if (-not $env:TENCENT_SECRET_KEY) { throw "Missing env var: TENCENT_SECRET_KEY" }
if (-not $env:TENCENT_COS_REGION) { $env:TENCENT_COS_REGION = "ap-guangzhou" }
if (-not $env:TENCENT_COS_BUCKET) { $env:TENCENT_COS_BUCKET = "dy-productdata-1439925566" }
if (-not $env:TENCENT_COS_KEY) { $env:TENCENT_COS_KEY = "index.html" }

& $python (Join-Path $root "build_sales_dashboard.py")
& $python (Join-Path $root "upload_dashboard_to_tencent_cos.py")

Write-Host "Done: dashboard generated and uploaded to Tencent COS."
