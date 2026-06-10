# 抖音来客看板

本仓库用于维护抖音来客订单、核销、退款、抖音号明细匹配、商品销售看板和门店分账看板相关脚本。

## 主要能力

- 导出抖音来客订单、券核销、退款数据。
- 补充券状态、核销时间、核销门店等字段。
- 生成商品销售核销看板。
- 生成门店分账看板，支持按核销月份、门店、商品类型筛选。
- 输出分账基础表、异常名单和诊断明细。

## 常用脚本

- `daily_dashboard_workflow.py`：每日看板更新工作流。
- `build_sales_dashboard.py`：生成商品销售核销看板。
- `export_may_verify_by_backend_pois.py`：按后台 POI 拉取 2026 年 5 月门店验券记录。
- `build_may_settlement_dashboard.py`：生成五月门店分账基础表和看板。
- `build_monthly_settlement_dashboard_from_base.py`：从分账基础表生成支持月份筛选的分账看板。
- `diagnose_unmatched_verify_cert_reasons.py`：诊断核销券未进入分账的原因。

## 本地数据路径

脚本已经支持统一配置。协作者应复制示例配置并按本机环境填写：

```powershell
Copy-Item config.example.json config.local.json
```

`config.local.json` 不会提交到 Git。常用配置包括：

- `paths.workspace_root`：本机数据根目录。
- `paths.script_root`：脚本所在目录，默认可用当前仓库。
- `paths.python_exe`：本机 Python 解释器。
- `douyin.app_id`、`douyin.app_secret`、`douyin.account_id`：抖音开放平台配置。
- `sku.type_map`：SKU 到商品类型的映射。
- `tencent_cos.*`：腾讯云 COS 发布配置。

配置读取优先级：环境变量 > `DY_DATA_CONFIG` 指向的 JSON 文件 > `config.local.json` > 内置默认值。

## 运行说明

脚本依赖本地 Python 环境和抖音开放平台应用配置。运行前需要确保环境变量或脚本配置中有：

- `DOUYIN_APP_ID`
- `DOUYIN_APP_SECRET`
- `DOUYIN_ACCOUNT_ID`

建议先安装依赖：

```powershell
python -m pip install -r requirements.txt
```

常用入口：

```powershell
python build_sales_dashboard.py
python douyin_verify_record_export.py
python douyin_refund_export.py
powershell -ExecutionPolicy Bypass -File .\run_daily_dashboard_workflow.ps1
```

看板 HTML 可直接用浏览器打开，也可以上传到腾讯云 COS 静态网站进行共享。

## 代码结构

当前阶段先新增公共模块，不移动历史脚本，降低对协作者现有流程的影响：

```text
src/dy_data/config.py      统一配置读取
src/dy_data/sku.py         SKU 和商品类型映射
src/dy_data/paths.py       路径读取辅助
src/dy_data/csv_io.py      CSV 读写辅助
src/dy_data/douyin_client.py  抖音接口常量和请求头辅助
```

后续等配置化在协作者环境跑稳，再把根目录脚本迁移到 `scripts/exports`、`scripts/dashboards`、`scripts/settlement`、`scripts/diagnostics`、`scripts/tasks`。
