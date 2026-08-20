# PRD 6: 指标、扣款与订单穿透

> **文档版本**: 1.0 | **最后更新**: 2026-08-20
> **关联文档**: [mainprd](../mainprd-dy-data.md) · [PRD 5](05-subprd-finance-promotion.md) · [用户流程](../../../src/frontend/page-preview/explainer-flow-dy-data.md) · [交互语义](../../../src/frontend/page-preview/explainer-b-interaction-dy-data.md) · [术语表](../foundation/foundation-glossary-dy-data.md) · [Schema](../foundation/foundation-schema-dy-data.md) · [API](../foundation/foundation-api-dy-data.md)

## §1 文档范围

本文档覆盖**管理员管理服务费**（单月/累计指标 + 厂家扣款/发票 + 订单穿透）。

### 需求清单

| # | 需求 | 需求简述 | 对应章节 |
|---|---|---|---|
| R1 | 指标查询 | 查询管理服务费单月和累计 | §3 |
| R2 | 扣款查询 | 查询管理员导入的当前有效厂家扣款/发票 | §3 |
| R3 | 订单穿透 | 进入管理服务费订单明细 | §3 |

## §2 页面整体布局

```
[单月/累计][账期/门店] [账单总额][已确认][待开票][已开票/扣款] [明细表][订单]
```

## §3 管理服务费财务工作台

### 3.1 用户体验

**数据来源**：`GET /api/v1/admin/finance/summary`、`GET /api/v1/admin/finance/invoices`、`GET /api/v1/admin/finance/order-details`。

**交互语义引用**：`dy19.routing.navigate.1`、`dy19.metrics.scope.1`

**布局**：

```
[MANAGEMENT][MONTH/CUMULATIVE] [指标卡] [厂家扣款/发票列表] [查看订单]
```

**前端职责**：不套用推广费审核四态；“已开票金额”和“厂家扣款金额”按厂端同一事实展示。

### 3.2 服务端处理逻辑

1. 以 `feeDirection=MANAGEMENT` 读取当前账单、确认和当前有效发票版本。
2. 管理员当期导入上一账期；导入成功时间同时为审核通过和已结算时间。
3. 不允许部分扣款；负向调整按同方向后续正数账期结转，不回改历史扣款。

### 3.3 数据链路

| UI 元素 | API 字段 | 计算规则 | 数据源（服务端读取） | 配置源（服务端读取） |
|---|---|---|---|---|
| 管理费账单 | `statementAmountCent` | 当前有效管理费净额 | `settlement_statement.management_net_fee_cent` | — |
| 厂家扣款/已开票 | `invoicedAmountCent/deductionAmountCent` | 两字段同一当前有效金额 | `invoice_record.invoice_amount_cent` | — |
| 结算时间 | `settledAt` | 管理费导入成功服务器时间 | `invoice_record.registered_at` | — |

### 3.4 异常与兜底

**服务端兜底**：

| 场景 | 处理 |
|---|---|
| 部分扣款 | 422 拒绝整行/整批写入 |
| 负数未抵扣完成 | 继续结转后续正数账期，待开票显示不小于零 |

**前端渲染兜底**：

| 场景 | 处理 |
|---|---|
| 未导入 | 显示待开票，不显示推广费审核状态 |
| 负向结转 | 显示结转说明，不生成负数发票操作 |

### 3.6 验收

| # | 类型 | 场景 | 触发条件 | 预期结果 |
|---|---|---|---|---|
| 1 | 业务规则 | 当期导入上期 | 10 月导入 9 月明细 | 账期为 9 月，导入时间为结算时间 |
| 2 | 业务规则 | 厂端口径 | 已导入厂家扣款 | 已开票金额等于厂家扣款金额 |
| 3 | UX 交互 | 订单穿透 | 点击管理费订单 | 进入 `/finance/orders/management` 并保持方向 |

## §4 接口契约

### 4.1 接口引用

完整契约见 [账单发票 API §4.3](../foundation/foundation-api-dy-data/billing-invoice.md#43-管理员财务查询-3134)。
