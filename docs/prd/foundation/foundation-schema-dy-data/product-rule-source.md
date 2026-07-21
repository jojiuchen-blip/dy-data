# 商品、费率规则与原始数据 Schema

> 所属索引: [foundation-schema-dy-data.md](../foundation-schema-dy-data.md)
> 覆盖表: `dim_sku_product_rules`、`sku_product_sync_history`、`settlement_scope_rule`、`sku_fee_rule`、`sku_fee_rule_import_batch`、`sku_fee_rule_import_row`、`raw_douyin_orders`、`raw_douyin_order_coupons`、`douyin_refund_event`

## 1 `dim_sku_product_rules` — SKU 统一事实源（现有·需改动）

> 兼容说明: 保留现有表名；目标结构新增自增主键并把 `sku_id` 改为业务唯一键。现有 `commission_rate` 不作为新双费用运行时事实源，也不自动迁移为 2026-08 正式费率。

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| id | bigint unsigned | NO | PK | AUTO_INCREMENT | 主键 |
| sku_id | varchar(128) | NO | UK | — | SKU 稳定业务键 |
| sku_name | varchar(512) | YES | | NULL | SKU 展示名称 |
| product_id | varchar(128) | YES | IDX | NULL | 抖音商品 ID |
| product_name | varchar(512) | YES | | NULL | 商品名称 |
| spu_id | varchar(128) | YES | IDX | NULL | SPU 标识 |
| product_scope | varchar(128) | NO | IDX | `''` | 人工维护的产品范围 |
| product_type | varchar(128) | NO | IDX | `''` | 人工维护的商品类型 |
| is_service_product | tinyint unsigned | NO | | `0` | 是否服务类商品 |
| creator_account_id | varchar(128) | YES | | NULL | 商品创建者稳定 ID |
| creator_account_name | varchar(255) | YES | | NULL | 商品创建者名称快照 |
| owner_account_id | varchar(128) | YES | IDX | NULL | 商品归属账号稳定 ID |
| owner_account_name | varchar(255) | YES | | NULL | 商品归属账号名称快照 |
| product_status_raw | varchar(128) | YES | | NULL | 平台原始商品状态 |
| product_status_normalized | varchar(32) | YES | IDX | NULL | `active/inactive/deleted/unknown` |
| is_active_product | tinyint unsigned | NO | IDX | `0` | 是否有效商品 |
| sync_source | varchar(64) | YES | | NULL | 同步来源接口 |
| sync_run_id | varchar(128) | YES | IDX | NULL | 最近成功同步运行 ID |
| last_synced_at | datetime | YES | IDX | NULL | 最近成功同步时间 |
| manual_modified_by | varchar(128) | YES | | NULL | 人工字段最后操作人 |
| manual_modified_at | datetime | YES | | NULL | 人工字段最后修改时间 |
| gmt_create | datetime | NO | | CURRENT_TIMESTAMP | 创建时间 |
| gmt_modified | datetime | NO | | CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP | 更新时间 |

**索引**：
- `pk_dim_sku_product_rules` (id)
- `uk_dim_sku_product_rules_sku_id` (sku_id)
- `idx_dim_sku_product_rules_product_id` (product_id)
- `idx_dim_sku_product_rules_scope_type` (product_scope, product_type)
- `idx_dim_sku_product_rules_owner_status` (owner_account_id, product_status_normalized)
- `idx_dim_sku_product_rules_sync_run` (sync_run_id)

**写入边界**：商品同步只更新平台同步字段；`product_scope / product_type / is_service_product` 只允许管理员写入，不能被同步覆盖。

**使用接口**：
- `GET /api/v1/meta/filters` — 提供产品范围与商品类型联动选项。
- `GET /api/v1/admin/sku-products` — 查询 SKU 当前平台快照和人工分类。
- `PUT /api/v1/admin/sku-products/{skuId}` — 只更新人工维护字段。
- `POST /api/v1/admin/sku-fee-rules` — 发布费率时读取名称和产品维度快照。
- `POST /api/v1/admin/product-sync-runs` — 触发 worker 更新平台字段，不覆盖人工字段。

## 2 `sku_product_sync_history` — 商品同步历史

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| id | bigint unsigned | NO | PK | AUTO_INCREMENT | 主键 |
| snapshot_id | varchar(128) | NO | UK | — | 快照业务 ID |
| sync_run_id | varchar(128) | NO | IDX | — | 同步运行 ID |
| sku_id | varchar(128) | NO | IDX | — | SKU ID |
| product_id | varchar(128) | YES | IDX | NULL | 商品 ID |
| spu_id | varchar(128) | YES | | NULL | SPU ID |
| sku_name | varchar(512) | YES | | NULL | SKU 名称快照 |
| product_name | varchar(512) | YES | | NULL | 商品名称快照 |
| creator_account_id | varchar(128) | YES | | NULL | 创建者 ID 快照 |
| creator_account_name | varchar(255) | YES | | NULL | 创建者名称快照 |
| owner_account_id | varchar(128) | YES | IDX | NULL | 归属账号 ID 快照 |
| owner_account_name | varchar(255) | YES | | NULL | 归属账号名称快照 |
| product_status_raw | varchar(128) | YES | | NULL | 原始状态快照 |
| product_status_normalized | varchar(32) | YES | | NULL | 标准化状态快照 |
| payload_sha256 | char(64) | NO | IDX | — | 脱敏规范化载荷摘要 |
| observed_at | datetime | NO | IDX | — | 平台观测时间 |
| raw_payload | json | YES | | NULL | 脱敏后的必要原始字段 |
| gmt_create | datetime | NO | | CURRENT_TIMESTAMP | 创建时间 |
| gmt_modified | datetime | NO | | CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP | 更新时间 |

**索引**：
- `pk_sku_product_sync_history` (id)
- `uk_sku_product_sync_history_snapshot_id` (snapshot_id)
- `idx_sku_product_sync_history_sku_observed` (sku_id, observed_at)
- `idx_sku_product_sync_history_run` (sync_run_id)
- `idx_sku_product_sync_history_owner` (owner_account_id)

**使用接口**：
- `GET /api/v1/admin/product-sync-runs` — 查询同步运行汇总。
- `GET /api/v1/admin/product-sync-runs/{syncRunId}` — 查询单次同步详情。
- `GET /api/v1/admin/sku-products/{skuId}/sync-history` — 查询单个 SKU 的同步历史。
- `POST /api/v1/admin/product-sync-runs` — 触发内部 worker 写入历史快照。

## 3 `settlement_scope_rule` — 结算范围规则

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| id | bigint unsigned | NO | PK | AUTO_INCREMENT | 主键 |
| scope_rule_version | varchar(64) | NO | UK | — | 范围规则版本 |
| idempotency_key_hash | char(64) | NO | IDX | — | 发布请求 `Idempotency-Key` 的不可逆摘要 |
| request_payload_sha256 | char(64) | NO | | — | 规范化请求体摘要，用于识别同键异参 |
| effective_month | char(7) | NO | IDX | — | 生效月份 `YYYY-MM` |
| owner_account_id | varchar(128) | NO | IDX | — | 目标商品归属账号稳定 ID |
| sale_channel_normalized | varchar(32) | NO | IDX | — | `live/short_video` |
| is_active | tinyint unsigned | NO | | `1` | 是否启用 |
| created_by | varchar(128) | NO | | — | 操作人 |
| change_reason | varchar(512) | NO | | — | 变更原因 |
| gmt_create | datetime | NO | | CURRENT_TIMESTAMP | 创建时间 |
| gmt_modified | datetime | NO | | CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP | 更新时间 |

**索引**：
- `pk_settlement_scope_rule` (id)
- `uk_settlement_scope_rule_version` (scope_rule_version)
- `uk_settlement_scope_rule_idempotency_channel` (idempotency_key_hash, sale_channel_normalized)
- `uk_settlement_scope_rule_slot` (effective_month, owner_account_id, sale_channel_normalized)
- `idx_settlement_scope_rule_active` (is_active, effective_month)

**使用接口**：
- `GET /api/v1/admin/settlement-scope-rules` — 查询范围规则版本。
- `POST /api/v1/admin/settlement-scope-rules` — 按归属账号、渠道和月份发布不可变版本。

## 4 `sku_fee_rule` — SKU 双费率版本

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| id | bigint unsigned | NO | PK | AUTO_INCREMENT | 主键 |
| rule_version | varchar(64) | NO | UK | — | 不可变规则版本 |
| idempotency_key_hash | char(64) | NO | IDX | — | 单条发布或批次提交幂等键摘要 |
| request_payload_sha256 | char(64) | NO | | — | 规范化单条/批次行请求摘要 |
| sku_id | varchar(128) | NO | IDX | — | SKU ID |
| sku_name_snapshot | varchar(512) | YES | | NULL | 发布时 SKU 名称 |
| product_scope_snapshot | varchar(128) | NO | | `''` | 发布时产品范围 |
| product_type_snapshot | varchar(128) | NO | | `''` | 发布时商品类型 |
| promotion_service_fee_rate | decimal(8,6) | NO | | `0` | 推广服务费率，0-1 |
| management_service_fee_rate | decimal(8,6) | NO | | `0` | 管理服务费率，0-1 |
| effective_date | date | NO | IDX | — | 规则生效日；首批为 `2026-08-01`，后续可选择到日 |
| effective_at | datetime | NO | IDX | — | 生效日对应的 Asia/Shanghai `00:00:00` |
| rule_status | tinyint unsigned | NO | IDX | `1` | 1=启用，2=停用 |
| previous_rule_version | varchar(64) | YES | | NULL | 上一版本逻辑关联 |
| created_by | varchar(128) | NO | | — | 创建人 |
| change_reason | varchar(512) | NO | | — | 变更原因 |
| published_at | datetime | NO | | — | 发布时间 |
| gmt_create | datetime | NO | | CURRENT_TIMESTAMP | 创建时间 |
| gmt_modified | datetime | NO | | CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP | 更新时间 |

**索引**：
- `pk_sku_fee_rule` (id)
- `uk_sku_fee_rule_version` (rule_version)
- `uk_sku_fee_rule_idempotency_sku` (idempotency_key_hash, sku_id)
- `uk_sku_fee_rule_sku_date` (sku_id, effective_date)
- `idx_sku_fee_rule_match` (sku_id, rule_status, effective_at)

**约束**：`effective_at` 固定为 `effective_date` 在 `Asia/Shanghai` 的 `00:00:00`。同一 SKU/生效日冲突在预校验和数据库唯一索引两层拒绝；同月不同日期允许创建多个顺序生效版本，订单按业务日匹配 `effective_at` 不晚于该日的最新有效版本。锁账结果只保存其已用 `rule_version`，不回溯替换。

**使用接口**：
- `GET /api/v1/admin/sku-fee-rules` — 查询费率版本列表。
- `GET /api/v1/admin/sku-fee-rules/{ruleVersion}` — 查询不可变版本详情。
- `POST /api/v1/admin/sku-fee-rules` — 发布单条新版本。
- `POST /api/v1/admin/sku-fee-rule-imports/{batchId}/commit` — 全量原子发布导入批次。
- `GET /api/v1/stores/{storeId}/monthly-settlement`、`GET /api/v1/order-fee-details` — 追溯汇总中的费率区间和订单实际使用版本。

## 5 `sku_fee_rule_import_batch` — 费率导入批次

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| id | bigint unsigned | NO | PK | AUTO_INCREMENT | 主键 |
| batch_id | varchar(128) | NO | UK | — | 导入批次 ID |
| file_name | varchar(512) | NO | | — | 原始文件名 |
| file_sha256 | char(64) | NO | IDX | — | 文件摘要，禁止保存本地路径 |
| batch_status | tinyint unsigned | NO | IDX | `1` | 1=已上传，2=校验失败，3=待确认，4=写入中，5=完成，6=失败 |
| commit_mode | tinyint unsigned | NO | | `1` | 固定 1=全量原子写入；首版不支持合法行部分写入 |
| effective_date | date | NO | IDX | — | 整批规则统一生效日；首批固定为 `2026-08-01`，后续可选择到日 |
| total_count | int unsigned | NO | | `0` | 总行数 |
| valid_count | int unsigned | NO | | `0` | 预校验合法行数 |
| success_count | int unsigned | NO | | `0` | 写入成功行数 |
| failed_count | int unsigned | NO | | `0` | 失败行数 |
| uploaded_by | varchar(128) | NO | IDX | — | 上传人 |
| validated_at | datetime | YES | | NULL | 校验完成时间 |
| committed_at | datetime | YES | | NULL | 写入完成时间 |
| commit_idempotency_key_hash | char(64) | YES | IDX | NULL | 提交请求幂等键摘要 |
| commit_payload_sha256 | char(64) | YES | | NULL | 提交请求体摘要，用于识别同键异参 |
| result_file_key | varchar(512) | YES | | NULL | 结果文件对象键，不存本机绝对路径 |
| gmt_create | datetime | NO | | CURRENT_TIMESTAMP | 创建时间 |
| gmt_modified | datetime | NO | | CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP | 更新时间 |

**索引**：
- `pk_sku_fee_rule_import_batch` (id)
- `uk_sku_fee_rule_import_batch_id` (batch_id)
- `idx_sku_fee_rule_import_batch_sha` (file_sha256)
- `idx_sku_fee_rule_import_batch_effective_date` (effective_date)
- `idx_sku_fee_rule_import_batch_user_status` (uploaded_by, batch_status)
- `uk_sku_fee_rule_import_batch_commit_key` (commit_idempotency_key_hash)

**提交口径**：模板每行只有 SKU 名称、SKU ID、推广服务费率和管理服务费率四个业务字段，规则生效日由批次统一选择。校验发现任一非法行时，批次进入“校验失败”，`success_count=0`，不得向 `sku_fee_rule` 写入任何规则；批次记录、逐行校验记录和结果文件仍须保留。

**使用接口**：
- `GET /api/v1/admin/sku-fee-rule-imports` — 查询导入批次列表。
- `POST /api/v1/admin/sku-fee-rule-imports` — 创建批次并全量预校验。
- `GET /api/v1/admin/sku-fee-rule-imports/{batchId}` — 查询批次详情。
- `POST /api/v1/admin/sku-fee-rule-imports/{batchId}/commit` — 原子提交整批规则。
- `GET /api/v1/admin/sku-fee-rule-imports/{batchId}/result-file` — 下载结果文件。

## 6 `sku_fee_rule_import_row` — 导入逐行结果

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| id | bigint unsigned | NO | PK | AUTO_INCREMENT | 主键 |
| batch_id | varchar(128) | NO | IDX | — | 导入批次 ID |
| row_number | int unsigned | NO | | — | 原文件行号 |
| sku_name | varchar(512) | YES | | NULL | 解析后的 SKU 名称 |
| sku_id | varchar(128) | YES | IDX | NULL | 解析后的 SKU ID |
| promotion_service_fee_rate | decimal(8,6) | YES | | NULL | 解析后的推广费率 |
| management_service_fee_rate | decimal(8,6) | YES | | NULL | 解析后的管理费率 |
| validation_status | tinyint unsigned | NO | IDX | `1` | 1=待校验，2=合法，3=非法，4=写入成功，5=写入失败 |
| error_count | int unsigned | NO | | `0` | 本行错误数量 |
| error_field | varchar(64) | YES | IDX | NULL | 首个错误字段名，用于列表快速定位 |
| error_code | varchar(64) | YES | IDX | NULL | 首个错误的稳定错误码 |
| error_message | varchar(1000) | YES | | NULL | 首个错误的中文可操作说明 |
| validation_errors_json | json | YES | | NULL | 全部错误数组：字段、错误码和中文原因 |
| created_rule_version | varchar(64) | YES | | NULL | 成功写入的规则版本 |
| source_row_json | json | YES | | NULL | 脱敏后的原始行内容 |
| gmt_create | datetime | NO | | CURRENT_TIMESTAMP | 创建时间 |
| gmt_modified | datetime | NO | | CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP | 更新时间 |

**索引**：
- `pk_sku_fee_rule_import_row` (id)
- `uk_sku_fee_rule_import_row_number` (batch_id, row_number)
- `idx_sku_fee_rule_import_row_sku` (sku_id)
- `idx_sku_fee_rule_import_row_status` (batch_id, validation_status)

**错误定位**：页面和结果文件必须至少展示 `row_number + error_field + error_message`；同一行有多个错误时，以 `validation_errors_json` 全量输出，不得只返回“导入失败”等无法操作的笼统提示。SKU 名称与 SKU ID 不匹配、费率为空或越界、同一批次 SKU 重复、同一 SKU/生效日已存在规则都应分别给出明确错误。

**使用接口**：
- `POST /api/v1/admin/sku-fee-rule-imports` — 写入逐行预校验结果。
- `GET /api/v1/admin/sku-fee-rule-imports/{batchId}` — 分页查询逐行错误。
- `POST /api/v1/admin/sku-fee-rule-imports/{batchId}/commit` — 原子更新逐行写入状态与版本。
- `GET /api/v1/admin/sku-fee-rule-imports/{batchId}/result-file` — 输出全部行的校验与写入结果。

## 7 `raw_douyin_orders` — 原始订单（现有·需改动）

保留现有字段，新增或明确以下本轮关键字段：

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| id | bigint unsigned | NO | PK | AUTO_INCREMENT | 目标结构主键 |
| order_id | varchar(128) | NO | UK | — | 抖音订单 ID |
| order_status_raw | varchar(128) | YES | | NULL | 原始订单状态 |
| order_status_normalized | varchar(32) | YES | IDX | NULL | `paid/closed/refunded/unknown` |
| sku_id | varchar(128) | YES | IDX | NULL | SKU ID |
| sale_time | datetime | YES | IDX | NULL | 销售业务时间 |
| order_paid_amount_cent | bigint | NO | | `0` | 订单实付金额 |
| sale_channel_raw | varchar(128) | YES | | NULL | 平台原始渠道 |
| sale_channel_normalized | varchar(32) | YES | IDX | NULL | `live/short_video/other/unknown` |
| owner_account_id | varchar(128) | YES | IDX | NULL | 商品归属账号 ID |
| owner_account_name | varchar(255) | YES | | NULL | 归属账号名称快照 |
| source_run_id | varchar(128) | YES | IDX | NULL | 采集运行 ID |
| gmt_create | datetime | NO | | CURRENT_TIMESTAMP | 创建时间 |
| gmt_modified | datetime | NO | | CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP | 更新时间 |

**索引**：
- `pk_raw_douyin_orders` (id)
- `uk_raw_douyin_orders_order_id` (order_id)
- `idx_raw_douyin_orders_sale_month` (sale_time)
- `idx_raw_douyin_orders_channel_owner` (sale_channel_normalized, owner_account_id)

**使用接口**：
- `GET /api/v1/order-fee-details` — 间接读取平台订单 ID、状态、渠道和归属账号用于费用追溯。
- `GET /api/v1/order-fee-details/export` — 按同一授权口径导出业务字段。
- 无公开写接口；仅订单采集 worker 按平台 `order_id` 幂等写入。

## 8 `raw_douyin_order_coupons` — 原始券（现有·需改动）

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| id | bigint unsigned | NO | PK | AUTO_INCREMENT | 目标结构主键 |
| coupon_id | varchar(128) | NO | UK | — | 券 ID |
| order_id | varchar(128) | NO | IDX | — | 订单 ID，应用层关联 |
| raw_order_id | bigint unsigned | NO | IDX | — | `raw_douyin_orders.id` 内部逻辑关联 |
| coupon_status_raw | varchar(128) | YES | | NULL | 原始券状态 |
| coupon_status_normalized | varchar(32) | YES | IDX | NULL | `available/verified/cancelled/refunded/unknown` |
| coupon_paid_amount_cent | bigint | YES | | NULL | 单券实付金额；多券订单不得重复使用整单金额 |
| coupon_refunded_amount_cent | bigint | NO | | `0` | 单券累计退款金额 |
| latest_refund_at | datetime | YES | IDX | NULL | 最近退款事件时间 |
| source_run_id | varchar(128) | YES | IDX | NULL | 采集运行 ID |
| gmt_create | datetime | NO | | CURRENT_TIMESTAMP | 创建时间 |
| gmt_modified | datetime | NO | | CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP | 更新时间 |

**索引**：
- `pk_raw_douyin_order_coupons` (id)
- `uk_raw_douyin_order_coupons_coupon_id` (coupon_id)
- `idx_raw_douyin_order_coupons_raw_order` (raw_order_id)
- `idx_raw_douyin_order_coupons_order` (order_id)
- `idx_raw_douyin_order_coupons_status` (coupon_status_normalized)

**主键迁移约束**：目标结构以两表自增 `id` 为主键，平台 `order_id / coupon_id` 永久保持非空唯一。第一发布阶段只新增、回填和校验内部 ID，旧字符串主键及关联继续可用；第二发布阶段在采集 upsert、结算读取和券—订单关联均兼容内部 ID 后切换主键约束。`raw_order_id` 与 `order_id` 必须指向同一订单，任一不一致均阻断约束切换并记录数据质量问题。

**使用接口**：
- `GET /api/v1/order-fee-details` — 间接读取平台券 ID、状态、实付与退款金额。
- `GET /api/v1/order-fee-details/export` — 导出券级费用依据。
- 无公开写接口；仅订单/券采集 worker 写入，API 永不暴露内部 `id/raw_order_id`。

## 9 `douyin_refund_event` — 退款事件

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| id | bigint unsigned | NO | PK | AUTO_INCREMENT | 主键 |
| refund_event_id | varchar(128) | NO | UK | — | 平台退款事件 ID 或稳定派生 ID |
| order_id | varchar(128) | NO | IDX | — | 订单 ID |
| coupon_id | varchar(128) | YES | IDX | NULL | 券 ID；无法定位时进入质量问题 |
| refund_type | tinyint unsigned | NO | IDX | — | 1=部分退款，2=全额退款 |
| refund_status | tinyint unsigned | NO | IDX | — | 1=处理中，2=成功，3=失败，4=撤销 |
| refund_amount_cent | bigint | NO | | `0` | 本次退款金额 |
| occurred_at | datetime | NO | IDX | — | 退款事件发生时间 |
| source_run_id | varchar(128) | YES | IDX | NULL | 采集运行 ID |
| raw_payload | json | YES | | NULL | 脱敏必要载荷 |
| gmt_create | datetime | NO | | CURRENT_TIMESTAMP | 创建时间 |
| gmt_modified | datetime | NO | | CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP | 更新时间 |

**索引**：
- `pk_douyin_refund_event` (id)
- `uk_douyin_refund_event_id` (refund_event_id)
- `idx_douyin_refund_event_coupon_time` (coupon_id, occurred_at)
- `idx_douyin_refund_event_order_time` (order_id, occurred_at)

**使用接口**：
- `GET /api/v1/order-fee-details` — 通过费用调整数组间接追溯退款事件影响。
- `GET /api/v1/order-fee-details/export` — 导出调整入账月份和退款影响。
- 无公开写接口；仅退款采集 worker 写入并幂等触发费用调整。
