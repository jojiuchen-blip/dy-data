# `clue_allocation_candidate` - 分配候选快照

## 业务用途

结构化保存某次策略决策评估过的每家候选门店，包括资格、排除原因、距离、评分快照和排序结果，支撑可解释分配与稳定自动化测试。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `candidate_id` | varchar(64) | NO | - | 候选业务 ID |
| `decision_id` | varchar(64) | NO | - | 所属决策业务 ID |
| `lead_key` | varchar(64) | NO | - | 主线索业务键 |
| `order_id` | varchar(64) | YES | NULL | 订单编号 |
| `strategy_type` | smallint | NO | - | 1销售店优先、2城市半径优选、3城市兜底 |
| `store_id` | varchar(64) | NO | - | 候选门店 ID |
| `store_name_snapshot` | varchar(255) | NO | - | 门店名称快照 |
| `city_code` | varchar(32) | YES | NULL | 门店城市代码 |
| `eligibility_status` | smallint | NO | - | 1合格、2排除、3数据不足 |
| `exclusion_reason_code` | varchar(64) | YES | NULL | 排除原因码 |
| `exclusion_detail` | varchar(500) | YES | NULL | 脱敏排除说明 |
| `is_sales_store` | smallint | NO | 0 | 是否订单关联销售店 |
| `is_historical_assignment` | smallint | NO | 0 | 是否历史已分配门店 |
| `is_serviceable` | smallint | NO | 0 | 是否满足门店服务资格 |
| `distance_km` | decimal(10,3) | YES | NULL | 门店距锚点直线距离 |
| `store_location_snapshot` | jsonb | NO | `{}` | 评估时门店经纬度和数据版本 |
| `score_snapshot_id` | varchar(64) | YES | NULL | 引用的门店评分快照；类型1可空 |
| `conversion_rate` | decimal(10,6) | YES | NULL | 核销转化能力快照 |
| `follow_24h_rate` | decimal(10,6) | YES | NULL | 24小时有效跟进率快照 |
| `store_weight` | decimal(8,4) | YES | NULL | 门店权重快照 |
| `composite_score` | decimal(12,6) | YES | NULL | 综合评分快照 |
| `rank_no` | integer | YES | NULL | 合格候选最终排名 |
| `is_selected` | smallint | NO | 0 | 是否被本决策选中 |
| `sort_key_snapshot` | jsonb | NO | `{}` | 分数、距离和稳定门店键排序值 |
| `evaluated_at` | timestamptz | NO | CURRENT_TIMESTAMP | 评估时间 |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 仅兼容必备字段，候选内容禁止更新 |

## 索引

- `pk_clue_allocation_candidate` (`id`)
- `uk_clue_allocation_candidate_candidate_id` (`candidate_id`)
- `uk_clue_allocation_candidate_decision_store` (`decision_id`, `store_id`)
- `uk_clue_allocation_candidate_selected` (`decision_id`) WHERE `is_selected=1`
- `idx_clue_allocation_candidate_decision_rank` (`decision_id`, `eligibility_status`, `rank_no`)
- `idx_clue_allocation_candidate_store` (`store_id`, `evaluated_at` DESC)
- `idx_clue_allocation_candidate_exclusion` (`exclusion_reason_code`, `evaluated_at` DESC)
- `idx_clue_allocation_candidate_score_snapshot` (`score_snapshot_id`)

## 关系与约束

- 销售店优先只允许订单销售店成为候选且不要求评分；半径优选/城市兜底必须引用评分证据。
- 历史已分配门店必须标记并排除；评分相同按距离升序，再按稳定门店 ID 兜底。
- 一个决策最多一个选中候选；`is_selected=1` 必须同时 `eligibility_status=1`。
- 候选快照不可被后续门店资料或评分更新改写。

## 页面字段映射

- 分配记录详情：候选门店、资格、排除原因、距离、评分和排名。
- 试运行：展示预计选中门店及候选解释。

## 迁移说明

本表新增。从现有决策 JSON 中回填可证明的候选；无法还原的历史记录保留决策摘要并标记候选证据不完整。

## 使用接口

- `GET /api/v1/admin/clue-allocation/decisions/{decision_id}` — 按当时排名返回资格、排除、距离、评分和选中证据。
- `POST /api/v1/admin/clue-allocation/trial-cycles` — 写入试运行候选快照。
- `POST /api/v1/admin/clue-allocation/rebuild-cycles` — 写入试运行重建候选快照。
- `POST /api/v1/internal/clue-allocation/formal-cycles` — 写入正式候选快照并由选中项创建轮次。
- `POST /api/v1/admin/sync/clue-center/rebuilds` — 写入新重建批次候选，历史不可改写。
