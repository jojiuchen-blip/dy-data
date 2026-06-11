# 运行手册

## 1. 准备配置

复制示例配置：

```powershell
Copy-Item config.example.json config.local.json
```

填写本机路径和抖音开放平台配置。`config.local.json` 已加入 `.gitignore`，不要提交真实密钥。

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

PowerShell entrypoints read Python in this order:

1. `DY_DATA_PYTHON_EXE`
2. `paths.python_exe` in `DY_DATA_CONFIG`, `config.local.json`, or `config.json`
3. `.venv\Scripts\python.exe`
4. `python` on `PATH`

Python scripts under `scripts/` add the repository root before importing `src.dy_data`, so isolated embedded Python runtimes do not fail with `ModuleNotFoundError: No module named 'src'`.

## 3. 常用命令

导出核销记录：

```powershell
python scripts/exports/douyin_verify_record_export.py
```

导出退款单：

```powershell
python scripts/exports/douyin_refund_export.py
```

生成五月分账基础表和看板：

```powershell
python scripts/settlement/build_may_settlement_dashboard.py
```

从分账基础表生成多月份看板：

```powershell
python scripts/settlement/build_monthly_settlement_dashboard_from_base.py
```

诊断核销券未进入分账的原因：

```powershell
python scripts/diagnostics/diagnose_unmatched_verify_cert_reasons.py
```

## 4. 协作者验收

协作者环境确认重点：

- `config.local.json` 指向的数据目录、输出目录、Python 路径正确。
- `python scripts/exports/douyin_verify_record_export.py` 能写入核销 CSV/JSON。
- `python scripts/exports/douyin_refund_export.py` 能写入退款 CSV/JSON。
- `python scripts/settlement/build_may_settlement_dashboard.py` 能生成分账基础表、异常名单和 HTML 看板。
