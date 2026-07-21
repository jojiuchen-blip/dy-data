# `clue_allocation_strategy_config` - 分配策略配置

## 业务用途

保存固定三类策略模块在某个规则版本中的启停、执行顺序和参数。固定沿用的是策略类型，不是固定距离或固定启用顺序。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `strategy_config_id` | varchar(64) | NO | - | 策略配置业务 ID |
| `rule_version_id` | varchar(64) | NO | - | 规则版本业务 ID |
| `strategy_type` | smallint | NO | - | 1销售店优先、2城市半径优选、3城市兜底 |
| `is_enabled` | smallint | NO | 1 | 是否启用 |
| `execution_order` | integer | NO | - | 版本内执行顺序 |
| `radius_km` | decimal(8,3) | YES | NULL | 半径公里数；类型1默认10、类型2默认15、类型3为空 |
| `candidate_limit` | integer | YES | NULL | 候选上限，空表示按规则默认 |
| `is_exclude_sales_store` | smallint | NO | 0 | 是否排除销售店；类型2默认为1 |
| `is_exclude_historical_store` | smallint | NO | 1 | 是否排除历史已分配门店 |
| `params_json` | jsonb | NO | `{}` | 远期扩展参数，不承载当前结构化参数 |
| `config_hash` | char(64) | NO | - | 配置内容摘要 |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 更新时间 |

## 索引

- `pk_clue_allocation_strategy_config` (`id`)
- `uk_clue_allocation_strategy_config_config_id` (`strategy_config_id`)
- `uk_clue_allocation_strategy_config_version_type` (`rule_version_id`, `strategy_type`)
- `uk_clue_allocation_strategy_config_version_order` (`rule_version_id`, `execution_order`)
- `idx_clue_allocation_strategy_config_enabled` (`rule_version_id`, `is_enabled`, `execution_order`)

## 关系与约束

- 每个规则版本必须各有一条类型 1/2/3 配置，不能创建第四种自定义类型。
- 类型 1/2 启用时 `radius_km>0`；类型 3 的 `radius_km` 必须为空。
- 类型 1 不参与综合评分；类型 2/3 使用相同评分公式，评分相同由距离兜底。
- 发布版本下的策略配置不可修改。

## 页面字段映射

- 规则编辑：启停、排序、半径和高级参数。
- 详情/分配记录：将策略类型转为“销售店优先”“N公里城市优选”“城市兜底”。

## 迁移说明

由 `clue_allocation_strategy_configs` 迁移；从 JSON 中提取半径和排除规则为结构化列。

## 使用接口

- `GET /api/v1/admin/clue-allocation/rules/{rule_id}` — 返回每个版本三类固定策略。
- `POST /api/v1/admin/clue-allocation/rules/{rule_id}/versions` — 随草稿版本创建完整策略集合。
- `PUT /api/v1/admin/clue-allocation/rule-versions/{rule_version_id}` — 随草稿全量更新启停、顺序和参数。
- `POST /api/v1/admin/clue-allocation/rule-versions/{rule_version_id}/publish` — 校验三类固定策略并冻结。
- `GET /api/v1/admin/clue-allocation/decisions/{decision_id}` — 解释当时命中策略及参数。
- `POST /api/v1/internal/clue-allocation/formal-cycles` — 按启用顺序执行固定策略模块。
