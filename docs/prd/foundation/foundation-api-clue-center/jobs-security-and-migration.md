# 内部任务、外部接口、安全与一次性迁移

> 返回 [API 索引](../foundation-api-clue-center.md) · 公共约定见 [common-contract.md](common-contract.md)

## 1. 内部接口边界

- `/api/v1/internal/*` 只允许 Railway 私网内的 worker 服务身份访问，公网路由不可达。
- 服务身份使用可轮换凭证或平台工作负载身份；凭证、抖音 token 和应用密钥禁止写入 URL、日志、审计或错误响应。
- 每个命令必须提供 `Idempotency-Key`，并将调用方、任务名、时间分片和请求摘要绑定。
- 内部接口只负责提交或执行明确任务，不提供任意 SQL、任意状态修改或任意时间窗口无限扫描。
- 大任务按城市、日期或稳定业务键分片；批次结果可部分失败并只重试失败项。

## 2. J01 `POST /api/v1/internal/clue-center/materializations`

> 调用方: 自动采集 worker、受控重建 worker
> 读取: `raw_douyin_clues`、`raw_douyin_refund_record`、原始订单/核销共享表、POI/门店/商品共享维表
> 写入: `clue_source_record_link`、`clue_master_lead`、`clue_contact`、`clue_order_status_event`、`clue_center_order`

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source_run_id` | string | 是 | 采集或重建来源运行 ID |
| `mode` | string | 是 | `incremental` 或 `rebuild` |
| `window_start` | datetime | 是 | 本分片证据起点 |
| `window_end` | datetime | 是 | 本分片证据终点，开区间 |
| `source_record_keys` | string[] | 否 | 精确重放时使用，最大 1,000 |

**响应 `data`**：返回 `processed_source_records`、`linked_records`、`isolated_records`、`contact_upserts`、`status_events_appended`、`projection_refreshes`、`pending_allocation_count`、`terminal_without_round_count`、`failed_count` 和脱敏 `error_summary`。

**事务**：按主线索/订单分组提交。每条非空订单源记录必须有且只有一个链接；缺订单源记录进入隔离主线索，不静默丢弃。首次已核销/已退款主线索直接关闭，不创建轮次。

## 3. J02 `POST /api/v1/internal/clue-center/order-status-transitions`

> 调用方: 订单、核销、退款采集完成事件；终态补偿任务
> 读取: `clue_order_status_event`、`clue_master_lead`
> 写入: 主线索、活动轮次、活动总部池条目、指标事实、查询投影和审计/可靠事件

请求体包含 `source_run_id`、`event_ids[]`（最大 1,000）和 `as_of`。响应按 `verified_closed`、`refunded_closed`、`unchanged`、`skipped_stale`、`failed` 汇总。

同一订单事件按 `precedence_rank`、`effective_at`、`observed_at` 排序。已退款/已核销终态优先于 SLA、保护期和门店动作；重复事件由 `event_key` 幂等去重。

## 4. J03 `POST /api/v1/internal/clue-allocation/formal-cycles`

> 调用方: 可配置自动分配调度器、跟进/到期后的可靠待办消费者
> 写入: 规则绑定、评分引用、正式批次/执行项、决策、候选、真实轮次、总部池和审计

**请求体**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `scheduled_key` | string | 是 | 计划时间片或待办消费键 |
| `trigger_type` | string | 是 | `new_lead`、`next_strategy`、`rebuild` |
| `lead_keys` | string[] | 否 | 事件驱动精确范围，最大 500 |
| `city_code` | string/null | 否 | 扫描任务分片 |
| `max_items` | integer | 否 | 默认 500，最大 2,000 |
| `as_of` | datetime | 是 | 任务判定时间 |

**执行规则**：

1. 排除订单终态、源记录隔离和已有活动轮次。
2. 锚点不可用时直接进入总部池并记录标准原因。
3. 首次分配锁定规则版本；后续沿用绑定版本。
4. 从下一未耗尽启用策略开始，排除历史门店。
5. 策略无候选只写决策/候选证据，不创建空轮次。
6. 实际选中门店才创建连续 `round_no`；所有策略耗尽进入总部池。

单条线索在独立事务中完成，数据库唯一约束保证同一主线索最多一条活动轮次或一个活动总部池条目。批次返回六类数量和失败项游标。

## 5. J04 `POST /api/v1/internal/clue-allocation/round-expirations`

> 调用方: 可配置 SLA/保护期扫描任务
> 读取/写入: `clue_assignment_round`、`clue_master_lead`、正式分配待办

请求体：`scheduled_key`、`as_of`、可选 `city_code/store_id`、`max_items`。执行两个互斥扫描：

- `pending_follow_up` 且启用自动到期、`sla_expires_at <= as_of`：关闭为 `sla_expired`。
- `protected` 且 `protection_expires_at <= as_of`、订单仍未终态：关闭为 `protection_expired`。

SLA 配置为无限时 `sla_expires_at=null`，永不进入首类扫描。任务关闭旧轮后只写下一策略待办，由 J03 创建新轮或总部池条目，避免两个任务同时创建轮次。

## 6. J05 `POST /api/v1/internal/clue-allocation/metric-refreshes`

> 调用方: 每日评分计划、状态事件回补、重建收尾
> 写入: `store_score_snapshot_run`、`store_score_snapshot`、`clue_order_metric_fact`、`clue_center_order`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `refresh_type` | string | 是 | `store_scores`、`order_metrics`、`projections`、`all` |
| `as_of` | datetime | 是 | 口径时间点 |
| `rule_version_ids` | string[] | 否 | 评分范围 |
| `order_ids` | string[] | 否 | 事件回补范围，最大 2,000 |
| `cohort_months` | string[] | 否 | 月度指标回补范围 |

评分只使用正式轮次和成熟样本；总部池、试运行和旧 legacy 轮次不进入门店评分。订单指标按唯一订单和下单月份回补，历史曾核销事实不得因后续退款被抹除。

## 7. J06 `POST /api/v1/internal/clue-allocation/data-quality-checks`

> 调用方: 每日数据质量计划、重建收尾
> 读取: 全部线索 Foundation 表及共享门店/POI 表
> 写入: 任务日志/现有监控存储；V1 不自动修复业务事实

检查至少包括：

- 每条 `raw_douyin_clues` 是否恰好一条源映射。
- 非空订单是否唯一主线索；隔离线索是否未进入完整主池。
- 终态主线索是否无活动轮次/活动总部池。
- 活跃主线索是否唯一落在待分配、门店池或总部池。
- 活动轮次是否唯一、轮次号是否连续、当前轮引用是否一致。
- `follow_poi_id` 映射率、锚点城市/经纬度完整率和门店服务资格。
- 试运行是否零正式轮次、零正式总部池和零经营指标污染。
- 明文手机号是否只存在于 `clue_contact`。

响应返回检查版本、总数、各问题数和报告 ID；A12 读取最近报告摘要。

## 8. J07 `POST /api/v1/admin/sync/clue-center/rebuild-previews`

> 消费页面: 数据同步中的线索中心维护
> 权限: D10 + 最高管理员
> 写入: 短期预览证据、审计

请求体：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `scope` | string | 是 | `all`、`date_range`、`order_ids` |
| `date_start/date_end` | date/null | 条件 | 日期范围重建 |
| `order_ids` | string[] | 条件 | 精确重建，最大 2,000 |
| `rebind_rule_versions` | boolean | 是 | 是否按当前发布规则重新绑定 |
| `recompute_scores` | boolean | 是 | 是否重算评分 |
| `remove_legacy_rounds` | boolean | 是 | V1 正式切换固定为 true |

响应包含预计源记录、主线索、联系人、状态事件、删除 legacy 轮次、重建正式轮次、总部池变化和指标回补数量，以及绑定版本前后变化样例、`preview_token` 和失效时间。

## 9. J08 `POST /api/v1/admin/sync/clue-center/rebuilds`

> 消费页面: 数据同步中的线索中心维护
> 权限: D10 + 最高管理员
> 写入: `formal_rebuild` 批次及全部受影响 Foundation 表、审计

请求头：`Idempotency-Key`。请求体：`preview_token`、`confirmation_text`、`reason`。服务端重新计算范围摘要，任何上游状态变化使预览失效。

响应立即返回 `cycle_id`、`cycle_status=pending` 和预览摘要；异步执行后由 A05/A06 查询。重建必须支持按稳定分片断点续跑，不能依赖一次 30 天大事务。

## 10. 调度配置

实际频率由后台同步/运行配置管理，不在代码中硬编码。配置至少区分：

| 任务 | 推荐默认值 | 可配置项 |
|------|------------|----------|
| 线索增量采集 | 10-30 分钟 | 时区、频率、回看窗口、启停 |
| 订单/核销/退款补拉 | 30-60 分钟 + 每日回补 | 频率、回看天数、分片天数 |
| 联系方式解密 | 每批采集后异步紧随 | 批量大小、重试、启停 |
| 正式分配 | 新线索物化后事件触发 + 定时补偿 | 批量大小、城市分片、启停 |
| SLA/保护期扫描 | 5-15 分钟 | 频率、批量大小、启停 |
| 门店评分 | 每日低峰 | 执行时间、时区、启停 |
| 指标与投影 | 事件增量 + 每日全量校验 | 批量大小、执行时间 |
| 数据质量检查 | 每日低峰 + 重建收尾 | 执行时间、阈值告警 |

规则中的 SLA 为无限时只影响相应轮次，不停止其他线索的到期扫描。

## 11. 外部抖音接口

外部接口只由 collector/client 调用，不向浏览器透传。URL 以当前官方开放平台文档和 `douyin_client.py` 常量为准。

### 11.1 E01 线索查询（外部引用）

- **接口**：`GET https://open.douyin.com/goodlife/v1/open_api/crm/clue/query/`
- **Scope**：`life.crm.clue.query`
- **用途**：原始线索、订单关联、`follow_poi_id` 锚点、商品和来源场景。
- **关键字段**：`clue_id`、`order_id`、`create_time_detail`、`modify_time`、`telephone`、`enc_telephone`、`follow_poi_id`、`product_id/name`、`author_nickname`、`leads_page`、`flow_type`、`flow_entrance`、`content_id`、`video_id`。
- **约束**：结束时间至少早于当前 10 分钟；单窗口不超过 365 天；页大小最大 100；接近 10,000 行自动缩小时间窗口。

### 11.2 E02 订单查询（外部引用）

- **接口**：`GET https://open.douyin.com/goodlife/v1/trade/order/query/`
- **用途**：订单号、下单时间、原始订单状态、销售店、商品和券关系。
- **关键字段**：`order_id`、`order_status`、`create_order_time`、`update_order_time`、`poi_id`、`sku_id`、商品/券明细。
- **约束**：按时间窗口和游标分片；同一订单多次观察追加状态事件，不覆盖历史证据。

### 11.3 E03 核销记录查询（外部引用）

- **接口**：`GET https://open.douyin.com/goodlife/v1/fulfilment/certificate/verify_record/query/`
- **用途**：已核销终态、核销门店和时间证据。
- **关键字段**：`verify_id`、`certificate_id`、`verify_status`、`verify_time`、`verify_poi_id/name`。
- **约束**：通过订单券关系归并到唯一订单；撤销等非 V1 主流程状态保留原始事件，不自行猜测终态。

### 11.4 E04 售后退款查询（外部引用·需补完整闭环）

- **接口**：`GET https://open.douyin.com/goodlife/v1/akte/after_sale/order/query/`
- **用途**：建立独立退款原始事实和退款终态。
- **关键字段**：订单 ID、售后/退款 ID、原始状态、申请/完成时间、退款金额和原始 payload。
- **改动项**：必须写入 `raw_douyin_refund_record`，按窗口分片保存断点；不能只依赖订单券上的退款金额推断全部退款生命周期。

### 11.5 E05 密文解密（外部引用）

- **接口**：`POST https://open.douyin.com/goodlife/v1/open/common_biz/crypto/decrypt/batch/`
- **用途**：后台静默解密 `enc_telephone` 并写入 `clue_contact.phone_plain`。
- **约束**：批量请求和响应不写日志；失败只保存标准错误码；投影和普通 API 永不返回批量解密原文。

## 12. 一次性迁移与切换顺序

1. 冻结线索写任务，记录源表水位和当前 Foundation 表快照。
2. 创建目标表并迁移退款原始证据、源映射、主线索、联系方式和状态事件。
3. 迁移规则、发布版本、固定策略、门店组、评分运行与快照。
4. 迁移试运行/正式批次、逐线索项、决策和可证明候选。
5. 仅保留新引擎正式轮次；删除全部 `execution_mode=legacy` 轮次和旧物化轮次。
6. 迁移五类可证明跟进记录、总部池和操作审计；无法证明的旧枚举进入质量清单。
7. 从事实全量重建查询投影与订单指标，不从旧看板百分比倒推。
8. 运行 J06 全量一致性检查并对账完整主池、活动轮次、总部池、手机号位置和指标。
9. 切换 API/worker 到唯一新模型，删除旧引擎入口、兼容字段、旧计划任务和旧路由。
10. 恢复增量采集，从冻结水位续跑并再次执行状态/分配补偿。

## 13. 切换验收门槛

- 原始线索源记录映射覆盖率 100%；缺订单记录进入隔离，不丢失。
- 非空订单唯一主线索；完整主池唯一订单数与源事实对账一致。
- 任一活跃主线索最多一条活动真实轮次；轮次号连续且无“双第 1 轮”。
- 终态订单无活动轮次、无活动总部池；首次已终态订单从未创建轮次。
- 所有活跃非隔离线索唯一落在待分配、门店池或总部池。
- 试运行零正式状态副作用；legacy 轮次、任务和接口数量为 0。
- 明文手机号只存在 `clue_contact`；日志、投影、异常和审计扫描无明文泄漏。
- 总体核销率按唯一订单、下单月份和成熟窗口可复算；总部池不进入门店分母。
- 全量自动化、前端生产构建、本地 PostgreSQL 集成验收和两个角色浏览器验收通过后，方可进入部署。
