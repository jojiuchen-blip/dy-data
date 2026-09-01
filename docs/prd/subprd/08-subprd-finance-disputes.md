# PRD 8: 门店提交与管理员处理

> **文档版本**: 1.1 | **最后更新**: 2026-08-31
> **关联文档**: [mainprd](../mainprd-dy-data.md) · [PRD 2](02-subprd-store-settlement.md) · [用户流程](../../../src/frontend/page-preview/explainer-flow-dy-data.md) · [交互语义](../../../src/frontend/page-preview/explainer-b-interaction-dy-data.md) · [术语表](../foundation/foundation-glossary-dy-data.md) · [Schema](../foundation/foundation-schema-dy-data.md) · [API](../foundation/foundation-api-dy-data.md)

## §1 文档范围

本文档覆盖**账单异议**（门店提交/撤回 + 内部管理员处理 + 新账单版本）。

### 需求清单

| # | 需求 | 需求简述 | 对应章节 |
|---|---|---|---|
| R1 | 门店提交 | 提交完整异议、具体原因和账单事实 | §3 |
| R2 | 管理员处理 | 系统内流转并记录结果 | §3 |
| R3 | 撤回与纠正 | 按结果产生前后采用不同规则 | §3 |

## §2 页面整体布局

```
[筛选][异议列表] [类型/订单/金额/具体原因/联系人] [状态处理][历史]
```

## §3 异议生命周期

### 3.1 用户体验

**数据来源**：门店 `GET/POST /api/v1/store-settlements/{statementId}/disputes`、`POST /api/v1/disputes/{disputeId}/withdrawals`；管理员 `GET /api/v1/admin/disputes`、`POST /api/v1/admin/disputes/{disputeId}/transitions`。

**交互语义引用**：`dy19.routing.navigate.1`

**布局**：

```
[待处理 → 审核中 → 待管理员审批 → 成立并调整 / 不成立] [撤回]
```

**前端职责**：按服务端能力显示操作；不推导异议是否成立，不使用“外部结果”文案。

### 3.2 服务端处理逻辑

1. 门店提交费用方向、类型、具体原因、争议订单、金额、联系人和手机号。
2. 异议只冻结本方向相关处理，推广费和管理费互不阻断。
3. 管理员在系统内流转；成立并调整生成新账单版本，旧版本和确认永久保留。
4. 结果产生前可撤回并解除冻结；结果后撤回不逆转金额调整，纠正需新异议。

### 3.3 数据链路

| UI 元素 | API 字段 | 计算规则 | 数据源（服务端读取） | 配置源（服务端读取） |
|---|---|---|---|---|
| 类型/状态 | `disputeType/status` | 固定枚举 | `settlement_dispute.dispute_type/status` | — |
| 争议订单 | `orders[]` | 精确订单/券范围 | `settlement_dispute_order.order_id/coupon_id` | — |
| 具体原因 | `description` | 必填、去除首尾空白后不得为空；不新增未确认的长度限制 | `settlement_dispute.description` | — |
| 处理结果 | `resolutionNote/resultStatementId` | 成立时指向新账单版本 | `settlement_dispute.resolution_note/result_statement_id` | — |

### 3.4 异常与兜底

**服务端兜底**：

| 场景 | 处理 |
|---|---|
| 订单不属于账单版本 | 422 拒绝提交 |
| 状态并发变化 | 409 返回当前状态和版本 |
| 结果后撤回 | 保留调整，要求新建纠正异议 |

**前端渲染兜底**：

| 场景 | 处理 |
|---|---|
| 手机号展示 | 仅显示脱敏值 |
| 具体原因为空 | 保留表单并提示填写具体原因，不提交 |

### 3.5 用户裁决（2026-08-31）

- 账单异议取消文件上传，不创建对象存储、附件读取、清理或文件绑定流程。
- 新建异议使用现有 `description` 字段填写具体原因；请求中不接受非空 `evidence`，新建记录的 `evidence_json` 固定为空列表。
- 历史记录中的 `evidence_json` 仅为兼容既有数据的只读返回，不作为新建异议的输入或发布依赖。

### 3.6 验收

| # | 类型 | 场景 | 触发条件 | 预期结果 |
|---|---|---|---|---|
| 1 | 业务规则 | 方向隔离 | 推广费存在异议 | 管理费确认和处理不被阻断 |
| 2 | 业务规则 | 成立调整 | 管理员确认成立 | 生成新账单版本，旧版本和确认可查 |
| 3 | 异常兜底 | 结果后撤回 | 已产生金额调整 | 不逆转调整，提示新建纠正异议 |

## §4 接口契约

### 4.1 接口：异议 #26—#28、#35—#36

完整契约见 [账单发票 API §3](../foundation/foundation-api-dy-data/billing-invoice.md#3-门店异议与内部处理)。
