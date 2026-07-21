# `store_score_snapshot_run` - 门店评分运行

## 业务用途

记录一次门店综合评分计算的时间窗口、公式版本和运行结果，使后续分配能够引用不可变评分快照，而不是按当前配置重算历史。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `snapshot_run_id` | varchar(64) | NO | - | 评分运行业务 ID |
| `snapshot_date` | date | NO | - | 快照业务日期 |
| `run_mode` | smallint | NO | 1 | 1定时、2手动、3重建 |
| `run_status` | smallint | NO | 1 | 1运行中、2完成、3部分失败、4失败 |
| `scheduled_key` | varchar(128) | YES | NULL | 定时运行幂等键 |
| `rule_version_id` | varchar(64) | YES | NULL | 评分参数来源规则版本 |
| `score_definition_version` | varchar(32) | NO | `v1` | 评分算法定义版本 |
| `score_policy_hash` | char(64) | NO | - | 公式、参数和冷启动规则摘要 |
| `window_start` | timestamptz | NO | - | 数据窗口起点 |
| `window_end` | timestamptz | NO | - | 数据窗口终点 |
| `candidate_store_count` | integer | NO | 0 | 参与评分门店数 |
| `snapshot_count` | integer | NO | 0 | 成功生成快照数 |
| `triggered_by` | varchar(64) | YES | NULL | 触发人或任务标识 |
| `config_snapshot` | jsonb | NO | `{}` | 完整评分参数和冷启动口径 |
| `computed_at` | timestamptz | YES | NULL | 计算完成时间 |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 更新时间 |

## 索引

- `pk_store_score_snapshot_run` (`id`)
- `uk_store_score_snapshot_run_run_id` (`snapshot_run_id`)
- `uk_store_score_snapshot_run_scheduled_key` (`scheduled_key`) WHERE `scheduled_key IS NOT NULL`
- `idx_store_score_snapshot_run_date_mode` (`snapshot_date`, `run_mode`)
- `idx_store_score_snapshot_run_policy` (`score_policy_hash`, `computed_at` DESC)

## 关系与约束

- 完成状态的运行不可修改评分参数；补算创建新的运行。
- `window_end` 必须晚于 `window_start`，不得使用未来数据计算历史决策。
- 不同规则版本若评分参数完全一致，可共享同一 `score_policy_hash` 快照运行；决策仍保存实际规则版本。

## 页面字段映射

- 分配后台：评分运行时间、窗口、门店数和运行状态。

## 迁移说明

由 `store_score_snapshot_runs` 迁移，补充运行状态、规则版本和公式摘要；删除数据库外键依赖。

## 使用接口

- `GET /api/v1/admin/clue-allocation/store-scores` — 读取评分运行时间、窗口、口径、数量和状态。
- `POST /api/v1/admin/clue-allocation/store-score-snapshot-runs` — 最高管理员幂等触发评分运行。
- `POST /api/v1/internal/clue-allocation/formal-cycles` — 新轮次引用创建当时可用的评分快照运行。
- `POST /api/v1/internal/clue-allocation/metric-refreshes` — 定时创建评分运行并刷新快照。
- `POST /api/v1/admin/sync/clue-center/rebuilds` — 按受控范围重算；历史运行不可改写。
