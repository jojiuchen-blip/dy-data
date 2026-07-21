# `clue_allocation_cycle_item` - 分配批次明细

## 业务用途

保存批次内每条主线索的前置条件、执行进度和最终结果，支持大批量分片、断点重试、逐线索对账及失败诊断。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `cycle_item_id` | varchar(64) | NO | - | 批次明细业务 ID |
| `cycle_id` | varchar(64) | NO | - | 批次业务 ID |
| `sequence_no` | integer | NO | - | 批次内稳定顺序 |
| `lead_key` | varchar(64) | NO | - | 主线索业务键 |
| `order_id` | varchar(64) | YES | NULL | 订单编号 |
| `item_status` | smallint | NO | 1 | 1待执行、2运行中、3已分配、4已入总部池、5跳过、6失败 |
| `initial_pool_location` | smallint | NO | 0 | 执行前池位置快照 |
| `rule_binding_id` | varchar(64) | YES | NULL | 使用或新建的规则绑定 ID |
| `decision_id` | varchar(64) | YES | NULL | 最终决策 ID |
| `assignment_round_id` | varchar(64) | YES | NULL | 创建的真实轮次 ID |
| `headquarters_pool_entry_id` | varchar(64) | YES | NULL | 创建的总部池条目 ID |
| `outcome_reason` | varchar(64) | YES | NULL | 结果原因码 |
| `precondition_snapshot` | jsonb | NO | `{}` | 状态版本、锚点和当前轮次前置快照 |
| `attempt_count` | integer | NO | 0 | 执行尝试次数 |
| `started_at` | timestamptz | YES | NULL | 开始处理时间 |
| `completed_at` | timestamptz | YES | NULL | 完成时间 |
| `error_code` | varchar(64) | YES | NULL | 脱敏错误码 |
| `error_detail` | varchar(1000) | YES | NULL | 脱敏错误摘要 |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 更新时间 |

## 索引

- `pk_clue_allocation_cycle_item` (`id`)
- `uk_clue_allocation_cycle_item_item_id` (`cycle_item_id`)
- `uk_clue_allocation_cycle_item_cycle_lead` (`cycle_id`, `lead_key`)
- `uk_clue_allocation_cycle_item_cycle_sequence` (`cycle_id`, `sequence_no`)
- `idx_clue_allocation_cycle_item_status` (`cycle_id`, `item_status`)
- `idx_clue_allocation_cycle_item_lead` (`lead_key`, `gmt_create` DESC)

## 关系与约束

- 正式批次同一主线索只执行一次；重试复用本明细并递增 `attempt_count`。
- 结果 3 必须有 `assignment_round_id`；结果 4 必须有总部池条目；试运行不得填两者。
- 执行前比较主线索 `state_version`，不一致时跳过或重试，避免并发覆盖终态。

## 页面字段映射

- 分配记录批次详情：逐线索状态、原因、决策、轮次/总部池结果。
- 试运行明细：预计命中策略和门店，不产生正式结果 ID。

## 迁移说明

本表新增，用于替代 `clue_allocation_cycles.selected_lead_keys` 大 JSON。历史批次按原列表和决策记录回填可证明的明细。

## 使用接口

- `POST /api/v1/admin/clue-allocation/trial-cycles` — 为每条试运行线索写执行项。
- `POST /api/v1/admin/clue-allocation/rebuild-cycles` — 为试运行重建写新执行项。
- `GET /api/v1/admin/clue-allocation/cycles/{cycle_id}` — 分页读取逐线索状态、原因和结果 ID。
- `POST /api/v1/internal/clue-allocation/formal-cycles` — 按单线索事务记录正式结果与失败重试状态。
- `POST /api/v1/admin/sync/clue-center/rebuilds` — 记录正式重建逐线索结果。
