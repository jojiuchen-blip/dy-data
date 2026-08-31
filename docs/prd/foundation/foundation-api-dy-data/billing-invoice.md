# 账单确认、异议、发票登记与财务导入 API

> 增量来源: DYDATA-19 冻结规格（2026-08-20）
> 消费路由: `/settlement`、`/settlement/invoice`、`/finance/promotion`、`/finance/management`、`/finance/orders/*`、`/finance/stores`、`/finance/disputes`、`/finance/imports`
> S4 回捞: 2026-08-21 按 `S4-FCR-001` 补齐不可变账单版本链、当前版本并发校验和新版本原子切换契约

## 0 公共业务约束

- 所有接口沿用 `{ data, definitions?, meta }` 项目包络；JSON 使用 camelCase；时间返回 ISO 8601 +08:00。
- 门店接口同时校验页面权限和 `storeId` 范围；管理员接口要求管理员或最高管理员角色，两者在本模块业务动作权限一致。财务人员使用管理员角色，不新增财务角色。
- 所有 POST 接受 `Idempotency-Key`；确认、发票登记、异议处理和导入提交同时校验当前版本。账单相关请求的 `readVersion` 固定对应 `settlement_statement.version_no`，不是数据库自增 ID 或锁版本号。
- 409 至少区分 `STATEMENT_VERSION_CONFLICT`、`INVOICE_VERSION_CONFLICT`、`IMPORT_VERSION_CONFLICT`；账单版本冲突响应返回 `readVersion/currentVersion/currentStatementId/lastOperator/lastOperatedAt`。
- 同一 `storeId + month` 可以永久保留多个不可变账单版本，但只能有一个 `isCurrent=true`；任何新版本都通过 `supersedesStatementId` 指向直接上一版本。
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

查询：`storeId` 必填，`month` 必填，`metricScope=MONTH/CUMULATIVE` 必填，`feeDirection` 可选，`page/pageSize`。列表按门店和账期只返回当前有效账单版本；累计从 `2026-08` 开始，测试账期不计入。

`data`：`list[]` 至少返回 `statementId/storeId/storeName/month/versionNo/isCurrent/supersedesStatementId/status/promotionAmountCent/managementAmountCent/promotionConfirmation/managementConfirmation/promotionInvoiceStatus/managementInvoiceStatus`；其中列表行的 `isCurrent` 必须为 `true`，首版 `supersedesStatementId=null`。`metrics` 返回当前单月值及可选 `cumulative`，确认金额只按单月展示。

### 2.2 `GET /api/v1/store-settlements/{statementId}`

返回账单头、方向确认、产品汇总行、来源明细摘要、异议摘要和发票摘要，并必返 `statementId/versionNo/isCurrent/supersedesStatementId`。`versions[]` 按 `versionNo` 倒序返回同门店同账期的 `statementId/versionNo/isCurrent/supersedesStatementId/status/createdAt`，使每个历史版本可独立回读；历史版本可查但不可再确认或登记发票。

### 2.3 `POST /api/v1/store-settlements/{statementId}/confirmations`

请求：`feeDirection` 必填，`confirmedAmountCent` 必填，`readVersion` 必填。服务端必须同时校验路径 `statementId` 仍是该门店账期的当前版本，且 `readVersion` 等于其 `versionNo`，再重新计算当前净额；任一条件不成立返回 `409 STATEMENT_VERSION_CONFLICT`。提交成功时间取系统校验无误后的服务器时间。

成功：返回 `confirmationId/status/confirmedAmountCent/confirmedAt/statementId/versionNo/isCurrent`。重复同幂等键返回原结果。推广费与管理服务费分别确认，不互相阻断。

## 3 门店异议与内部处理

### 3.1 `POST /api/v1/store-settlements/{statementId}/disputes`

请求：`feeDirection`、`disputeType=RATE_ERROR/DATA_MISSING/AMOUNT_ERROR/OTHER`、`description`、`contactName`、`contactPhone`、`disputedAmountCent`、`orders[]`、`readVersion`。`description` 为具体原因，去除首尾空白后不得为空；`orders[]` 含 `orderId/couponId?/disputedAmountCent`。不接受非空 `evidence` 字段，不创建或保存异议附件。

成功后状态为 `PENDING`（待处理）。异议不阻断另一费用方向，且用户已确认两个方向均不互相阻断。

### 3.2 `POST /api/v1/disputes/{disputeId}/withdrawals`

外部处理结果产生前可撤回并解除本方向冻结；管理员已作出金额调整后只标记撤回，不逆转既有调整，纠错需新建异议。请求含 `reason/readVersion`。

### 3.3 `GET /api/v1/admin/disputes` 与 `POST .../transitions`

列表筛选：`storeId/month/feeDirection/status/disputeType/submittedFrom/submittedTo/page/pageSize`。

处理请求：`targetStatus=IN_REVIEW/PENDING_ADMIN_APPROVAL/ACCEPTED_WITH_ADJUSTMENT/REJECTED`、`resolutionNote`、`adjustmentAmountCent?`、`readVersion`。`readVersion` 必须等于处理开始时该门店账期当前账单的 `versionNo`；冲突时返回 `409 STATEMENT_VERSION_CONFLICT`，不得写入部分结果。不存在“外部结果”字段。

`ACCEPTED_WITH_ADJUSTMENT` 必须在单一事务内完成：锁定当前账单 Vn → 生成完整不可变快照 Vn+1 → 复制 Vn 的账单行和版本内来源项并写入本次调整 → 设置 `supersedesStatementId=Vn.statementId` → 校验账单头、汇总行、来源项金额一致 → 将 Vn 切为 `isCurrent=false`、Vn+1 切为 `isCurrent=true` → 写入异议处理和操作审计。任一步失败都回滚，旧账单和旧确认永久保留。成功返回 `previousStatementId/previousVersion/currentStatementId/currentVersion`。

## 4 发票登记与财务查询

### 4.1 `GET /api/v1/promotion-invoices`

筛选：`storeId/month/status/page/pageSize`。列表按账期分配行返回当前有效及可选历史版本；每行同时返回发票头字段和 `statementId/statementMonth/allocatedAmountCent`，因此同一张合票会在其覆盖的每个账期各出现一行。状态固定为 `PENDING_INVOICE/SUBMITTED_PENDING_FACTORY_REVIEW/APPROVED_SETTLED/REJECTED_REUPLOAD`。

### 4.2 `POST /api/v1/promotion-invoices`

请求：`storeId/invoiceNumber/invoiceDate/invoiceAmountCent/allocations[]`；每个 `allocations[]` 元素为 `statementId/statementMonth/allocatedAmountCent/readVersion`。校验 20 位数电专票号码、日期、金额和每个账期推广费当前有效确认金额。发票可覆盖同一门店的多个完整账期；每个账期分配金额必须等于该账期有效确认金额，全部分配金额必须严格等于发票总额。同一门店同一账期只允许一条当前有效分配，不允许把账期拆到多张发票，也不允许跨门店合票。

成功状态为 `SUBMITTED_PENDING_FACTORY_REVIEW`，登记时间取服务器校验通过时间。重新上传生成新版本覆盖；不要求原发票 ID，不接收附件和备注，不调用外部验真或企业微信发送。

### 4.3 管理员财务查询 #31—#34

`feeDirection=PROMOTION/MANAGEMENT` 强制单选；`metricScope=MONTH/CUMULATIVE`；通用筛选含 `month/storeId/invoiceStatus/confirmationStatus/page/pageSize`。`summary` 返回账单总额、已确认金额、待开票金额、已开票金额、已结算/厂家扣款金额；管理费厂端视角“已开票金额”等于厂家扣款金额。

订单明细必须按 `feeDirection` 分页查询，推广服务费和管理服务费由两个子页面消费；`GET /api/v1/admin/finance/order-details/export` 必须复用 `month/feeDirection/storeId` 的筛选、数据范围和管理员授权，导出所有匹配行而不受列表分页影响。业务视图按账期统计，资金视图按实际结算/厂家扣款时间统计。

## 5 四类财务导入

### 5.1 `POST /api/v1/admin/finance-imports`

multipart 请求：`importType`、`statementMonth`、`file`，并要求 `Idempotency-Key`。模板类型固定为以下四类；只保存文件名、文件摘要、标准化摘要和逐行结果，不长期保存原文件。

| `importType` | 模板字段 | 业务唯一键 | 正式写入目标 |
|---|---|---|---|
| `BASIC_INFO` | `storeId/storeName/sapCode/importedAt` | `storeId` | `store_finance_profile` 基础信息新版本 |
| `PROMOTION_FACTORY_RESULT` | `invoiceNumber/reviewResult/rejectionReason/settlementDate/settlementAmountCent` | `invoiceNumber` | `promotion_invoice` 新版本及 `invoice_status_event` |
| `MANAGEMENT_FACTORY_RESULT` | `storeId/statementMonth/storeName/invoiceNumber/invoiceDate/deductionDate/deductionAmountCent` | `storeId + statementMonth` | `invoice_record` 管理费厂家结果新版本 |
| `SAP_CONFIRMATION` | `storeId/storeName/financeInitialSap/serviceStoreCode/factoryConfirmationResult/confirmedAt` | `storeId` | `store_finance_profile` SAP 确认新版本 |

处理顺序：流式解析 → 全行格式校验 → 业务唯一键精确匹配 → 门店 ID 与门店名称二次一致性校验（适用模板）→ 当前版本差异比较。推广服务费厂家结果只按 20 位发票号码精确匹配当前发票及批次账期；禁止 SAP 编码、名称、金额或月份模糊匹配；禁止部分写入、自动截断和人工待匹配池。

同一上传幂等键与相同“模板 + 账期 + 文件摘要”重放原批次；同键不同请求返回 `409 IDEMPOTENCY_KEY_REUSED`。相同标准化业务内容但使用新幂等键时返回 `NO_CHANGE`，不生成业务版本。

返回五种场景：`FIRST_IMPORT_READY`、`NO_CHANGE`、`DIFF_CONFIRMATION_REQUIRED`、`BATCH_VALIDATION_FAILED`、`VERSION_CONFLICT`。失败时返回错误总数和分页首批错误；完整错误由 #42 下载。

### 5.2 `GET /api/v1/admin/finance-imports/{batchId}`

查询：`errorPage/errorPageSize`。返回 `readVersion/currentVersion/contentChanged/diffSummary/totalRows/successRows/errorRows/errors.list`。每条错误含 `rowNumber/businessKey/field/originalValue/reason/suggestion`，同一行全部错误均保留。

### 5.3 `POST .../{batchId}/commits` 与 `/corrections`

请求：`readVersion/changeReason`。提交前重新校验当前版本；冲突返回 409 和最近操作人/时间。四类模板统一采用版本机制：新值生成新版本；更正导入覆盖当前版本；不删除历史。

管理服务费厂家结果在当期导入上一账期，并在同一行登记发票号码、开票日期、厂家扣款日期和全额扣款金额；不再提供独立“管理费发票明细”和“厂家扣款结果”模板。系统导入时间为审核通过/已结算记录时间，厂家扣款不允许部分扣款，金额必须严格等于账期有效确认金额。推广费模板登记系统外厂家结果，不创建系统内审核任务。

## 6 明确不提供

- 不提供开票申请单、真实开票、发票附件上传、外部验真、企业微信发送接口。
- 不提供系统内“财务审核任务”接口；推广费厂端审核已在系统外完成，管理员只导入结果。
- 不提供发票 DELETE、红冲原因、作废原因或原发票 ID 链接；错误通过新版本或更正导入覆盖。
- 不提供按 SAP 编码、名称、金额、月份的模糊匹配或跨门店合并开票。
