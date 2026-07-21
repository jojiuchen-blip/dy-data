# `clue_allocation_decision` - 分配决策

## 业务用途

以追加记录保存一次策略步骤的决策摘要，解释使用哪个规则版本、为什么跳过、比较了多少候选、选中哪个门店以及是否创建真实轮次。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `decision_id` | varchar(64) | NO | - | 决策业务 ID |
| `decision_key` | varchar(160) | NO | - | 批次+线索+策略的幂等键 |
| `cycle_id` | varchar(64) | NO | - | 分配批次业务 ID |
| `cycle_item_id` | varchar(64) | NO | - | 批次明细业务 ID |
| `dataset_kind` | smallint | NO | - | 1试运行、2正式、3重建 |
| `lead_key` | varchar(64) | NO | - | 主线索业务键 |
| `order_id` | varchar(64) | YES | NULL | 订单编号 |
| `rule_version_id` | varchar(64) | YES | NULL | 实际使用的发布版本 |
| `scope_type` | smallint | YES | NULL | 1全局、2城市、3门店组、4锚点门店 |
| `scope_key` | varchar(128) | YES | NULL | 实际命中范围键 |
| `strategy_config_id` | varchar(64) | YES | NULL | 策略配置业务 ID |
| `strategy_type` | smallint | YES | NULL | 1销售店优先、2城市半径优选、3城市兜底 |
| `execution_order` | integer | YES | NULL | 规则版本内策略顺序 |
| `decision_status` | smallint | NO | - | 1已选中、2策略跳过、3无候选、4进入总部池、5失败 |
| `selected_store_id` | varchar(64) | YES | NULL | 最终选中门店 ID |
| `selected_store_name_snapshot` | varchar(255) | YES | NULL | 选中门店名称快照 |
| `selected_composite_score` | decimal(12,6) | YES | NULL | 选中门店综合评分 |
| `selected_distance_km` | decimal(10,3) | YES | NULL | 选中门店距锚点距离 |
| `candidate_count` | integer | NO | 0 | 全部候选数 |
| `eligible_candidate_count` | integer | NO | 0 | 通过资格候选数 |
| `assignment_round_id` | varchar(64) | YES | NULL | 正式选中后创建的轮次 ID |
| `reason_code` | varchar(64) | YES | NULL | 跳过、无候选或失败原因码 |
| `reason_detail` | varchar(1000) | YES | NULL | 脱敏原因摘要 |
| `context_snapshot` | jsonb | NO | `{}` | 锚点、状态版本和排序定义摘要 |
| `actor` | varchar(64) | YES | NULL | 自动任务或用户标识 |
| `executed_at` | timestamptz | NO | CURRENT_TIMESTAMP | 决策时间 |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 仅兼容必备字段，决策内容禁止更新 |

## 索引

- `pk_clue_allocation_decision` (`id`)
- `uk_clue_allocation_decision_decision_id` (`decision_id`)
- `uk_clue_allocation_decision_decision_key` (`decision_key`)
- `idx_clue_allocation_decision_cycle_item` (`cycle_id`, `cycle_item_id`)
- `idx_clue_allocation_decision_lead` (`lead_key`, `executed_at` DESC)
- `idx_clue_allocation_decision_rule_strategy` (`rule_version_id`, `strategy_type`)
- `idx_clue_allocation_decision_store` (`selected_store_id`, `executed_at` DESC)
- `idx_clue_allocation_decision_status` (`dataset_kind`, `decision_status`, `executed_at` DESC)

## 关系与约束

- 每个启用策略步骤一条决策；无候选和跳过也留记录但不创建轮次。
- `dataset_kind=1` 时 `assignment_round_id` 必须为空；正式/重建只有状态 1 可创建轮次。
- 候选详情必须存在于 `clue_allocation_candidate`，不能只塞在 `context_snapshot`。
- 决策和候选完成后不可更新；更正通过新批次和新决策表达。

## 页面字段映射

- 分配记录：规则版本、作用范围、策略、结果、门店、评分、距离和原因。
- 详情轮次标题：从创建轮次的策略配置生成真实策略名。

## 迁移说明

由 `clue_allocation_decisions` 迁移；保留摘要 JSON，候选数组拆表；`execution_mode` 归一为 `dataset_kind`；删除数据库外键。

## 使用接口

Phase 4 回填，管理端只读。
