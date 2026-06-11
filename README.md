# 抖音订单分账数据看板

本仓库当前主线是面向经销商的抖音来客订单分账数据看板，重点维护订单、核销、退款、抖音号明细匹配、门店销售归属和门店核销归属之间的分账口径。

此前的“抖音服务产品销售数据看板 / 每日发布 / 腾讯云 COS 上传”内容已从当前主线迁出，归档到：

```text
C:\Users\86138\Documents\抖音服务产品数据拉取归档
```

## 主要能力

- 导出抖音来客订单、券核销、退款数据。
- 匹配订单归属人、后台抖音号、核销门店和门店 POI。
- 按核销月份生成门店分账基础表。
- 生成门店分账看板，支持按月份、门店、商品类型筛选。
- 输出分账异常名单和诊断明细，辅助人工复核。

## 常用脚本

- `export_raw_orders.py`：导出订单明细，并按 SKU 映射商品类型。
- `douyin_verify_record_export.py`：导出核销记录。
- `douyin_refund_export.py`：导出退款单。
- `export_may_verify_by_backend_pois.py`：按后台 POI 拉取 2026 年 5 月门店验券记录。
- `build_may_settlement_dashboard.py`：生成五月门店分账基础表和看板。
- `build_monthly_settlement_dashboard_from_base.py`：从分账基础表生成支持月份筛选的分账看板。
- `diagnose_unmatched_verify_cert_reasons.py`：诊断核销券未进入分账的原因。
- `validate_settlement_data_availability.py`：检查分账所需字段的数据可用性。

## 本地配置

复制示例配置并按本机环境填写：

```powershell
Copy-Item config.example.json config.local.json
```

`config.local.json` 不会提交到 Git。常用配置包括：

- `paths.workspace_root`：本机数据根目录。
- `paths.script_root`：脚本所在目录，默认可用当前仓库。
- `paths.python_exe`：本机 Python 解释器。
- `douyin.app_id`、`douyin.app_secret`、`douyin.account_id`：抖音开放平台配置。
- `sku.type_map`：SKU 到商品类型的映射，分账看板仍会按商品类型展示。

配置读取优先级：环境变量 > `DY_DATA_CONFIG` 指向的 JSON 文件 > `config.local.json` > 内置默认值。

## 运行说明

脚本依赖本地 Python 环境和抖音开放平台应用配置。运行前需要确保环境变量或脚本配置中有：

- `DOUYIN_APP_ID`
- `DOUYIN_APP_SECRET`
- `DOUYIN_ACCOUNT_ID`

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

常用入口：

```powershell
python douyin_verify_record_export.py
python douyin_refund_export.py
python build_may_settlement_dashboard.py
python build_monthly_settlement_dashboard_from_base.py
```

## 代码结构

```text
src/dy_data/config.py         统一配置读取
src/dy_data/sku.py            SKU 和商品类型映射
src/dy_data/paths.py          路径读取辅助
src/dy_data/csv_io.py         CSV 读写辅助
src/dy_data/douyin_client.py  抖音接口常量和请求头辅助
```

根目录仍保留部分一次性诊断、匹配和探查脚本，后续可再按 `scripts/exports`、`scripts/settlement`、`scripts/diagnostics` 分批整理。
