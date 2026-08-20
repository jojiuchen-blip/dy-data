# PRD 5: 指标、发票与订单穿透

> **文档版本**: 1.0 | **最后更新**: 2026-08-20
> **关联文档**: [mainprd](../mainprd-dy-data.md) · [PRD 4](04-subprd-invoice-registration.md) · [用户流程](../../../src/frontend/page-preview/explainer-flow-dy-data.md) · [交互语义](../../../src/frontend/page-preview/explainer-b-interaction-dy-data.md) · [术语表](../foundation/foundation-glossary-dy-data.md) · [Schema](../foundation/foundation-schema-dy-data.md) · [API](../foundation/foundation-api-dy-data.md)

## §1 文档范围

本文档覆盖**管理员推广服务费**（单月/累计指标 + 四态发票 + 订单穿透）。

### 需求清单

| # | 需求 | 需求简述 | 对应章节 |
|---|---|---|---|
| R1 | 指标查询 | 展示推广费单月和正式累计 | §3 |
| R2 | 状态查询 | 按固定四态筛选当前有效发票 | §3 |
| R3 | 订单穿透 | 进入推广服务费订单明细 | §3 |

## §2 页面整体布局

```
[单月/累计][账期/门店/状态] [账单总额][已确认][待开票][已开票][已结算] [发票表][订单]
```

## §3 推广费财务工作台

### 3.1 用户体验

**数据来源**：`GET /api/v1/admin/finance/summary`、`GET /api/v1/admin/finance/invoices`、`GET /api/v1/admin/finance/order-details`。

**交互语义引用**：`dy19.routing.navigate.1`、`dy19.metrics.scope.1`、`dy19.promotion.status.1`

**布局**：

```
[PROMOTION][MONTH/CUMULATIVE] [指标卡] [四态列表] [查看订单]
```

**前端职责**：只渲染后端指标和状态；不把“待厂端审核”解释为系统内待审核任务。

### 3.2 服务端处理逻辑

1. 以 `feeDirection=PROMOTION` 校验管理员页面权限和门店范围。
2. 单月按账期聚合；累计从 `2026-08` 至截止月，确认金额仍只返回所选单月。
3. 已开票只统计当前有效发票；已结算来自管理员导入的系统外结果。

### 3.3 数据链路

| UI 元素 | API 字段 | 计算规则 | 数据源（服务端读取） | 配置源（服务端读取） |
|---|---|---|---|---|
| 账单总额 | `statementAmountCent` | 当前有效推广费账单净额 | `settlement_statement.promotion_net_fee_cent` | — |
| 已确认 | `confirmedAmountCent` | 仅所选单月有效确认 | `settlement_statement_confirmation.confirmed_amount_cent` | — |
| 已开票/已结算 | `invoicedAmountCent/settledAmountCent` | 当前发票按状态汇总 | `invoice_record.invoice_amount_cent/invoice_status` | — |
| 状态更新时间 | `registeredAt` | 最近当前版本事件时间 | `invoice_record.registered_at` | — |

### 3.4 异常与兜底

**服务端兜底**：

| 场景 | 处理 |
|---|---|
| 累计截止月早于正式账期 | 返回零累计和口径说明 |
| 越权门店 | 返回 403，不返回聚合值 |

**前端渲染兜底**：

| 场景 | 处理 |
|---|---|
| 无发票 | 显示待开票空态，不显示审核任务 |
| 查询失败 | 保留筛选并提供重试，不沿用旧指标 |

### 3.6 验收

| # | 类型 | 场景 | 触发条件 | 预期结果 |
|---|---|---|---|---|
| 1 | 业务规则 | 累计口径 | 切换累计 | 从 2026-08 起累计，确认金额仍为单月 |
| 2 | 业务规则 | 系统外结果 | 状态为待厂端审核 | 系统内不存在审核任务或审批按钮 |
| 3 | UX 交互 | 订单穿透 | 点击推广费订单 | 进入 `/finance/orders/promotion` 并保持方向 |

## §4 接口契约

### 4.1 接口引用

完整契约见 [账单发票 API §4.3](../foundation/foundation-api-dy-data/billing-invoice.md#43-管理员财务查询-3134)。
