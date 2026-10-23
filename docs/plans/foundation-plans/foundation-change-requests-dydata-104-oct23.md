# DYDATA-104 10月23日契约回捞

## S4-FCR-001 发票登记简化与可信金额摘要

| 字段 | 内容 |
|---|---|
| 来源 Task | dydata-104-followthrough T3.1 发布与验收 |
| 分类 | DRIFT |
| 改动项 | 账单列表增加 promotionInvoiceSummary；登记移除人工购买方、税率及三项金额，分配金额由服务端确认事实派生 |
| 原因 | 用户已批准10月23日新增范围；旧合同仍要求客户端金额，会与已验证的登记请求不符 |
| 指向代码块 | apps/api/dy_api/routes/dashboard.py:757；apps/api/dy_api/routes/dashboard.py:3830；tests/test_api_store_billing.py |
| 目标 foundation 文件:章节 | docs/prd/foundation/foundation-api-dy-data/billing-invoice.md §2.1、§4.2；foundation-schema-dy-data/billing-invoice.md 发票金额与审计 |
| 严重度 | 建议 |
| 状态 | 待评审 |

当前实现合同：`storeId/invoiceNumber/invoiceDate/fillerPhone/allocations[]`，分配项为 `statementId/statementMonth/readVersion/promotionInvoiceGroupId`，保留可选 `replacesInvoiceId`。旧五项人工字段及分配金额接受但忽略，不进入新幂等摘要。当前有效完整组必须全部覆盖，组内负抵扣保留；无合格组摘要为 null。总额由锁定后的确认金额合计，净额按整数分 `floor((总额×100+53)/106)`，税额为差额，整张合票只舍入一次。20位 ASCII 数字保留前导零，不调用外部验真。权限、日期、状态、版本、号码唯一性、事务和历史保护保持；旧幂等请求从持久化历史事实重建校验，不重写旧金额。

## S4-FCR-002 历史商品状态时间语义

| 字段 | 内容 |
|---|---|
| 来源 Task | dydata-104-followthrough T3.1 发布与验收 |
| 分类 | GAP |
| 改动项 | 明确历史账期有效商品的判定时间及证据来源 |
| 原因 | 当前代码用重算时平台状态；附件六笔历史轮胎订单的商品当前已下架，不能通过修改上线状态绕过 |
| 指向代码块 | apps/worker/settlement.py:3063；apps/worker/product_sync.py:785 |
| 目标 foundation 文件:章节 | docs/prd/foundation/foundation-glossary-dy-data.md 有效商品；foundation-schema-dy-data/product-rule-source.md 历史快照 |
| 严重度 | 阻断对应历史订单计费决策 |
| 状态 | 待评审 |

已向用户询问：对本次附件明确覆盖、历史已付款且已核销的订单，按历史交易和附件规则计算，或继续按当前下架状态排除。答复前保留现状，不把等待答复视为批准。
