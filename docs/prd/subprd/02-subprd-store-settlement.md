# PRD 2: 账单版本、方向确认与订单下钻

> **文档版本**: 2.0 | **最后更新**: 2026-08-20
> **关联文档**: [mainprd](../mainprd-dy-data.md) · [用户流程](../../../src/frontend/page-preview/explainer-flow-dy-data.md) · [交互语义](../../../src/frontend/page-preview/explainer-b-interaction-dy-data.md) · [术语表](../foundation/foundation-glossary-dy-data.md) · [Schema](../foundation/foundation-schema-dy-data.md) · [API](../foundation/foundation-api-dy-data.md)

## §1 文档范围

本文档覆盖**月度账单确认**（当前/历史版本 + 双方向确认 + 异议/开票/订单入口）。

### 需求清单

| # | 需求 | 需求简述 | 对应章节 |
|---|---|---|---|
| R1 | 账单查询 | 查询当前版本、历史版本及单月金额 | §3 |
| R2 | 方向确认 | 分别确认推广服务费和管理服务费 | §3 |
| R3 | 下游入口 | 携带账单版本进入订单、异议或发票登记 | §3 |

## §2 页面整体布局

门店页面由筛选、指标和双方向账单组成：

```
[账期][门店][版本] [推广费/管理费指标] [确认][异议][开票] [订单下钻]
```

## §3 账单版本与方向确认

### 3.1 用户体验

**数据来源**：`GET /api/v1/store-settlements`、`GET /api/v1/store-settlements/{statementId}`；确认调用 `POST /api/v1/store-settlements/{statementId}/confirmations`。

**交互语义引用**：`dy19.routing.navigate.1`、`dy19.metrics.scope.1`

**布局**：

```
[当前版本 Vn][历史版本] [推广费净额][管理费净额] [按方向确认] [查看订单]
```

**前端职责**：只渲染服务端金额、版本和能力状态；不自行计算确认金额、当前版本或自动确认时间。

### 3.2 服务端处理逻辑

1. 校验页面权限和门店范围，读取所选月当前账单版本。
2. 分别聚合两方向确认与当前发票状态；历史版本只读。
3. 确认时校验 `statementId/readVersion/confirmedAmountCent`；成功时间取服务器校验通过时间。
4. 1—6 日内等待门店确认，6 日后按自动确认规则处理；双方向互不阻断。

### 3.3 数据链路

| UI 元素 | API 字段 | 计算规则 | 数据源（服务端读取） | 配置源（服务端读取） |
|---|---|---|---|---|
| 当前版本 | `versionNo/isCurrent` | 只展示当前指针；历史只读 | `settlement_statement.version_no/is_current` | — |
| 双方向净额 | `promotionAmountCent/managementAmountCent` | 读取当前不可变账单快照 | `settlement_statement.promotion_net_fee_cent/management_net_fee_cent` | — |
| 方向确认 | `confirmationStatus/confirmedAt` | 每方向最多一条有效确认 | `settlement_statement_confirmation.fee_direction/confirmation_status/confirmed_at` | — |
| 订单下钻 | `statementId/feeDirection` | 作为来源上下文，服务端再次鉴权 | `settlement_statement.statement_id` | — |

### 3.4 异常与兜底

**服务端兜底**：

| 场景 | 处理 |
|---|---|
| 账单版本已变化 | 返回 409 `STATEMENT_VERSION_CONFLICT`，不写确认 |
| 无门店权限 | 返回 403，不返回账单摘要 |
| 金额不一致 | 返回 422 与当前服务端金额 |

**前端渲染兜底**：

| 场景 | 处理 |
|---|---|
| 409 冲突 | 展示读取/当前版本并刷新，不保留可提交旧金额 |
| 无数据 | 显示方向性空态，不沿用上一账期 |

### 3.6 验收

| # | 类型 | 场景 | 触发条件 | 预期结果 |
|---|---|---|---|---|
| 1 | 业务规则 | 双方向确认 | 仅推广费确认 | 管理服务费仍可独立确认且不被阻断 |
| 2 | 业务规则 | 新账单版本 | 重算生成 Vn+1 | Vn 及其确认永久可查，Vn+1 成为当前版本 |
| 3 | UX 交互 | 订单下钻 | 点击某方向查看订单 | 路由携带账单与方向上下文，服务端重新鉴权 |
| 4 | 异常兜底 | 并发确认 | 提交时版本已变化 | 整次写入拒绝并提示刷新 |

## §4 接口契约

### 4.1 接口：`GET /api/v1/store-settlements` 与 `POST /api/v1/store-settlements/{statementId}/confirmations`

完整契约见 [账单发票 API](../foundation/foundation-api-dy-data/billing-invoice.md)。前端不得由 URL、缓存金额或旧版本推导可确认状态。
