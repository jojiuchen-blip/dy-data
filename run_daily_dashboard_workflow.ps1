$ErrorActionPreference = "Stop"

if (-not $env:DOUYIN_APP_ID) { throw "Missing env var: DOUYIN_APP_ID" }
if (-not $env:DOUYIN_APP_SECRET) { throw "Missing env var: DOUYIN_APP_SECRET" }
if (-not $env:DOUYIN_ACCOUNT_ID) { throw "Missing env var: DOUYIN_ACCOUNT_ID" }

# 每天回扫90天，用于捕捉较早订单的核销、退款等状态变化。
$env:DOUYIN_DAILY_LOOKBACK_DAYS = "90"
$env:DOUYIN_REQUEST_SLEEP_SECONDS = "1"

# 企业微信机器人，可同时推文字和截图。
if (-not $env:DOUYIN_PUSH_WEBHOOK) { throw "Missing env var: DOUYIN_PUSH_WEBHOOK" }
$env:DOUYIN_PUSH_WEBHOOK_TYPE = "wecom"

# 如需每天自动上传到腾讯云 COS，取消下面注释并填入你的 COS 信息。
# $env:TENCENT_SECRET_ID = ""
# $env:TENCENT_SECRET_KEY = ""
# $env:TENCENT_COS_REGION = "ap-guangzhou"
# $env:TENCENT_COS_BUCKET = "dy-productdata-1439925566"
# $env:TENCENT_COS_KEY = "index.html"

$logDir = "D:\app\抖音来客看板\daily_logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("daily_dashboard_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")

& "D:\app\抖音来客看板\runtime\python\python.exe" "C:\Users\86138\Documents\抖音来客看板\daily_dashboard_workflow.py" *> $logFile



