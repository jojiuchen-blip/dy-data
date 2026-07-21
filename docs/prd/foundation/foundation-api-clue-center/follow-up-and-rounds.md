# 跟进、真实轮次与状态迁移

> 返回 [API 索引](../foundation-api-clue-center.md) · 公共约定见 [common-contract.md](common-contract.md)

## 1. 五类跟进动作

API 只接受以下五个稳定动作值。旧 `success`、`failed`、`continue_following` 不得继续写入；迁移时无法证明含义的历史值进入数据质量清单。

| `follow_action` | 店端文案 | 记为产生跟进 | 启动保护期 | 当前轮结果 |
|-----------------|----------|--------------|------------|------------|
| `appointment` | 已预约 | 是 | 是 | 保持有效，等待核销或保护期到期 |
| `further_follow_up` | 待进一步跟进 | 是 | 是 | 保持有效，等待后续动作、核销或保护期到期 |
| `unreachable` | 未联系上 | 是 | 是 | 保持有效；保护期到期仍进入下一策略 |
| `lost` | 暂不需要（线索战败） | 是 | 否 | 立即关闭本轮，进入下一启用策略 |
| `request_store_change` | 客户要求换门店 | 是 | 否 | 立即关闭本轮，排除当前门店后进入下一启用策略 |

预约、待进一步跟进和未联系上都被视为有效跟进行为，但不等于订单核销。保护期只由本轮首个可启动保护的动作确定，后续动作不得延长或重置保护期。

## 2. F01 `POST /api/v1/clues/orders/{order_id}/follow-ups`

> 消费页面: 线索跟进详情右侧操作面板
> 写入: `clue_follow_up_record`、`clue_assignment_round`、可靠待办事件、`clue_operation_audit_log`
> 读取: `clue_master_lead`、`clue_contact`、当前用户范围
> 权限: A02 + 当前有效轮次所属门店动作权限
> 状态: 新增，替代单数 `/follow-up`

**请求头**：

| 字段 | 必填 | 说明 |
|------|------|------|
| `Idempotency-Key` | 是 | 每次用户提交生成稳定 UUID；同请求重试不重复写入 |

**请求体**：

| 字段 | 类型 | 必填 | 说明 | 对应字段 |
|------|------|------|------|----------|
| `assignment_round_id` | string | 是 | 必须等于当前活动轮次 | `clue_assignment_round.assignment_round_id` |
| `follow_action` | string | 是 | 五类允许值之一 | `clue_follow_up_record.follow_action` |
| `note` | string/null | 否 | 本次结论或备注，去首尾空格后最多 1,000 字 | `clue_follow_up_record.note` |
| `lead_state_version` | integer | 是 | 主线索乐观锁版本 | `clue_master_lead.state_version` |
| `round_state_version` | integer | 是 | 当前轮乐观锁版本 | `clue_assignment_round.state_version` |

**响应 `data`**：

| 字段 | 类型 | 说明 | 来源 |
|------|------|------|------|
| `follow_up_record_id` | string | 新记录业务 ID | `clue_follow_up_record.follow_up_record_id` |
| `order_id` | string | 订单号 | `order_id` |
| `assignment_round_id` | string | 本轮 ID | `assignment_round_id` |
| `round_no` | integer | 真实轮次号 | `round_no` |
| `follow_action` | string | 已保存动作 | `follow_action` |
| `note` | string/null | 已规范化备注 | `note` |
| `action_at` | datetime | 服务端动作时间 | `action_at` |
| `operator_username` | string/null | 操作人快照 | `operator_username_snapshot` |
| `store_display_status` | string | 保存后的店端状态 | 查询投影 |
| `round_status` | string | 保存后的轮次状态 | `clue_assignment_round.round_status` |
| `protection_started_at` | datetime/null | 本轮首次保护开始时间 | `protection_started_at` |
| `protection_expires_at` | datetime/null | 固定保护期结束时间 | `protection_expires_at` |
| `next_allocation_pending` | boolean | 是否已写入进入下一策略的可靠待办 | 状态迁移结果 |
| `lead_state_version` | integer | 更新后版本 | `clue_master_lead.state_version` |
| `round_state_version` | integer | 更新后版本 | `clue_assignment_round.state_version` |

### 2.1 服务端校验顺序

1. 验证页面权限、数据范围和动作权限。
2. 锁定主线索和请求轮次。
3. 重新读取订单状态；已核销/已退款优先返回 `CLUE_40901`，不得写入动作。
4. 验证主线索位于门店跟进池、请求轮次等于当前轮次且状态为活动态。
5. 比较两个 `state_version` 和幂等键。
6. 写入动作、更新轮次摘要并按动作执行状态迁移。
7. 写入审计/可靠事件，提交事务。

### 2.2 动作事务结果

- `appointment`、`further_follow_up`、`unreachable`：
  - `is_followed=1`，更新 `latest_follow_action/latest_follow_at`。
  - 若 `protection_started_at` 为空，按动作时间写入，并根据本轮锁定的 `protection_days` 计算一次结束时间。
  - `round_status=protected`；后续同类动作只更新摘要，不改变保护期起止点。
- `lost`：
  - 写记录并关闭本轮为 `lost`，`ended_at=action_at`。
  - 清除主线索当前轮次并写下一策略待办；前端立即清除完整号缓存。
- `request_store_change`：
  - 写记录并关闭本轮为 `store_change`，`ended_at=action_at`。
  - 下一策略必须排除本轮及全部历史门店；前端立即清除完整号缓存。

下一策略任务可能异步创建新轮；F01 响应不伪造下一轮 ID。待办执行期间主线索处于受控 `pending_allocation`，最后策略结束或无候选时进入总部池。

## 3. F02 `DELETE /api/v1/clues/follow-up-records/{follow_up_record_id}`

> 消费页面: 跟进历史每条记录的垃圾桶图标
> 写入: `clue_follow_up_record`、必要的轮次摘要、`clue_operation_audit_log`
> 权限: A02 + 最高管理员；普通管理员和门店无入口也无接口权限
> 状态: 变更为有原因、有版本的软删除

**请求头**：`Idempotency-Key` 必填。

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `deletion_reason` | string | 是 | 5-200 字，说明误录原因 |
| `round_state_version` | integer | 是 | 目标轮次当前版本 |

**响应 `data`**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `follow_up_record_id` | string | 已软删除记录 |
| `is_deleted` | boolean | 固定为 `true` |
| `deleted_at` | datetime | 删除时间 |
| `deleted_by_username` | string | 删除人快照 |
| `round_status` | string | 删除后的轮次状态；通常不改变 |
| `latest_follow_action` | string/null | 从剩余未删除记录重算的最近摘要 |
| `latest_follow_at` | datetime/null | 从剩余未删除记录重算的最近时间 |
| `round_state_version` | integer | 更新后版本 |

### 3.1 删除边界

- 只做软删除；原记录、删除人、原因和审计不可物理清除。
- 删除可重算 `latest_follow_action/latest_follow_at/is_followed` 的展示摘要。
- 已经关闭的轮次、已经创建的后续轮次、总部池条目和历史决策不得因删除记录自动回滚。
- 若目标是活动保护轮次，删除后仍有可启动保护的动作，则保护起止点保持首次实际进入保护时的历史值，不因删除重新延长。
- 若删除会使当前活动轮次失去唯一保护依据、产生无法证明的 SLA 回退，返回 `CLUE_42204`，由最高管理员通过受控重建处理。
- 已删除记录再次删除返回幂等成功或 `CLUE_40903`，同一项目实现必须统一；推荐幂等成功并返回原删除结果。

## 4. 轮次状态 API 枚举

| API 值 | 店端状态 | 是否活动 | 进入方式 |
|--------|----------|----------|----------|
| `pending_follow_up` | 待跟进 | 是 | 正式分配创建 |
| `protected` | 已跟进 | 是 | 首次有效跟进动作 |
| `sla_expired` | 超期失效 | 否 | SLA 任务关闭未跟进轮次 |
| `protection_expired` | 超期失效 | 否 | 保护期任务关闭未核销轮次 |
| `lost` | 主动战败 | 否 | 门店提交战败 |
| `store_change` | 主动战败 | 否 | 客户要求换门店；详情展示具体原因 |
| `verified_closed` | 已核销 | 否 | 订单核销终态优先关闭 |
| `refunded_closed` | 已退款 | 否 | 退款终态优先关闭 |
| `admin_closed` | 由原因决定 | 否 | 仅受控重建/治理，不提供普通状态编辑 |

`store_display_status` 的店端六值由订单终态优先，再结合当前/历史轮次计算；API 不允许客户端提交该字段。

## 5. 状态迁移优先级

同一时刻发生多个事件时按以下顺序处理：

1. 已退款终态事件。
2. 已核销终态事件。
3. 已经提交并锁定成功的门店动作。
4. 保护期到期。
5. 首次跟进 SLA 到期。

订单终态不可逆地关闭线索。若同一订单先观察到核销、后观察到退款，指标事实仍保留 `is_ever_verified=1`，生命周期按最新更高优先级退款状态关闭；具体业务展示由 PRD 固定为“已退款”。

## 6. 内部状态迁移命令

业务前端不直接调用以下动作，它们由 [任务契约](jobs-security-and-migration.md) 触发：

| 命令 | 读取 | 原子写入 |
|------|------|----------|
| 订单终态关闭 | 状态事件、主线索、当前轮 | 主线索、轮次、总部池、指标事实、查询投影 |
| SLA 到期 | `pending_follow_up` 且到期轮次 | 关闭轮次、清当前归属、下一策略待办 |
| 保护期到期 | `protected` 且未核销轮次 | 关闭轮次、清当前归属、下一策略待办 |
| 正式分配成功 | 待分配主线索、规则/评分/候选 | 绑定、决策、候选、真实轮次、池位置、审计 |
| 策略耗尽 | 待分配主线索、最后策略结果 | 总部池活动条目、池位置、审计 |

任何内部命令都必须比较 `state_version`、使用稳定事件键，并在订单已终态时直接跳过分配或过期迁移。
