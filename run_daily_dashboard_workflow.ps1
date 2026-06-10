$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptDir "scripts\dy_data_runtime.ps1")
$python = Initialize-DyDataRuntime -Root $scriptDir

# 每天回扫90天，用于捕捉较早订单的核销、退款等状态变化。
$env:DOUYIN_DAILY_LOOKBACK_DAYS = "90"
$env:DOUYIN_REQUEST_SLEEP_SECONDS = "1"

# 企业微信机器人，可同时推文字和截图；不配置则只更新数据和看板。
if ($env:DOUYIN_PUSH_WEBHOOK -and -not $env:DOUYIN_PUSH_WEBHOOK_TYPE) {
    $env:DOUYIN_PUSH_WEBHOOK_TYPE = "wecom"
}

# 如需每天自动上传到腾讯云 COS，取消下面注释并填入你的 COS 信息。
# $env:TENCENT_SECRET_ID = ""
# $env:TENCENT_SECRET_KEY = ""
# $env:TENCENT_COS_REGION = "ap-guangzhou"
# $env:TENCENT_COS_BUCKET = "dy-productdata-1439925566"
# $env:TENCENT_COS_KEY = "index.html"

$logDir = $env:DY_DATA_DAILY_LOG_DIR
if (-not $logDir) {
    $logDir = Join-Path $scriptDir "logs\daily"
}
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("daily_dashboard_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")

& $python (Join-Path $scriptDir "daily_dashboard_workflow.py") *> $logFile



