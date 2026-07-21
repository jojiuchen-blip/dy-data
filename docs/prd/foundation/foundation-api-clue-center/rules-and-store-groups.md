# 分配规则、版本、固定策略与门店组

> 返回 [API 索引](../foundation-api-clue-center.md) · 公共约定见 [common-contract.md](common-contract.md)

## 1. 权限和不变量

- D05 页面权限允许读取；普通管理员默认只读。
- 创建、更新、发布、退役和成员替换只允许最高管理员或 DYDATA-32 明确授予的等价动作权限。
- 规则按 `anchor_store > store_group > city > global` 匹配优先级选择。
- 主线索首次正式分配时写入 `clue_lead_rule_version_binding`；后续规则修改不切换既有绑定。
- 每个版本必须包含三类固定策略配置：`sales_store_priority`、`city_radius_best`、`city_fallback`。类型不可新增、替换或改名；可启停、排序和配置参数。
- 发布版本及其策略配置不可更新，只能新建草稿或退役。
- 规则与门店组采用停用而非物理删除历史证据。

## 2. 公共规则对象

### 2.1 `rule`

| 字段 | 类型 | 说明 | 来源 |
|------|------|------|------|
| `rule_id` | string | 规则业务 ID | `clue_allocation_rule.rule_id` |
| `rule_name` | string | 规则名称 | `rule_name` |
| `scope_type` | string | `global`、`city`、`store_group`、`anchor_store` | `scope_type` |
| `scope_key` | string | 规范化范围键 | `scope_key` |
| `scope_city_code` | string/null | 城市范围 | `scope_city_code` |
| `scope_store_group_id` | string/null | 门店组范围 | `scope_store_group_id` |
| `scope_anchor_store_id` | string/null | 锚点门店范围 | `scope_anchor_store_id` |
| `is_enabled` | boolean | 是否参与新线索规则匹配 | `is_enabled` |
| `current_published_version_id` | string/null | 当前发布版本 | `current_published_version_id` |
| `description` | string/null | 规则说明 | `description` |
| `bound_lead_count` | integer | 当前历史绑定数量，只读聚合 | `clue_lead_rule_version_binding` |
| `state_version` | integer | 乐观锁版本 | `state_version` |
| `gmt_modified` | datetime | 最近修改时间 | `gmt_modified` |

### 2.2 `rule_version`

| 字段 | 类型 | 说明 | 来源 |
|------|------|------|------|
| `rule_version_id` | string | 版本业务 ID | `clue_allocation_rule_version.rule_version_id` |
| `rule_id` | string | 所属规则 | `rule_id` |
| `version_no` | integer | 规则内递增版本号 | `version_no` |
| `version_status` | string | `draft`、`published`、`retired` | `version_status` |
| `is_auto_expiry_enabled` | boolean | 是否启用 SLA 自动到期 | `is_auto_expiry_enabled` |
| `first_follow_up_sla_hours` | integer/null | 首次跟进 SLA；无限时为 null | `first_follow_up_sla_hours` |
| `protection_days` | integer | 核销保护期，默认 7 | `protection_days` |
| `conversion_weight` | number | 核销转化权重，默认 0.7 | `conversion_weight` |
| `follow_24h_weight` | number | 24 小时有效跟进率权重，默认 0.3 | `follow_24h_weight` |
| `lookback_days` | integer | 评分回看窗口 | `lookback_days` |
| `min_samples` | integer | 门店自有样本最小值 | `min_samples` |
| `score_definition_version` | string | 评分口径版本 | `score_definition_version` |
| `config_hash` | string | 完整配置摘要 | `config_hash` |
| `change_note` | string/null | 变更说明 | `change_note` |
| `strategies` | array | 恰好三条固定策略 | `clue_allocation_strategy_config` |
| `state_version` | integer | 草稿乐观锁版本 | `state_version` |
| `published_at` | datetime/null | 发布时间 | `published_at` |
| `retired_at` | datetime/null | 退役时间 | `retired_at` |

### 2.3 `strategy`

| 字段 | 类型 | 说明 | 来源 |
|------|------|------|------|
| `strategy_config_id` | string | 配置业务 ID；新草稿可省略 | `strategy_config_id` |
| `strategy_type` | string | 三类固定值之一 | `strategy_type` |
| `is_enabled` | boolean | 是否启用 | `is_enabled` |
| `execution_order` | integer | 启用策略中的唯一顺序 | `execution_order` |
| `radius_km` | number/null | 销售店优先/城市半径优选的可配置半径 | `radius_km` |
| `candidate_limit` | integer/null | 候选证据上限，不改变应评估范围 | `candidate_limit` |
| `is_exclude_sales_store` | boolean | 城市半径优选是否排除销售店；默认 true | `is_exclude_sales_store` |
| `is_exclude_historical_store` | boolean | 是否排除历史已分配门店；城市策略必须 true | `is_exclude_historical_store` |
| `params` | object | 预留高级参数；未知键发布时拒绝 | `params_json` |

## 3. R01 `GET /api/v1/admin/clue-allocation/rule-options`

> 数据源: `dim_store`、`clue_store_group`、`clue_store_group_member`
> 权限: D05
> 状态: 新增

返回 `cities[]`、`anchor_stores[]`、`store_groups[]`。门店候选仅含具备 POI 映射且可作为锚点范围的门店；不可服务或地理无效门店可保留在只读诊断信息中，但不得作为可选值。

| 字段 | 类型 | 说明 |
|------|------|------|
| `cities[].city_code` | string | 稳定城市代码 |
| `cities[].city_name` | string | 城市名 |
| `anchor_stores[].store_id` | string | 内部门店 ID |
| `anchor_stores[].store_name` | string | 门店名称 |
| `anchor_stores[].city_code` | string/null | 门店城市代码 |
| `anchor_stores[].geo_status` | string | `valid` 或数据质量状态 |
| `store_groups[].store_group_id` | string | 门店组 ID |
| `store_groups[].group_name` | string | 门店组名 |
| `store_groups[].active_member_count` | integer | 当前活动成员数 |

## 4. R02-R05 规则身份接口

### 4.1 R02 `GET /api/v1/admin/clue-allocation/rules`

**请求参数**：`scope_type`、`is_enabled`、`q`、`page`、`page_size`。

**响应**：分页 `rule` 列表；每行附 `current_published_version_no/status`。普通管理员和最高管理员响应结构相同，另返回 `capabilities.can_manage_rules` 供 UI 控制，但服务端仍独立鉴权。

### 4.2 R03 `POST /api/v1/admin/clue-allocation/rules`

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `rule_name` | string | 是 | 1-100 字 |
| `scope_type` | string | 是 | 四类范围之一 |
| `scope_city_code` | string/null | 条件 | `city` 时唯一必填 |
| `scope_store_group_id` | string/null | 条件 | `store_group` 时唯一必填 |
| `scope_anchor_store_id` | string/null | 条件 | `anchor_store` 时唯一必填 |
| `description` | string/null | 否 | 最多 500 字 |

创建时生成唯一 `scope_key`。同一范围只允许一条规则身份，冲突返回 `CLUE_40906`。响应为完整 `rule`。

### 4.3 R04 `GET /api/v1/admin/clue-allocation/rules/{rule_id}`

响应包含 `rule`、按版本号降序的 `versions[]`、每个版本的 `bound_lead_count` 和 `capabilities`。发布版本必须返回完整策略快照，不从当前默认值动态拼接。

### 4.4 R05 `PUT /api/v1/admin/clue-allocation/rules/{rule_id}`

请求体全量包含 `rule_name`、`description`、`is_enabled`、`state_version`。范围身份创建后不可修改；需要不同范围时新建规则。停用只影响尚未绑定的新线索。

## 5. R06-R10 版本生命周期接口

### 5.1 R06 `POST /api/v1/admin/clue-allocation/rules/{rule_id}/versions`

**请求体**：完整 `rule_version` 可写字段及恰好三条 `strategies`；不传 ID、状态、哈希和审计字段。新版本默认为 `draft`，版本号服务端递增。

### 5.2 R07 `PUT /api/v1/admin/clue-allocation/rule-versions/{rule_version_id}`

仅 `draft` 可全量覆盖。请求必须带 `state_version` 和完整三条策略；服务端重新计算 `config_hash`。发布/退役版本返回 `CLUE_40905`。

### 5.3 R08 `DELETE /api/v1/admin/clue-allocation/rule-versions/{rule_version_id}`

仅允许从未发布、未被线索绑定、未被评分或批次引用的草稿。删除前写普通管理审计；不允许删除发布/退役历史。

### 5.4 R09 `POST /api/v1/admin/clue-allocation/rule-versions/{rule_version_id}/publish`

**请求头**：`Idempotency-Key`。

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `state_version` | integer | 是 | 草稿当前版本 |
| `confirmation_text` | string | 是 | UI 明确确认，不使用普通保存动作代替 |

发布校验：

1. 三类固定策略恰好各一条，至少一条启用。
2. 启用策略顺序唯一；半径、SLA、保护期、样本窗口合法。
3. 两个评分权重均非负且之和为 1。
4. 城市策略必须排除历史门店；城市半径优选默认排除销售店。
5. 范围引用的城市、门店组或锚点门店存在且可用。
6. 计算哈希后再锁定发布；同一规则只有一个当前发布版本。

发布、退役旧版本、更新规则当前版本指针和写审计在一个事务中完成。已绑定旧版本线索不切换。

### 5.5 R10 `POST /api/v1/admin/clue-allocation/rule-versions/{rule_version_id}/retire`

请求包含 `state_version` 和 `reason`。退役后该范围的新线索按优先级回退到下一可用规则；既有绑定继续沿用退役版本完成后续轮次。若退役将导致无任何全局已发布规则，返回业务确认错误，由 PRD 决定是否允许强制操作；V1 推荐禁止。

## 6. 门店组对象

| 字段 | 类型 | 说明 | 来源 |
|------|------|------|------|
| `store_group_id` | string | 门店组 ID | `clue_store_group.store_group_id` |
| `group_name` | string | 名称 | `group_name` |
| `description` | string/null | 说明 | `description` |
| `is_enabled` | boolean | 新规则匹配是否可用 | `is_enabled` |
| `sort_order` | integer | 管理页顺序 | `sort_order` |
| `active_member_count` | integer | 当前成员数 | 成员聚合 |
| `members` | array | 详情接口返回当前和历史成员 | `clue_store_group_member` |

## 7. R11-R15 门店组接口

### 7.1 R11 `GET /api/v1/admin/clue-allocation/store-groups`

请求参数：`is_enabled`、`q`、`page`、`page_size`。响应为分页门店组摘要。

### 7.2 R12 `POST /api/v1/admin/clue-allocation/store-groups`

请求体：`group_name`、`description`、`sort_order`、可选 `initial_store_ids[]`。同名冲突返回 `CLUE_40906`；每个门店同一时刻只允许一个活动门店组关系。

### 7.3 R13 `GET /api/v1/admin/clue-allocation/store-groups/{store_group_id}`

响应包含门店组、`active_members[]` 和分页/按需加载的 `membership_history[]`。成员字段包含 `member_id`、`store_id`、`store_name`、`active_from`、`active_to`、`is_active`。

### 7.4 R14 `PUT /api/v1/admin/clue-allocation/store-groups/{store_group_id}`

全量更新 `group_name`、`description`、`is_enabled`、`sort_order`。服务端锁定门店组行后更新；被发布规则引用的门店组可以停用，但不得物理删除；停用不改写历史绑定或决策。

### 7.5 R15 `PUT /api/v1/admin/clue-allocation/store-groups/{store_group_id}/members`

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `store_ids` | string[] | 是 | 完整活动成员集合，最多 2,000 |
| `expected_member_hash` | string | 是 | R13 返回的当前活动成员集合摘要，用于防止并发覆盖 |
| `change_note` | string | 是 | 成员变更原因 |

服务端锁定门店组并校验 `expected_member_hash` 后比较新旧集合：移除项写 `active_to`，新增项插入新历史行，不覆盖旧关系；若某门店已在其他活动门店组，返回冲突并列出脱敏可诊断信息。响应为更新后的门店组详情及新成员摘要。

## 8. 规则命中与版本绑定

规则匹配和绑定只由正式分配任务执行，不提供管理端直接写绑定接口：

1. 根据主线索锚点门店、锚点城市和活动门店组关系，按优先级寻找已启用规则的当前发布版本。
2. 首次正式批次写入 `clue_lead_rule_version_binding`，记录范围类型、范围键、优先级和批次。
3. 后续轮次始终读取该绑定版本，即使版本已退役或门店组成员后来变化。
4. 受控全量重建若选择“重新绑定规则”，必须在 J07 预览中逐条展示前后版本，并由 J08 写新绑定证据和高风险审计；不得静默覆盖。
