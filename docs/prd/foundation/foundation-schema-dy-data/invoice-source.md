# 发票可信来源与号码归属（既有结构回捞）

> 所属索引：[Schema](../foundation-schema-dy-data.md) · [发票 API](../foundation-api-dy-data/billing-invoice.md#42-post-apiv1promotion-invoices)
> 依据：`apps/api/dy_api/models.py` 的 PromotionInvoice/Allocation/NumberRegistry/ReplacementSource/LifecycleEvent，及 `apps/api/dy_api/routes/dashboard.py`。本次仅同步现有合同，不新增发票业务规则。

## 1 金额与版本来源

`promotion_invoice` 在既有字段外的实际字段如下；默认值指应用默认，不伪称数据库 server default。

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
|---|---|---|---|
| physical_invoice_id | varchar(128) | NO | 实体票 ID，应用生成，状态版本沿用 |
| version_kind | integer | NO | 应用默认 1；区分登记/状态等版本 |
| is_tombstone | boolean | NO | 应用默认 false，撤销结果不等于删除 |
| replaces_invoice_id | varchar(128) | YES | 原发票来源；不等于 supersedes 直接版本链 |
| buyer_name | varchar(255) | NO | 服务端可信购方名称 |
| tax_rate_percent | integer | NO | CHECK=6，服务端确定 |
| filler_phone_ciphertext | text | YES | 填报手机加密存储，旧行允许 NULL |
| net_amount_cent | bigint | YES | 不含税金额；旧行可空，新登记服务端生成 |
| tax_amount_cent | bigint | YES | 税额；旧行可空，新登记服务端生成 |

net/tax 非负，必须同时为空或同时有值且与总额闭合（数据库误差上限 1 分）；新登记算法按合票总额一次取整：`net=(gross*100+53)//106`，`tax=gross-net`。不按分配行分别取整，不以客户端税额/总额为权威。

`promotion_invoice_allocation.settlement_batch_month varchar(7) NOT NULL` 是实际结算分组来源；`allocated_amount_cent` 为有符号 bigint，负账期抵扣必须保留，不能沿用旧文档“每行非负”的假设。当前全部可开票组的正负账期必须整体登记；总额必须为正。组 ID 由可信账单/确认/抵扣投影派生，不为此新增数据库列。

## 2 `promotion_invoice_number_registry`

| 字段 | PostgreSQL 类型 | 可空 | 约束 |
|---|---|---|---|
| id | bigint identity | NO | PK |
| invoice_number | varchar(20) | NO | UK uk_promotion_invoice_number_registry_number |
| physical_invoice_id | varchar(128) | NO | UK uk_promotion_invoice_number_registry_physical |
| first_invoice_id | varchar(128) | NO | 首次登记版本 |
| store_id | varchar(128) | NO | 归属门店 |
| registered_at | timestamptz | NO | 应用 UTC 时间 |

20 位 ASCII 数字按文本保留前导零。新登记、替换、管理费更正/导入均在号码锁内校验跨方向归属；推广费当前版本部分唯一不代表旧票号可被另一张实体票抢占。状态版本沿用同实体票，保留号码历史。

## 3 `promotion_invoice_replacement_source`

| 字段 | PostgreSQL 类型 | 可空 | 约束 |
|---|---|---|---|
| id | bigint identity | NO | PK |
| replacement_invoice_id | varchar(128) | NO | 替换发票；普通索引 |
| source_invoice_id | varchar(128) | NO | UK；每个来源只可被替换一次 |
| source_physical_invoice_id | varchar(128) | NO | 原实体票 |
| linked_at | timestamptz | NO | 应用 UTC 时间 |

另有 `(replacement_invoice_id,source_invoice_id)` 唯一约束。它记录已有替换来源链，不授予缺证据修复或跨门店合票权。

## 4 `promotion_invoice_lifecycle_event`

| 字段 | PostgreSQL 类型 | 可空 | 约束 |
|---|---|---|---|
| id | bigint identity | NO | PK |
| lifecycle_event_id | varchar(128) | NO | UK |
| physical_invoice_id | varchar(128) | NO | is_current=true 时部分唯一 |
| invoice_id | varchar(128) | NO | 普通索引 |
| invoice_version | integer | NO | 事件引用版本 |
| event_type | integer | NO | CHECK IN(1,2)，已有系统外红冲/作废事实 |
| reason | varchar(1000) | NO | 已有原因记录 |
| read_version | integer | NO | CHECK >0 |
| is_current | boolean | NO | 应用默认 true |
| operator_id | varchar(128) | NO | 操作人 |
| idempotency_key_hash | varchar(64) | NO | UK |
| request_payload_sha256 | varchar(64) | NO | 同键异参校验 |
| occurred_at | timestamptz | NO | 应用 UTC 时间 |
| gmt_create | timestamptz | NO | 应用 UTC 时间 |

此处仅引用现有模型消除早期“完全没有原发票/生命周期来源”的冲突，不改变其操作权限和状态机，也不将导入撤销等同于系统执行红冲或真实作废。
