# `clue_allocation_cycle` - 分配运行批次

## 业务用途

保存一次试运行、正式分配或受控重建的总体执行信息。批次只保存计数和摘要，线索明细拆到 `clue_allocation_cycle_item`，避免大 JSON 无法分页或重试。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `cycle_id` | varchar(64) | NO | - | 批次业务 ID |
| `parent_cycle_id` | varchar(64) | YES | NULL | 父批次业务 ID |
| `cycle_mode` | smallint | NO | - | 1试运行、2正式、3重建 |
| `trigger_type` | smallint | NO | - | 1初始、2 SLA、3保护期、4战败、5换店、6终态回补、7人工重建 |
| `cycle_status` | smallint | NO | 1 | 1待执行、2运行中、3完成、4部分失败、5失败、6取消 |
| `source_cycle_id` | varchar(64) | YES | NULL | 重建或重试来源批次 |
| `requested_lead_count` | integer | NO | 0 | 请求线索数 |
| `eligible_lead_count` | integer | NO | 0 | 通过前置校验线索数 |
| `assigned_lead_count` | integer | NO | 0 | 形成真实轮次线索数 |
| `headquarters_pool_count` | integer | NO | 0 | 进入总部池线索数 |
| `skipped_lead_count` | integer | NO | 0 | 终态、非活动或幂等跳过数 |
| `failed_lead_count` | integer | NO | 0 | 执行失败线索数 |
| `preview_token_hash` | char(64) | YES | NULL | 试运行确认令牌摘要 |
| `preview_expires_at` | timestamptz | YES | NULL | 预览令牌到期时间 |
| `is_privileged_confirmation` | smallint | NO | 0 | 是否完成高风险二次确认 |
| `actor_user_id` | varchar(64) | YES | NULL | 发起人 ID；自动任务可空 |
| `actor_username_snapshot` | varchar(255) | YES | NULL | 发起人名称快照 |
| `requested_at` | timestamptz | NO | CURRENT_TIMESTAMP | 请求时间 |
| `executed_at` | timestamptz | YES | NULL | 开始执行时间 |
| `completed_at` | timestamptz | YES | NULL | 完成时间 |
| `request_scope_snapshot` | jsonb | NO | `{}` | 账号范围、筛选和重建范围快照 |
| `summary_json` | jsonb | NO | `{}` | 按结果/原因汇总，不存线索列表 |
| `error_summary` | jsonb | NO | `{}` | 脱敏错误分类与数量 |
| `state_version` | integer | NO | 1 | 批次状态乐观锁版本 |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 更新时间 |

## 索引

- `pk_clue_allocation_cycle` (`id`)
- `uk_clue_allocation_cycle_cycle_id` (`cycle_id`)
- `idx_clue_allocation_cycle_mode_status` (`cycle_mode`, `cycle_status`, `requested_at` DESC)
- `idx_clue_allocation_cycle_trigger` (`trigger_type`, `requested_at` DESC)
- `idx_clue_allocation_cycle_parent` (`parent_cycle_id`)
- `idx_clue_allocation_cycle_source` (`source_cycle_id`)
- `idx_clue_allocation_cycle_actor` (`actor_user_id`, `requested_at` DESC)

## 关系与约束

- 试运行只写批次、明细、决策和候选，不能改变主线索、创建轮次或进入总部池。
- 正式与重建必须使用未过期预览证据并完成高风险确认；重建必须指向来源批次或范围快照。
- `requested_lead_count` 等于批次明细总数；完成时各结果计数之和必须可对账。
- 失败线索允许逐条重试，不得整批重复创建轮次。

## 页面字段映射

- 试运行：范围、预览、预计影响和确认。
- 分配记录：模式、状态、数量、执行人和时间。
- 重建：来源批次、预览令牌和实际影响。

## 迁移说明

由 `clue_allocation_cycles` 迁移；`selected_lead_keys` 拆到明细表；统一模式和状态枚举，删除数据库外键。

## 使用接口

- `POST /api/v1/admin/clue-allocation/cycle-previews` — 生成绑定选择范围和状态版本的短时预览。
- `POST /api/v1/admin/clue-allocation/trial-cycles` — 创建试运行批次。
- `POST /api/v1/admin/clue-allocation/rebuild-cycles` — 创建新的试运行重建批次。
- `GET /api/v1/admin/clue-allocation/cycles` — 分页读取试运行、正式和重建批次。
- `GET /api/v1/admin/clue-allocation/cycles/{cycle_id}` — 读取批次摘要和逐线索执行项。
- `POST /api/v1/internal/clue-allocation/formal-cycles` — 创建唯一正式分配批次。
- `POST /api/v1/admin/sync/clue-center/rebuild-previews` — 预览正式重建范围。
- `POST /api/v1/admin/sync/clue-center/rebuilds` — 创建 `formal_rebuild` 批次并异步执行。
