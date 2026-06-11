# 数据模型草案

本文档用于约定抖音订单分账数据看板第一阶段的数据表方向。当前草案不是最终数据库 DDL，也不是已经确认的真实数据结构。协作者需要基于本地真实拉取数据校对字段来源、唯一键和状态枚举后，再固化为 PostgreSQL 表结构和迁移脚本。

## 确认状态

当前状态：待协作者确认。

确认前，本草案只用于前后端讨论和前端 mock 开发，不作为后端建表、数据迁移或财务口径定稿依据。协作者确认时至少需要对照真实拉取样本检查字段是否存在、字段含义是否稳定、状态值是否完整、唯一键是否可靠。

## 一、协作分工

- 后端和数据侧主导：基于本地真实订单、券核销、退款、职人绑定和门店映射数据，确认底表字段、唯一键、状态枚举和数据质量问题。
- 前端侧校对：基于页面 1、页面 2、页面 3 的展示和筛选需求，确认 API 是否能提供必要字段。
- 双方共同确认：哪些字段来自抖音原始数据，哪些字段来自人工维护，哪些字段由系统计算。

真实业务数据、密钥、账号配置和本地路径不得提交到仓库。仓库只提交字段草案、接口契约、脱敏 mock 数据和可重复执行的脚本。

## 二、建模原则

- 原始数据要保留：订单、券核销、退款等源数据先进入 `raw_*` 表，避免清洗后无法追溯。
- 业务口径要集中：跨店核销、是否分佣、分佣金额、到票状态等口径应在共享计算层中统一，不由前端重复计算。
- 明细表支撑汇总：页面 1 和页面 2 的汇总结果都应能从页面 3 对应的明细表追溯。
- 金额字段避免浮点误差：数据库可使用 `numeric(12,2)`，API 建议返回人民币分为单位的整数。
- 时间口径必须显式：销售月份、核销月份、到票月份分别来自不同时间字段，不应混用。
- 任务可重跑：采集和汇总任务需要记录 `job_runs`，同一业务主键重复拉取时应幂等更新。

## 三、核心表分层

```text
raw_douyin_orders
raw_douyin_verify_records
raw_douyin_refunds
raw_aweme_bindings
        |
        v
dim_stores
dim_products
dim_aweme_accounts
dim_commission_rules
        |
        v
settlement_order_details
        |
        v
agg_store_monthly_settlement
agg_store_ranking
job_runs
```

## 四、原始数据表

### raw_douyin_orders

保存抖音订单原始数据。后端需要保留原始响应或原始导出字段，便于后续修正口径。

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| order_id | text | 抖音订单 ID，建议作为业务唯一键。 |
| order_status | text | 抖音订单状态原值。 |
| coupon_id | text | 券 ID；如果一单多券，后续需要确认一行一券还是订单表和券表拆分。 |
| sku_id | text | 商品 SKU ID。 |
| product_name | text | 商品名称。 |
| pay_time | timestamptz | 支付或下单时间，以真实数据字段为准。 |
| sale_month | char(7) | 销售月份，格式 `YYYY-MM`。 |
| paid_amount_cent | integer | 订单实收金额，单位分。 |
| owner_account_id | text | 订单归属抖音号、职人或账号 ID。 |
| raw_payload | jsonb | 原始记录，便于追溯。 |
| source_run_id | text | 采集任务 ID。 |
| created_at | timestamptz | 入库时间。 |
| updated_at | timestamptz | 更新时间。 |

### raw_douyin_verify_records

保存券核销原始数据。

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| verify_id | text | 核销记录 ID，建议作为业务唯一键。 |
| coupon_id | text | 券 ID，用于关联订单或券明细。 |
| order_id | text | 如接口返回订单 ID，则保留。 |
| verify_status | text | 核销状态原值。 |
| verify_time | timestamptz | 核销时间。 |
| verify_month | char(7) | 核销月份，格式 `YYYY-MM`。 |
| poi_id | text | 实际核销门店 POI。 |
| verify_store_name_raw | text | 接口或后台返回的核销门店原始名称。 |
| raw_payload | jsonb | 原始记录。 |
| source_run_id | text | 采集任务 ID。 |

### raw_douyin_refunds

保存退款原始数据。

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| refund_id | text | 退款单 ID，建议作为业务唯一键。 |
| order_id | text | 订单 ID。 |
| coupon_id | text | 券 ID，如接口提供则保留。 |
| refund_status | text | 退款状态原值。 |
| refund_amount_cent | integer | 退款金额，单位分。 |
| refund_finished_at | timestamptz | 退款完成时间。 |
| raw_payload | jsonb | 原始记录。 |
| source_run_id | text | 采集任务 ID。 |

## 五、维表和人工维护表

### dim_stores

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| store_id | text | 系统内部门店 ID。 |
| store_name | text | 门店展示名称。 |
| poi_id | text | 抖音 POI ID，可一店多 POI 时另建映射表。 |
| certified_subject_id | text | 认证主体 ID。 |
| region | text | 区域或城市。 |
| is_active | boolean | 是否启用。 |

### dim_products

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| sku_id | text | 抖音 SKU ID。 |
| product_type | text | 页面展示的商品类型，如 `268保养`、`168保养`。 |
| product_name | text | 商品名称。 |
| is_service_product | boolean | 是否进入服务产品筛选。 |

### dim_aweme_accounts

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| account_id | text | 抖音号、职人或后台账号 ID。 |
| nickname | text | 昵称。 |
| store_id | text | 绑定销售归属门店。 |
| binding_status | text | 绑定状态。 |
| valid_from | date | 绑定生效日期。 |
| valid_to | date | 绑定失效日期，可空。 |

### dim_commission_rules

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| rule_id | text | 分佣规则 ID。 |
| product_type | text | 商品类型。 |
| commission_rate | numeric(6,4) | 分佣比例，如 `0.1000`。 |
| valid_from | date | 生效日期。 |
| valid_to | date | 失效日期，可空。 |

### finance_invoice_status

第一阶段不实现发票上传、发票存储和 OCR，只预留财务维护或导入的到票状态。

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| invoice_status_id | text | 到票状态记录 ID。 |
| order_id | text | 订单 ID。 |
| coupon_id | text | 券 ID，如按券确认到票则必填。 |
| invoice_status | text | `not_received`、`received`、`approved`、`rejected`。 |
| invoice_received_at | timestamptz | 到票时间。 |
| invoice_approved_at | timestamptz | 审核通过时间。 |
| remark | text | 财务备注。 |

## 六、核心明细表

### settlement_order_details

该表是页面 3 的主要数据来源，也是页面 1 和页面 2 汇总计算的证据来源。

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| detail_id | text | 明细行 ID，可由订单 ID + 券 ID 生成。 |
| order_id | text | 订单 ID。 |
| coupon_id | text | 券 ID。 |
| product_type | text | 商品类型。 |
| sale_store_id | text | 销售归属门店 ID。 |
| sale_store_name | text | 销售归属门店名称。 |
| sale_month | char(7) | 销售月份。 |
| sale_time | timestamptz | 销售时间。 |
| is_verified | boolean | 是否核销。 |
| verify_store_id | text | 实际核销门店 ID。 |
| verify_store_name | text | 实际核销门店名称。 |
| verify_month | char(7) | 核销月份。 |
| verify_time | timestamptz | 核销时间。 |
| is_commissionable | boolean | 是否分佣；未核销记录不参与该字段计算。 |
| invoice_status | text | 到票状态。 |
| invoice_received_at | timestamptz | 到票时间。 |
| invoice_approved_at | timestamptz | 审核通过时间。 |
| refund_status | text | 退款状态。 |
| refund_amount_cent | integer | 退款金额，单位分。 |
| paid_amount_cent | integer | 订单实收金额，单位分。 |
| commission_rate | numeric(6,4) | 分佣比例。 |
| receivable_commission_cent | integer | 本店卖出、他店核销时，销售门店预计获得的分佣参考额。 |
| payable_commission_cent | integer | 他店卖出、本店核销时，核销门店预计分出的分佣参考额。 |
| source_run_id | text | 生成该明细的任务 ID。 |

## 七、汇总表

### agg_store_ranking

页面 1 的全国门店榜单汇总表。

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| month | char(7) | 月份或统计周期。 |
| product_type | text | `all` 或具体商品类型。 |
| store_id | text | 门店 ID。 |
| store_name | text | 门店名称。 |
| sales_order_count | integer | 销售归属门店订单数，不要求已核销。 |
| self_sold_self_verified_count | integer | 本店卖出、本店核销数。 |
| self_sold_other_verified_count | integer | 本店卖出、他店核销数。 |
| other_sold_self_verified_count | integer | 他店销售、在本店核销数。 |
| self_verify_income_cent | integer | 本店核销收入，单位分。 |
| effective_commission_income_cent | integer | 有效分佣收入，单位分。 |

### agg_store_monthly_settlement

页面 2 的单店月度分账汇总表。

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| month | char(7) | 月份。 |
| store_id | text | 当前门店 ID。 |
| product_type | text | `all` 或具体商品类型。 |
| current_receivable_commission_cent | integer | 当期应收分佣，按到票或审核通过时间归属。 |
| commissionable_total_cent | integer | 可分佣总金额，按核销时间归属。 |
| estimated_payable_commission_cent | integer | 本店预计分出分佣参考额，按核销时间归属。 |
| updated_at | timestamptz | 汇总更新时间。 |

## 八、状态枚举

| 字段 | 枚举 | 说明 |
| --- | --- | --- |
| invoice_status | `not_received`、`received`、`approved`、`rejected` | 未到票、已到票、审核通过、审核未通过。 |
| refund_status | `none`、`refunding`、`refunded` | 未退款、退款中、已退款。 |
| product_type | `all` 或商品类型名称 | `all` 只用于查询和汇总，不建议作为明细表真实商品类型。 |

## 九、待协作者确认

- 订单与券的真实关系：是否存在一单多券，以及页面明细粒度应该按订单还是按券。
- 抖音接口中稳定可用的唯一键：订单 ID、券 ID、核销 ID、退款 ID 是否完整且可重复拉取。
- 销售归属门店的优先级：订单归属人、职人绑定、后台账号映射冲突时如何处理。
- 核销门店映射：POI、认证主体、门店名称之间是否一对一。
- 退款冲减口径：已核销后退款是否从当月分佣中冲减，还是进入待财务确认状态。
- 到票数据来源：第一阶段由 CSV 导入、飞书多维表格同步，还是后台手动维护。
