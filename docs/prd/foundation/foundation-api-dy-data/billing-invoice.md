# 账单确认、异议、发票登记与财务导入 API

> 增量来源: DYDATA-19 冻结规格（2026-08-20）
> 消费路由: `/settlement`、`/settlement/invoice`、`/finance/promotion`、`/finance/management`、`/finance/orders/*`、`/finance/stores`、`/finance/disputes`、`/finance/imports`

## 0 公共业务约束

- 所有接口沿用 `{ data, definitions?, meta }` 项目包络；JSON 使用 camelCase；时间返回 ISO 8601 +08:00。
- 门店接口同时校验页面权限和 `storeId` 范围；管理员接口要求管理员或最高管理员角色，两者在本模块业务动作权限一致。财务人员使用管理员角色，不新增财务角色。
- 所有 POST 接受 `Idempotency-Key`；确认、发票登记、异议处理和导入提交同时校验当前版本。
- 409 至少区分 `STATEMENT_VERSION_CONFLICT`、`INVOICE_VERSION_CONFLICT`、`IMPORT_VERSION_CONFLICT`；响应返回 `readVersion/currentVersion/lastOperator/lastOperatedAt`。
- 系统不创建开票申请单、不执行真实开票，也不创建“待财务审核”任务；厂端审核结果只由管理员导入后改变推广费发票状态。

## 1 接口总览

| # | 方法 | 路径 | 用途 | 主要表 |
|---:|---|---|---|---|
| 23 | GET | `/api/v1/store-settlements` | 门店账单列表、单月/累计指标 | 账单、确认、发票 |
| 24 | GET | `/api/v1/store-settlements/{statementId}` | 当前或历史账单版本详情 | 账单头/行/来源项 |
| 25 | POST | `/api/v1/store-settlements/{statementId}/confirmations` | 按费用方向确认 | `settlement_statement_confirmation` |
| 26 | GET | `/api/v1/store-settlements/{statementId}/disputes` | 查询账单异议 | 两张异议表 |
| 27 | POST | `/api/v1/store-settlements/{statementId}/disputes` | 门店提交异议 | 两张异议表、审计 |
| 28 | POST | `/api/v1/disputes/{disputeId}/withdrawals` | 门店撤回未出结果异议 | 异议、审计 |
| 29 | GET | `/api/v1/promotion-invoices` | 门店查询推广费发票登记 | 发票、事件 |
| 30 | POST | `/api/v1/promotion-invoices` | 门店登记/重新登记推广费发票 | 发票、事件、审计 |
| 31 | GET | `/api/v1/admin/finance/summary` | 管理员按方向查询单月/累计指标 | 账单、确认、发票 |
| 32 | GET | `/api/v1/admin/finance/invoices` | 管理员查询推广/管理费发票 | 发票、事件 |
| 33 | GET | `/api/v1/admin/finance/order-details` | 管理员查询双方向订单明细 | 账单来源、费用结果 |
| 34 | GET | `/api/v1/admin/finance/stores` | 管理员查询门店聚合 | 账单、确认、发票投影 |
| 35 | GET | `/api/v1/admin/disputes` | 管理员异议工作台 | 两张异议表 |
| 36 | POST | `/api/v1/admin/disputes/{disputeId}/transitions` | 内部管理员处理异议 | 异议、账单版本、审计 |
| 37 | GET | `/api/v1/admin/finance-imports` | 导入历史 | 导入批次 |
| 38 | POST | `/api/v1/admin/finance-imports` | 上传四类模板并全量预校验 | 导入批次/行 |
| 39 | GET | `/api/v1/admin/finance-imports/{batchId}` | 查询批次、差异和分页错误 | 导入批次/行 |
| 40 | POST | `/api/v1/admin/finance-imports/{batchId}/commits` | 确认差异并原子提交 | 导入、发票、事件、审计 |
| 41 | POST | `/api/v1/admin/finance-imports/{batchId}/corrections` | 以更正版本覆盖当前结果 | 同上 |
| 42 | GET | `/api/v1/admin/finance-imports/{batchId}/error-file` | 下载全部错误行 | 导入行 |

## 2 门店账单与确认

### 2.1 `GET /api/v1/store-settlements`

查询：`storeId` 必填，`month` 必填，`metricScope=MONTH/CUMULATIVE` 必填，`feeDirection` 可选，`page/pageSize`。累计从 `2026-08` 开始，测试账期不计入。

`data`：`list[]` 至少返回 `statementId/storeId/storeName/month/versionNo/isCurrent/status/promotionAmountCent/managementAmountCent/promotionConfirmation/managementConfirmation/promotionInvoiceStatus/managementInvoiceStatus`；`metrics` 返回当前单月值及可选 `cumulative`，确认金额只按单月展示。

### 2.2 `GET /api/v1/store-settlements/{statementId}`

返回账单头、方向确认、产品汇总行、来源明细摘要、当前/历史版本列表、异议摘要和发票摘要。历史版本可查但不可再确认或登记发票。

### 2.3 `POST /api/v1/store-settlements/{statementId}/confirmations`

请求：`feeDirection` 必填，`confirmedAmountCent` 必填，`readVersion` 必填。服务端重新计算当前净额；仅当前账单版本可确认。提交成功时间取系统校验无误后的服务器时间。

成功：返回 `confirmationId/status/confirmedAmountCent/confirmedAt/statementVersion`。重复同幂等键返回原结果。推广费与管理服务费分别确认，不互相阻断。

## 3 门店异议与内部处理

### 3.1 `POST /api/v1/store-settlements/{statementId}/disputes`

请求：`feeDirection`、`disputeType=RATE_ERROR/DATA_MISSING/AMOUNT_ERROR/OTHER`、`description`、`contactName`、`contactPhone`、`disputedAmountCent`、`orders[]`、`evidence[]`、`readVersion`。`orders[]` 含 `orderId/couponId?/disputedAmountCent`；证明资料先经受控上传取得对象键。

成功后状态为 `PENDING`（待处理）。异议不阻断另一费用方向，且用户已确认两个方向均不互相阻断。

### 3.2 `POST /api/v1/disputes/{disputeId}/withdrawals`

外部处理结果产生前可撤回并解除本方向冻结；管理员已作出金额调整后只标记撤回，不逆转既有调整，纠错需新建异议。请求含 `reason/readVersion`。

### 3.3 `GET /api/v1/admin/disputes` 与 `POST .../transitions`

列表筛选：`storeId/month/feeDirection/status/disputeType/submittedFrom/submittedTo/page/pageSize`。

处理请求：`targetStatus=IN_REVIEW/PENDING_ADMIN_APPROVAL/ACCEPTED_WITH_ADJUSTMENT/REJECTED`、`resolutionNote`、`adjustmentAmountCent?`、`readVersion`。成立并调整时同事务生成新账单版本，旧账单和确认永久保留。不存在“外部结果”字段。

## 4 发票登记与财务查询

### 4.1 `GET /api/v1/promotion-invoices`

筛选：`storeId/month/status/page/pageSize`。返回当前有效及可选历史版本；状态固定为 `PENDING_INVOICE/SUBMITTED_PENDING_FACTORY_REVIEW/APPROVED_SETTLED/REJECTED_REUPLOAD`。

### 4.2 `POST /api/v1/promotion-invoices`

请求：`storeId/statementId/statementMonth/invoiceNumber/invoiceDate/invoiceAmountCent/readVersion`。校验 20 位数电专票号码、日期、金额和该账期推广费有效确认金额；一门店一账期只允许一张当前有效推广费发票，不跨账期、不拆票。

成功状态为 `SUBMITTED_PENDING_FACTORY_REVIEW`，登记时间取服务器校验通过时间。重新上传生成新版本覆盖；不要求原发票 ID，不接收附件和备注，不调用外部验真或企业微信发送。

### 4.3 管理员财务查询 #31—#34

`feeDirection=PROMOTION/MANAGEMENT` 强制单选；`metricScope=MONTH/CUMULATIVE`；通用筛选含 `month/storeId/invoiceStatus/confirmationStatus/page/pageSize`。`summary` 返回账单总额、已确认金额、待开票金额、已开票金额、已结算/厂家扣款金额；管理费厂端视角“已开票金额”等于厂家扣款金额。

订单明细必须按 `feeDirection` 分页查询，推广服务费和管理服务费由两个子页面消费；导出复用同一筛选和授权。业务视图按账期统计，资金视图按实际结算/厂家扣款时间统计。

## 5 四类财务导入

### 5.1 `POST /api/v1/admin/finance-imports`

multipart 请求：`importType`、`statementMonth`、`file`。模板类型固定四类；只保存文件名、文件摘要、标准化摘要和逐行结果，不长期保存原文件。

处理顺序：流式解析 → 全行格式校验 → 门店 ID 精确匹配 → 业务唯一键校验 → 当前版本差异比较。禁止 SAP 编码、名称、金额或月份模糊匹配；禁止部分写入、自动截断和人工待匹配池。

返回五种场景：`FIRST_IMPORT_READY`、`NO_CHANGE`、`DIFF_CONFIRMATION_REQUIRED`、`BATCH_VALIDATION_FAILED`、`VERSION_CONFLICT`。失败时返回错误总数和分页首批错误；完整错误由 #42 下载。

### 5.2 `GET /api/v1/admin/finance-imports/{batchId}`

查询：`errorPage/errorPageSize`。返回 `readVersion/currentVersion/contentChanged/diffSummary/totalRows/successRows/errorRows/errors.list`。每条错误含 `rowNumber/businessKey/field/originalValue/reason/suggestion`，同一行全部错误均保留。

### 5.3 `POST .../{batchId}/commits` 与 `/corrections`

请求：`readVersion/changeReason`。提交前重新校验当前版本；冲突返回 409 和最近操作人/时间。四类模板统一采用版本机制：新值生成新版本；更正导入覆盖当前版本；不删除历史。

管理服务费发票明细在当期导入上一账期，导入成功时间同时作为审核通过和已结算时间；不设置推广费的待审核状态链。厂家扣款不允许部分扣款，分配金额必须严格等于账期有效确认金额及发票金额。

## 6 明确不提供

- 不提供开票申请单、真实开票、发票附件上传、外部验真、企业微信发送接口。
- 不提供系统内“财务审核任务”接口；推广费厂端审核已在系统外完成，管理员只导入结果。
- 不提供发票 DELETE、红冲原因、作废原因或原发票 ID 链接；错误通过新版本或更正导入覆盖。
- 不提供按 SAP 编码、名称、金额、月份的模糊匹配或跨门店合并开票。
