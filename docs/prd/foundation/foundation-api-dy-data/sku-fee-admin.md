# SKU、双费率与导入 API

> 所属索引: [foundation-api-dy-data.md](../foundation-api-dy-data.md)
> 消费页面: SKU 规则后台及其批量导入区
> 权限: 授权后台管理员；发布类动作须记录操作人、原因、请求 ID 和幂等键

## 0 共享响应对象

### 0.1 `SkuProductItem`

| 字段 | 类型 | 说明 | 来源表.列 |
|------|------|------|----------|
| `skuId` | string | SKU 业务 ID | `dim_sku_product_rules.sku_id` |
| `skuName` | string/null | SKU 名称 | `.sku_name` |
| `productId` | string/null | 商品 ID | `.product_id` |
| `productName` | string/null | 商品名称 | `.product_name` |
| `spuId` | string/null | SPU ID | `.spu_id` |
| `productScope` | string | 产品范围 | `.product_scope` |
| `productType` | string | 商品类型 | `.product_type` |
| `isServiceProduct` | boolean | 是否服务类商品 | `.is_service_product` |
| `creatorAccountId` | string/null | 创建者账号 ID | `.creator_account_id` |
| `creatorAccountName` | string/null | 创建者名称 | `.creator_account_name` |
| `ownerAccountId` | string/null | 归属账号 ID | `.owner_account_id` |
| `ownerAccountName` | string/null | 归属账号名称 | `.owner_account_name` |
| `productStatus` | string/null | `ACTIVE/INACTIVE/DELETED/UNKNOWN` | `.product_status_normalized` |
| `isActiveProduct` | boolean | 是否有效商品 | `.is_active_product` |
| `lastSyncedAt` | datetime/null | 最近成功同步时间 | `.last_synced_at` |
| `manualModifiedAt` | datetime/null | 人工字段最后修改时间 | `.manual_modified_at` |

### 0.2 `SkuFeeRuleItem`

| 字段 | 类型 | 说明 | 来源表.列 |
|------|------|------|----------|
| `ruleVersion` | string | 不可变规则版本 | `sku_fee_rule.rule_version` |
| `skuId` | string | SKU ID | `.sku_id` |
| `skuName` | string/null | 发布时名称快照 | `.sku_name_snapshot` |
| `productScope` | string | 发布时产品范围 | `.product_scope_snapshot` |
| `productType` | string | 发布时商品类型 | `.product_type_snapshot` |
| `promotionServiceFeeRate` | decimal-string | 推广服务费率 | `.promotion_service_fee_rate` |
| `managementServiceFeeRate` | decimal-string | 管理服务费率 | `.management_service_fee_rate` |
| `effectiveDate` | date | 生效自然日 | `.effective_date` |
| `effectiveAt` | datetime | 上海时区当日零点 | `.effective_at` |
| `ruleStatus` | string | `ACTIVE/INACTIVE` | `.rule_status` |
| `previousRuleVersion` | string/null | 上一版本 | `.previous_rule_version` |
| `createdBy` | string | 创建人 | `.created_by` |
| `changeReason` | string | 变更原因 | `.change_reason` |
| `publishedAt` | datetime | 发布时间 | `.published_at` |

### 0.3 `ImportBatchItem`

| 字段 | 类型 | 说明 | 来源表.列 |
|------|------|------|----------|
| `batchId` | string | 导入批次 ID | `sku_fee_rule_import_batch.batch_id` |
| `fileName` | string | 原始文件名 | `.file_name` |
| `batchStatus` | string | `UPLOADED/VALIDATION_FAILED/PENDING_COMMIT/COMMITTING/COMPLETED/FAILED` | `.batch_status` |
| `commitMode` | string | 固定 `ATOMIC` | `.commit_mode` |
| `effectiveDate` | date | 整批生效日 | `.effective_date` |
| `totalCount` | integer | 总行数 | `.total_count` |
| `validCount` | integer | 合法行数 | `.valid_count` |
| `successCount` | integer | 成功写入行数 | `.success_count` |
| `failedCount` | integer | 非法/失败行数 | `.failed_count` |
| `uploadedBy` | string | 上传人 | `.uploaded_by` |
| `validatedAt` | datetime/null | 校验完成时间 | `.validated_at` |
| `committedAt` | datetime/null | 提交完成时间 | `.committed_at` |
| `hasResultFile` | boolean | 是否可下载结果 | `.result_file_key` 是否非空 |

### 0.4 `ImportRowItem`

| 字段 | 类型 | 说明 | 来源表.列 |
|------|------|------|----------|
| `rowNumber` | integer | 原文件行号 | `sku_fee_rule_import_row.row_number` |
| `skuName` | string/null | 解析名称 | `.sku_name` |
| `skuId` | string/null | 解析 SKU ID | `.sku_id` |
| `promotionServiceFeeRate` | decimal-string/null | 解析推广费率 | `.promotion_service_fee_rate` |
| `managementServiceFeeRate` | decimal-string/null | 解析管理费率 | `.management_service_fee_rate` |
| `validationStatus` | string | `PENDING/VALID/INVALID/COMMITTED/COMMIT_FAILED` | `.validation_status` |
| `errors` | array | 全部 `{ field, code, message }` | `.validation_errors_json` |
| `createdRuleVersion` | string/null | 成功生成的版本 | `.created_rule_version` |

## 1 `GET /api/v1/admin/sku-products` — SKU 商品列表

> 数据源表: `dim_sku_product_rules`

**请求参数**：`page`、`pageSize`、`q`（SKU ID/名称/商品名）、`productScope`、`productType`、`productStatus`、`isActiveProduct`。

**响应 `data`**：分页对象，`list` 项为 `SkuProductItem`。

**约束**：商品同步失败时返回最后一次成功快照；不得用失败载荷覆盖当前快照。

## 2 `PUT /api/v1/admin/sku-products/{skuId}` — 更新 SKU 人工分类

> 数据源表: `dim_sku_product_rules`

**请求 JSON**：

| 字段 | 类型 | 必填 | 说明 | 写入列 |
|------|------|:---:|------|--------|
| `productScope` | string | 是 | 产品范围，1～128 字符 | `.product_scope` |
| `productType` | string | 是 | 商品类型，1～128 字符 | `.product_type` |
| `isServiceProduct` | boolean | 是 | 是否服务类商品 | `.is_service_product` |

**响应 `data`**：更新后的 `SkuProductItem`。

**约束**：只允许更新三个人工字段和审计列；请求中的平台字段即使出现也必须拒绝。SKU 不存在返回 404。成功后使筛选元数据和相关投影缓存失效。

## 3 `GET /api/v1/admin/sku-fee-rules` — 双费率版本列表

> 数据源表: `sku_fee_rule`

**请求参数**：`page`、`pageSize`、`q`、`skuId`、`productScope`、`productType`、`ruleStatus`、`effectiveDateFrom`、`effectiveDateTo`、`asOfDate`。

**响应 `data`**：分页对象，`list` 项为 `SkuFeeRuleItem`。`asOfDate` 存在时可附加 `isMatchedVersion`，表示该日实际匹配版本。

## 4 `GET /api/v1/admin/sku-fee-rules/{ruleVersion}` — 费率版本详情

> 数据源表: `sku_fee_rule`

**响应 `data`**：`SkuFeeRuleItem`。不存在返回 404；已被后续版本替代仍可查询。

## 5 `POST /api/v1/admin/sku-fee-rules` — 发布单条费率版本

> 数据源表: `dim_sku_product_rules`、`sku_fee_rule`
> 请求头: 必须提供 `Idempotency-Key`

**请求 JSON**：

| 字段 | 类型 | 必填 | 说明 | 写入列 |
|------|------|:---:|------|--------|
| `skuId` | string | 是 | 必须存在于 SKU 事实源 | `sku_fee_rule.sku_id` |
| `promotionServiceFeeRate` | decimal-string | 是 | 0～1，最多六位小数 | `.promotion_service_fee_rate` |
| `managementServiceFeeRate` | decimal-string | 是 | 0～1，最多六位小数 | `.management_service_fee_rate` |
| `effectiveDate` | date | 是 | 首批为 `2026-08-01`，后续可到日 | `.effective_date/effective_at` |
| `ruleStatus` | string | 是 | `ACTIVE/INACTIVE` | `.rule_status` |
| `changeReason` | string | 是 | 1～512 字符 | `.change_reason` |

**响应 `data`**：新建的 `SkuFeeRuleItem`。

**事务与校验**：名称和产品维度由 `dim_sku_product_rules` 快照，客户端不得提交；同一 `skuId + effectiveDate` 冲突返回 409；成功只新增版本，不回写历史结果，也不触碰已锁账账单。

## 6 `GET /api/v1/admin/sku-fee-rule-imports` — 导入批次列表

> 数据源表: `sku_fee_rule_import_batch`

**请求参数**：`page`、`pageSize`、`batchStatus`、`effectiveDateFrom`、`effectiveDateTo`、`uploadedBy`。

**响应 `data`**：分页对象，`list` 项为 `ImportBatchItem`。

## 7 `POST /api/v1/admin/sku-fee-rule-imports` — 上传并预校验

> Content-Type: `multipart/form-data`
> 数据源表: `sku_fee_rule_import_batch`、`sku_fee_rule_import_row`；只校验，不写 `sku_fee_rule`

**表单字段**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `file` | binary | 是 | `.xlsx` 或 UTF-8 `.csv`，≤10 MiB、≤5000 数据行，已在 Phase 4 确认 |
| `effectiveDate` | date | 是 | 整批统一生效日 |

**模板业务列**：`skuName`、`skuId`、`promotionServiceFeeRate`、`managementServiceFeeRate`，四列均必填。

**响应 `data`**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `batch` | `ImportBatchItem` | 批次汇总 |
| `errorPreview` | `ImportRowItem[]` | 前 100 个非法行；同一行返回全部错误 |
| `hasMoreErrors` | boolean | 是否需从详情或结果文件查看其余错误 |

**全量校验**：模板/类型、四字段、SKU 名称与 ID 对应、费率范围、批内 SKU 重复、数据库同 SKU/生效日冲突。任一行错误时 `batchStatus=VALIDATION_FAILED`、`successCount=0`，正式规则零写入。

## 8 `GET /api/v1/admin/sku-fee-rule-imports/{batchId}` — 导入批次详情

> 数据源表: 两张费率导入表

**请求参数**：`page`、`pageSize`、`validationStatus`。

**响应 `data`**：`{ batch: ImportBatchItem, rows: { list: ImportRowItem[], total, page, pageSize } }`。

## 9 `POST /api/v1/admin/sku-fee-rule-imports/{batchId}/commit` — 原子发布整批规则

> 数据源表: 两张费率导入表、`sku_fee_rule`
> 请求头: 必须提供 `Idempotency-Key`

**请求 JSON**：`{ "changeReason": "2026-08 正式费率首批发布" }`，原因 1～512 字符。

**响应 `data`**：`{ batch: ImportBatchItem, createdRuleVersions: string[] }`。

**事务**：仅 `PENDING_COMMIT` 可提交；事务内重新校验所有行及唯一冲突，再一次性插入全部费率版本并更新逐行/批次状态。任一插入失败整批回滚，`successCount=0`，不得留下部分规则。完成批次的幂等重试返回原结果。

## 10 `GET /api/v1/admin/sku-fee-rule-imports/{batchId}/result-file` — 下载结果文件

> 数据源表: 两张费率导入表

返回与上传格式相匹配的文件，保留四个原始业务列并追加 `validationStatus`、`errorFields`、`errorMessages`、`createdRuleVersion`。文件名不得包含本地路径；无结果文件返回 404。

## 11 `GET /api/v1/admin/sku-fee-rule-imports/template` — 下载导入模板

无请求参数。返回四列模板及填写说明；不包含真实 SKU、账号或费率数据。

## 12 `GET /api/v1/admin/settlement-scope-rules` — 结算范围版本列表

> 数据源表: `settlement_scope_rule`

**请求参数**：`page`、`pageSize`、`effectiveMonth`、`ownerAccountId`、`saleChannel`、`isActive`。

**响应 `list` 项**：`scopeRuleVersion`、`effectiveMonth`、`ownerAccountId`、`saleChannel`（`LIVE/SHORT_VIDEO`）、`isActive`、`createdBy`、`changeReason`、`createdAt`，逐字段映射同名 Schema 列。

## 13 `POST /api/v1/admin/settlement-scope-rules` — 发布结算范围版本

> 数据源表: `settlement_scope_rule`
> 请求头: 必须提供 `Idempotency-Key`

**请求 JSON**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `effectiveMonth` | string | 是 | `YYYY-MM` |
| `ownerAccountId` | string | 是 | 稳定平台归属账号 ID，不接受名称替代 |
| `allowedSaleChannels` | string[] | 是 | 仅 `LIVE`、`SHORT_VIDEO`，去重后至少一项 |
| `changeReason` | string | 是 | 变更原因 |

**响应 `data`**：`{ scopeRuleVersions: string[], effectiveMonth, ownerAccountId, allowedSaleChannels }`。

**约束**：按渠道分别创建不可变版本；同月、同账号、同渠道冲突返回 409。未知渠道默认不计费并进入数据质量问题，不允许通过该接口配置为“默认允许”。
