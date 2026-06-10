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

当前脚本默认读取和输出到：

- `D:\app\抖音来客看板`
- `D:\浏览器下载`

如果迁移到其他电脑，需要同步调整脚本中的本地路径，或后续改造成配置文件读取。

## 运行说明

脚本依赖本地 Python 环境和抖音开放平台应用配置。运行前需要确保环境变量或脚本配置中有：

- `DOUYIN_APP_ID`
- `DOUYIN_APP_SECRET`
- `DOUYIN_ACCOUNT_ID`

看板 HTML 可直接用浏览器打开，也可以上传到腾讯云 COS 静态网站进行共享。
