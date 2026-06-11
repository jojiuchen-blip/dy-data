# 数据模型第一轮确认

本文档用于约定抖音订单分账数据看板第一阶段的数据表方向。第一轮确认基于本地已拉取的订单、券核销、退款、职人绑定和 POI 映射数据，只确认字段来源、唯一键和第一版接口可支持性；不提交任何真实业务数据、密钥、账号配置或本地路径。

## 确认状态

当前状态：第一轮数据侧已确认，可进入 FastAPI 查询接口设计。

字段状态说明：

| 状态 | 含义 |
| --- | --- |
| confirmed | 真实数据或现有脚本输出中稳定存在。 |
| computed | 需要由清洗或汇总脚本计算得到。 |
| manual | 需要人工维护、配置或财务导入。 |
| missing | 当前真实数据中没有，或来源不明确。 |

## 一、关键结论

- 明细粒度应按券/核销明细建模，不应只按订单建模。订单数据中存在一单多券，订单表的 `certificate` 数组最多至少出现到第 3 张券；`coupon_id` 应来自 `certificate[].certificate_id`。
- `order_id` 可作为订单原始表业务唯一键；订单采集脚本已按 `order_id` 去重。
- `coupon_id` 在订单 `certificate[]` 和核销记录 `certificate_id` 中稳定存在，是订单券明细与核销记录的主要关联键。
- `verify_id` 在核销记录接口中稳定存在，可作为核销记录唯一键；核销记录接口当前不返回 `order_id`，必须通过 `coupon_id` 反查订单。
- `refund_id` 对应退款接口 `after_sale_id`，可作为退款单唯一键；退款接口稳定返回 `order_id`，但当前没有稳定券 ID，退款到券粒度的关联存在风险。
- `store_id` 是系统内部 ID，需要由门店/账号映射维护；`poi_id` 在订单意向门店、职人绑定门店和核销 POI 中可获得，但不是所有业务视角都天然一对一。
- 到票状态、分佣规则和内部区域等字段不来自抖音接口，第一阶段按人工维护或导入处理。

## 二、核心表分层

```text
raw_douyin_orders
raw_douyin_order_coupons
raw_douyin_verify_records
raw_douyin_refunds
raw_aweme_bindings
        |
        v
dim_stores
dim_store_poi_mappings
dim_sku_product_rules
dim_aweme_accounts
finance_invoice_status
        |
        v
settlement_order_details
        |
        v
agg_store_monthly_settlement
agg_store_ranking
job_runs
```

## 三、原始数据表

### raw_douyin_orders

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| order_id | text | confirmed | 抖音订单 `order_id`，订单表业务唯一键。 |
| order_status | text | confirmed | 订单接口 `order_status` / `status` / `trade_status` 原值或映射值。 |
| sku_id | text | confirmed | 订单接口 `sku_id` 或 `products[].sku_id`。 |
| product_name | text | confirmed | 订单接口 `sku_name` 或 `products[].product_name`。 |
| pay_time | timestamptz | confirmed | 订单接口 `pay_time`；销售月优先使用该字段。 |
| create_order_time | timestamptz | confirmed | 订单接口 `create_order_time`，无支付时间时可作兜底。 |
| sale_month | char(7) | computed | 由 `pay_time` 优先、`create_order_time` 兜底计算 `YYYY-MM`。 |
| paid_amount_cent | integer | confirmed | 优先取 `sub_order_amount_infos[].receipt_amount` 汇总；兜底 `receipt_amount` / `pay_amount`。 |
| owner_account_id | text | confirmed | 订单 `order_sale_info.transfer_uid`，部分订单为空。 |
| owner_douyin_uid | text | confirmed | 订单 `order_sale_info.transfer_douyin_uid`，覆盖率低于 `transfer_uid`。 |
| owner_nickname | text | confirmed | 订单 `order_sale_info.transfer_nickName`。 |
| sale_role | text | confirmed | 订单 `order_sale_info.sale_role`，用于筛选商家订单。 |
| sale_channel | text | confirmed | 订单 `order_sale_info.sale_channel`。 |
| intention_poi_id | text | confirmed | 订单接口 `intention_poi_id` 或 `poi_id`，表示订单意向门店，不等同销售归属门店。 |
| raw_payload | jsonb | confirmed | 原始订单响应。 |
| source_run_id | text | computed | 采集任务 ID。 |
| created_at | timestamptz | computed | 入库时间。 |
| updated_at | timestamptz | computed | 更新时间。 |

### raw_douyin_order_coupons

订单和券需要拆分。该表从订单 `certificate[]` 数组展开，一行一券。

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| order_id | text | confirmed | 所属订单 ID。 |
| coupon_id | text | confirmed | `certificate[].certificate_id`，券业务主键。 |
| order_item_id | text | confirmed | `certificate[].order_item_id`，可辅助关联子订单金额。 |
| coupon_status | text | confirmed | `certificate[].item_status`，原始枚举值或映射值。 |
| coupon_updated_at | timestamptz | confirmed | `certificate[].item_update_time`。 |
| coupon_refund_amount_cent | integer | confirmed | `certificate[].refund_amount`。 |
| coupon_refund_time | timestamptz | confirmed | `certificate[].refund_time`。 |
| raw_payload | jsonb | confirmed | 单张券原始 JSON。 |

### raw_douyin_verify_records

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| verify_id | text | confirmed | 核销接口 `verify_id`，核销记录业务唯一键。 |
| coupon_id | text | confirmed | 核销接口 `certificate_id`。 |
| order_id | text | missing | 核销接口当前未返回订单 ID，需要由 `coupon_id` 关联订单券表。 |
| verify_status | text | confirmed | 核销接口 `status`，已观察到有效和撤销状态。 |
| verify_time | timestamptz | confirmed | 核销接口 `verify_time`。 |
| verify_month | char(7) | computed | 由 `verify_time` 计算。 |
| poi_id | text | confirmed | 按 POI 拉取时由查询 POI 回填 `verify_poi_id`，或来自接口/门店查询结果。 |
| verify_store_name_raw | text | confirmed | `verify_poi_name` 或核销操作人名称；部分接口字段覆盖有限。 |
| sku_id | text | confirmed | 核销接口 `sku.sku_id`。 |
| product_name | text | confirmed | 核销接口 `sku.title`。 |
| paid_amount_cent | integer | confirmed | 核销接口 `amount.pay_amount` / `amount.coupon_pay_amount`。 |
| cancel_time | timestamptz | confirmed | 撤销记录存在时返回。 |
| raw_payload | jsonb | confirmed | 原始核销记录。 |
| source_run_id | text | computed | 采集任务 ID。 |

### raw_douyin_refunds

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| refund_id | text | confirmed | 退款接口 `after_sale_id`。 |
| order_id | text | confirmed | 退款接口 `order_id`。 |
| coupon_id | text | missing | 退款接口当前没有稳定券 ID；只能尝试由订单券退款金额/时间推断，存在风险。 |
| refund_status | text | confirmed | 退款接口 `refund_status`，脚本已映射初始化、审核中、退款成功等状态。 |
| refund_amount_cent | integer | confirmed | 优先 `real_refund_amount`，可保留 `refund_amount`、`total_refund_amount` 等原值。 |
| refund_created_at | timestamptz | confirmed | 退款接口 `create_time`。 |
| refund_finished_at | timestamptz | confirmed | 退款接口 `complete_time`。 |
| raw_payload | jsonb | confirmed | 原始退款记录。 |
| source_run_id | text | computed | 采集任务 ID。 |

## 四、维表和人工维护表

### dim_stores

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| store_id | text | manual | 系统内部门店 ID，建议由后台维护。 |
| store_name | text | confirmed | 职人绑定门店名称、POI 名称或人工标准名。 |
| certified_subject_id | text | manual | 抖音接口当前可获得主体名称，稳定主体 ID 来源未确认。 |
| certified_subject_name | text | confirmed | 职人绑定 `account_name` / 商家主体。 |
| region | text | manual | 区域/城市需人工维护或从门店主数据导入。 |
| is_active | boolean | manual | 是否启用需人工维护。 |

### dim_store_poi_mappings

一店可能对应多个 POI，POI 与内部 `store_id` 建议拆成映射表。

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| store_id | text | manual | 内部门店 ID。 |
| poi_id | text | confirmed | 职人绑定 `poi_id`、核销查询 POI、门店 POI 查询结果。 |
| poi_name | text | confirmed | POI 名称或绑定门店名称。 |
| mapping_source | text | computed | `craftsman_binding`、`poi_query`、`manual` 等。 |
| is_primary | boolean | manual | 多 POI 场景下的主 POI 需人工确认。 |

### dim_sku_product_rules

SKU ID、商品类型和分佣比例使用独立映射表维护；订单明细保留 `sku_id`，页面展示的商品类型和分佣比例由该表派生。

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| sku_id | text | confirmed | 订单和核销接口均稳定返回。 |
| product_type | text | manual | 由配置中的 SKU 到产品类型映射维护。 |
| product_name | text | confirmed | 订单 `sku_name` 或核销 `sku.title`。 |
| commission_rate | numeric(6,4) | manual | 该商品类型对应的分佣比例，需财务确认。 |
| is_service_product | boolean | computed | 是否进入看板由 SKU 映射是否存在计算。 |

### dim_aweme_accounts

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| account_id | text | confirmed | 职人绑定 `craftsman_uid` 或商家账号 ID；订单归属优先使用 `transfer_uid`。 |
| nickname | text | confirmed | 职人绑定昵称、订单归属人昵称。 |
| store_id | text | computed | 由绑定 POI/门店映射到内部 `store_id`。 |
| binding_status | text | confirmed | 职人绑定接口 `bind_status`。 |
| valid_from | date | confirmed | 职人绑定 `bind_start_time`。 |
| valid_to | date | confirmed | 职人绑定 `bind_end_time`，可空。 |

### finance_invoice_status

第一阶段不实现发票上传、发票存储和 OCR，只预留财务维护或导入的到票状态。

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| invoice_status_id | text | computed | 可由 `order_id + coupon_id` 或导入记录 ID 生成。 |
| order_id | text | manual | 财务导入或后台维护。 |
| coupon_id | text | manual | 建议按券维护；如果只按订单维护，需拆分到券时标记风险。 |
| invoice_status | text | manual | `not_received`、`received`、`approved`、`rejected`。 |
| invoice_received_at | timestamptz | manual | 到票时间。 |
| invoice_approved_at | timestamptz | manual | 审核通过时间。 |
| remark | text | manual | 财务备注。 |

## 五、核心明细表

### settlement_order_details

该表是页面 3 的主要数据来源，也是页面 1 和页面 2 汇总计算的证据来源。第一阶段建议一行一券；月份类字段由销售时间或核销时间派生，不作为底表独立字段。

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| order_id | text | confirmed | 来自订单表。 |
| coupon_id | text | confirmed | 来自订单券表或核销记录。 |
| sku_id | text | confirmed | 来自订单或核销接口，用于关联 SKU 商品类型映射表。 |
| owner_account_id | text | confirmed | 订单归属账号 ID，优先使用订单归属字段。 |
| owner_account_name | text | confirmed | 订单归属账号展示名。 |
| product_type | text | computed | 由 SKU 商品类型映射表得到，不作为明细底表原始字段。 |
| sale_store_id | text | computed | 订单归属人/职人绑定门店映射到内部门店。 |
| sale_store_name | text | computed | 由销售归属门店映射得到。 |
| sale_time | timestamptz | confirmed | 订单 `pay_time` 或 `create_order_time`。 |
| is_verified | boolean | computed | 是否存在有效核销记录。 |
| verify_store_id | text | computed | 核销 POI 映射到内部 `store_id`。 |
| verify_store_name | text | confirmed | 核销 POI 名称或映射后的门店名。 |
| verify_time | timestamptz | confirmed | 核销接口 `verify_time`。 |
| relation_type | text | computed | `same_store`、`cross_store`、`unverified`、`unknown`。 |
| is_commissionable | boolean | computed | 已核销且销售门店、核销门店均可识别且不同店。 |
| invoice_status | text | manual | 财务维护，未维护默认 `not_received`。 |
| invoice_received_at | timestamptz | manual | 财务维护。 |
| invoice_approved_at | timestamptz | manual | 财务维护。 |
| refund_status | text | computed | 订单/券退款状态归一化。 |
| refund_amount_cent | integer | confirmed | 订单券或退款接口金额；到券粒度时存在分摊风险。 |
| paid_amount_cent | integer | confirmed | 订单或核销金额，建议优先订单实收。 |
| commission_rate | numeric(6,4) | manual | 来自 SKU 商品类型映射/规则表。 |
| receivable_commission_cent | integer | computed | 跨店核销时销售门店应收参考额。 |
| payable_commission_cent | integer | computed | 跨店核销时核销门店应付参考额。 |
| source_run_id | text | computed | 生成该明细的任务 ID。 |

## 六、汇总表

### agg_store_ranking

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| month | char(7) | computed | 页面 1 建议明确为销售月 `sale_month`。 |
| product_type | text | computed | `all` 或具体产品类型。 |
| store_id | text | computed | 销售归属或核销归属内部店 ID。 |
| store_name | text | computed | 门店名称。 |
| sales_order_count | integer | computed | 按销售归属门店统计，建议按券明细去重订单或按券口径需显式说明。 |
| self_sold_self_verified_count | integer | computed | `relation_type=same_store`。 |
| self_sold_other_verified_count | integer | computed | 本店销售、他店核销。 |
| other_sold_self_verified_count | integer | computed | 他店销售、本店核销。 |
| self_verify_income_cent | integer | computed | 本店核销收入参考额。 |
| effective_commission_income_cent | integer | computed | 本店销售、他店核销的应收分佣参考额。 |

### agg_store_monthly_settlement

| 字段 | 类型建议 | 状态 | 来源/说明 |
| --- | --- | --- | --- |
| month | char(7) | computed | 页面 2 建议明确为核销月 `verify_month`；应收确认另用到票/审核月。 |
| store_id | text | computed | 当前门店 ID。 |
| product_type | text | computed | `all` 或具体产品类型。 |
| current_receivable_commission_cent | integer | computed/manual | 依赖财务到票或审核状态；没有到票数据时只能返回 0 或待确认。 |
| commissionable_total_cent | integer | computed | 本店销售、他店核销的可分佣基础金额，按核销月。 |
| estimated_payable_commission_cent | integer | computed | 他店销售、本店核销的预计分出金额，按核销月。 |
| updated_at | timestamptz | computed | 汇总更新时间。 |

## 七、状态枚举

| 字段 | 枚举 | 状态 | 说明 |
| --- | --- | --- | --- |
| verify_status | `valid`、`cancelled`、`unknown` | computed | 抖音核销 `status=1` 归一为 `valid`，`status=2` 归一为 `cancelled`。 |
| coupon_status | `pending`、`refunding`、`refunded`、`fulfilled`、`unknown` | computed | 由订单券状态 `100/300/301/401` 等归一化。 |
| invoice_status | `not_received`、`received`、`approved`、`rejected` | manual | 财务维护。 |
| refund_status | `none`、`refunding`、`refunded`、`failed`、`cancelled`、`unknown` | computed | 抖音退款状态归一化；`50` 归一为 `refunded`。 |
| relation_type | `same_store`、`cross_store`、`unverified`、`unknown` | computed | 由销售门店和核销门店比较得到。 |
| product_type | `all` 或商品类型名称 | manual/computed | `all` 只用于查询和汇总，不进入明细真实商品类型。 |

## 八、仍需确认的风险

- 退款只能稳定关联到订单，不能稳定关联到券；一单多券且部分退款时，需要补充券粒度退款匹配规则。
- 订单归属人 UID 与职人绑定 UID 的直接匹配覆盖有限，当前结算脚本实际依赖昵称/门店名称等映射策略，需在后续固化优先级。
- 核销接口不返回订单 ID，必须保留订单券展开表，否则无法可靠回溯订单。
- 核销 POI 与内部店的映射需要支持一店多 POI，不能把 `poi_id` 直接当作内部 `store_id`。
- 到票数据和分佣规则仍需财务或运营侧维护，未接入前无法确认“当期应收分佣”的最终财务口径。
