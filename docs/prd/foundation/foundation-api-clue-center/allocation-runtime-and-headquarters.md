# 分配运行、决策、评分、总部池与审计

> 返回 [API 索引](../foundation-api-clue-center.md) · 公共约定见 [common-contract.md](common-contract.md)

## 1. 运行数据集隔离

| 数据集/模式 | 可由谁触发 | 可写决策/候选 | 可写真实轮次/池位置 | 进入指标 |
|-------------|------------|---------------|----------------------|----------|
| `trial` | 最高管理员 | 是，标记 `dataset_kind=trial` | 否 | 否 |
| `trial_rebuild` | 最高管理员 | 是，建立新试运行批次 | 否 | 否 |
| `formal` | 内部正式分配任务 | 是，标记 `dataset_kind=formal` | 是 | 是 |
| `formal_rebuild` | 最高管理员确认后由内部任务执行 | 是，建立新正式证据 | 是 | 是，重建后对账 |

试运行不得通过参数切换为正式写入。管理端 A02-A04 只产生 `trial` 或 `trial_rebuild`；正式运行只由 J03/J08 进入。

## 2. A01 `GET /api/v1/admin/clue-allocation/eligible-leads`

> 消费页面: 分配试运行
> 数据源: `clue_master_lead`、`clue_center_order`
> 权限: D06；普通管理员可读，只有最高管理员可选择执行
> 状态: 变更

**请求参数**：`pool_location`（默认 `pending_allocation`）、`anchor_mapping_status`、`city_code`、`q`、`page`、`page_size`（最大 200）。

**响应行字段**：

| 字段 | 类型 | 说明 | 来源 |
|------|------|------|------|
| `lead_key` | string | 主线索键 | `clue_master_lead.lead_key` |
| `canonical_clue_id` | string/null | 代表线索 ID | `canonical_clue_id` |
| `order_id` | string | 订单号 | `order_id` |
| `normalized_order_status` | string | 必须为 `active` | `normalized_order_status` |
| `pool_location` | string | 待分配或按重建范围读取 | `pool_location` |
| `anchor_poi_id` | string/null | 唯一代理锚点 | `anchor_poi_id` |
| `anchor_store_id` | string/null | 映射锚点门店 | `anchor_store_id` |
| `anchor_mapping_status` | string | 锚点质量状态 | `anchor_mapping_status` |
| `anchor_city` | string/null | 锚点城市 | `anchor_city` |
| `sales_store_id` | string/null | 销售店 | `sales_store_id` |
| `current_rule_version_id` | string/null | 已锁定版本或预计命中版本 | 版本绑定/规则解析 |
| `state_version` | integer | 预览一致性校验 | `state_version` |

已核销、已退款、源记录隔离线索和已有活动轮次的线索不进入默认结果。总部池 V1 不通过此接口再次投放。

## 3. A02 `POST /api/v1/admin/clue-allocation/cycle-previews`

> 消费页面: 分配试运行预览、试运行重建预览
> 写入: 可选短期预览缓存；不得写正式事实
> 权限: D06 + 最高管理员
> 状态: 新增，替代 `/cycles/preview`

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `operation` | string | 是 | `trial` 或 `trial_rebuild` |
| `lead_keys` | string[] | 条件 | `trial` 时 1-200 条 |
| `source_cycle_id` | string/null | 条件 | `trial_rebuild` 时必填且必须为试运行批次 |
| `rebind_rule_version` | boolean | 否 | 试运行比较项；不写正式绑定 |

**响应 `data`**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `operation` | string | 预览类型 |
| `requested_lead_count` | integer | 请求数量 |
| `eligible_lead_count` | integer | 当前可试运行数量 |
| `summary` | object | 预计分配、入总部池、跳过和异常数 |
| `changed_leads` | array | 预计规则、策略、门店或总部池变化摘要，最多返回前 200 条 |
| `preview_token` | string | 绑定操作者、范围、状态版本和请求摘要的短时令牌 |
| `preview_expires_at` | datetime | 默认 10 分钟 |

预览过程中可在内存计算候选，也可创建有 TTL 的预览证据，但不得创建 `clue_assignment_round`、活动总部池条目或指标事实。

## 4. A03 `POST /api/v1/admin/clue-allocation/trial-cycles`

> 写入: `clue_allocation_cycle`、`clue_allocation_cycle_item`、`clue_allocation_decision`、`clue_allocation_candidate`、审计
> 权限: D06 + 最高管理员
> 状态: 新增，替代 `/cycles/trial`

**请求头**：`Idempotency-Key`。

**请求体**：`lead_keys[]`、`preview_token`、`confirmation_text`。服务端重新校验令牌、操作者、线索 `state_version` 和规则哈希。

**响应 `data`**：

| 字段 | 类型 | 说明 | 来源 |
|------|------|------|------|
| `cycle_id` | string | 试运行批次 ID | `clue_allocation_cycle.cycle_id` |
| `cycle_mode` | string | 固定 `trial` | `cycle_mode` |
| `cycle_status` | string | `pending`、`running`、`completed`、`partial_failed`、`failed` | `cycle_status` |
| `requested_lead_count` | integer | 请求数 | `requested_lead_count` |
| `eligible_lead_count` | integer | 可执行数 | `eligible_lead_count` |
| `assigned_lead_count` | integer | 预计选中门店数，仅试运行语义 | `assigned_lead_count` |
| `headquarters_pool_count` | integer | 预计入总部池数 | `headquarters_pool_count` |
| `skipped_lead_count` | integer | 跳过数 | `skipped_lead_count` |
| `failed_lead_count` | integer | 失败数 | `failed_lead_count` |

即使字段名为 `assigned_lead_count`，试运行也只表示模拟选中，不创建真实轮次。

## 5. A04 `POST /api/v1/admin/clue-allocation/rebuild-cycles`

> 消费页面: 试运行重建
> 写入: 新 `trial_rebuild` 批次及不可变试运行证据
> 权限: D06 + 最高管理员
> 状态: 新增，替代 `/cycles/rebuild`

请求头为 `Idempotency-Key`；请求体包含 `source_cycle_id`、`preview_token`、`confirmation_text`。来源必须为试运行类批次。响应同 A03，另返回 `parent_cycle_id/source_cycle_id`。

此接口用于重复验证规则和候选变化，不是正式主池全量重建。正式重建使用 J07/J08。

## 6. A05 `GET /api/v1/admin/clue-allocation/cycles`

> 消费页面: 分配试运行、分配记录
> 数据源: `clue_allocation_cycle`
> 权限: D06 或 D07
> 状态: 变更

**请求参数**：`cycle_mode`、`cycle_status`、`requested_date_start/end`、`actor_user_id`、`page`、`page_size`。

**响应行字段**：暴露 `cycle_id`、`parent_cycle_id`、`cycle_mode`、`trigger_type`、`cycle_status`、六个数量字段、`actor_username`、`requested_at`、`executed_at`、`completed_at`、`error_summary`。不返回预览令牌哈希或含敏感值的请求快照。

## 7. A06 `GET /api/v1/admin/clue-allocation/cycles/{cycle_id}`

> 数据源: `clue_allocation_cycle`、`clue_allocation_cycle_item`
> 权限: D06 或 D07
> 状态: 新增

响应包含批次摘要及分页 `items`。每个执行项返回：

- `cycle_item_id`、`sequence_no`、`lead_key`、`order_id`
- `item_status`、`initial_pool_location`、`outcome_reason`
- `rule_binding_id`、`decision_id`、`assignment_round_id`、`headquarters_pool_entry_id`
- `attempt_count`、`started_at`、`completed_at`、`error_code`

`error_detail` 必须脱敏，不能包含手机号、密钥或外部原始响应全文。

## 8. A07 `GET /api/v1/admin/clue-allocation/decisions`

> 消费页面: 分配记录
> 数据源: `clue_allocation_decision`
> 权限: D07
> 状态: 变更

请求参数：`cycle_id`、`lead_key`、`order_id`、`dataset_kind`、`strategy_type`、`decision_status`、`page`、`page_size`。

响应行包含 `decision_id`、`cycle_id`、`dataset_kind`、`lead_key`、`order_id`、`rule_version_id`、范围、策略、顺序、结果、选中门店、综合分、距离、候选数、真实轮次 ID、原因和执行时间。

## 9. A08 `GET /api/v1/admin/clue-allocation/decisions/{decision_id}`

> 数据源: `clue_allocation_decision`、`clue_allocation_candidate`
> 权限: D07
> 状态: 新增

**响应 `data`**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `decision` | object | A07 行字段 + 脱敏上下文快照 |
| `candidates` | array | 按 `rank_no`、`candidate_id` 稳定排序 |
| `candidates[].store_id/name` | string | 候选门店及名称快照 |
| `candidates[].eligibility_status` | string | `eligible` 或 `excluded` |
| `candidates[].exclusion_reason_code` | string/null | 排除原因 |
| `candidates[].is_sales_store` | boolean | 是否销售店 |
| `candidates[].is_historical_assignment` | boolean | 是否历史门店 |
| `candidates[].distance_km` | number/null | 当时距离 |
| `candidates[].conversion_rate` | number/null | 当时核销转化能力 |
| `candidates[].follow_24h_rate` | number/null | 当时 24 小时有效跟进率 |
| `candidates[].store_weight` | number/null | 当时权重 |
| `candidates[].composite_score` | number/null | 当时综合分 |
| `candidates[].rank_no` | integer/null | 合格候选排名 |
| `candidates[].is_selected` | boolean | 是否选中 |

候选快照不可用当前门店资料或最新评分回填覆盖。

## 10. A09 `GET /api/v1/admin/clue-allocation/store-scores`

> 消费页面: 分配记录评分区
> 数据源: `store_score_snapshot_run`、`store_score_snapshot`
> 权限: D07
> 状态: 变更

请求参数：`snapshot_run_id`、`rule_version_id`、`snapshot_date`、`city_code`、`store_id`、`page`、`page_size`。

响应包含 `run` 和分页 `rows`。运行返回窗口、口径版本、规则版本、门店数、快照数和状态；门店行返回两个分子/分母、比率、值来源、权重、综合分、样本状态和计算时间。

## 11. A10 `POST /api/v1/admin/clue-allocation/store-score-snapshot-runs`

> 写入: `store_score_snapshot_run`、`store_score_snapshot`、审计
> 权限: D07 + 最高管理员
> 状态: 新增，替代 `/store-scores/refresh`

请求头：`Idempotency-Key`。请求体：`rule_version_id`、可选 `snapshot_date`、`reason`。只能基于已发布/已绑定可用版本计算；计算窗口不得包含未来数据。响应返回 `snapshot_run_id`、`run_status`，异步时由 A09/A05 轮询。

## 12. A11 `GET /api/v1/admin/clue-allocation/master-leads`

> 消费页面: 分配记录的数据排查区
> 数据源: `clue_master_lead`
> 权限: D07
> 状态: 变更，删除旧 `allocation_state`

请求参数：`lifecycle_status`、`pool_location`、`normalized_order_status`、`anchor_mapping_status`、`city_code`、`q`、分页。

响应行包含主线索、订单、生命周期、池位置、当前轮次/批次、锚点、销售店、完整主池标识、关闭原因、首次/最近观察时间和 `state_version`。不返回明文手机号或原始 payload。

## 13. A12 `GET /api/v1/admin/clue-allocation/data-quality`

> 消费页面: 分配记录的数据质量摘要
> 数据源: `clue_source_record_link`、`clue_master_lead`、共享门店/POI 表
> 权限: D07
> 状态: 新增

请求参数：`observed_date_start/end`、`issue_type`、`city_code`。响应包含：

- `source_record_total`、`linked_record_total`、`isolated_record_total`、`conflict_record_total`
- `missing_anchor_count`、`unmapped_anchor_count`、`invalid_geo_count`
- `pending_allocation_count`、`duplicate_active_round_count`、`pool_inconsistency_count`
- `issues[]`：脱敏样例键、原因、首次/最近观察时间和建议治理动作

V1 只读。人工修复源映射和地理数据作为 DYDATA-35 后续写入接口，不在本 Foundation 中先行定义。

## 14. A13 `GET /api/v1/admin/clue-allocation/audit-logs`

> 消费页面: 分配记录审计区
> 数据源: `clue_operation_audit_log`
> 权限: D07 + 最高管理员或专门审计权限
> 状态: 变更

请求参数：`event_type`、`result_status`、`actor_user_id`、`target_type`、`target_id`、`occurred_date_start/end`、分页。

响应行包含 `audit_id`、事件类型、敏感级别、操作人/角色快照、目标、关联订单/轮次/版本/批次、结果、原因码、脱敏前后快照、请求 ID 和时间。账号范围快照只返回组织 ID 摘要，不返回手机号或令牌。

## 15. H01 `GET /api/v1/admin/clue-allocation/headquarters-pool`

> 消费页面: 总部线索池
> 数据源: `clue_headquarters_pool_entry`、`clue_master_lead`
> 权限: D08；门店账号禁止；普通管理员只读
> 状态: 变更

**请求参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `entry_status` | string | `active`、`closed` |
| `reason_code` | string | 标准入池原因 |
| `entered_date_start/end` | date | 入池自然日闭区间 |
| `normalized_order_status` | string | 订单归一化状态 |
| `city_code` | string | 锚点城市 |
| `q` | string | 订单号或主线索键 |
| `page/page_size` | integer | 分页 |

**响应**：`rows`、`pagination`、`summary`、`filter_options`。

行字段包括总部池条目 ID、主线索、订单、状态、原因及用户可读标签、进入/关闭时间、锚点门店/城市、来源轮次/决策/规则版本/批次。`summary.current_inventory` 统计所有活动总部池库存，`summary.filtered_total` 统计当前筛选结果。

V1 不提供“重新投放”“分配门店”“领取”或任何总部池写接口。订单核销/退款由内部状态任务自动关闭活动条目；这不是页面操作。

## 16. 标准总部池原因

| 原因码 | 用户文案 | 产生阶段 |
|--------|----------|----------|
| `missing_follow_poi` | 缺少位置锚点 | 主池物化 |
| `anchor_store_unmapped` | 锚点门店无法匹配 | 主池物化 |
| `anchor_geo_invalid` | 锚点城市或经纬度不可用 | 正式分配前置校验 |
| `no_published_rule` | 未匹配可用分配规则 | 规则解析 |
| `all_strategies_disabled` | 当前规则未启用分配策略 | 规则执行 |
| `no_eligible_candidate` | 所有启用策略均无可用门店 | 策略执行 |
| `all_strategies_exhausted` | 所有启用策略均已结束 | 再分配 |
| `data_inconsistency` | 关键事实不一致，待总部治理 | 一致性检查 |

未知历史原因可迁移为 `data_inconsistency` 并保留原值于脱敏 `source_snapshot`，不得向页面显示 `unknown`。
