# `clue_operation_audit_log` - 线索操作审计

## 业务用途

统一记录联系方式查看/复制/明文导出、规则发布、试运行、重建、跟进记录删除及其他高风险动作。记录只追加，不保存 access token、client secret 或完整手机号。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `audit_id` | varchar(64) | NO | - | 审计业务 ID |
| `event_type` | smallint | NO | - | 1看完整号、2复制完整号、3明文导出、4删跟进、5发规则、6试运行、7重建、8正式分配、9其他 |
| `sensitivity_level` | smallint | NO | 1 | 1普通、2敏感、3高风险 |
| `actor_user_id` | varchar(64) | YES | NULL | 操作人 ID |
| `actor_username_snapshot` | varchar(255) | YES | NULL | 操作人名称快照 |
| `actor_role_snapshot` | varchar(128) | YES | NULL | 操作角色快照 |
| `account_scope_snapshot` | jsonb | NO | `{}` | 操作时数据范围快照 |
| `target_type` | varchar(64) | NO | - | 目标类型 |
| `target_id` | varchar(128) | YES | NULL | 目标业务 ID |
| `lead_key` | varchar(64) | YES | NULL | 相关主线索 |
| `order_id` | varchar(64) | YES | NULL | 相关订单 |
| `assignment_round_id` | varchar(64) | YES | NULL | 相关轮次 |
| `rule_version_id` | varchar(64) | YES | NULL | 相关规则版本 |
| `cycle_id` | varchar(64) | YES | NULL | 相关批次 |
| `request_id` | varchar(64) | YES | NULL | 链路请求 ID |
| `result_status` | smallint | NO | 1 | 1成功、2拒绝、3失败 |
| `reason_code` | varchar(64) | YES | NULL | 拒绝/失败/业务原因码 |
| `before_snapshot` | jsonb | NO | `{}` | 操作前脱敏快照 |
| `after_snapshot` | jsonb | NO | `{}` | 操作后脱敏快照 |
| `detail_json` | jsonb | NO | `{}` | 必要上下文，不含敏感明文 |
| `client_ip_hash` | char(64) | YES | NULL | 客户端 IP 摘要 |
| `user_agent_hash` | char(64) | YES | NULL | User-Agent 摘要 |
| `occurred_at` | timestamptz | NO | CURRENT_TIMESTAMP | 事件时间 |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 仅兼容必备字段，记录禁止更新 |

## 索引

- `pk_clue_operation_audit_log` (`id`)
- `uk_clue_operation_audit_log_audit_id` (`audit_id`)
- `idx_clue_operation_audit_log_actor` (`actor_user_id`, `occurred_at` DESC)
- `idx_clue_operation_audit_log_event` (`event_type`, `occurred_at` DESC)
- `idx_clue_operation_audit_log_target` (`target_type`, `target_id`, `occurred_at` DESC)
- `idx_clue_operation_audit_log_order` (`order_id`, `occurred_at` DESC)
- `idx_clue_operation_audit_log_round` (`assignment_round_id`, `occurred_at` DESC)
- `idx_clue_operation_audit_log_cycle` (`cycle_id`, `occurred_at` DESC)

## 安全与约束

- 审计记录禁止更新和删除；更正通过追加说明记录。
- 查看/复制/导出即使被权限拒绝也应记录拒绝事件，但绝不记录手机号明文。
- 规则发布、重建和跟进删除必须含前后快照、操作人和原因；自动任务使用稳定服务身份。
- 审计查询本身受最高管理员或专门审计权限控制。

## 页面字段映射

- 分配记录/审计页：事件类型、操作人、目标、结果、时间和脱敏详情。
- 联系方式轻提示不展示审计内容，但成功/拒绝均在后台留痕。

## 迁移说明

由 `clue_allocation_audit_logs` 扩展迁移。现有分配审计映射到事件类型 5-9；手机号与跟进删除历史按现有日志可证明范围补录，不伪造缺失审计。

## 使用接口

- `GET /api/v1/admin/clue-allocation/audit-logs` — 最高管理员或审计权限分页读取脱敏日志。
- `POST /api/v1/clues/orders/{order_id}/phone-access` — 记录 reveal/copy 成功或拒绝。
- `POST /api/v1/clues/assignment-round-exports` — 记录明文导出范围与数量摘要。
- `DELETE /api/v1/clues/follow-up-records/{follow_up_record_id}` — 记录软删除前后脱敏快照和原因。
- `POST /api/v1/admin/clue-allocation/rule-versions/{rule_version_id}/publish` — 记录规则发布。
- `POST /api/v1/admin/clue-allocation/rule-versions/{rule_version_id}/retire` — 记录规则退役。
- `POST /api/v1/admin/clue-allocation/trial-cycles` — 记录试运行。
- `POST /api/v1/admin/clue-allocation/rebuild-cycles` — 记录试运行重建。
- `POST /api/v1/admin/clue-allocation/store-score-snapshot-runs` — 记录人工评分刷新。
- `POST /api/v1/internal/clue-allocation/formal-cycles` — 记录正式分配服务身份和批次。
- `POST /api/v1/admin/sync/clue-center/rebuild-previews` — 记录高风险预览。
- `POST /api/v1/admin/sync/clue-center/rebuilds` — 记录正式重建确认与结果。
- 所有写入均禁止保存手机号明文、token、client_secret 或未脱敏原始 payload。
