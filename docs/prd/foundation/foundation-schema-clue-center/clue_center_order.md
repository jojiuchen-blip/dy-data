# `clue_center_order` - 线索中心订单投影

## 业务用途

提供订单粒度的低延迟查询投影，支持线索看板、明细、详情和导出。所有字段均可从事实表及分配账本重建，不作为状态迁移或权限判断的唯一依据。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `order_id` | varchar(64) | NO | - | 订单编号 |
| `lead_key` | varchar(64) | NO | - | 主线索业务键 |
| `canonical_clue_id` | varchar(64) | YES | NULL | 代表性平台线索 ID |
| `source_clue_count` | integer | NO | 0 | 关联原始线索行数 |
| `normalized_order_status` | smallint | NO | 0 | 0未知、1可促核销、2已核销、3已退款 |
| `store_display_status` | smallint | YES | NULL | 1待跟进、2已跟进、3超期失效、4主动战败、5已核销、6已退款 |
| `pool_location` | smallint | NO | 0 | 0无、1待分配、2门店池、3总部池、4关闭 |
| `current_assignment_round_id` | varchar(64) | YES | NULL | 当前活动轮次业务 ID |
| `current_round_no` | integer | YES | NULL | 当前真实轮次号 |
| `current_round_status` | smallint | YES | NULL | 当前轮次状态快照 |
| `assigned_at` | timestamptz | YES | NULL | 当前轮分配时间 |
| `assigned_store_id` | varchar(64) | YES | NULL | 当前责任门店 ID |
| `assigned_store_name` | varchar(255) | YES | NULL | 当前责任门店名称快照 |
| `assigned_city` | varchar(64) | YES | NULL | 当前责任门店城市 |
| `assigned_province` | varchar(64) | YES | NULL | 当前责任门店省份 |
| `phone_masked` | varchar(32) | NO | - | 默认展示脱敏手机号 |
| `product_id` | varchar(64) | YES | NULL | 商品/SKU ID |
| `product_name` | text | YES | NULL | 完整商品名称 |
| `product_type` | varchar(128) | YES | NULL | 商品分类 |
| `author_nickname` | varchar(255) | YES | NULL | 内容作者昵称 |
| `order_created_at` | timestamptz | YES | NULL | 用户下单时间 |
| `clue_created_at` | timestamptz | YES | NULL | 线索生成时间 |
| `latest_follow_action` | smallint | NO | 0 | 0无、1预约、2继续、3战败、4未联系上、5换店 |
| `latest_follow_at` | timestamptz | YES | NULL | 当前轮最近跟进时间 |
| `latest_follow_note_excerpt` | varchar(255) | YES | NULL | 当前轮最近备注摘要 |
| `round_expires_at` | timestamptz | YES | NULL | 当前轮 SLA/保护期最近到期时间 |
| `verified_store_id` | varchar(64) | YES | NULL | 核销门店 ID |
| `verified_store_name` | varchar(255) | YES | NULL | 核销门店名称快照 |
| `verified_at` | timestamptz | YES | NULL | 首次核销时间 |
| `is_self_store_verified` | smallint | NO | 0 | 当前责任门店是否为核销门店 |
| `projection_version` | integer | NO | 1 | 投影结构版本 |
| `source_state_version` | integer | NO | 1 | 对应主线索状态版本 |
| `refreshed_at` | timestamptz | NO | CURRENT_TIMESTAMP | 最近重建时间 |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 更新时间 |

## 索引

- `pk_clue_center_order` (`id`)
- `uk_clue_center_order_order_id` (`order_id`)
- `uk_clue_center_order_lead_key` (`lead_key`)
- `idx_clue_center_order_store_status` (`assigned_store_id`, `store_display_status`, `clue_created_at` DESC)
- `idx_clue_center_order_region` (`assigned_province`, `assigned_city`)
- `idx_clue_center_order_product_type` (`product_type`)
- `idx_clue_center_order_clue_created` (`clue_created_at` DESC)
- `idx_clue_center_order_order_created` (`order_created_at` DESC)
- `idx_clue_center_order_pool_status` (`pool_location`, `normalized_order_status`)

## 关系与约束

- 每个完整主池订单一条投影；缺订单隔离线索不生成本表记录。
- `phone_masked` 可保存，`phone_plain` 禁止存在。
- 店端状态由订单终态、当前/历史轮次状态按固定优先级派生，不允许页面自行拼装事实。
- 投影与事实不一致时，以事实表和账本为准，任务应重建本行并记录数据质量问题。

## 页面字段映射

- 看板筛选：省、市、门店、线索生成日期、线索状态、商品类型。
- 明细：联系方式、线索状态、分配轮次、本轮跟进时间、商品、生成和失效时间。
- 详情：订单号、订单状态、下单时间、商品、核销状态及当前摘要。
- 导出：按账号数据范围和当前筛选导出全量匹配结果；明文号码另行授权读取。

## 迁移说明

由 `clue_center_orders` 重建。删除明文手机号、重复的事实状态和旧引擎归属语义；保留页面需要的快照与投影版本。旧投影不直接逐行继承，按新事实表全量重建。

## 使用接口

- `GET /api/v1/clues/filters` — 读取组织、商品和店端状态候选。
- `GET /api/v1/clues/overview` — 聚合当前筛选摘要。
- `GET /api/v1/clues/assignment-rounds` — 分页读取线索明细投影。
- `GET /api/v1/clues/orders/{order_id}` — 读取订单、商品、脱敏联系方式和当前摘要。
- `POST /api/v1/clues/assignment-round-exports` — 按账号范围与筛选导出投影。
- `POST /api/v1/internal/clue-center/materializations` — 原始证据变化后刷新投影。
- `POST /api/v1/internal/clue-center/order-status-transitions` — 终态迁移后刷新投影。
- `POST /api/v1/internal/clue-allocation/metric-refreshes` — 批量重算查询投影。
- `POST /api/v1/admin/sync/clue-center/rebuilds` — 从事实表全量重建，禁止客户端直接写投影。
