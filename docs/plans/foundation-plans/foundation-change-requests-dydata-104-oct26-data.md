# DYDATA-104 数据根因契约回捞

## S4-FCR-DATA-001 OpenAPI 归属与诊断计数

| 字段 | 内容 |
|---|---|
| 来源 Task | dydata-104-followthrough T3.1，10月26日 D1–D7 核查与通用修复 |
| 分类 | GAP / DRIFT |
| 改动项 | 普通两费归属增加精确职人 UID / 完整历史区间 / 唯一 POI 门店兜底；记录具体拒绝原因；月结 issueCount 使用 blocked_count |
| 原因 | 不同来源 account_id 命名空间被混用，原始绑定区间未被普通解析消费，零调整数掩盖阻断数 |
| 代码 | apps/worker/settlement.py；apps/worker/settlement_rebuild.py |
| 目标 foundation | foundation-schema-dy-data/settlement-reporting.md 的归属证据；foundation-api-dy-data 的任务结果字段 |
| 保护 | 原有硬拒绝与历史裁决优先；不写账号/权限，不推断无日期历史，不改已确认/开票/锁账事实 |
| 状态 | 通用代码及专项验证完成，foundation 回捞待评审；生产未部署 |

完整边界、验证和后续验收见 [验证记录](../../verification/dydata-104-data-rootcause-oct26.md)。源码/快照验证不代替生产发布和业务验收；不得用新计数规则倒推历史任务当时完整通过。

## S4-FCR-DATA-002 冻结的销售归属依据与正式单据状态

| 字段 | 内容 |
| --- | --- |
| 来源 | DYDATA-104 / T3.1，2026 年 11 月 18 日验收意见 |
| 分类与状态 | GAP，待 foundation 评审 |
| 数据结构 | `settlement_fee_result.sale_account_match_json` 保存十月起使用的原始销售名称及其来源、资格版本与摘要、唯一账号、POI 和结算门店。此前费用可以缺少该字段。 |
| 业务读法 | 财务固定发布账单及其费用范围，另读当前合法确认、发票、厂家反馈与撤销。待出账行可有金额，仍需显示实际办理状态。 |
| 代码与目标文档 | `apps/worker/account_qualification.py`、`apps/worker/monthly_close_scope.py` 对应 `foundation-schema-dy-data/settlement-reporting.md`。`apps/api/dy_api/dashboard_publications/finance_live.py` 对应 `foundation-api-dy-data/billing-invoice.md`。 |
