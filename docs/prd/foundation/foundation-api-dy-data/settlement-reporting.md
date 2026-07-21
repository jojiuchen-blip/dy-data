# 双费用结算与报表 API

> 所属索引: [foundation-api-dy-data.md](../foundation-api-dy-data.md)
> 消费页面: 全国门店榜单、单店分账、订单费用明细
> 只读边界: 开票确认页不调用发票 API；本轮无账单确认、锁账、修改或删除 Web 接口

## 0 共享枚举与口径

| 字段 | 枚举/格式 | 口径 |
|------|-----------|------|
| `periodType` | `MONTHLY/CUMULATIVE` | 累计只从 `2026-08` 开始 |
| `feeDirection` | `PROMOTION/MANAGEMENT` | 推广按销售业务日与销售月；管理按核销业务日与核销月 |
| `statementStatus` | `GENERATING/PENDING_CONFIRMATION/CONFIRMED/LOCKED` | 锁账后头、行、来源项不可改 |
| `dataStatus` | `VALID/ADJUSTED/BLOCKED/LOCKED` | 查询筛选派生状态 |
| `resultStatus` | `VALID/SUPERSEDED/DATA_QUALITY_BLOCKED` | 费用结果状态 |
| `adjustmentType` | `PARTIAL_REFUND/FULL_REFUND/VERIFY_CANCELLED/MANUAL_CORRECTION` | 调整只新增，不覆盖原结果 |

## 1 `GET /api/v1/dashboard/store-ranking` — 全国门店榜单

> 消费语义: `settlement-ranking.filter-and-rank.1`、`settlement-ranking.product-filter.2`
> 数据源表: `agg_store_ranking`
> 变更: 保留现有路径；增加月度/正式累计、双费用净额、销售金额和标准分页

**请求参数**：

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|:---:|:---:|------|
| `periodType` | string | 否 | `MONTHLY` | 月度或正式累计 |
| `periodKey` | string | 是 | — | 所选月份或累计截止月 `YYYY-MM` |
| `productScope` | string | 否 | `all` | 产品范围 |
| `productType` | string | 否 | `all` | 商品类型，须受产品范围约束 |
| `q` | string | 否 | — | 门店名称关键词 |
| `sortBy` | string | 否 | `NET_SETTLEMENT_REFERENCE` | 可选 `SALES_AMOUNT/VERIFIED_AMOUNT/PROMOTION_FEE/MANAGEMENT_FEE/NET_SETTLEMENT_REFERENCE` |
| `sortOrder` | string | 否 | `DESC` | `ASC/DESC` |
| `page` | integer | 否 | 1 | 全国前 20 例外用户固定为 1 |
| `pageSize` | integer | 否 | 20 | 例外访问最大 20 |

**响应 `data`**：

| 字段 | 类型 | 说明 | 来源表.列 |
|------|------|------|----------|
| `periodType` | string | 实际口径 | `agg_store_ranking.period_type` |
| `periodKey` | string | 月份/截止月 | `.period_key` |
| `productScope` | string | 产品范围 | `.product_scope` |
| `productType` | string | 商品类型 | `.product_type` |
| `formalPeriodStartMonth` | string | 固定 `2026-08` | 已确认业务规则 |
| `scopeMode` | string | `AUTHORIZED/GLOBAL_TOP_20_EXCEPTION` | 当前用户授权判定 |
| `totals` | object | 当前筛选总体指标 | 下列聚合字段求和 |
| `totals.salesOrderCount` | integer | 销售订单数 | `.sales_order_count` |
| `totals.salesAmountCent` | integer | 销售金额 | `.sales_amount_cent` |
| `totals.verifiedOrderCount` | integer | 核销订单数 | `.verified_order_count` |
| `totals.verifiedAmountCent` | integer | 核销金额 | `.verified_amount_cent` |
| `totals.promotionNetFeeCent` | integer | 推广费净额 | `.promotion_net_fee_cent` |
| `totals.managementNetFeeCent` | integer | 管理费净额 | `.management_net_fee_cent` |
| `totals.netSettlementReferenceCent` | integer | 推广净额减管理净额 | `.net_settlement_reference_cent` |
| `list` | array | 门店排名行 | `agg_store_ranking` |
| `list[].rank` | integer | 当前筛选排序名次 | 查询派生 |
| `list[].storeId` | string | 门店 ID | `.store_id` |
| `list[].storeName` | string | 名称快照 | `.store_name` |
| `list[]` 其余指标 | integer | 与 `totals` 同名的门店值 | 对应同名列 |
| `total` / `page` / `pageSize` | integer | 标准分页 | 查询派生 |

**权限与空态**：例外用户只能获得全国前 20 汇总行，不能由此下钻任意门店账单；无正式累计数据返回空列表和零 totals，并保留口径说明。

## 2 `GET /api/v1/stores/{storeId}/monthly-settlement` — 单店月度分账

> 消费语义: `store-settlement.filter.1`、`store-settlement.order-drilldown.2`
> 数据源表: `agg_store_monthly_settlement`、`settlement_statement`、`settlement_statement_line`、`dim_stores`，费率摘要读取账单来源关联的 `settlement_fee_result`
> 变更: 保留现有路径；旧单一分佣表替换为双费用、原始/调整/净额和账单状态

**请求参数**：

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|:---:|:---:|------|
| `month` | string | 是 | — | `YYYY-MM` |
| `productScope` | string | 否 | `all` | 产品范围 |
| `productType` | string | 否 | `all` | 商品类型 |

**响应 `data` 顶层**：

| 字段 | 类型 | 说明 | 来源表.列 |
|------|------|------|----------|
| `store` | object | `{ storeId, storeName }` | `dim_stores.store_id/store_name` |
| `month` | string | 账期 | `agg_store_monthly_settlement.month` |
| `productScope` / `productType` | string | 实际筛选 | 同名投影列 |
| `isFormalPeriod` | boolean | 是否不早于 2026-08 | 业务规则派生 |
| `statement` | object/null | 月度账单头；未生成时为 null | `settlement_statement` |
| `metrics` | object | 双费用汇总 | 月度投影及账单头 |
| `lines` | array | 双费用产品汇总行 | 账单行；未锁账时由月度投影/当前结果生成只读预览 |

**`statement`**：

| 字段 | 类型 | 说明 | 来源表.列 |
|------|------|------|----------|
| `statementId` | string | 账单业务 ID | `settlement_statement.statement_id` |
| `statementStatus` | string | 账单状态 | `.statement_status` |
| `confirmedAt` | datetime/null | 确认时间 | `.confirmed_at` |
| `lockedAt` | datetime/null | 锁账时间 | `.locked_at` |
| `lockVersion` | string/null | 锁账版本 | `.lock_version` |

**`metrics` 字段**：

| 字段 | 类型 | 说明 | 来源表.列/计算 |
|------|------|------|---------------|
| `salesOrderCount` | integer | 本店销售订单数 | `agg_store_monthly_settlement.sales_order_count` |
| `salesAmountCent` | integer | 本店销售总金额 | `.sales_amount_cent` |
| `verifiedOrderCount` | integer | 本店核销订单数 | `.verified_order_count` |
| `verifiedAmountCent` | integer | 本店核销总金额 | `.verified_amount_cent` |
| `promotionBaseCent` | integer | 推广费净额基数 | `.promotion_base_cent` |
| `promotionOriginalFeeCent` | integer | 推广费原始金额 | `.promotion_original_fee_cent` |
| `promotionAdjustmentFeeCent` | integer | 推广费调整 | `.promotion_adjustment_fee_cent` |
| `promotionNetFeeCent` | integer | 推广费调整后净额 | `.promotion_net_fee_cent` |
| `managementBaseCent` | integer | 管理费净额基数 | `.management_base_cent` |
| `managementOriginalFeeCent` | integer | 管理费原始金额 | `.management_original_fee_cent` |
| `managementAdjustmentFeeCent` | integer | 管理费调整 | `.management_adjustment_fee_cent` |
| `managementNetFeeCent` | integer | 管理费调整后净额 | `.management_net_fee_cent` |
| `netSettlementReferenceCent` | integer | 推广净额减管理净额 | 前两方向净额计算 |

**`lines[]`**：

| 字段 | 类型 | 说明 | 来源表.列 |
|------|------|------|----------|
| `statementLineId` | string/null | 已生成账单行 ID | `settlement_statement_line.statement_line_id` |
| `feeDirection` | string | 费用方向 | `.fee_direction` |
| `productScope` / `productType` | string | 产品维度 | `.product_scope/.product_type` |
| `originalEntryCount` | integer | 原始项数量 | `.original_entry_count` |
| `adjustmentEntryCount` | integer | 调整项数量 | `.adjustment_entry_count` |
| `originalBaseCent` | integer | 原始基数 | `.original_base_cent` |
| `adjustmentBaseCent` | integer | 基数调整 | `.adjustment_base_cent` |
| `netBaseCent` | integer | 调整后基数 | `.net_base_cent` |
| `originalFeeCent` | integer | 原始费用 | `.original_fee_cent` |
| `adjustmentFeeCent` | integer | 费用调整 | `.adjustment_fee_cent` |
| `netFeeCent` | integer | 调整后净额 | `.net_fee_cent` |
| `minFeeRate` / `maxFeeRate` | decimal-string/null | 行内使用费率区间 | 关联 `settlement_fee_result.fee_rate` 聚合 |
| `ruleVersionCount` | integer | 行内规则版本数量 | 关联 `settlement_fee_result.rule_version` 去重 |
| `feeRates` | decimal-string[] | 行内实际费率去重集合 | 关联 `settlement_fee_result.fee_rate` 去重 |
| `ruleVersions` | string[] | 行内实际规则版本集合 | 关联 `settlement_fee_result.rule_version` 去重 |

**下钻规则**：日级规则使同一产品行可能包含多个费率和版本，前端不得把汇总行伪装为单一费率。下钻时优先携带 `statementId + statementLineId + feeRates + ruleVersions`；未生成账单时携带 `storeId + month + feeDirection + productScope + productType + feeRates + ruleVersions`。费率和版本只用于恢复来源上下文，服务端以账单行或实际结果重新校验并授权。

## 3 `GET /api/v1/order-fee-details` — 订单费用明细

> 消费语义: `order-fee-detail.restore-context.1`、`direction-tabs.2`、`filter-export.3`
> 数据源表: `settlement_fee_result_current`、`settlement_fee_result`、`settlement_fee_adjustment`、`settlement_statement_entry`、`settlement_statement`、两张原始订单/券表、`douyin_refund_event`，以及既有 `raw_douyin_verify_records`、`dim_stores`

**请求参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| `statementId` | string | 否 | 锁账口径；有值时读取冻结来源项 |
| `statementLineId` | string | 否 | 须属于 `statementId` |
| `storeId` | string | 条件必填 | 无 `statementId` 时必填且需授权 |
| `month` | string | 条件必填 | 无 `statementId` 时必填；按方向解释业务月 |
| `saleMonth` | string | 否 | 额外按销售月份筛选 |
| `verifyMonth` | string | 否 | 额外按核销月份筛选，支撑当前页面筛选语义 |
| `feeDirection` | string | 是 | `PROMOTION/MANAGEMENT` |
| `productScope` / `productType` | string | 否 | 产品筛选 |
| `feeRates` | decimal-string[] | 否 | 来源汇总行实际费率集合；只作上下文校验 |
| `ruleVersions` | string[] | 否 | 来源汇总行规则版本集合；只作上下文校验 |
| `dataStatus` | string | 否 | `VALID/ADJUSTED/BLOCKED/LOCKED` |
| `q` | string | 否 | 订单 ID、券 ID、SKU ID/名称、商品名称 |
| `page` / `pageSize` | integer | 否 | 默认 1/50，`pageSize` 最大 100 |

**响应 `data`**：`{ context, list, total, page, pageSize }`。`context` 回显服务端接受并规范化后的筛选及 `statementStatus`，不回显未经授权的门店参数。

**`list[]` 一券一方向一行**：

| 字段 | 类型 | 说明 | 来源表.列 |
|------|------|------|----------|
| `feeResultId` | string | 原费用结果 ID | `settlement_fee_result.fee_result_id` |
| `statementEntryId` | string/null | 锁账来源项 ID | `settlement_statement_entry.statement_entry_id` |
| `orderId` / `couponId` | string | 平台业务 ID | 费用结果及原始表业务 ID |
| `orderStatus` / `couponStatus` | string/null | 标准化状态 | 两张原始表状态列 |
| `feeDirection` | string | 费用方向 | `settlement_fee_result.fee_direction` |
| `originalBusinessMonth` | string | 原始发生月 | `.original_business_month` |
| `saleMonth` | string/null | 销售月份 | `raw_douyin_orders.sale_time` 按上海时区派生 |
| `verifyMonth` | string/null | 核销月份 | `raw_douyin_verify_records.verify_time` 按上海时区派生 |
| `ruleMatchDate` | date | 费率匹配日 | `.rule_match_date` |
| `saleTime` | datetime/null | 销售时间 | `raw_douyin_orders.sale_time` |
| `verifyTime` | datetime/null | 核销时间 | `raw_douyin_verify_records.verify_time` |
| `saleStoreId` / `verifyStoreId` | string/null | 销售/核销门店 | 费用结果同名列 |
| `saleStoreName` / `verifyStoreName` | string/null | 门店展示名称 | `dim_stores.store_name` |
| `skuId` | string | SKU ID | `.sku_id` |
| `skuName` | string/null | SKU 名称 | `dim_sku_product_rules.sku_name` |
| `productName` | string/null | 商品名称 | `dim_sku_product_rules.product_name`，缺失时回退原始订单快照 |
| `productScope` / `productType` | string | 产品快照 | `.product_scope/.product_type` |
| `saleChannel` | string | 标准化渠道 | `.sale_channel_normalized` |
| `sourceAmountCent` | integer | 原始方向金额 | `.source_amount_cent` |
| `refundedAmountCent` | integer | 计算时累计退款 | `.refunded_amount_cent` |
| `originalBaseCent` | integer | 原结果基数 | `.fee_base_cent` |
| `feeRate` | decimal-string | 实际使用费率 | `.fee_rate` |
| `originalFeeCent` | integer | 原费用金额 | `.fee_amount_cent` |
| `adjustmentBaseCent` | integer | 全部调整基数合计 | `settlement_fee_adjustment.adjustment_base_cent` 聚合 |
| `adjustmentFeeCent` | integer | 全部调整费用合计 | `.adjustment_fee_cent` 聚合 |
| `adjustedNetBaseCent` | integer | 原基数 + 调整 | 查询派生 |
| `adjustedNetFeeCent` | integer | 原费用 + 调整 | 查询派生 |
| `ruleVersion` | string | 实际使用版本 | `settlement_fee_result.rule_version` |
| `resultStatus` | string | 结果状态 | `.result_status` |
| `statementId` / `statementLineId` | string/null | 锁账归属 | `settlement_statement_entry` |
| `adjustments` | array | 调整明细 | `settlement_fee_adjustment` |

`adjustments[]` 必返字段：`adjustmentId`、`adjustmentPostingMonth`、`adjustmentType`、`adjustmentBaseCent`、`adjustmentFeeCent`、`ruleVersion`、`adjustmentReason`、`occurredAt`，均映射调整表同名列。

**查询口径**：有 `statementId` 时只返回已冻结来源；无账单时从当前指针读取最新未锁账结果。响应 `context` 必须返回服务端核验后的 `feeRates/ruleVersions`。非法/过期来源上下文返回 422 并保留用户可返回汇总页的信息；不得按 URL 中的费率或规则版本重新计算。

## 4 `GET /api/v1/order-fee-details/export` — 导出订单费用明细

> 数据源与权限: 与 §3 完全一致

请求参数与 §3 相同，但忽略 `page/pageSize`。返回 `text/csv; charset=utf-8`，含 UTF-8 BOM；文件名使用安全业务日期，不含门店隐私或本机路径。

**至少包含列**：订单 ID、券 ID、费用方向、原始发生月份、销售月份、核销月份、调整入账月份集合、规则匹配日、销售/核销门店、SKU 与产品维度、原始基数、调整基数、净基数、费率、原始费用、调整费用、调整后净额、规则版本、账单/锁账状态。

**约束**：导出前重新验权；筛选摘要与生成时间写入响应头；空结果返回 409 `EXPORT_EMPTY`；失败可重试且不改变任何业务状态。

## 5 开票确认页与账单写入边界

- `#/invoice` 的五节点、材料、预计范围和 FAQ 是前端静态只读内容，不调用发票接口。
- 单店分账 #2 可返回账单状态和推广费预计开票范围，但不得据此声称已经在线确认或开票。
- 本轮不提供 `confirm/lock/unlock/update/delete` 账单路由；内部锁账事务必须先冻结来源项，再汇总账单行和账单头，三层一致后才切为 `LOCKED`。
- 若后续要开放门店确认或财务锁账操作，必须新建/更新 Linear issue，补充角色、幂等、撤回、审计和异常验收后再扩展本契约。
