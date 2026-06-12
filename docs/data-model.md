# 数据模型 v1（生产 MVP）

本文档约定抖音订单分账数据看板生产 MVP 的数据库表方向。v1 只支持订单、券、核销、抖音号/职人绑定、门店/POI 映射、SKU 分佣规则、结算明细、汇总和任务状态；不提交任何真实业务数据、密钥、账号配置或本地路径。

当前状态：v1 数据模型已按“发票不上线、退款不展示、预计应收分佣”口径调整，可进入 PostgreSQL 迁移和 FastAPI 查询实现。

## 一、字段状态

| 状态 | 含义 |
| --- | --- |
| confirmed | 真实数据或现有脚本输出中稳定存在。 |
| computed | 需要由清洗、映射、汇总或任务计算得到。 |
| manual | 需要人工维护、配置或运营导入。 |
| missing | 当前真实数据中没有，或来源不明确。 |

## 二、关键结论

- 明细粒度按券建模，一行一券；订单数据中存在一单多券，不能只按订单建模。
- `order_id` 是订单原始表业务唯一键。
- `coupon_id` 来自订单 `certificate[].certificate_id` 和核销 `certificate_id`，是订单券与核销记录的主要关联键。
- `verify_id` 是核销记录唯一键；核销接口当前不返回 `order_id`，必须通过 `coupon_id` 关联订单券。
- `store_id` 是系统内部 ID；`poi_id` 来自订单意向门店、职人绑定、后台抖音号明细和核销查询，二者不能混用。
- 订单归属匹配按 ID 优先、昵称兜底；未匹配或冲突必须写入异常表，不能默认归店。
- v1 不展示发票/到票字段，不实现财务审核和正式应收确认。
- v1 不接退款接口，也不在页面展示退款字段；订单/券状态仅用于后台排除退款券和异常诊断。

## 三、核心表分层

```text
raw_douyin_orders
raw_douyin_order_coupons
raw_douyin_verify_records
raw_aweme_bindings
        |
        v
dim_stores
dim_store_poi_mappings
dim_sku_product_rules
dim_aweme_accounts
        |
        v
settlement_order_details
        |
        v
agg_store_monthly_settlement
agg_store_ranking
job_runs
data_quality_issues
```

## 四、原始数据表

### raw_douyin_orders

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| order_id | text | confirmed | 抖音订单 ID，业务唯一键。 |
| order_status | text | confirmed | 订单接口原始状态或映射值。 |
| sku_id | text | confirmed | 订单接口 SKU ID。 |
| product_name | text | confirmed | 订单 SKU 或商品名称。 |
| pay_time | timestamptz | confirmed | 支付时间；销售月优先使用。 |
| create_order_time | timestamptz | confirmed | 下单时间；无支付时间时兜底。 |
| paid_amount_cent | integer | confirmed | 订单实收金额，优先使用子订单实收汇总。 |
| owner_account_id | text | confirmed | 订单归属账号 ID，优先 `transfer_uid`。 |
| owner_douyin_uid | text | confirmed | 订单归属抖音 UID，覆盖率较低。 |
| owner_account_name | text | confirmed | 订单归属账号展示名。 |
| sale_role | text | confirmed | 订单销售角色，用于识别商家订单。 |
| sale_channel | text | confirmed | 订单销售渠道。 |
| intention_poi_id | text | confirmed | 订单意向 POI，不等于销售归属门店。 |
| raw_payload | jsonb | confirmed | 原始订单响应。 |
| source_run_id | text | computed | 采集任务 ID。 |
| created_at | timestamptz | computed | 入库时间。 |
| updated_at | timestamptz | computed | 更新时间。 |

### raw_douyin_order_coupons

订单 `certificate[]` 数组展开，一行一券。

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| coupon_id | text | confirmed | `certificate[].certificate_id`，业务唯一键。 |
| order_id | text | confirmed | 所属订单 ID。 |
| order_item_id | text | confirmed | 子订单或订单项 ID。 |
| coupon_status | text | confirmed | `certificate[].item_status` 原始值或映射值。 |
| coupon_updated_at | timestamptz | confirmed | 券状态更新时间。 |
| coupon_refunded_cent | integer | confirmed | 券退款金额，仅用于内部排除/诊断。 |
| coupon_refund_time | timestamptz | confirmed | 券退款时间，仅用于内部排除/诊断。 |
| raw_payload | jsonb | confirmed | 单张券原始 JSON。 |
| source_run_id | text | computed | 采集任务 ID。 |

### raw_douyin_verify_records

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| verify_id | text | confirmed | 核销接口 ID，业务唯一键。 |
| coupon_id | text | confirmed | 核销接口 `certificate_id`。 |
| verify_status | text | confirmed | 核销状态原始值或映射值。 |
| verify_time | timestamptz | confirmed | 核销时间。 |
| poi_id | text | confirmed | 核销 POI，或按 POI 拉取时回填。 |
| verify_store_name_raw | text | confirmed | 核销门店名称原始值。 |
| sku_id | text | confirmed | 核销接口 SKU ID。 |
| product_name | text | confirmed | 核销接口商品名称。 |
| paid_amount_cent | integer | confirmed | 核销金额或券支付金额。 |
| cancel_time | timestamptz | confirmed | 撤销核销时间。 |
| raw_payload | jsonb | confirmed | 原始核销记录。 |
| source_run_id | text | computed | 采集任务 ID。 |

### raw_aweme_bindings

来自抖音号/职人绑定接口或后台抖音号明细导出。

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| binding_key | text | computed | 由抖音 ID、账户 ID、POI ID、昵称生成，业务去重键。 |
| douyin_id | text | confirmed | 抖音号 ID。 |
| douyin_nickname | text | confirmed | 抖音号昵称。 |
| account_id | text | confirmed | 所属账号 ID 或职人 UID。 |
| account_name | text | confirmed | 所属账号名称。 |
| poi_id | text | confirmed | 所属账号关联 POI。 |
| binding_status | text | confirmed | 绑定状态。 |
| raw_payload | jsonb | confirmed | 原始记录。 |
| source_run_id | text | computed | 采集任务 ID。 |
| created_at | timestamptz | computed | 入库时间。 |
| updated_at | timestamptz | computed | 更新时间。 |

## 五、维表

### dim_stores

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| store_id | text | manual | 系统内部门店 ID，业务唯一键。 |
| store_name | text | manual/confirmed | 标准门店名。 |
| certified_subject_name | text | confirmed | 职人绑定或商家主体名称。 |
| region | text | manual | 区域/城市。 |
| is_active | boolean | manual | 是否启用。 |

### dim_store_poi_mappings

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| store_id | text | manual | 内部门店 ID。 |
| poi_id | text | confirmed | POI ID。 |
| poi_name | text | confirmed | POI 名称或绑定门店名称。 |
| mapping_source | text | computed/manual | `aweme_binding`、`poi_query`、`manual` 等。 |
| is_primary | boolean | manual | 多 POI 场景下主 POI。 |

### dim_sku_product_rules

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| sku_id | text | confirmed | 订单和核销接口稳定返回。 |
| product_type | text | manual | 商品类型。 |
| product_name | text | confirmed | 商品名称。 |
| commission_rate | numeric(6,4) | manual | 分佣比例。 |
| is_service_product | boolean | computed/manual | 是否进入看板。 |

### dim_aweme_accounts

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| account_id | text | confirmed | 职人 UID、商家账号 ID 或订单归属 ID。 |
| nickname | text | confirmed | 抖音号昵称或订单归属昵称。 |
| store_id | text | computed/manual | 通过绑定 POI 映射到内部店。 |
| binding_status | text | confirmed | 绑定状态。 |
| valid_from | date | confirmed | 绑定开始日期。 |
| valid_to | date | confirmed | 绑定结束日期，可空。 |

归属人匹配策略：

| 优先级 | 匹配方式 | 结论 |
| --- | --- | --- |
| 1 | `raw_douyin_orders.owner_account_id = dim_aweme_accounts.account_id` | ID 语义最稳定，命中时优先采用。 |
| 2 | `raw_douyin_orders.owner_account_name = dim_aweme_accounts.nickname` | UID 未命中时兜底。 |
| 3 | 人工补充 | 两者均未命中的订单写入异常表，交由业务补齐。 |

## 六、核心明细表

### settlement_order_details

该表是页面 3 的主要数据来源，也是页面 1 和页面 2 汇总计算的证据来源。v1 一行一券；月份类字段由销售时间或核销时间派生，不作为底表独立字段。

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| order_id | text | confirmed | 来自订单表。 |
| coupon_id | text | confirmed | 来自订单券表。 |
| sku_id | text | confirmed | 订单或核销 SKU。 |
| owner_account_id | text | confirmed | 订单归属账号 ID。 |
| owner_account_name | text | confirmed | 订单归属账号展示名。 |
| product_type | text | computed | 由 SKU 商品类型规则得到。 |
| sale_store_id | text | computed | 订单归属人映射到内部店。 |
| sale_store_name | text | computed | 销售归属门店名称。 |
| sale_time | timestamptz | confirmed | 订单支付时间或下单时间。 |
| is_verified | boolean | computed | 是否存在有效核销记录。 |
| verify_store_id | text | computed | 核销 POI 映射到内部店，未核销为空。 |
| verify_store_name | text | computed | 核销门店名称，未核销为空。 |
| verify_time | timestamptz | confirmed | 核销时间，未核销为空。 |
| relation_type | text | computed | `same_store`、`cross_store`、`unverified`、`unknown`。 |
| is_commissionable | boolean | computed | 已核销且销售门店、核销门店均可识别且不同店。 |
| is_refund_excluded | boolean | computed | 是否因订单/券状态被排除出分账；内部字段，不进入 v1 API。 |
| paid_amount_cent | integer | confirmed | 券或订单实收金额。 |
| commission_rate | numeric(6,4) | manual | SKU 分佣规则。 |
| receivable_commission_cent | integer | computed | 跨店核销时销售门店预计应收分佣。 |
| payable_commission_cent | integer | computed | 跨店核销时核销门店预计应付分佣。 |
| source_run_id | text | computed | 生成该明细的任务 ID。 |
| updated_at | timestamptz | computed | 更新时间。 |

## 七、汇总表

### agg_store_ranking

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| month | char(7) | computed | 销售月。 |
| product_type | text | computed | `all` 或具体商品类型。 |
| store_id | text | computed | 销售归属或核销归属内部店 ID。 |
| store_name | text | computed | 门店名称。 |
| sales_order_count | integer | computed | 按销售归属门店去重订单统计。 |
| self_sold_self_verified_count | integer | computed | 本店销售、本店核销券数。 |
| self_sold_other_verified_count | integer | computed | 本店销售、他店核销券数。 |
| other_sold_self_verified_count | integer | computed | 他店销售、本店核销券数。 |
| self_verify_income_cent | integer | computed | 本店核销收入参考额。 |
| effective_commission_income_cent | integer | computed | 本店销售、他店核销的预计应收分佣。 |
| updated_at | timestamptz | computed | 更新时间。 |

### agg_store_monthly_settlement

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| month | char(7) | computed | 核销月。 |
| store_id | text | computed | 当前门店 ID。 |
| product_type | text | computed | `all` 或具体产品类型。 |
| estimated_receivable_commission_cent | integer | computed | 本店销售、他店核销的预计应收分佣。 |
| commissionable_total_cent | integer | computed | 本店销售、他店核销的可分佣基础金额。 |
| estimated_payable_commission_cent | integer | computed | 他店销售、本店核销的预计应付分佣。 |
| updated_at | timestamptz | computed | 更新时间。 |

## 八、任务和异常表

### job_runs

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| job_id | text | computed | 任务唯一 ID。 |
| job_name | text | computed | 任务名称。 |
| status | text | computed | `running`、`success`、`failed`。 |
| started_at | timestamptz | computed | 开始时间。 |
| finished_at | timestamptz | computed | 结束时间。 |
| success_count | integer | computed | 成功行数。 |
| failed_count | integer | computed | 失败行数。 |
| error_message | text | computed | 脱敏错误信息。 |
| metadata_json | jsonb | computed | 脱敏任务元信息；采集任务包含 `source_window` 和各阶段 `phases` 统计。 |

### data_quality_issues

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| issue_id | text | computed | 异常唯一 ID。 |
| issue_type | text | computed | `missing_coupon_id`、`unmatched_owner`、`unmatched_poi`、`unmatched_sku`、`conflicting_owner_match` 等。 |
| order_id | text | computed | 关联订单，可空。 |
| coupon_id | text | computed | 关联券，可空。 |
| severity | text | computed | `warning`、`error`。 |
| message | text | computed | 脱敏说明。 |
| raw_context_json | jsonb | computed | 脱敏上下文。 |
| source_run_id | text | computed | 任务 ID。 |
| created_at | timestamptz | computed | 创建时间。 |

## 九、状态枚举

| 字段 | 枚举 | 状态 | 说明 |
| --- | --- | --- | --- |
| verify_status | `valid`、`cancelled`、`unknown` | computed | 抖音核销状态归一化。 |
| coupon_status | `pending`、`refunding`、`refunded`、`fulfilled`、`unknown` | computed | 订单券状态归一化；v1 不展示。 |
| relation_type | `same_store`、`cross_store`、`unverified`、`unknown` | computed | 由销售门店和核销门店比较得到。 |
| product_type | `all` 或商品类型名称 | manual/computed | `all` 只用于查询和汇总。 |
| job_status | `running`、`success`、`failed` | computed | 任务状态。 |

## 十、Deferred / Risk

- `raw_douyin_refunds`、`refund_id`、`refund_status`、`refund_amount_cent` 是 v2 售后明细候选，不进入 v1 页面和 API。v1 只用订单/券状态做内部排除。
- `finance_invoice_status`、`invoice_status`、`invoice_received_at`、`invoice_approved_at`、`invoiced_coupon_count`、`pending_invoice_commission_cent`、`current_receivable_commission_cent` 是 v2 财务确认候选，不进入 v1 页面和 API。
- 若后续接入退款接口，退款只能稳定关联到订单，不能稳定关联到券；一单多券且部分退款时，需要新增券粒度归因规则。
- 核销 POI 与内部店的映射需支持一店多 POI，不能把 `poi_id` 直接当作内部 `store_id`。
- 订单归属 UID 与昵称双重匹配结果不一致时，必须进入异常表并人工确认。
