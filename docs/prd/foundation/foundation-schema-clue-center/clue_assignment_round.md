# `clue_assignment_round` - 真实分配轮次

## 业务用途

记录一次正式分配给具体门店的责任周期。策略步骤无候选或试运行不创建轮次；实际选中门店才创建从 1 连续递增的 `round_no`。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `assignment_round_id` | varchar(64) | NO | - | 轮次业务 ID |
| `lead_key` | varchar(64) | NO | - | 主线索业务键 |
| `order_id` | varchar(64) | NO | - | 订单编号 |
| `round_no` | integer | NO | - | 从 1 连续递增的真实轮次号 |
| `rule_version_id` | varchar(64) | NO | - | 锁定规则版本 |
| `strategy_config_id` | varchar(64) | NO | - | 实际命中的策略配置 |
| `strategy_type` | smallint | NO | - | 1销售店优先、2城市半径优选、3城市兜底 |
| `decision_id` | varchar(64) | NO | - | 创建本轮的正式决策 ID |
| `cycle_id` | varchar(64) | NO | - | 正式分配批次 ID |
| `score_snapshot_run_id` | varchar(64) | YES | NULL | 本轮使用的评分快照批次；销售店优先可空 |
| `assigned_store_id` | varchar(64) | NO | - | 跟进门店 ID |
| `assigned_store_name_snapshot` | varchar(255) | NO | - | 跟进门店名称快照 |
| `assigned_province` | varchar(64) | YES | NULL | 门店省份快照 |
| `assigned_city` | varchar(64) | YES | NULL | 门店城市快照 |
| `assigned_city_code` | varchar(32) | YES | NULL | 门店城市代码快照 |
| `assigned_longitude` | decimal(10,6) | YES | NULL | 分配时门店经度快照 |
| `assigned_latitude` | decimal(10,6) | YES | NULL | 分配时门店纬度快照 |
| `assigned_at` | timestamptz | NO | - | 正式分配时间 |
| `round_status` | smallint | NO | 1 | 1待跟进、2保护期中、10 SLA超期、11保护期到期、12战败、13换店、14核销关闭、15退款关闭、16管理关闭 |
| `latest_follow_action` | smallint | NO | 0 | 0无、1预约、2进一步跟进、3战败、4未联系上、5换店 |
| `latest_follow_at` | timestamptz | YES | NULL | 本轮最近有效跟进时间 |
| `is_followed` | smallint | NO | 0 | 本轮是否产生过任一有效跟进行为 |
| `is_auto_expiry_enabled` | smallint | NO | 1 | 1启用 SLA 自动到期，0表示无限 |
| `first_follow_up_sla_hours` | integer | YES | 24 | 本轮锁定的首次跟进 SLA；无限时为空 |
| `sla_expires_at` | timestamptz | YES | NULL | 未产生跟进时的 SLA 到期点 |
| `protection_days` | integer | NO | 7 | 本轮锁定的保护期天数 |
| `protection_started_at` | timestamptz | YES | NULL | 首次保护动作时间，只写一次 |
| `protection_expires_at` | timestamptz | YES | NULL | 保护期结束时间，只写一次 |
| `ended_at` | timestamptz | YES | NULL | 本轮关闭时间 |
| `end_reason` | varchar(64) | YES | NULL | 关闭原因码，与状态一致 |
| `matured_at` | timestamptz | YES | NULL | 门店评分可比较成熟时间 |
| `verified_store_id` | varchar(64) | YES | NULL | 核销门店 ID 快照 |
| `verified_store_name_snapshot` | varchar(255) | YES | NULL | 核销门店名称快照 |
| `verified_at` | timestamptz | YES | NULL | 首次核销时间 |
| `is_self_store_verified` | smallint | NO | 0 | 跟进门店是否为核销门店 |
| `state_version` | integer | NO | 1 | 轮次迁移乐观锁版本 |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 更新时间 |

## 索引

- `pk_clue_assignment_round` (`id`)
- `uk_clue_assignment_round_round_id` (`assignment_round_id`)
- `uk_clue_assignment_round_lead_round_no` (`lead_key`, `round_no`)
- `uk_clue_assignment_round_decision_id` (`decision_id`)
- `uk_clue_assignment_round_active_lead` (`lead_key`) WHERE `round_status IN (1,2)`
- `idx_clue_assignment_round_order` (`order_id`, `round_no`)
- `idx_clue_assignment_round_store_status` (`assigned_store_id`, `round_status`, `assigned_at` DESC)
- `idx_clue_assignment_round_rule` (`rule_version_id`, `strategy_type`)
- `idx_clue_assignment_round_cycle` (`cycle_id`)
- `idx_clue_assignment_round_expiry` (`round_status`, `sla_expires_at`, `protection_expires_at`)
- `idx_clue_assignment_round_score_run` (`score_snapshot_run_id`)

## 状态与并发约束

- 状态 1/2 为活动态，其余为关闭态；一个 `lead_key` 最多一条活动记录。
- 预约、进一步跟进、未联系上均将状态从 1 迁移到 2；后续动作不重置保护期。
- 战败和换店即时迁移到 12/13，并触发下一启用策略；SLA 只处理状态 1，保护期任务只处理状态 2。
- 核销/退款事件可从任意活动态迁移到 14/15，并优先于同时到达的其他动作。
- 新轮次创建必须在同一事务中关闭旧轮、排除所有历史门店并更新主线索当前轮次。

## 页面字段映射

- 明细：线索状态、分配轮次、本轮跟进时间、本轮失效时间。
- 详情：`第N轮 · 策略名称`、分配时间、跟进门店、再分配原因、失效时间、最近结果。
- 门店指标：线索跟进率、24 小时有效跟进率和门店核销转化能力的轮次分母。

## 迁移说明

由 `clue_assignment_rounds` 迁移时只保留新引擎正式轮次。删除 `execution_mode` 和全部 `legacy` 轮次；文本主键改为数字主键并保留唯一业务 ID；数据库外键改为逻辑引用。历史重复轮次不直接搬迁，须按新决策账本对账或重建。

## 使用接口

Phase 4 回填，覆盖列表、详情、跟进保存和内部状态迁移。
