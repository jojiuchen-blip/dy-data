# `store_score_snapshot` - 门店评分快照

## 业务用途

保存某次评分运行下每家门店的核销转化能力、24 小时有效跟进率、权重、冷启动来源和综合评分。历史分配只能引用当时快照。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `snapshot_id` | varchar(64) | NO | - | 评分快照业务 ID |
| `snapshot_run_id` | varchar(64) | NO | - | 评分运行业务 ID |
| `rule_version_id` | varchar(64) | YES | NULL | 参数来源规则版本 |
| `snapshot_date` | date | NO | - | 快照业务日期 |
| `run_mode` | smallint | NO | 1 | 1定时、2手动、3重建 |
| `store_id` | varchar(64) | NO | - | 门店 ID |
| `store_name_snapshot` | varchar(255) | NO | - | 门店名称快照 |
| `city_code` | varchar(32) | YES | NULL | 门店城市代码 |
| `window_start` | timestamptz | NO | - | 数据窗口起点 |
| `window_end` | timestamptz | NO | - | 数据窗口终点 |
| `conversion_numerator` | integer | NO | 0 | 成熟订单核销数 |
| `conversion_denominator` | integer | NO | 0 | 门店成熟订单数 |
| `conversion_rate` | decimal(10,6) | NO | 0 | 核销转化能力 |
| `conversion_value_source` | smallint | NO | 1 | 1门店样本、2城市冷启动、3全局冷启动、4空样本默认 |
| `follow_24h_numerator` | integer | NO | 0 | 24小时内有效跟进轮次数 |
| `follow_24h_denominator` | integer | NO | 0 | 到达24小时观察点轮次数 |
| `follow_24h_rate` | decimal(10,6) | NO | 0 | 24小时有效跟进率 |
| `follow_24h_value_source` | smallint | NO | 1 | 1门店样本、2城市冷启动、3全局冷启动、4空样本默认 |
| `conversion_weight` | decimal(6,4) | NO | 0.7000 | 核销指标权重 |
| `follow_24h_weight` | decimal(6,4) | NO | 0.3000 | 跟进指标权重 |
| `store_weight` | decimal(8,4) | NO | 1.0000 | 门店权重，V1 默认1 |
| `composite_score` | decimal(12,6) | NO | 0 | 综合评分 |
| `sample_status` | smallint | NO | 0 | 0空样本、1冷启动、2门店样本充足 |
| `config_snapshot` | jsonb | NO | `{}` | 最小样本及回退口径 |
| `computed_at` | timestamptz | NO | - | 计算完成时间 |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 仅兼容必备字段，完成后禁止更新 |

## 索引

- `pk_store_score_snapshot` (`id`)
- `uk_store_score_snapshot_snapshot_id` (`snapshot_id`)
- `uk_store_score_snapshot_run_store` (`snapshot_run_id`, `store_id`)
- `idx_store_score_snapshot_date_store` (`snapshot_date`, `store_id`)
- `idx_store_score_snapshot_city_score` (`city_code`, `composite_score` DESC)
- `idx_store_score_snapshot_rule` (`rule_version_id`, `snapshot_date` DESC)
- `idx_store_score_snapshot_sample_status` (`sample_status`, `computed_at` DESC)

## 关系与约束

- `composite_score=(conversion_rate*conversion_weight + follow_24h_rate*follow_24h_weight)*store_weight`。
- 评分相同不在本表决定胜负；分配候选按距锚点距离升序兜底。
- 快照生成后不可修改，纠错或新样本必须创建新的运行和快照。
- 门店指标分母只含实际分配给该店的正式轮次/订单，不含总部池和试运行。

## 页面字段映射

- 评分列表：两个分子/分母、比率、来源、门店权重、综合评分。
- 分配记录：候选和最终门店引用当时 `snapshot_id`。

## 迁移说明

由 `store_score_snapshots` 迁移，保留历史数值并补门店名称、规则版本和样本状态；删除数据库外键与级联。

## 使用接口

- `GET /api/v1/clues/metrics/stores` — 返回授权范围内最近综合分及诊断指标。
- `GET /api/v1/admin/clue-allocation/store-scores` — 分页读取两个分子/分母、比率、来源、权重和综合分。
- `GET /api/v1/admin/clue-allocation/decisions/{decision_id}` — 读取候选当时引用的评分快照证据。
- `POST /api/v1/admin/clue-allocation/store-score-snapshot-runs` — 创建新运行及其门店快照。
- `POST /api/v1/internal/clue-allocation/formal-cycles` — 候选排序时只读当时快照。
- `POST /api/v1/internal/clue-allocation/metric-refreshes` — 定时计算新快照，历史不可改写。
