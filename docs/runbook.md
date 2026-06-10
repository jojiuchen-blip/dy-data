# 运行手册

## 1. 准备配置

复制示例配置：

```powershell
Copy-Item config.example.json config.local.json
```

填写本机路径、抖音开放平台配置和可选 COS 配置。`config.local.json` 已加入 `.gitignore`，不要提交真实密钥。

也可以用环境变量覆盖配置文件：

```powershell
$env:DOUYIN_APP_ID = "..."
$env:DOUYIN_APP_SECRET = "..."
$env:DOUYIN_ACCOUNT_ID = "..."
$env:DY_DATA_CONFIG = "C:\path\to\config.local.json"
```

## 2. 安装依赖

```powershell
python -m pip install -r requirements.txt
```

## 3. 常用命令

生成销售看板：

```powershell
python build_sales_dashboard.py
```

导出核销记录：

```powershell
python douyin_verify_record_export.py
```

导出退款单：

```powershell
python douyin_refund_export.py
```

运行每日工作流：

```powershell
powershell -ExecutionPolicy Bypass -File .\run_daily_dashboard_workflow.ps1
```

## 4. 协作者验收

协作者环境确认重点：

- `config.local.json` 指向的基础表、输出目录、Python 路径正确。
- `python build_sales_dashboard.py` 能生成 HTML。
- `python douyin_verify_record_export.py` 能写入核销 CSV/JSON。
- 每日 PowerShell 脚本不再依赖个人 Documents 路径。
