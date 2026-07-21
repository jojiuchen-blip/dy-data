# `clue_master_lead` - 线索主记录

## 业务用途

保存线索中心唯一主线索、订单生命周期、当前池位置和位置锚点。它是状态迁移的聚合根，不保存候选列表、跟进明细或明文手机号。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `lead_key` | varchar(64) | NO | - | 内部稳定业务键 |
| `master_kind` | smallint | NO | 1 | 1订单主线索、2缺订单源记录隔离线索 |
| `canonical_clue_id` | varchar(64) | YES | NULL | 代表性平台线索 ID |
| `order_id` | varchar(64) | YES | NULL | 经营统计唯一订单键 |
| `raw_order_status` | varchar(128) | YES | NULL | 最近一次平台原始订单状态 |
| `normalized_order_status` | smallint | NO | 0 | 0未知、1可促核销、2已核销、3已退款 |
| `status_source` | smallint | NO | 1 | 1线索、2订单、3核销、4退款 |
| `order_status_observed_at` | timestamptz | YES | NULL | 当前订单状态证据时间 |
| `lifecycle_status` | smallint | NO | 1 | 0源记录隔离、1活跃、2核销关闭、3退款关闭 |
| `pool_location` | smallint | NO | 0 | 0无、1待分配、2门店跟进池、3总部池、4关闭 |
| `current_assignment_round_id` | varchar(64) | YES | NULL | 当前活动轮次业务 ID |
| `current_cycle_id` | varchar(64) | YES | NULL | 最近正式分配批次业务 ID |
| `is_ended_without_assignment` | smallint | NO | 0 | 1表示首次已终态或从未形成轮次即关闭 |
| `closed_at` | timestamptz | YES | NULL | 生命周期关闭时间 |
| `closed_reason` | varchar(64) | YES | NULL | 标准关闭原因码 |
| `first_seen_at` | timestamptz | NO | - | 首条源记录时间 |
| `last_seen_at` | timestamptz | NO | - | 最近源记录时间 |
| `anchor_poi_id` | varchar(64) | YES | NULL | 唯一允许的 `follow_poi_id` 锚点 |
| `anchor_store_id` | varchar(64) | YES | NULL | POI 映射后的内部门店 ID |
| `anchor_source` | smallint | YES | NULL | 1仅 `follow_poi_id`；不允许其他 POI 回退 |
| `anchor_mapping_status` | smallint | NO | 0 | 0待解析、1有效、2缺失、3未映射、4地理无效 |
| `anchor_unavailable_reason` | varchar(64) | YES | NULL | 锚点不可用标准原因码 |
| `anchor_province` | varchar(64) | YES | NULL | 锚点省份快照 |
| `anchor_city` | varchar(64) | YES | NULL | 锚点城市快照 |
| `anchor_city_code` | varchar(32) | YES | NULL | 锚点城市代码 |
| `anchor_longitude` | decimal(10,6) | YES | NULL | 锚点经度 |
| `anchor_latitude` | decimal(10,6) | YES | NULL | 锚点纬度 |
| `sales_store_id` | varchar(64) | YES | NULL | 订单关联销售店，用于销售店优先策略 |
| `sales_store_name_snapshot` | varchar(255) | YES | NULL | 销售店名称快照 |
| `is_complete_pool` | smallint | NO | 0 | 1表示非空订单已进入完整主池指标分母 |
| `state_version` | integer | NO | 1 | 状态迁移乐观锁版本 |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 更新时间 |

## 索引

- `pk_clue_master_lead` (`id`)
- `uk_clue_master_lead_lead_key` (`lead_key`)
- `uk_clue_master_lead_order_id` (`order_id`) WHERE `order_id IS NOT NULL`
- `idx_clue_master_lead_lifecycle_pool` (`lifecycle_status`, `pool_location`)
- `idx_clue_master_lead_anchor_store` (`anchor_store_id`)
- `idx_clue_master_lead_anchor_city` (`anchor_city_code`, `pool_location`)
- `idx_clue_master_lead_current_round` (`current_assignment_round_id`)
- `idx_clue_master_lead_last_seen` (`last_seen_at` DESC)

## 关系与约束

- 一条主线索拥有多条源记录映射、状态事件、真实轮次和总部池历史。
- `master_kind=2` 时 `order_id IS NULL`、`is_complete_pool=0`、`pool_location=0`，且不得创建轮次。
- `normalized_order_status IN (2,3)` 时 `lifecycle_status IN (2,3)`、`pool_location=4`，不得存在活动轮次或活动总部池条目。
- `pool_location=2` 时必须存在 `current_assignment_round_id`；`pool_location=3` 时该字段必须为空。
- `anchor_mapping_status` 非 1 的活跃订单不得进入正式候选计算，应进入总部池并保留原因。

## 页面字段映射

- 看板：完整主池、门店池、总部池和关闭库存的底层范围。
- 明细/详情：订单终态、当前池位置、当前轮次和锚点城市。
- 分配后台：待分配线索、锚点、销售店和当前正式批次。

## 迁移说明

由 `clue_master_leads` 迁移。`source_clue_row_key`、`source_identity_key` 拆到 `clue_source_record_link`；删除与池位置重复的 `allocation_state`；文本主键改为数字主键并保留唯一 `lead_key`。旧引擎产生的主线索状态不作为正式轮次证据，按原始事实重建。

## 使用接口

Phase 4 回填。业务接口不得直接允许任意修改本表状态。
