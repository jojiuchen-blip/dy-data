# `clue_headquarters_pool_entry` - 总部池条目

## 业务用途

保存活跃线索进入总部池及离开总部池的历史。总部池没有责任门店，不进入门店指标；V1 只读，不实现再次投放。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `headquarters_pool_entry_id` | varchar(64) | NO | - | 总部池条目业务 ID |
| `lead_key` | varchar(64) | NO | - | 主线索业务键 |
| `order_id` | varchar(64) | YES | NULL | 订单编号 |
| `entry_status` | smallint | NO | 1 | 1活动、2关闭 |
| `reason_code` | smallint | NO | - | 1缺锚点、2锚点未映射、3地理无效、4无规则、5无候选、6策略耗尽、7分配失败 |
| `reason_detail` | varchar(1000) | YES | NULL | 用户可读且脱敏的原因说明 |
| `entered_at` | timestamptz | NO | CURRENT_TIMESTAMP | 入池时间 |
| `closed_at` | timestamptz | YES | NULL | 关闭时间 |
| `close_reason` | varchar(64) | YES | NULL | 终态、重建纠正等关闭原因 |
| `source_assignment_round_id` | varchar(64) | YES | NULL | 入池前最后轮次 ID |
| `source_decision_id` | varchar(64) | YES | NULL | 触发入池的决策 ID |
| `source_rule_version_id` | varchar(64) | YES | NULL | 使用的规则版本 ID |
| `cycle_id` | varchar(64) | YES | NULL | 分配批次 ID |
| `anchor_poi_id` | varchar(64) | YES | NULL | 入池时锚点 POI |
| `anchor_store_id` | varchar(64) | YES | NULL | 入池时锚点门店 |
| `anchor_city` | varchar(64) | YES | NULL | 入池时锚点城市 |
| `anchor_city_code` | varchar(32) | YES | NULL | 入池时城市代码 |
| `anchor_geo_snapshot` | jsonb | NO | `{}` | 锚点地理和映射版本证据 |
| `source_snapshot` | jsonb | NO | `{}` | 规则、策略和候选汇总证据 |
| `entered_by_event_key` | varchar(128) | NO | - | 入池幂等事件键 |
| `closed_by_event_key` | varchar(128) | YES | NULL | 关闭幂等事件键 |
| `state_version` | integer | NO | 1 | 条目状态乐观锁版本 |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 更新时间 |

## 索引

- `pk_clue_headquarters_pool_entry` (`id`)
- `uk_clue_headquarters_pool_entry_entry_id` (`headquarters_pool_entry_id`)
- `uk_clue_headquarters_pool_entry_enter_event` (`entered_by_event_key`)
- `uk_clue_headquarters_pool_entry_active_lead` (`lead_key`) WHERE `entry_status=1`
- `idx_clue_headquarters_pool_entry_status_time` (`entry_status`, `entered_at` DESC)
- `idx_clue_headquarters_pool_entry_reason` (`reason_code`, `entered_at` DESC)
- `idx_clue_headquarters_pool_entry_order` (`order_id`)
- `idx_clue_headquarters_pool_entry_city` (`anchor_city_code`, `entry_status`)

## 关系与约束

- 同一主线索最多一个活动条目；入池时主线索 `pool_location=3` 且无活动轮次。
- 订单核销/退款后关闭活动条目并将主线索转为关闭；V1 不因人工查看或筛选改变条目。
- 总部池线索计入完整主池和总部库存，但不计任何门店线索数、跟进率或核销转化分母。

## 页面字段映射

- 总部池：状态、原因、订单状态、锚点城市、入池时间和来源证据。
- 门店账号不得查看总部池；普通管理员按权限只读。

## 迁移说明

由 `clue_headquarters_pool_entries` 迁移，统一原因枚举并补地理/来源快照和幂等事件键。

## 使用接口

- `GET /api/v1/clues/overview` — 总部范围聚合当前总部池库存。
- `GET /api/v1/clues/orders/{order_id}` — 管理范围内展示池位置和来源轮次摘要。
- `GET /api/v1/admin/clue-allocation/headquarters-pool` — 分页查询库存、原因和来源证据；V1 页面只读。
- `POST /api/v1/internal/clue-center/order-status-transitions` — 订单核销/退款时关闭活动条目。
- `POST /api/v1/internal/clue-allocation/formal-cycles` — 锚点异常、无规则、无候选或策略耗尽时幂等入池。
- `POST /api/v1/internal/clue-allocation/round-expirations` — 最后策略结束后写入总部池待办结果。
- `POST /api/v1/admin/sync/clue-center/rebuilds` — 按事实重建条目和来源证据。
- 不提供再次投放、领取或人工分配写接口。
