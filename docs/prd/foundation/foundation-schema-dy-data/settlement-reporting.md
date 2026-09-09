# 双费用结果、调整、锁账与报表 Schema

> 所属索引: [foundation-schema-dy-data.md](../foundation-schema-dy-data.md)
> 覆盖表: `douyin_refund_event`、`settlement_fee_result`、`settlement_fee_result_current`、`settlement_fee_adjustment`、`settlement_statement`、`settlement_statement_line`、`settlement_statement_entry`、`agg_store_monthly_settlement`、`agg_store_ranking`

### 0 `douyin_refund_event` — 退款事件

在既有退款事件字段基础上新增 `successful_observed_at datetime NULL`：首次观察到 `refund_status=2`（成功）时写入，之后重复同步只允许更新来源元数据，不得修改该时间。存量成功事件按 `gmt_create`、`gmt_modified`、`occurred_at` 的顺序回填。结算结果以该不可变时间判断事件是否已进入计算快照，避免重复同步把同一退款再次计为调整。

### 1 `settlement_fee_result` — 单券费用结果

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| id | bigint unsigned | NO | PK | AUTO_INCREMENT | 主键 |
| fee_result_id | varchar(128) | NO | UK | — | 费用结果业务 ID |
| coupon_id | varchar(128) | NO | IDX | — | 券 ID |
| order_id | varchar(128) | NO | IDX | — | 订单 ID |
| fee_direction | tinyint unsigned | NO | IDX | — | 1=推广服务费，2=管理服务费 |
| result_version | int unsigned | NO | | `1` | 券+方向内递增版本 |
| original_business_month | char(7) | NO | IDX | — | 两方向均取有效核销月（Asia/Shanghai）；不取销售月 |
| rule_match_date | date | NO | IDX | — | 两方向均取有效核销业务日，据此匹配各自费率版本 |
| sale_store_id | varchar(128) | YES | IDX | NULL | 销售门店 |
| verify_store_id | varchar(128) | YES | IDX | NULL | 核销门店 |
| sku_id | varchar(128) | NO | IDX | — | SKU ID |
| product_scope | varchar(128) | NO | IDX | `''` | 产品范围快照 |
| product_type | varchar(128) | NO | IDX | `''` | 商品类型快照 |
| sale_channel_normalized | varchar(32) | NO | IDX | — | 标准化渠道 |
| source_amount_cent | bigint | NO | | `0` | 同一有效券两方向共同使用的核销实收金额 |
| refunded_amount_cent | bigint | NO | | `0` | 计算时累计退款金额 |
| fee_base_cent | bigint | NO | | `0` | 同一有效券两方向共同使用的核销实收净额基数，按退款口径扣减 |
| fee_rate | decimal(8,6) | NO | | `0` | 使用费率 |
| fee_amount_cent | bigint | NO | | `0` | 四舍五入后的费用金额 |
| rule_version | varchar(64) | NO | IDX | — | 使用的 SKU 费率版本 |
| scope_rule_version | varchar(64) | NO | | — | 使用的范围规则版本 |
| result_status | tinyint unsigned | NO | IDX | `1` | 1=有效，2=被新版本替代，3=数据质量阻断 |
| calculation_run_id | varchar(128) | NO | IDX | — | 计算运行 ID |
| qualifying_verify_id | text | YES | | NULL | 使本不可变结果获得计费资格的核销业务 ID（0051） |
| qualifying_verify_time | timestamptz | YES | | NULL | 该次核销时间快照；与核销 ID 一起识别血缘 |
| qualifying_verify_store_id | varchar(128) | YES | | NULL | 该次核销门店 ID 快照，不随后续 POI 映射变动 |
| qualifying_verify_store_name | text | YES | | NULL | 该次核销门店名称快照 |
| reverification_anchor_id | varchar(128) | YES | IDX | NULL | 仅通过调整入账的非当前重核销依据指向原冻结费用结果 ID；不是核销 ID |
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
- `idx_settlement_fee_result_reverification_anchor` (reverification_anchor_id, result_version)，普通非唯一索引。

**0051 血缘兼容**：字段类型与 `apps/api/dy_api/models.py`、`alembic/versions/20260909_0051_fee_result_verification_provenance.py` 一致，使用 PostgreSQL `timestamptz`，不套用旧表中的 MySQL 类型示意。旧行允许 NULL，迁移不猜测或回填历史归属；新结果保存实际资格核销。取消须关联原资格核销，重核销不被历史取消误冲；已冻结槽位的恢复通过关联原结果的追加差额，不替换冻结依据。任一血缘字段非空或来源包表已有记录时，0051 downgrade 拒绝删除审计数据，只能回滚应用镜像或前滚修复。

**使用接口**：
- `GET /api/v1/stores/{storeId}/monthly-settlement` — 聚合账单行费率区间和规则版本数量。
- `GET /api/v1/order-fee-details` — 返回券级原始基数、费率、金额、业务月和规则版本。
- `GET /api/v1/order-fee-details/export` — 导出同口径费用依据。
- 无公开写接口；仅结算计算 worker 新增不可变结果版本。

**DYDATA-87 增量约束（2026-09-09 用户确认）**：两费均须有效核销；推广仍归销售门店，管理仍归核销门店，不改变各自配置费率。取消核销影响两方向；未锁账结果通过新版本/当前指针退出，已冻结结果通过独立调整追溯，不改写原结果、历史账单或发票事实。销售时间仍是独立事实字段，不再作为推广计费日期依据。

### 2 `settlement_fee_result_current` — 当前结果指针

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

### 3 `settlement_fee_adjustment` — 费用调整记录

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

### 4 `settlement_statement` — 门店月度账单不可变版本与锁账

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| id | bigint unsigned | NO | PK | AUTO_INCREMENT | 主键 |
| statement_id | varchar(128) | NO | UK | — | 账单业务 ID |
| store_id | varchar(128) | NO | UK* | — | 门店 ID |
| statement_month | char(7) | NO | UK* | — | 账单月份 |
| version_no | int unsigned | NO | UK* | `1` | 同门店、同账期递增版本号；接口 `readVersion` 使用此值 |
| is_current | boolean | NO | IDX | `true` | 是否为该门店、账期的当前有效版本 |
| supersedes_statement_id | varchar(128) | YES | IDX | NULL | 新版本指向直接被替代的上一账单版本；首版为空 |
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
- `uk_settlement_statement_store_month_version` (store_id, statement_month, version_no)
- `idx_settlement_statement_current_slot` (store_id, statement_month) WHERE is_current，部分唯一索引
- `uk_settlement_statement_lock_version` (lock_version)
- `idx_settlement_statement_status_month` (statement_status, statement_month)
- `idx_settlement_statement_supersedes` (supersedes_statement_id)

**约束**：同一 `store_id + statement_month` 可永久保留多个版本，但只能有一个 `is_current=true`。新版本必须在一个事务中写入完整账单头、汇总行和来源项，核对三层金额后把上一版本切为非当前；任何失败均不得改变当前指针。状态进入“已锁账”前必须已经写入并核对账单汇总行与账单来源项；锁账后各版本均不可修改或删除。跨月退款只进入事件发生月份的后续账单；异议成立的账单更正则生成同账期新版本，并通过 `supersedes_statement_id` 保留直接版本链。

**使用接口**：
- `GET /api/v1/stores/{storeId}/monthly-settlement` — 返回月度账单状态、确认和锁账信息。
- `GET /api/v1/store-settlements`、`GET /api/v1/store-settlements/{statementId}` — 返回当前/历史版本、`versionNo/isCurrent` 和版本链。
- `POST /api/v1/store-settlements/{statementId}/confirmations` — 只允许确认当前版本，并按 `version_no` 校验读取版本。
- `POST /api/v1/admin/disputes/{disputeId}/transitions` — 异议成立并调整时新增账单版本并原子切换当前标识。
- `GET /api/v1/order-fee-details` — 在锁账查询中返回账单归属和状态。
- `GET /api/v1/order-fee-details/export` — 导出账单/锁账状态。
- 不提供已锁账账单的原地修改、解锁或删除接口；确认单独写入方向确认表，账单更正只新增版本。

### 5 `settlement_statement_line` — 账单汇总行

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
- `GET /api/v1/store-settlements/{statementId}` — 返回指定不可变版本的账单汇总行。
- `GET /api/v1/order-fee-details` — 通过 `statementLineId` 下钻冻结来源。
- `GET /api/v1/order-fee-details/export` — 导出同一账单行的来源明细。
- 无公开写接口；锁账事务生成后不可修改。

### 6 `settlement_statement_entry` — 账单来源项

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
- `uk_settlement_statement_entry_source` (statement_id, source_type, source_record_id)
- `idx_settlement_statement_entry_line` (statement_line_id)
- `idx_settlement_statement_entry_statement_order` (statement_id, order_id)
- `idx_settlement_statement_entry_coupon` (coupon_id)
- `idx_settlement_statement_entry_original` (original_fee_result_id)

**来源映射**：
- `source_type=1`：`source_record_id = settlement_fee_result.fee_result_id`，金额取 `fee_base_cent / fee_amount_cent`，计入其原始发生月份。
- `source_type=2`：`source_record_id = settlement_fee_adjustment.adjustment_id`，`original_fee_result_id` 指向被调整结果，金额取 `adjustment_base_cent / adjustment_fee_cent`，计入调整发生月份。

**约束**：来源记录必须不可变，并且在同一个账单版本内只能出现一次；生成 Vn+1 时允许把 Vn 的原始来源重新快照到新版本，从而保证每个历史版本都可独立回读。`statement_posting_month` 必须等于所属账单月份，费用方向和产品维度必须与所属汇总行一致。推广服务费按销售门店归账，管理服务费按核销门店归账。任一账单版本锁定后不得增删或替换来源项。

**使用接口**：
- `GET /api/v1/order-fee-details` — 有 `statementId` 时只读取已冻结来源项。
- `GET /api/v1/store-settlements/{statementId}` — 返回指定不可变版本的来源明细摘要。
- `GET /api/v1/order-fee-details/export` — 导出锁账来源快照。
- 无公开写接口；仅锁账事务写入并在三层金额一致后冻结。

### 7 `agg_store_monthly_settlement` — 单店月度双费用投影（现有·需改动）

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

### 9 `settlement_billing_source_bundle` — 私有冻结账单来源包（0051 新增）

| 字段 | PostgreSQL 类型 | 可空 | 键 | 默认值 | 说明 |
|---|---|---|---|---|---|
| generation_id | varchar(128) | NO | PK* | — | 候选发布代际 |
| store_id | varchar(128) | NO | PK* | — | 责任门店 |
| statement_month | varchar(7) | NO | PK* | — | 账期，包含已撤销最后来源的空槽位 |
| source_job_id | text | NO | | — | 捕获来源的重建任务 ID |
| source_fingerprint | varchar(64) | NO | | — | 该包规范化来源数组的 SHA-256 |
| sources_json | jsonb | NO | | — | 冻结 `StatementSource[]`，空槽位保存 `[]`，不是缺失来源 |
| created_at | timestamptz | NO | | ORM utcnow | 创建时间；迁移无数据库默认值，由写入端提供 |

**实际结构**：映射 `SettlementBillingSourceBundle`；复合主键 `(generation_id, store_id, statement_month)`，0051 无额外索引或外键。此私有不可变快照沿用实际复合键和 `created_at`，不虚构 `id/gmt_modified` 列。

**来源结构**：`sources_json` 来自 `apps/worker/settlement.py::StatementSource`。每项包含 `source_type/source_record_id/original_fee_result_id`、订单/券、方向、原始月/入账月、门店、产品维度、基数/费用/来源金额、规则版本；并冻结订单/券状态、SKU/商品、渠道、销售与核销门店名称和 ID、销售/核销时间、实收金额、费率、退款时间及调整类型。时间和 Decimal 以字符串序列化，读取时恢复；详细来源不进入公共任务日志。

**完整性与事务**：`job_events` 中的 `settlement_billing_sources_frozen` 完成标记只保存 generation、总指纹、来源数和包数；总指纹同时覆盖来源及全部槽位。读取必须校验标记、每包指纹、数量和总指纹，缺包/缺标记不能当作零账单。同 job/generation 同来源可复用，变化抛 `BillingSourceDriftError`，不得覆盖冻结包。

**使用接口**：无公开 CRUD，不直接返回 `sources_json`。内部 `billing_source_capture.py` 捕获/读取，`billing_statements.py::generate_pending_statements` 消费；公开账单详情通过 `settlement_statement_entry` 返回授权快照。发布事务合同见 [账单生成边界](billing-invoice.md#dydata-87-待确认账单生成合同)。

### 8 `agg_store_ranking` — 门店排名投影（现有·需改动）

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
