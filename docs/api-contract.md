# API 契约 v1（生产 MVP）

本文档约定生产 MVP 的前后端接口。当前版本面向可上线部署，数据来自 PostgreSQL 中的订单、券、核销、抖音号/职人绑定、门店/POI 映射、SKU 分佣规则和结算汇总表。

当前状态：v1 契约已按“发票不上线、退款不展示、预计应收分佣”口径调整，可作为 FastAPI 实现依据。

## 一、基本约定

- API 前缀：`/api/v1`
- 鉴权：除登录接口外，所有接口都需要单管理员登录态。
- 时间格式：日期时间使用 ISO 8601 字符串，月份使用 `YYYY-MM`。
- 金额格式：金额字段统一返回人民币分为单位的整数，字段名以 `_cent` 结尾。
- 明细粒度：页面 3 默认一行一券；核销 ID 仅作为后端追溯字段，不作为页面 3 查询或展示字段。
- 商品筛选：`product_type=all` 表示全部产品，其他值为具体商品类型。
- 月份口径：页面 1 默认销售月；页面 2 默认核销月；页面 3 的 `sale_month`、`verify_month` 由 `sale_time`、`verify_time` 派生过滤。
- 口径说明：页面需要展示的指标口径由 API 返回 `definitions`，前端用于 tooltip 和页面说明。
- 分页：明细接口返回 `pagination`，导出接口使用同一组筛选条件。

通用响应结构：

```json
{
  "data": {},
  "definitions": [],
  "meta": {
    "generated_at": "2026-06-12T10:00:00+08:00",
    "source": "postgres"
  }
}
```

分页结构：

```json
{
  "page": 1,
  "page_size": 50,
  "total": 120,
  "total_pages": 3
}
```

## 二、认证接口

### POST /api/v1/auth/login

请求字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| username | 是 | 管理员账号。 |
| password | 是 | 管理员密码。 |

成功后写入 HTTP-only session cookie。

### GET /api/v1/auth/me

返回当前登录用户：

```json
{
  "data": {
    "username": "admin"
  },
  "meta": {
    "generated_at": "2026-06-12T10:00:00+08:00",
    "source": "session"
  }
}
```

### POST /api/v1/auth/logout

清除当前 session cookie。

## 三、筛选元数据

### GET /api/v1/meta/filters

用于前端初始化门店、商品类型、月份等选项，避免从分页明细中反推。

响应字段：

| 字段 | 支持状态 | 说明 |
| --- | --- | --- |
| stores | computed | 可筛选门店列表。 |
| stores[].store_id | computed/manual | 内部门店 ID。 |
| stores[].store_name | computed/manual | 门店展示名。 |
| product_types | computed | 商品类型列表，包含 `all`。 |
| sale_months | computed | 可选销售月份。 |
| verify_months | computed | 可选核销月份。 |
| latest_job | computed | 最近一次结算任务状态。 |

## 四、页面 1：全国门店销售情况榜单

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
| limit | computed | 返回条数上限。 |
| rows | computed | 门店排名列表。 |
| rows[].rank | computed | 排名。 |
| rows[].store_id | computed | 内部门店 ID。 |
| rows[].store_name | computed | 门店名称。 |
| rows[].sales_order_count | computed | 销售订单数量，按销售归属门店去重订单统计。 |
| rows[].self_sold_self_verified_count | computed | 本店卖出、本店核销券数。 |
| rows[].self_sold_other_verified_count | computed | 本店卖出、他店核销券数。 |
| rows[].other_sold_self_verified_count | computed | 他店销售、在本店核销券数。 |
| rows[].self_verify_income_cent | computed | 本店核销收入参考额。 |
| rows[].effective_commission_income_cent | computed | 本店销售、他店核销的预计应收分佣。 |

## 五、页面 2：单店月度分账看板

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
| metrics.estimated_receivable_commission_cent | computed | 预计应收分佣：本店销售、他店核销、按分佣比例测算的应收分佣。 |
| metrics.commissionable_total_cent | computed | 本店销售、他店核销的可分佣基础金额，按核销月。 |
| metrics.estimated_payable_commission_cent | computed | 他店销售、本店核销的预计分出分佣参考额，按核销月。 |
| tables.receivable_commissions | computed | 预计应收分佣表，本店卖出、他店核销。 |
| tables.payable_commissions | computed | 预计应付分佣表，他店卖出、本店核销。 |
| tables.non_commission_orders | computed | 不参与分佣表，本店卖出、本店核销。 |

预计应收分佣表行字段：

| 字段 | 支持状态 | 说明 |
| --- | --- | --- |
| product_type | computed | 商品类型。 |
| verified_coupon_count | computed | 已核销券数。 |
| paid_amount_cent | confirmed | 订单或券实收金额汇总。 |
| commission_rate | manual | 分佣比例。 |
| commissionable_total_cent | computed | 可分佣基础金额。 |
| estimated_receivable_commission_cent | computed | 预计应收分佣。 |

预计应付分佣表行字段：

| 字段 | 支持状态 | 说明 |
| --- | --- | --- |
| product_type | computed | 商品类型。 |
| verified_coupon_count | computed | 已核销券数。 |
| paid_amount_cent | confirmed | 实收金额汇总。 |
| commission_rate | manual | 分佣比例。 |
| payable_commission_cent | computed | 预计应付分佣参考额。 |

不参与分佣表行字段：

| 字段 | 支持状态 | 说明 |
| --- | --- | --- |
| product_type | computed | 商品类型。 |
| verified_coupon_count | computed | 已核销券数。 |
| paid_amount_cent | confirmed | 实收金额汇总。 |

## 六、页面 3：门店月度数据明细表

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
| q | 否 | 订单 ID 或券 ID 搜索。 |
| page | 否 | 页码，默认 1。 |
| page_size | 否 | 每页条数，默认 50，最大 500。 |

响应字段：

| 字段 | 支持状态 | 说明 |
| --- | --- | --- |
| rows | computed | 明细行。 |
| pagination | computed | 分页信息。 |

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
| verify_store_id | computed | 实际核销门店 ID，未核销时为空。 |
| verify_store_name | computed | 实际核销门店名称，未核销时为空。 |
| verify_time | confirmed | 核销时间，未核销时为空。 |
| relation_type | computed | 销售和核销关系。 |
| is_commissionable | computed | 是否分佣；未核销数据为空。 |
| paid_amount_cent | confirmed | 实收金额。 |
| commission_rate | manual | 分佣比例，来自 SKU 商品类型映射/规则表。 |
| receivable_commission_cent | computed | 销售门店预计获得的分佣参考额。 |
| payable_commission_cent | computed | 核销门店预计分出的分佣参考额。 |

### GET /api/v1/order-details/export

使用与 `GET /api/v1/order-details` 相同的筛选参数，返回当前筛选结果的 CSV 文件。导出文件需要保留筛选条件和生成时间。

## 七、任务状态

### GET /api/v1/jobs/recent

查询参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| limit | 否 | 最近任务条数，默认 20。 |

响应字段：

| 字段 | 支持状态 | 说明 |
| --- | --- | --- |
| rows[].job_id | computed | 任务 ID。 |
| rows[].job_name | computed | 任务名称。 |
| rows[].status | computed | `running`、`success`、`failed`。 |
| rows[].started_at | computed | 开始时间。 |
| rows[].finished_at | computed | 结束时间。 |
| rows[].success_count | computed | 成功行数。 |
| rows[].failed_count | computed | 失败行数。 |
| rows[].error_message | computed | 失败信息，禁止包含密钥、cookie、真实文件路径。 |

## 八、页面跳转筛选约定

页面 2 点击指标后跳转页面 3 时，优先传递底层筛选条件。

| 页面 2 点击位置 | 页面 3 查询参数 |
| --- | --- |
| 预计应收分佣 | `sale_store_id={当前门店}`、`is_verified=true`、`relation_type=cross_store`、`verify_month={当前月份}`。 |
| 可分佣总金额 | `sale_store_id={当前门店}`、`is_verified=true`、`relation_type=cross_store`、`verify_month={当前月份}`。 |
| 本店预计分出分佣参考额 | `verify_store_id={当前门店}`、`is_verified=true`、`relation_type=cross_store`、`verify_month={当前月份}`。 |
| 不参与分佣表 | `sale_store_id={当前门店}`、`verify_store_id={当前门店}`、`is_verified=true`、`relation_type=same_store`、`is_commissionable=false`。 |

## 九、Deferred / Risk

- 发票、到票、OCR、财务审核和正式应收确认不进入 v1。旧字段 `invoice_status`、`invoiced_coupon_count`、`pending_invoice_commission_cent`、`current_receivable_commission_cent` 仅作为 v2 风险和兼容迁移说明，不进入 v1 API。
- 退款接口不进入 v1。旧展示字段 `refund_status`、`refund_amount_cent` 不进入 v1 API；订单/券退款状态只用于后台分账排除和异常检查。
- 若后续接入退款接口，退款只能稳定关联到订单，不能稳定关联到券；一单多券且部分退款时，需要补充券粒度退款归因规则。
- 门店筛选使用内部 `store_id`，后端必须完成 POI 到内部店的映射表。
- 销售归属门店按订单归属人 UID 优先匹配，未命中时用昵称补充；两者均未命中的订单必须进入异常清单，不能静默归错门店。
