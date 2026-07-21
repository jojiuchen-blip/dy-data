# `clue_lead_rule_version_binding` - 线索规则版本绑定

## 业务用途

在主线索首次进入正式分配判断时锁定命中的规则版本。后台后续发布新版本不切换已有线索，多轮分配始终沿用同一版本。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `binding_id` | varchar(64) | NO | - | 绑定业务 ID |
| `lead_key` | varchar(64) | NO | - | 主线索业务键 |
| `order_id` | varchar(64) | NO | - | 订单编号 |
| `rule_id` | varchar(64) | NO | - | 规则业务 ID |
| `rule_version_id` | varchar(64) | NO | - | 锁定发布版本 ID |
| `matched_scope_type` | smallint | NO | - | 1全局、2城市、3门店组、4锚点门店 |
| `matched_scope_key` | varchar(128) | NO | - | 实际命中范围键 |
| `matched_scope_priority` | smallint | NO | - | 1锚点门店、2门店组、3城市、4全局 |
| `bound_at` | timestamptz | NO | CURRENT_TIMESTAMP | 锁定时间 |
| `binding_reason` | varchar(255) | YES | NULL | 命中说明 |
| `binding_cycle_id` | varchar(64) | YES | NULL | 首次正式判断批次 |
| `is_locked` | smallint | NO | 1 | 固定为1；仅受控重建可重新生成 |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 更新时间 |

## 索引

- `pk_clue_lead_rule_version_binding` (`id`)
- `uk_clue_lead_rule_version_binding_binding_id` (`binding_id`)
- `uk_clue_lead_rule_version_binding_lead` (`lead_key`)
- `idx_clue_lead_rule_version_binding_version` (`rule_version_id`, `bound_at` DESC)
- `idx_clue_lead_rule_version_binding_scope` (`matched_scope_type`, `matched_scope_key`)

## 关系与约束

- 每条主线索最多一条绑定；再分配不得重新执行范围匹配。
- 仅绑定状态为已发布的规则版本。
- 受控全量重建如需改变绑定，必须先试运行、记录前后快照并产生审计，而不是原地更新历史证据。

## 页面字段映射

- 分配记录：展示命中的规则版本和作用范围。
- 规则后台：统计每个版本当前绑定线索数。

## 迁移说明

由 `clue_lead_rule_version_bindings` 迁移并补充订单、范围优先级和首次批次证据。

## 使用接口

- `GET /api/v1/admin/clue-allocation/rules/{rule_id}` — 聚合规则/版本绑定线索数。
- `GET /api/v1/admin/clue-allocation/cycles/{cycle_id}` — 读取逐线索绑定结果。
- `GET /api/v1/admin/clue-allocation/decisions` — 展示决策使用的锁定版本。
- `GET /api/v1/admin/clue-allocation/decisions/{decision_id}` — 展示命中范围和绑定证据。
- `POST /api/v1/internal/clue-allocation/formal-cycles` — 首次正式分配写入并在后续轮次只读沿用。
- `POST /api/v1/admin/sync/clue-center/rebuild-previews` — 展示重新绑定前后差异。
- `POST /api/v1/admin/sync/clue-center/rebuilds` — 仅在明确确认后创建新绑定证据。
- 不提供单独管理端写绑定接口。
