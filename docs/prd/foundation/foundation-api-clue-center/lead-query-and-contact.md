# 线索查询、指标、导出与联系方式

> 返回 [API 索引](../foundation-api-clue-center.md) · 公共约定见 [common-contract.md](common-contract.md)

## 1. 公共查询参数

Q01、Q02、Q04、Q05、Q07 使用同一筛选语义；不适用的接口可省略部分字段。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `province` | string | 否 | 省份；仅在账号数据范围内生效 |
| `city` | string | 否 | 城市；必须属于所选省份及账号范围 |
| `assigned_store_id` | string | 否 | 跟进门店 ID；不是抖音 `follow_life_account_id` |
| `clue_created_date_start` | date | 否 | 线索生成自然日起，闭区间 |
| `clue_created_date_end` | date | 否 | 线索生成自然日止，包含整日 |
| `store_display_status` | string | 否 | `pending_follow_up`、`followed`、`expired`、`lost`、`verified`、`refunded` |
| `product_type` | string | 否 | 商品口径配置允许的商品类型 |
| `q` | string | 否 | 订单号、脱敏手机号尾号或商品名，最长 100 字符 |
| `page` | integer | 否 | 默认 1 |
| `page_size` | integer | 否 | 默认 20，最大 100 |

单店账号不接收省、市、门店筛选覆盖；服务端始终使用账号范围。多店和管理账号只能在已授权门店集合内收窄，不能扩大范围。

## 2. Q01 `GET /api/v1/clues/filters`

> 消费页面: 线索看板、线索明细
> 数据源: `clue_center_order`、`dim_store`、商品口径配置、当前用户范围
> 权限: A01 或 A02
> 状态: 保留并校正候选项

**请求参数**：无。候选项由当前账号范围决定。

**响应 `data`**：

| 字段 | 类型 | 说明 | 来源 |
|------|------|------|------|
| `assigned_stores` | array | `{store_id, store_name}`，只含可见门店 | `dim_store` + 账号范围 |
| `assigned_provinces` | string[] | 可见门店省份 | `dim_store` |
| `assigned_cities` | string[] | 可见门店城市 | `dim_store` |
| `product_types` | string[] | 当前商品口径下可见值 | `clue_center_order.product_type` |
| `default_product_type` | string | 默认 `all` | 商品口径配置 |
| `store_display_statuses` | string[] | 与列表“线索状态”字段完全一致的六个值 | 固定业务枚举 |

不再返回 `round_statuses`、`verification_statuses`。轮次技术状态不作为店端筛选；核销状态已并入 `store_display_status`。

## 3. Q02 `GET /api/v1/clues/overview`

> 消费页面: 线索看板
> 数据源: `clue_order_metric_fact`、`clue_master_lead`、`clue_assignment_round`、`clue_center_order`
> 权限: A01；按账号范围过滤
> 状态: 变更

**请求参数**：公共筛选参数，不含 `page/page_size/q`。

**响应 `data`**：

| 字段 | 类型 | 说明 | 来源 |
|------|------|------|------|
| `complete_pool_order_count` | integer | 筛选范围内完整主池唯一订单数 | `clue_order_metric_fact.is_complete_pool` |
| `store_pool_lead_count` | integer | 当前存在有效门店轮次的唯一线索数 | `clue_master_lead.pool_location` |
| `headquarters_pool_count` | integer | 当前总部池库存；门店账号返回 0 或不展示 | `clue_headquarters_pool_entry.entry_status` |
| `followed_round_count` | integer | 实际产生任一有效跟进行为的成熟轮次数 | `clue_assignment_round.is_followed` |
| `matured_round_count` | integer | 已到达跟进率观察点的轮次数 | `clue_assignment_round.matured_at` |
| `follow_up_rate` | number | `followed_round_count / matured_round_count` | 轮次聚合 |
| `verified_order_count` | integer | 完整主池中曾达到已核销状态的唯一订单数 | `clue_order_metric_fact.is_ever_verified` |
| `overall_verification_rate` | number | `verified_order_count / complete_pool_order_count` | 订单指标事实 |
| `pending_action_count` | integer | 当前范围内仍待跟进的有效轮次数 | `clue_assignment_round.round_status` |
| `lost_or_expired_count` | integer | 战败、换店、SLA 或保护期到期的关闭轮次数 | `clue_assignment_round.round_status` |
| `metric_definition_version` | string | 指标口径版本 | `clue_order_metric_fact.metric_definition_version` |

页面只展示一个“线索跟进率”，不再返回或展示“跟进比例”和“跟进成功率”两个易混指标。总部池不进入任何门店的轮次分母。

## 4. Q03 `GET /api/v1/clues/metrics/monthly`

> 消费页面: 线索看板经营效果区
> 数据源: `clue_order_metric_fact`
> 权限: A01；门店账号只看到本店实际分配订单的诊断视角，总部账号可看完整主池口径
> 状态: 新增

**请求参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `cohort_month_start` | string `YYYY-MM` | 否 | 默认基线起月或最近 12 个月 |
| `cohort_month_end` | string `YYYY-MM` | 否 | 默认最近完整月份 |
| `province`、`city`、`assigned_store_id` | string | 否 | 组织范围筛选；不得扩大账号范围 |

**响应 `data`**：

| 字段 | 类型 | 说明 | 来源 |
|------|------|------|------|
| `baseline` | object | 2026-01 至 2026-06 合并口径摘要 | 指标事实聚合 |
| `baseline.complete_pool_order_count` | integer | 基线分母 | `is_complete_pool` |
| `baseline.verified_order_count` | integer | 基线分子 | `is_ever_verified` |
| `baseline.overall_verification_rate` | number | 基线总体核销率 | 聚合计算 |
| `operation_launch_month` | string/null | 正式运营启动所在自然月 | 系统经营配置 |
| `rows` | array | 月度队列，按月份升序 | 指标事实聚合 |
| `rows[].cohort_month` | string | 订单下单月份 | `cohort_month` |
| `rows[].cohort_type` | string | `baseline`、`transition`、`operation` | `cohort_type` |
| `rows[].maturity_status` | string | `observing`、`matured` | `maturity_status` |
| `rows[].complete_pool_order_count` | integer | 月度分母 | `is_complete_pool` |
| `rows[].verified_order_count` | integer | 月度分子 | `is_ever_verified` |
| `rows[].overall_verification_rate` | number | 月度总体核销率 | 聚合计算 |
| `first_observation_window` | object/null | 过渡月后连续三个成熟月的合并结果 | 指标事实聚合 |

月份归属严格使用 `order_created_at`，不得使用线索生成、分配或核销时间。

## 5. Q04 `GET /api/v1/clues/metrics/stores`

> 消费页面: 线索看板门店诊断区
> 数据源: `clue_assignment_round`、`clue_order_metric_fact`、`store_score_snapshot`
> 权限: A01；按账号范围
> 状态: 新增

**请求参数**：公共筛选参数，不含 `store_display_status/q`，另含分页。

**响应行字段**：

| 字段 | 类型 | 说明 | 来源 |
|------|------|------|------|
| `store_id` | string | 内部门店 ID | `clue_assignment_round.assigned_store_id` |
| `store_name` | string | 门店名称 | `assigned_store_name_snapshot` |
| `assigned_order_count` | integer | 实际分配给该店的唯一订单数 | 真实轮次聚合 |
| `followed_round_count` | integer | 产生有效跟进的成熟轮次数 | `is_followed` |
| `matured_round_count` | integer | 跟进率成熟轮次数 | `matured_at` |
| `follow_up_rate` | number | 门店线索跟进率 | 聚合计算 |
| `verified_order_count` | integer | 分配后最终核销的成熟唯一订单数 | 轮次 + 指标事实 |
| `matured_order_count` | integer | 核销转化可比较分母 | 轮次 + 指标事实 |
| `verification_conversion_rate` | number | 门店核销转化能力 | 聚合计算 |
| `latest_composite_score` | number/null | 最近评分快照综合分 | `store_score_snapshot.composite_score` |
| `score_snapshot_run_id` | string/null | 评分证据批次 | `store_score_snapshot.snapshot_run_id` |

总部池、试运行、未实际选中门店的策略步骤不进入门店分母。

## 6. Q05 `GET /api/v1/clues/assignment-rounds`

> 消费页面: 线索明细
> 数据源: `clue_center_order`、`clue_assignment_round`
> 权限: A02；按账号范围
> 状态: 变更

**请求参数**：全部公共筛选参数。

**响应行字段**：

| 字段 | 类型 | 说明 | 来源 |
|------|------|------|------|
| `assignment_round_id` | string | 内部定位用，不作为主表重点文案 | `clue_assignment_round.assignment_round_id` |
| `order_id` | string | 订单编号 | `clue_center_order.order_id` |
| `phone_masked` | string | 默认中间四位脱敏 | `clue_center_order.phone_masked` |
| `store_display_status` | string | 六类店端线索状态 | `clue_center_order.store_display_status` |
| `round_no` | integer | 实际分配轮次 | `clue_assignment_round.round_no` |
| `latest_follow_at` | datetime/null | 仅本轮最近跟进时间 | `clue_assignment_round.latest_follow_at` |
| `product_name` | string/null | 商品名称 | `clue_center_order.product_name` |
| `product_type` | string/null | 商品分类 | `clue_center_order.product_type` |
| `clue_created_at` | datetime/null | 线索生成时间 | `clue_center_order.clue_created_at` |
| `round_ended_at` | datetime/null | 本轮失效时间 | `clue_assignment_round.ended_at` |
| `is_current_round` | boolean | 是否当前轮 | 主线索当前轮 + 本轮 ID |
| `can_view_full_phone` | boolean | 当前用户能否读取完整号 | 服务端授权计算 |
| `can_follow_up` | boolean | 当前用户能否保存跟进 | 服务端授权计算 |
| `unavailable_reason` | string/null | 不可跟进原因码 | 订单/池位置/轮次/权限综合判断 |

主表不显示抖音分配门店、当前归属门店、技术轮次 ID 或“距离再分配剩余时间”。跟进门店只在轮次历史中按真实门店名展示。

## 7. Q06 `GET /api/v1/clues/orders/{order_id}`

> 消费页面: 线索跟进详情浮层
> 数据源: `clue_master_lead`、`clue_center_order`、`clue_assignment_round`、`clue_follow_up_record`
> 权限: A02；订单至少有一轮属于账号范围，或账号具有全局线索查看权限
> 状态: 变更

**路径参数**：`order_id`，必填。

**响应 `data`**：

| 字段 | 类型 | 说明 | 来源 |
|------|------|------|------|
| `order_id` | string | 订单编号 | `clue_center_order.order_id` |
| `canonical_clue_id` | string/null | 排查用代表线索 ID | `clue_master_lead.canonical_clue_id` |
| `normalized_order_status` | string | `unknown`、`active`、`verified`、`refunded` | `clue_master_lead.normalized_order_status` |
| `store_display_status` | string | 店端状态 | `clue_center_order.store_display_status` |
| `pool_location` | string | `pending_allocation`、`store_pool`、`headquarters_pool`、`closed` | `clue_master_lead.pool_location` |
| `phone_masked` | string | 始终只返回脱敏号 | `clue_center_order.phone_masked` |
| `can_view_full_phone` | boolean | 当前用户是否可调用 Q08 | 授权计算 |
| `can_follow_up` | boolean | 当前用户是否可调用 F01 | 授权计算 |
| `unavailable_reason` | string/null | 不可联系/跟进原因 | 授权计算 |
| `product_id` | string/null | 商品 ID | `clue_center_order.product_id` |
| `product_name` | string/null | 完整商品名称，详情商品与订单区展示 | `clue_center_order.product_name` |
| `product_type` | string/null | 商品类型 | `clue_center_order.product_type` |
| `author_nickname` | string/null | 带货账号昵称 | `clue_center_order.author_nickname` |
| `order_created_at` | datetime/null | 下单时间，不称为线索生成时间 | `clue_center_order.order_created_at` |
| `clue_created_at` | datetime/null | 线索生成时间，必要时在历史/排查区单独展示 | `clue_center_order.clue_created_at` |
| `verified_at` | datetime/null | 首次核销时间 | `clue_center_order.verified_at` |
| `rounds` | array | 按 `round_no` 升序的全部真实轮次 | `clue_assignment_round` |
| `rounds[].strategy_type` | string | 三类固定策略之一 | `strategy_type` |
| `rounds[].strategy_label` | string | 如“15公里城市优选”，使用当时参数快照 | 规则/决策快照 |
| `rounds[].assigned_store_id` | string | 跟进门店 ID | `assigned_store_id` |
| `rounds[].assigned_store_name` | string | 真实门店名称，不写“本店/其他店” | `assigned_store_name_snapshot` |
| `rounds[].assigned_at` | datetime | 分配时间 | `assigned_at` |
| `rounds[].round_status` | string | 本轮事实状态 | `round_status` |
| `rounds[].ended_at` | datetime/null | 失效/关闭时间 | `ended_at` |
| `rounds[].end_reason` | string/null | 再分配或关闭原因 | `end_reason` |
| `rounds[].follow_ups` | array | 本轮未删除跟进记录，按时间升序 | `clue_follow_up_record` |

`rounds[].follow_ups[]` 返回 `follow_up_record_id`、`follow_action`、`note`、`action_at`、`operator_username`、`can_delete`。普通用户不返回已软删除内容；最高管理员可额外收到删除标识和脱敏删除元数据用于审计排查。

## 8. Q07 `POST /api/v1/clues/assignment-round-exports`

> 消费页面: 线索明细工具栏
> 数据源: Q05 相同 + `clue_contact` + `clue_operation_audit_log`
> 权限: A02；需独立 `clue.export_plaintext_phone` 动作权限
> 状态: 新增，替代 GET 导出

**请求体**：公共筛选参数，不含分页；另含：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `format` | string | 是 | V1 为 `csv`；实现真实 XLSX 后可增加 `xlsx` |
| `include_plain_phone` | boolean | 是 | 默认 `true`，但仍逐行检查账号范围与当前轮权限 |
| `reason` | string | 是 | 导出用途，1-200 字符，进入脱敏审计摘要 |

**响应**：文件下载。列至少包括订单号、完整/空联系方式、线索状态、分配轮次、本轮跟进时间、商品、类型、线索生成时间、本轮失效时间和跟进门店。

**约束**：

- 只导出当前账号可见范围和当前筛选全部结果，不受当前页限制。
- `include_plain_phone=true` 不表示无条件输出明文。仅对当前有效轮次且用户有完整号权限的行写明文，其余为空；不得回退为脱敏字符串冒充完整号。
- 整次导出写一条审计摘要，并记录总行数、明文行数、拒绝行数和筛选摘要，不记录文件内容。
- 无结果返回 `CLUE_40001` 或 204 由 PRD 决定；推荐返回带表头的空文件以保持操作可预期。

## 9. Q08 `POST /api/v1/clues/orders/{order_id}/phone-access`

> 消费页面: 线索明细与跟进详情
> 数据源: `clue_contact`、`clue_master_lead`、`clue_assignment_round`、账号范围、`clue_operation_audit_log`
> 权限: A02 + 当前有效轮次动作授权
> 状态: 新增，替代 GET 手机号

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `assignment_round_id` | string | 是 | 前端当前展示的轮次，必须等于主线索当前轮次 |
| `operation` | string | 是 | `reveal` 或 `copy`，分别审计 |
| `state_version` | integer | 是 | 当前详情返回的主线索状态版本 |

**响应 `data`**：

| 字段 | 类型 | 说明 | 来源 |
|------|------|------|------|
| `order_id` | string | 订单号 | `clue_contact.order_id` |
| `assignment_round_id` | string | 已授权当前轮 | `clue_assignment_round.assignment_round_id` |
| `phone` | string | 完整手机号；仅本响应返回 | `clue_contact.phone_plain` |
| `phone_masked` | string | 脱敏号 | `clue_contact.phone_masked` |
| `access_expires_at` | datetime | 建议前端最晚清除明文时间，默认 5 分钟 | 服务计算 |

服务端在返回前再次锁定并校验订单终态、池位置、当前轮次、门店归属和动作权限。拒绝也写脱敏审计；成功响应不得被 CDN、浏览器持久缓存或服务日志记录。
