# `clue_allocation_rule_version` - 分配规则版本

## 业务用途

保存 SLA、保护期、评分公式和策略模块的不可变版本。草稿可编辑；发布后只读；已绑定线索固定沿用该版本。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `rule_version_id` | varchar(64) | NO | - | 规则版本业务 ID |
| `rule_id` | varchar(64) | NO | - | 规则业务 ID |
| `version_no` | integer | NO | - | 规则内连续版本号 |
| `version_status` | smallint | NO | 1 | 1草稿、2已发布、3已退役 |
| `is_auto_expiry_enabled` | smallint | NO | 1 | 是否启用首次跟进 SLA |
| `first_follow_up_sla_hours` | integer | YES | 24 | 首次跟进 SLA；无限时为空 |
| `protection_days` | integer | NO | 7 | 首次保护动作后的保护天数 |
| `conversion_weight` | decimal(6,4) | NO | 0.7000 | 核销转化能力权重 |
| `follow_24h_weight` | decimal(6,4) | NO | 0.3000 | 24小时有效跟进率权重 |
| `lookback_days` | integer | NO | 30 | 门店评分回看窗口 |
| `min_samples` | integer | NO | 1 | 门店自身指标最低样本数 |
| `score_definition_version` | varchar(32) | NO | `v1` | 评分算法定义版本 |
| `config_hash` | char(64) | NO | - | 发布内容摘要 |
| `change_note` | varchar(1000) | YES | NULL | 版本变更说明 |
| `created_by` | varchar(64) | YES | NULL | 创建人 ID |
| `published_by` | varchar(64) | YES | NULL | 发布人 ID |
| `published_at` | timestamptz | YES | NULL | 发布时间 |
| `retired_by` | varchar(64) | YES | NULL | 退役人 ID |
| `retired_at` | timestamptz | YES | NULL | 退役时间 |
| `state_version` | integer | NO | 1 | 草稿编辑乐观锁版本 |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 更新时间 |

## 索引

- `pk_clue_allocation_rule_version` (`id`)
- `uk_clue_allocation_rule_version_version_id` (`rule_version_id`)
- `uk_clue_allocation_rule_version_rule_no` (`rule_id`, `version_no`)
- `uk_clue_allocation_rule_version_published_rule` (`rule_id`) WHERE `version_status=2`
- `idx_clue_allocation_rule_version_status` (`version_status`, `published_at` DESC)
- `idx_clue_allocation_rule_version_hash` (`config_hash`)

## 关系与约束

- `conversion_weight + follow_24h_weight = 1.0000` 且两者非负。
- `is_auto_expiry_enabled=0` 时 `first_follow_up_sla_hours` 必须为空；启用时必须大于 0。
- 发布前必须恰好存在三类固定策略配置，允许其中部分停用；启用策略顺序不得重复。
- 发布后所有配置和策略行不可更新，只能创建下一草稿版本或退役当前版本。

## 页面字段映射

- 分配规则：SLA、保护期、评分权重、回看窗口、最小样本、版本状态和历史。

## 迁移说明

由 `clue_allocation_rule_versions` 迁移并补充算法版本、摘要、操作人和乐观锁。现有发布版本逐一计算 `config_hash`。

## 使用接口

- `GET /api/v1/admin/clue-allocation/rules` — 返回当前发布版本摘要。
- `GET /api/v1/admin/clue-allocation/rules/{rule_id}` — 返回全部版本和绑定数量。
- `POST /api/v1/admin/clue-allocation/rules/{rule_id}/versions` — 创建完整草稿版本。
- `PUT /api/v1/admin/clue-allocation/rule-versions/{rule_version_id}` — 全量更新未发布草稿。
- `DELETE /api/v1/admin/clue-allocation/rule-versions/{rule_version_id}` — 删除未发布、未引用草稿。
- `POST /api/v1/admin/clue-allocation/rule-versions/{rule_version_id}/publish` — 校验、哈希并发布不可变版本。
- `POST /api/v1/admin/clue-allocation/rule-versions/{rule_version_id}/retire` — 退役版本但不切换已绑定线索。
- `GET /api/v1/admin/clue-allocation/store-scores` — 按规则版本读取评分证据。
- `POST /api/v1/admin/clue-allocation/store-score-snapshot-runs` — 触发该版本评分运行。
- `POST /api/v1/internal/clue-allocation/formal-cycles` — 读取线索锁定版本执行后续策略。
- `POST /api/v1/admin/sync/clue-center/rebuild-previews` — 预览是否重新绑定版本。
- `POST /api/v1/admin/sync/clue-center/rebuilds` — 按确认结果受控重建绑定。
