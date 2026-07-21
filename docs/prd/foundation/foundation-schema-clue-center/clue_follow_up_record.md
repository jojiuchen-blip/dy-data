# `clue_follow_up_record` - 跟进动作流水

## 业务用途

保存门店在某一真实轮次内提交的每一次跟进行为。记录可由最高管理员软删除，但原始操作、删除人和删除原因必须保留，且轮次摘要需按未删除记录重算。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `follow_up_record_id` | varchar(64) | NO | - | 跟进记录业务 ID |
| `idempotency_key` | varchar(128) | NO | - | 客户端提交幂等键 |
| `lead_key` | varchar(64) | NO | - | 主线索业务键 |
| `order_id` | varchar(64) | NO | - | 订单编号 |
| `assignment_round_id` | varchar(64) | NO | - | 所属真实轮次业务 ID |
| `round_no` | integer | NO | - | 所属轮次号快照 |
| `assigned_store_id` | varchar(64) | NO | - | 跟进门店 ID |
| `assigned_store_name_snapshot` | varchar(255) | NO | - | 跟进门店名称快照 |
| `follow_action` | smallint | NO | - | 1已预约、2待进一步跟进、3暂不需要/战败、4未联系上、5客户要求换门店 |
| `note` | text | YES | NULL | 本次跟进结论或备注 |
| `operator_user_id` | varchar(64) | NO | - | 操作人 ID |
| `operator_username_snapshot` | varchar(255) | NO | - | 操作人名称快照 |
| `operator_role_snapshot` | varchar(64) | YES | NULL | 操作角色快照 |
| `source_channel` | smallint | NO | 1 | 1网页、2移动端、3内部修复 |
| `action_at` | timestamptz | NO | CURRENT_TIMESTAMP | 跟进行为时间 |
| `is_deleted` | smallint | NO | 0 | 是否被最高管理员软删除 |
| `deleted_at` | timestamptz | YES | NULL | 删除时间 |
| `deleted_by_user_id` | varchar(64) | YES | NULL | 删除人 ID |
| `deleted_by_username_snapshot` | varchar(255) | YES | NULL | 删除人名称快照 |
| `deletion_reason` | varchar(500) | YES | NULL | 删除原因，删除时必填 |
| `state_event_key` | varchar(128) | NO | - | 本动作驱动状态迁移的幂等键 |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 更新时间 |

## 索引

- `pk_clue_follow_up_record` (`id`)
- `uk_clue_follow_up_record_record_id` (`follow_up_record_id`)
- `uk_clue_follow_up_record_idempotency_key` (`idempotency_key`)
- `uk_clue_follow_up_record_state_event_key` (`state_event_key`)
- `idx_clue_follow_up_record_round` (`assignment_round_id`, `action_at` DESC)
- `idx_clue_follow_up_record_order` (`order_id`, `action_at` DESC)
- `idx_clue_follow_up_record_store` (`assigned_store_id`, `is_deleted`, `action_at` DESC)

## 关系与约束

- 保存时必须验证轮次仍是当前活动轮次、门店匹配且用户拥有跟进操作权。
- 五类动作均计为跟进行为；1/2/4 首次启动保护期，3/5 即时关闭并进入下一策略。
- 已关闭轮次不得补录；最高管理员删除不直接抹除历史状态迁移，必须在事务中重算轮次摘要并根据规则决定是否需要纠正事件。
- 软删除动作必须写 `clue_operation_audit_log`，普通管理员只读。

## 页面字段映射

- 详情时间轴：动作时间、结果、备注、门店、操作人。
- 跟进操作面板：五类单选、备注和保存。
- 最高管理员：每条记录旁垃圾桶图标触发删除确认。

## 迁移说明

由 `clue_follow_up_records` 迁移。旧 `success/failed/continue_following` 等模糊值须按可证明映射转换；无法确定的记录进入数据质量清单，不自动猜测为五类动作。

## 使用接口

- `GET /api/v1/clues/orders/{order_id}` — 按真实轮次返回未删除跟进历史。
- `POST /api/v1/clues/orders/{order_id}/follow-ups` — 幂等创建五类动作记录并同步轮次摘要。
- `DELETE /api/v1/clues/follow-up-records/{follow_up_record_id}` — 最高管理员带原因软删除并审计。
- `POST /api/v1/internal/clue-allocation/metric-refreshes` — 计算 24 小时有效跟进率与门店评分。
- `POST /api/v1/admin/sync/clue-center/rebuilds` — 迁移可证明枚举，模糊旧值进入质量清单。
