# 抖音订单分账数据看板

本仓库当前主线是面向经销商的抖音来客订单分账数据看板，重点维护订单、核销、退款、抖音号明细匹配、门店销售归属和门店核销归属之间的分账口径。

此前的“抖音服务产品销售数据看板 / 每日发布 / 腾讯云 COS 上传”内容已从当前主线迁出；本仓库不记录个人电脑上的归档路径。

产品定位和业务边界以 `docs/项目产品介绍书.md` 为准；本 README 只说明仓库结构、配置方式和常用运行入口。

协作开发时优先阅读：

- `docs/项目产品介绍书.md`：产品定义和业务边界。
- `docs/技术架构与部署规划.md`：技术栈、服务拆分、部署方向和协作边界。
- `docs/data-model.md`：数据表草案，需基于真实拉取数据持续校对。
- `docs/api-contract.md`：页面 1、页面 2、页面 3 的 API 返回结构草案。
- `mock/`：前端并行开发使用的脱敏示例数据。

## 主要能力

- 导出抖音来客订单、券核销、退款数据。
- 匹配订单归属人、后台抖音号、核销门店和门店 POI。
- 按核销月份生成门店分账基础表。
- 生成门店分账看板，支持按月份、门店、商品类型筛选。
- 输出分账异常名单和诊断明细，辅助人工复核。

## 常用脚本

- `scripts/exports/export_raw_orders.py`：导出订单明细，并按 SKU 映射商品类型。
- `scripts/exports/douyin_verify_record_export.py`：导出核销记录。
- `scripts/exports/douyin_refund_export.py`：导出退款单。
- `scripts/exports/export_may_verify_by_backend_pois.py`：按后台 POI 拉取 2026 年 5 月门店验券记录。
- `scripts/settlement/build_may_settlement_dashboard.py`：生成五月门店分账基础表和看板。
- `scripts/settlement/build_monthly_settlement_dashboard_from_base.py`：从分账基础表生成支持月份筛选的分账看板。
- `scripts/diagnostics/diagnose_unmatched_verify_cert_reasons.py`：诊断核销券未进入分账的原因。
- `scripts/diagnostics/validate_settlement_data_availability.py`：检查分账所需字段的数据可用性。
- `scripts/import_store_locations.py`：通过现有 POI 映射导入抖音适用门店经纬度和候选资格。
- `scripts/refresh_store_scores.py`：手动生成一批不可变的门店评分快照。

## 本地配置

复制示例配置并按本机环境填写：

```powershell
Copy-Item config.example.json config.local.json
```

`config.local.json` 不会提交到 Git。常用配置包括：

- `paths.workspace_root`：数据根目录，生产环境建议通过环境变量或服务器配置指定。
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
python scripts/exports/douyin_verify_record_export.py
python scripts/exports/douyin_refund_export.py
python scripts/settlement/build_may_settlement_dashboard.py
python scripts/settlement/build_monthly_settlement_dashboard_from_base.py
```

脚本已按用途移动到 `scripts/` 下，仍可从仓库根目录直接运行。Python 脚本会自动把仓库根目录加入模块搜索路径，以便继续导入 `src.dy_data`。

## 代码结构

```text
docs/                         产品、架构、运行和协作说明
mock/                         前端开发使用的脱敏示例数据
scripts/exports/              订单、核销、退款等数据导出入口
scripts/settlement/           分账基础表和看板生成入口
scripts/diagnostics/          数据可用性、异常原因和字段检查入口
scripts/exploration/          接口、字段、匹配关系的一次性探查脚本
scripts/tasks/                PowerShell 任务入口
scripts/utilities/            辅助工具脚本
src/dy_data/config.py         统一配置读取
src/dy_data/sku.py            SKU 和商品类型映射
src/dy_data/paths.py          路径读取辅助
src/dy_data/csv_io.py         CSV 读写辅助
src/dy_data/douyin_client.py  抖音接口常量和请求头辅助
```

## Production Docker Compose

The Linux production skeleton lives in `deploy/` and is intended for a single-server MVP:

- `postgres`: PostgreSQL primary store.
- `api`: FastAPI image supplied by the backend slice.
- `worker`: scheduled jobs and browser export jobs.
- `web`: static React/Vite build served by Nginx.
- `browser`: Chromium + noVNC for Douyin backend login/export flows.
- `proxy`: the only published entrypoint.

Create a local env file from placeholders and replace every `CHANGE_ME_*` value on the server:

```bash
cp deploy/.env.example deploy/.env
docker compose --env-file deploy/.env -f deploy/compose.yaml config
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build
```

Do not commit `deploy/.env`, browser profiles, cookies, downloads, exported files, or real server paths. Raw service ports are not published; noVNC is only available through the proxy at `/browser/`, where Nginx checks the same admin session through `/api/v1/auth/me` before proxying to the browser container.
