# PRD 4: 发票登记、状态与历史

> **文档版本**: 2.0 | **最后更新**: 2026-08-20
> **关联文档**: [mainprd](../mainprd-dy-data.md) · [PRD 2](02-subprd-store-settlement.md) · [用户流程](../../../src/frontend/page-preview/explainer-flow-dy-data.md) · [交互语义](../../../src/frontend/page-preview/explainer-b-interaction-dy-data.md) · [术语表](../foundation/foundation-glossary-dy-data.md) · [Schema](../foundation/foundation-schema-dy-data.md) · [API](../foundation/foundation-api-dy-data.md)

## §1 文档范围

本文档覆盖**推广费发票登记**（系统外开票信息登记 + 四态状态 + 历史版本）。

### 需求清单

| # | 需求 | 需求简述 | 对应章节 |
|---|---|---|---|
| R1 | 发票登记 | 登记 20 位号码、日期、总金额及一个或多个完整账期分配 | §3 |
| R2 | 状态查询 | 查询四态状态与更新时间 | §3 |
| R3 | 重新登记 | 驳回后生成新版本覆盖 | §3 |

## §2 页面整体布局

```
[门店/账期/账单版本] [发票号码][日期][金额][登记] [状态时间线] [历史版本]
```

## §3 推广费发票登记

### 3.1 用户体验

**数据来源**：`GET /api/v1/promotion-invoices`；登记调用 `POST /api/v1/promotion-invoices`。

**交互语义引用**：`dy19.routing.navigate.1`、`dy19.promotion.status.1`

**布局**：

```
[待开票 → 提交成功，待厂端审核 → 审核通过，已结算 / 审核不通过，请重新上传]
```

**前端职责**：只登记系统外开票事实并展示服务端状态；不创建申请单、不执行开票、审核、验真或企业微信发送。

### 3.2 服务端处理逻辑

1. 校验门店、一个或多个完整账期、各账期当前账单版本及推广费有效确认。
2. 校验 20 位数电专票号码、日期、总金额、各账期分配金额和读取版本；同一张发票只允许同一门店，每个账期必须完整分配且不得拆票。
3. 新增发票版本及登记事件；状态设为“提交成功，待厂端审核”。
4. 管理员导入系统外审核/结算结果后追加状态事件；驳回重传生成新版本。

### 3.3 数据链路

| UI 元素 | API 字段 | 计算规则 | 数据源（服务端读取） | 配置源（服务端读取） |
|---|---|---|---|---|
| 发票号码 | `invoiceNumber` | 必须为 20 位 | `invoice_record.invoice_number` | — |
| 日期与金额 | `invoiceDate/invoiceAmountCent` | 金额等于有效确认分配金额 | `invoice_record.invoice_date/invoice_amount_cent` | — |
| 四态状态 | `invoiceStatus` | 只使用推广费四态 | `invoice_record.invoice_status` | — |
| 更新时间线 | `events[]` | 按事件时间升序 | `invoice_status_event.to_status/occurred_at` | — |

### 3.4 异常与兜底

**服务端兜底**：

| 场景 | 处理 |
|---|---|
| 未确认或金额不等 | 返回 422，不创建发票版本 |
| 已存在当前有效发票 | 返回 409 或按重新登记规则新增版本，绝不覆盖历史 |
| 版本冲突 | 返回 409 `INVOICE_VERSION_CONFLICT` |

**前端渲染兜底**：

| 场景 | 处理 |
|---|---|
| 驳回 | 显示“请重新上传/登记”并保留历史只读 |
| 提交失败 | 保留输入和账单上下文，不伪造成功状态 |

### 3.6 验收

| # | 类型 | 场景 | 触发条件 | 预期结果 |
|---|---|---|---|---|
| 1 | 业务规则 | 系统边界 | 门店进入页面 | 明确系统只登记，不执行开票、审核或发送 |
| 2 | 业务规则 | 完整账期分配 | 同一门店将一个或多个完整账期登记到一张发票 | 每个账期只有一条当前有效分配，不跨门店、不拆票，历史版本可查 |
| 3 | UX 交互 | 四态状态 | 管理员导入结果 | 状态只按固定四态变化并显示更新时间 |
| 4 | 异常兜底 | 版本冲突 | 提交期间当前版本变化 | 拒绝写入并要求刷新 |

## §4 接口契约

### 4.1 接口：`GET/POST /api/v1/promotion-invoices`

完整契约见 [账单发票 API §4](../foundation/foundation-api-dy-data/billing-invoice.md#4-发票登记与财务查询)。请求不含附件、备注或原发票 ID；通过 `allocations[]` 提交同一门店的一个或多个完整账期分配。
