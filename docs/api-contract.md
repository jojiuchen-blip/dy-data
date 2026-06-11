# API 契约第一轮确认

本文档用于约定前端页面 1、页面 2、页面 3 所需的接口结构。第一轮数据侧确认后，接口字段均可由 `settlement_order_details`、汇总表和人工维护表支持；到票与分佣规则依赖财务/运营维护数据。

当前状态：第一轮数据侧已确认，可开始 FastAPI 数据查询接口设计。

## 一、基本约定

- API 前缀：`/api/v1`
- 时间格式：日期时间使用 ISO 8601 字符串，月份使用 `YYYY-MM`。
- 金额格式：金额字段统一返回人民币分为单位的整数，字段名以 `_cent` 结尾。
- 明细粒度：页面 3 默认一行一券；核销 ID 作为后端追溯字段保留，不作为页面 3 默认明细展示字段。
- 商品筛选：`product_type=all` 表示全部产品，其他值为具体商品类型。
- 月份口径：页面 1 默认使用销售月 `sale_month`；页面 2 默认使用核销月 `verify_month`；到票/审核确认金额使用 `invoice_approved_at` 或 `invoice_received_at` 派生月份。
- 口径说明：页面需要展示的指标口径由 API 返回 `definitions`，前端用于 tooltip 和页面底部说明。
- 分页：明细接口返回 `pagination`，导出接口使用同一组筛选条件。

通用响应结构：

```json
{
  "data": {},
  "definitions": [],
  "meta": {
    "generated_at": "2026-06-11T10:00:00+08:00",
    "source": "mock"
  }
}
```

## 二、页面 1：全国门店销售情况榜单

### GET /api/v1/dashboard/store-ranking

查询参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| month | 是 | 销售月份，格式 `YYYY-MM`。 |
| product_type | 否 | `all` 或具体商品类型，默认 `all`。 |
| limit | 否 | 榜单条数，默认 20。 |

响应字段：

| 字段 | 支持状态 | 说明 |
| --- | --- | --- |
| month | computed | 当前销售月份。 |
| product_type | computed | 当前产品筛选。 |
| rows | computed | 门店排名列表。 |
| rows[].rank | computed | 排名。 |
| rows[].store_id | computed | 内部门店 ID。 |
| rows[].store_name | computed | 门店名称。 |
| rows[].sales_order_count | computed | 销售订单数量，按销售归属门店统计；如后续改为券数需另出字段。 |
| rows[].self_sold_self_verified_count | computed | 本店卖出、本店核销数。 |
| rows[].self_sold_other_verified_count | computed | 本店卖出、他店核销数。 |
| rows[].other_sold_self_verified_count | computed | 他店销售、在本店核销数。 |
| rows[].self_verify_income_cent | computed | 本店核销收入参考额。 |
| rows[].effective_commission_income_cent | computed | 本店销售、他店核销的应收分佣参考额。 |

对应 mock：`mock/page1_store_ranking.json`

## 三、页面 2：单店月度分账看板

### GET /api/v1/stores/{store_id}/monthly-settlement

查询参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| month | 是 | 核销月份，格式 `YYYY-MM`。 |
| product_type | 否 | `all` 或具体商品类型，默认 `all`。 |

响应字段：

| 字段 | 支持状态 | 说明 |
| --- | --- | --- |
| store | computed | 当前门店。 |
| month | computed | 当前核销月份。 |
| product_type | computed | 当前产品筛选。 |
| metrics.current_receivable_commission_cent | computed/manual | 当期应收分佣，依赖到票或审核通过时间；未接入财务数据时为待确认口径。 |
| metrics.commissionable_total_cent | computed | 本店销售、他店核销的可分佣基础金额，按核销月。 |
| metrics.estimated_payable_commission_cent | computed | 他店销售、本店核销的预计分出分佣参考额，按核销月。 |
| tables.receivable_commissions | computed/manual | 应收分佣表，本店卖出、他店核销，含到票字段。 |
| tables.payable_commissions | computed | 应付分佣表，他店卖出、本店核销。 |
| tables.non_commission_orders | computed | 不参与分佣表，本店卖出、本店核销。 |

应收分佣表行字段：

| 字段 | 支持状态 | 说明 |
| --- | --- | --- |
| product_type | computed | 商品类型。 |
| verified_coupon_count | computed | 已核销券数。 |
| paid_amount_cent | confirmed | 订单或券实收金额汇总。 |
| commission_rate | manual | 分佣比例。 |
| commissionable_total_cent | computed | 可分佣总金额。 |
| invoiced_coupon_count | manual | 已到票券数。 |
| current_receivable_commission_cent | computed/manual | 当期应收分佣。 |
| pending_invoice_commission_cent | computed/manual | 未到票待确认分佣。 |

应付分佣表行字段：

| 字段 | 支持状态 | 说明 |
| --- | --- | --- |
| product_type | computed | 商品类型。 |
| verified_coupon_count | computed | 已核销券数。 |
| paid_amount_cent | confirmed | 实收金额汇总。 |
| commission_rate | manual | 分佣比例。 |
| payable_commission_cent | computed | 应付分佣参考额。 |

不参与分佣表行字段：

| 字段 | 支持状态 | 说明 |
| --- | --- | --- |
| product_type | computed | 商品类型。 |
| verified_coupon_count | computed | 已核销券数。 |
| paid_amount_cent | confirmed | 实收金额汇总。 |

对应 mock：

- `mock/page2_store_month_summary.json`
- `mock/page2_commission_tables.json`

## 四、页面 3：门店月度数据明细表

### GET /api/v1/order-details

查询参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| product_type | 否 | `all` 或具体商品类型。 |
| sale_store_id | 否 | 销售归属门店。 |
| exclude_sale_store_id | 否 | 排除某销售归属门店。 |
| sale_month | 否 | 销售月份。 |
| is_verified | 否 | `true` 或 `false`。 |
| verify_store_id | 否 | 实际核销门店。 |
| exclude_verify_store_id | 否 | 排除某实际核销门店。 |
| verify_month | 否 | 核销月份。 |
| relation_type | 否 | `same_store`、`cross_store`、`unverified`、`unknown`。 |
| is_commissionable | 否 | `true` 或 `false`。 |
| invoice_status | 否 | `not_received`、`received`、`approved`、`rejected`。 |
| refund_status | 否 | `none`、`refunding`、`refunded`、`failed`、`cancelled`、`unknown`。 |
| q | 否 | 订单 ID 或券 ID 搜索。 |
| page | 否 | 页码，默认 1。 |
| page_size | 否 | 每页条数，默认 50。 |

响应行字段：

| 字段 | 支持状态 | 说明 |
| --- | --- | --- |
| order_id | confirmed | 订单 ID。 |
| coupon_id | confirmed | 券 ID。 |
| sku_id | confirmed | SKU ID。 |
| owner_account_id | confirmed | 订单归属账号 ID。 |
| owner_account_name | confirmed | 订单归属账号展示名。 |
| product_type | computed | 商品类型，来自 SKU 到商品类型映射表。 |
| sale_store_id | computed | 销售归属门店 ID。 |
| sale_store_name | computed | 销售归属门店名称。 |
| sale_time | confirmed | 销售时间。 |
| is_verified | computed | 是否核销。 |
| verify_store_id | computed | 实际核销门店 ID。 |
| verify_store_name | confirmed | 实际核销门店名称。 |
| verify_time | confirmed | 核销时间。 |
| relation_type | computed | 销售和核销关系。 |
| is_commissionable | computed | 是否分佣；未核销数据为空。 |
| invoice_status | manual | 到票状态。 |
| refund_status | computed | 退款状态。 |
| refund_amount_cent | confirmed | 退款金额；券粒度可能来自推断。 |
| paid_amount_cent | confirmed | 实收金额。 |
| commission_rate | manual | 分佣比例，来自 SKU 商品类型映射/规则表。 |
| receivable_commission_cent | computed | 销售门店预计获得的分佣参考额。 |
| payable_commission_cent | computed | 核销门店预计分出的分佣参考额。 |

对应 mock：`mock/page3_order_detail.csv`

### GET /api/v1/order-details/export

使用与 `GET /api/v1/order-details` 相同的筛选参数，返回当前筛选结果的导出文件。导出文件需要保留筛选条件和生成时间。

## 五、页面跳转筛选约定

页面 2 点击指标后跳转页面 3 时，优先传递底层筛选条件。

| 页面 2 点击位置 | 页面 3 查询参数 |
| --- | --- |
| 当期应收分佣 | `sale_store_id={当前门店}`、`is_verified=true`、`invoice_status=approved`、`exclude_verify_store_id={当前门店}`。 |
| 可分佣总金额 | `sale_store_id={当前门店}`、`is_verified=true`、`relation_type=cross_store`、`verify_month={当前月份}`。 |
| 本店预计分出分佣参考额 | `verify_store_id={当前门店}`、`is_verified=true`、`relation_type=cross_store`、`verify_month={当前月份}`。 |
| 不参与分佣表 | `sale_store_id={当前门店}`、`verify_store_id={当前门店}`、`is_verified=true`、`relation_type=same_store`、`is_commissionable=false`。 |

## 六、当前风险

- `current_receivable_commission_cent` 依赖人工到票/审核数据；接口可以预留字段，但没有财务数据时不能代表最终应收。
- 退款接口缺少稳定券 ID；页面可展示退款状态和金额，但一单多券场景下券粒度归属需标记为推断。
- 门店筛选使用内部 `store_id`，后端需要先完成 POI 到内部店的映射表。
