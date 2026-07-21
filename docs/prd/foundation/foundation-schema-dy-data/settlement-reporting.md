# 双费用结果、调整、锁账与报表 Schema

> 所属索引: [foundation-schema-dy-data.md](../foundation-schema-dy-data.md)
> 覆盖表: `douyin_refund_event`、`settlement_fee_result`、`settlement_fee_result_current`、`settlement_fee_adjustment`、`settlement_statement`、`settlement_statement_line`、`settlement_statement_entry`、`agg_store_monthly_settlement`、`agg_store_ranking`

## 0 `douyin_refund_event` — 退款事件

在既有退款事件字段基础上新增 `successful_observed_at datetime NULL`：首次观察到 `refund_status=2`（成功）时写入，之后重复同步只允许更新来源元数据，不得修改该时间。存量成功事件按 `gmt_create`、`gmt_modified`、`occurred_at` 的顺序回填。结算结果以该不可变时间判断事件是否已进入计算快照，避免重复同步把同一退款再次计为调整。

## 1 `settlement_fee_result` — 单券费用结果

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| id | bigint unsigned | NO | PK | AUTO_INCREMENT | 主键 |
| fee_result_id | varchar(128) | NO | UK | — | 费用结果业务 ID |
| coupon_id | varchar(128) | NO | IDX | — | 券 ID |
| order_id | varchar(128) | NO | IDX | — | 订单 ID |
| fee_direction | tinyint unsigned | NO | IDX | — | 1=推广服务费，2=管理服务费 |
| result_version | int unsigned | NO | | `1` | 券+方向内递增版本 |
| original_business_month | char(7) | NO | IDX | — | 推广取销售月，管理取核销月 |
| rule_match_date | date | NO | IDX | — | 推广取销售业务日，管理取核销业务日 |
| sale_store_id | varchar(128) | YES | IDX | NULL | 销售门店 |
| verify_store_id | varchar(128) | YES | IDX | NULL | 核销门店 |
| sku_id | varchar(128) | NO | IDX | — | SKU ID |
| product_scope | varchar(128) | NO | IDX | `''` | 产品范围快照 |
| product_type | varchar(128) | NO | IDX | `''` | 商品类型快照 |
| sale_channel_normalized | varchar(32) | NO | IDX | — | 标准化渠道 |
| source_amount_cent | bigint | NO | | `0` | 原始实付或核销金额 |
| refunded_amount_cent | bigint | NO | | `0` | 计算时累计退款金额 |
| fee_base_cent | bigint | NO | | `0` | 方向性净额基数 |
| fee_rate | decimal(8,6) | NO | | `0` | 使用费率 |
| fee_amount_cent | bigint | NO | | `0` | 四舍五入后的费用金额 |
| rule_version | varchar(64) | NO | IDX | — | 使用的 SKU 费率版本 |
| scope_rule_version | varchar(64) | NO | | — | 使用的范围规则版本 |
| result_status | tinyint unsigned | NO | IDX | `1` | 1=有效，2=被新版本替代，3=数据质量阻断 |
| calculation_run_id | varchar(128) | NO | IDX | — | 计算运行 ID |
| calculated_at | datetime | NO | | — | 计算时间 |
| gmt_create | datetime | NO | | CURRENT_TIMESTAMP | 创建时间 |
| gmt_modified | datetime | NO | | CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP | 更新时间 |

**索引**：
- `pk_settlement_fee_result` (id)
- `uk_settlement_fee_result_id` (fee_result_id)
- `uk_settlement_fee_result_revision` (coupon_id, fee_direction, result_version)
- `idx_settlement_fee_result_month_store` (original_business_month, fee_direction, sale_store_id, verify_store_id)
- `idx_settlement_fee_result_product` (product_scope, product_type)
- `idx_settlement_fee_result_rule` (rule_version)
- `idx_settlement_fee_result_match_date` (rule_match_date, fee_direction)

**使用接口**：
- `GET /api/v1/stores/{storeId}/monthly-settlement` — 聚合账单行费率区间和规则版本数量。
- `GET /api/v1/order-fee-details` — 返回券级原始基数、费率、金额、业务月和规则版本。
- `GET /api/v1/order-fee-details/export` — 导出同口径费用依据。
- 无公开写接口；仅结算计算 worker 新增不可变结果版本。

## 2 `settlement_fee_result_current` — 当前结果指针

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| id | bigint unsigned | NO | PK | AUTO_INCREMENT | 主键 |
| coupon_id | varchar(128) | NO | UK* | — | 券 ID |
| fee_direction | tinyint unsigned | NO | UK* | — | 费用方向 |
| fee_result_id | varchar(128) | NO | UK | — | 当前费用结果 ID |
| gmt_create | datetime | NO | | CURRENT_TIMESTAMP | 创建时间 |
| gmt_modified | datetime | NO | | CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP | 更新时间 |

**索引**：
- `pk_settlement_fee_result_current` (id)
- `uk_settlement_fee_result_current_slot` (coupon_id, fee_direction)
- `uk_settlement_fee_result_current_result` (fee_result_id)

**约束**：未锁账结果重算时新增结果版本并原子切换指针；已锁账槽位禁止切换，只允许新增调整。

**使用接口**：
- `GET /api/v1/order-fee-details` — 未提供账单 ID 时读取当前未锁账结果。
- `GET /api/v1/order-fee-details/export` — 导出当前结果口径。
- 无公开写接口；仅未锁账重算事务原子切换指针。

## 3 `settlement_fee_adjustment` — 费用调整记录

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| id | bigint unsigned | NO | PK | AUTO_INCREMENT | 主键 |
| adjustment_id | varchar(128) | NO | UK | — | 调整业务 ID |
| original_fee_result_id | varchar(128) | NO | IDX | — | 原费用结果 ID |
| refund_event_id | varchar(128) | YES | IDX | NULL | 来源退款事件 ID |
| coupon_id | varchar(128) | NO | IDX | — | 券 ID |
| order_id | varchar(128) | NO | IDX | — | 订单 ID |
| fee_direction | tinyint unsigned | NO | IDX | — | 费用方向 |
| original_business_month | char(7) | NO | IDX | — | 原结果发生月份 |
| adjustment_posting_month | char(7) | NO | IDX | — | 调整事件入账月份 |
| adjustment_type | tinyint unsigned | NO | IDX | — | 1=部分退款，2=全额退款，3=取消核销，4=人工纠错 |
| adjustment_base_cent | bigint | NO | | `0` | 基数调整，通常为负数 |
| adjustment_fee_cent | bigint | NO | | `0` | 费用调整，通常为负数 |
| rule_version | varchar(64) | NO | IDX | — | 沿用原结果规则版本 |
| adjustment_reason | varchar(1000) | NO | | — | 中文调整原因 |
| occurred_at | datetime | NO | IDX | — | 调整业务事件时间 |
| created_by | varchar(128) | NO | | — | 系统任务或人工操作人 |
| gmt_create | datetime | NO | | CURRENT_TIMESTAMP | 创建时间 |
| gmt_modified | datetime | NO | | CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP | 更新时间 |

**索引**：
- `pk_settlement_fee_adjustment` (id)
- `uk_settlement_fee_adjustment_id` (adjustment_id)
- `idx_settlement_fee_adjustment_original` (original_fee_result_id)
- `idx_settlement_fee_adjustment_posting` (adjustment_posting_month, fee_direction)
- `idx_settlement_fee_adjustment_coupon` (coupon_id, occurred_at)

**约束**：同一退款事件、原结果和费用方向只能生成一次调整；该幂等键在应用层由 `refund_event_id + original_fee_result_id + fee_direction` 校验，拿到稳定事件 ID 后可升级为唯一索引。调整记录写入后不可原地改写，人工纠错通过新增反向或补充调整表达。

**使用接口**：
- `GET /api/v1/stores/{storeId}/monthly-settlement` — 汇总原始、调整和调整后净额。
- `GET /api/v1/order-fee-details` — 返回原结果关联的全部调整明细。
- `GET /api/v1/order-fee-details/export` — 导出调整入账月份、类型、金额和净额。
- 无公开修改/删除接口；退款、取消核销和受控纠错流程只能新增调整。

## 4 `settlement_statement` — 门店月度账单与锁账

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| id | bigint unsigned | NO | PK | AUTO_INCREMENT | 主键 |
| statement_id | varchar(128) | NO | UK | — | 账单业务 ID |
| store_id | varchar(128) | NO | UK* | — | 门店 ID |
| statement_month | char(7) | NO | UK* | — | 账单月份 |
| statement_status | tinyint unsigned | NO | IDX | `1` | 1=生成中，2=待确认，3=已确认，4=已锁账 |
| promotion_original_fee_cent | bigint | NO | | `0` | 推广费原始金额 |
| promotion_adjustment_fee_cent | bigint | NO | | `0` | 推广费调整金额 |
| promotion_net_fee_cent | bigint | NO | | `0` | 推广费调整后净额 |
| management_original_fee_cent | bigint | NO | | `0` | 管理费原始金额 |
| management_adjustment_fee_cent | bigint | NO | | `0` | 管理费调整金额 |
| management_net_fee_cent | bigint | NO | | `0` | 管理费调整后净额 |
| confirmed_by | varchar(128) | YES | | NULL | 确认人 |
| confirmed_at | datetime | YES | | NULL | 确认时间 |
| locked_by | varchar(128) | YES | | NULL | 锁账操作人/任务 |
| locked_at | datetime | YES | IDX | NULL | 锁账时间 |
| lock_version | varchar(64) | YES | UK | NULL | 锁账快照版本 |
| gmt_create | datetime | NO | | CURRENT_TIMESTAMP | 创建时间 |
| gmt_modified | datetime | NO | | CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP | 更新时间 |

**索引**：
- `pk_settlement_statement` (id)
- `uk_settlement_statement_id` (statement_id)
- `uk_settlement_statement_store_month` (store_id, statement_month)
- `uk_settlement_statement_lock_version` (lock_version)
- `idx_settlement_statement_status_month` (statement_status, statement_month)

**约束**：状态进入“已锁账”前，必须已经写入并核对账单汇总行与账单来源项；锁账后账单头、汇总行和来源项均不可修改或删除。跨月退款只进入事件发生月份的后续账单，并通过来源项关联调整记录及原费用结果。

**使用接口**：
- `GET /api/v1/stores/{storeId}/monthly-settlement` — 返回月度账单状态、确认和锁账信息。
- `GET /api/v1/order-fee-details` — 在锁账查询中返回账单归属和状态。
- `GET /api/v1/order-fee-details/export` — 导出账单/锁账状态。
- 本轮无确认、锁账、解锁、修改或删除 Web 接口；仅内部账单事务写入。

## 5 `settlement_statement_line` — 账单汇总行

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| id | bigint unsigned | NO | PK | AUTO_INCREMENT | 主键 |
| statement_line_id | varchar(128) | NO | UK | — | 账单汇总行业务 ID |
| statement_id | varchar(128) | NO | UK* | — | 所属账单 ID |
| fee_direction | tinyint unsigned | NO | UK* | — | 1=推广服务费，2=管理服务费 |
| product_scope | varchar(128) | NO | UK* | `''` | 产品范围快照 |
| product_type | varchar(128) | NO | UK* | `''` | 商品类型快照 |
| original_entry_count | int unsigned | NO | | `0` | 原始费用来源项数量 |
| adjustment_entry_count | int unsigned | NO | | `0` | 调整来源项数量 |
| original_base_cent | bigint | NO | | `0` | 原始费用基数合计 |
| adjustment_base_cent | bigint | NO | | `0` | 基数调整合计，允许负数 |
| net_base_cent | bigint | NO | | `0` | 调整后基数合计 |
| original_fee_cent | bigint | NO | | `0` | 原始费用金额合计 |
| adjustment_fee_cent | bigint | NO | | `0` | 费用调整合计，允许负数 |
| net_fee_cent | bigint | NO | | `0` | 调整后费用净额 |
| gmt_create | datetime | NO | | CURRENT_TIMESTAMP | 创建时间 |
| gmt_modified | datetime | NO | | CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP | 更新时间 |

**索引**：
- `pk_settlement_statement_line` (id)
- `uk_settlement_statement_line_id` (statement_line_id)
- `uk_settlement_statement_line_dimension` (statement_id, fee_direction, product_scope, product_type)
- `idx_settlement_statement_line_statement` (statement_id, fee_direction)

**约束**：每行金额必须由同一 `statement_line_id` 下的账单来源项汇总产生，且 `net_base_cent = original_base_cent + adjustment_base_cent`、`net_fee_cent = original_fee_cent + adjustment_fee_cent`。账单头对应费用方向的三项金额必须等于其全部汇总行之和。

**使用接口**：
- `GET /api/v1/stores/{storeId}/monthly-settlement` — 返回按费用方向和产品维度冻结的汇总行。
- `GET /api/v1/order-fee-details` — 通过 `statementLineId` 下钻冻结来源。
- `GET /api/v1/order-fee-details/export` — 导出同一账单行的来源明细。
- 无公开写接口；锁账事务生成后不可修改。

## 6 `settlement_statement_entry` — 账单来源项

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| id | bigint unsigned | NO | PK | AUTO_INCREMENT | 主键 |
| statement_entry_id | varchar(128) | NO | UK | — | 账单来源项业务 ID |
| statement_id | varchar(128) | NO | IDX | — | 所属账单 ID |
| statement_line_id | varchar(128) | NO | IDX | — | 所属账单汇总行 ID |
| source_type | tinyint unsigned | NO | UK* | — | 1=订单费用结果，2=费用调整 |
| source_record_id | varchar(128) | NO | UK* | — | `fee_result_id` 或 `adjustment_id` |
| original_fee_result_id | varchar(128) | NO | IDX | — | 原费用结果 ID；原始项等于自身，调整项指向被调整结果 |
| coupon_id | varchar(128) | NO | IDX | — | 券 ID 快照 |
| order_id | varchar(128) | NO | IDX | — | 订单 ID 快照 |
| fee_direction | tinyint unsigned | NO | IDX | — | 费用方向快照 |
| original_business_month | char(7) | NO | IDX | — | 原费用结果发生月份 |
| statement_posting_month | char(7) | NO | IDX | — | 本来源项计入的账单月份 |
| product_scope | varchar(128) | NO | | `''` | 产品范围快照 |
| product_type | varchar(128) | NO | | `''` | 商品类型快照 |
| base_amount_cent | bigint | NO | | `0` | 原始基数或基数调整；调整允许负数 |
| fee_amount_cent | bigint | NO | | `0` | 原始费用或费用调整；调整允许负数 |
| rule_version | varchar(64) | NO | IDX | — | 原费用结果使用的规则版本 |
| gmt_create | datetime | NO | | CURRENT_TIMESTAMP | 创建时间 |
| gmt_modified | datetime | NO | | CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP | 更新时间 |

**索引**：
- `pk_settlement_statement_entry` (id)
- `uk_settlement_statement_entry_id` (statement_entry_id)
- `uk_settlement_statement_entry_source` (source_type, source_record_id)
- `idx_settlement_statement_entry_line` (statement_line_id)
- `idx_settlement_statement_entry_statement_order` (statement_id, order_id)
- `idx_settlement_statement_entry_coupon` (coupon_id)
- `idx_settlement_statement_entry_original` (original_fee_result_id)

**来源映射**：
- `source_type=1`：`source_record_id = settlement_fee_result.fee_result_id`，金额取 `fee_base_cent / fee_amount_cent`，计入其原始发生月份。
- `source_type=2`：`source_record_id = settlement_fee_adjustment.adjustment_id`，`original_fee_result_id` 指向被调整结果，金额取 `adjustment_base_cent / adjustment_fee_cent`，计入调整发生月份。

**约束**：来源记录必须不可变且只能进入一个账单；`statement_posting_month` 必须等于所属账单月份，费用方向和产品维度必须与所属汇总行一致。推广服务费按销售门店归账，管理服务费按核销门店归账。锁账后不得增删或替换来源项。

**使用接口**：
- `GET /api/v1/order-fee-details` — 有 `statementId` 时只读取已冻结来源项。
- `GET /api/v1/order-fee-details/export` — 导出锁账来源快照。
- 无公开写接口；仅锁账事务写入并在三层金额一致后冻结。

## 7 `agg_store_monthly_settlement` — 单店月度双费用投影（现有·需改动）

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| id | bigint unsigned | NO | PK | AUTO_INCREMENT | 目标结构主键 |
| month | char(7) | NO | UK* | — | 月份 |
| store_id | varchar(128) | NO | UK* | — | 门店 ID |
| product_scope | varchar(128) | NO | UK* | `all` | 产品范围 |
| product_type | varchar(128) | NO | UK* | `all` | 商品类型 |
| sales_order_count | int unsigned | NO | | `0` | 本店销售订单数 |
| sales_amount_cent | bigint | NO | | `0` | 本店销售总金额 |
| verified_order_count | int unsigned | NO | | `0` | 本店核销订单数 |
| verified_amount_cent | bigint | NO | | `0` | 本店核销总金额 |
| promotion_base_cent | bigint | NO | | `0` | 推广费净额基数 |
| promotion_original_fee_cent | bigint | NO | | `0` | 推广费原始金额 |
| promotion_adjustment_fee_cent | bigint | NO | | `0` | 推广费调整金额 |
| promotion_net_fee_cent | bigint | NO | | `0` | 推广费调整后净额 |
| management_base_cent | bigint | NO | | `0` | 管理费净额基数 |
| management_original_fee_cent | bigint | NO | | `0` | 管理费原始金额 |
| management_adjustment_fee_cent | bigint | NO | | `0` | 管理费调整金额 |
| management_net_fee_cent | bigint | NO | | `0` | 管理费调整后净额 |
| statement_status | tinyint unsigned | NO | IDX | `1` | 账单状态快照 |
| projection_run_id | varchar(128) | NO | IDX | — | 投影运行 ID |
| gmt_create | datetime | NO | | CURRENT_TIMESTAMP | 创建时间 |
| gmt_modified | datetime | NO | | CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP | 更新时间 |

**索引**：
- `pk_agg_store_monthly_settlement` (id)
- `uk_agg_store_monthly_settlement_slot` (month, store_id, product_scope, product_type)
- `idx_agg_store_monthly_settlement_store_month` (store_id, month)

**使用接口**：
- `GET /api/v1/meta/filters` — 提供可用结算账期。
- `GET /api/v1/stores/{storeId}/monthly-settlement` — 返回单店月度双费用投影与未锁账预览。
- 无公开写接口；仅投影任务重建。

## 8 `agg_store_ranking` — 门店排名投影（现有·需改动）

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| id | bigint unsigned | NO | PK | AUTO_INCREMENT | 目标结构主键 |
| period_type | tinyint unsigned | NO | UK* | — | 1=月度，2=正式累计 |
| period_key | char(7) | NO | UK* | — | 月份或累计截止月 |
| store_id | varchar(128) | NO | UK* | — | 门店 ID |
| store_name | varchar(255) | NO | | — | 门店名称快照 |
| product_scope | varchar(128) | NO | UK* | `all` | 产品范围 |
| product_type | varchar(128) | NO | UK* | `all` | 商品类型 |
| sales_order_count | int unsigned | NO | | `0` | 销售订单数 |
| sales_amount_cent | bigint | NO | | `0` | 销售金额 |
| verified_order_count | int unsigned | NO | | `0` | 核销订单数 |
| verified_amount_cent | bigint | NO | | `0` | 核销金额 |
| promotion_net_fee_cent | bigint | NO | | `0` | 推广费调整后净额 |
| management_net_fee_cent | bigint | NO | | `0` | 管理费调整后净额 |
| net_settlement_reference_cent | bigint | NO | | `0` | 推广费净额减管理费净额 |
| projection_run_id | varchar(128) | NO | IDX | — | 投影运行 ID |
| gmt_create | datetime | NO | | CURRENT_TIMESTAMP | 创建时间 |
| gmt_modified | datetime | NO | | CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP | 更新时间 |

**索引**：
- `pk_agg_store_ranking` (id)
- `uk_agg_store_ranking_slot` (period_type, period_key, store_id, product_scope, product_type)
- `idx_agg_store_ranking_period_fee` (period_type, period_key, promotion_net_fee_cent)
- `idx_agg_store_ranking_period_sales` (period_type, period_key, sales_amount_cent)

**口径**：正式累计只从 `2026-08` 开始；2026-07 测试数据不进入累计投影。

**使用接口**：
- `GET /api/v1/meta/filters` — 提供榜单可用账期。
- `GET /api/v1/dashboard/store-ranking` — 返回月度或正式累计门店排名与双费用指标。
- 无公开写接口；仅投影任务重建。
