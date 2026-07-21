# `clue_order_status_event` - 订单状态事件

## 业务用途

以不可变事件流保存订单从不同抖音数据源观察到的状态，支持终态优先、重复事件幂等、历史回补和状态冲突排查。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `event_id` | varchar(64) | NO | - | 事件业务 ID |
| `event_key` | varchar(160) | NO | - | 来源+对象+状态+观测时间的幂等键 |
| `lead_key` | varchar(64) | NO | - | 主线索业务键 |
| `order_id` | varchar(64) | YES | NULL | 订单编号 |
| `raw_status` | varchar(128) | YES | NULL | 平台原始状态 |
| `normalized_status` | smallint | NO | 0 | 0未知、1可促核销、2已核销、3已退款 |
| `status_source` | smallint | NO | 1 | 1线索、2订单、3核销、4退款 |
| `source_record_key` | varchar(128) | YES | NULL | 原始证据键 |
| `source_run_id` | varchar(64) | YES | NULL | 采集运行标识 |
| `observed_at` | timestamptz | NO | - | 平台状态被观察到的时间 |
| `effective_at` | timestamptz | YES | NULL | 平台业务状态生效时间 |
| `precedence_rank` | smallint | NO | 0 | 归一化优先级，终态高于活动态 |
| `is_terminal` | smallint | NO | 0 | 1表示核销或退款终态 |
| `payload_hash` | char(64) | YES | NULL | 来源证据摘要 |
| `evidence_snapshot` | jsonb | NO | `{}` | 最小必要来源证据，不保存密钥 |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 仅兼容必备字段，事件内容禁止更新 |

## 索引

- `pk_clue_order_status_event` (`id`)
- `uk_clue_order_status_event_event_id` (`event_id`)
- `uk_clue_order_status_event_event_key` (`event_key`)
- `idx_clue_order_status_event_lead_observed` (`lead_key`, `observed_at` DESC)
- `idx_clue_order_status_event_order_terminal` (`order_id`, `is_terminal`, `observed_at` DESC)

## 关系与约束

- 同一业务事件重复消费必须返回已有结果，不重复关闭轮次或创建下一轮。
- 已核销/已退款事件优先于战败、换店、SLA 和保护期事件；晚到的低优先级活动状态不得重开终态订单。
- 事件写入后只允许追加纠正事件，不允许修改或删除原事件。

## 页面与任务映射

- 详情页订单状态由主线索/投影读取；后台排查可追溯事件证据。
- 状态归一化任务写入，状态机消费并更新主线索、活动轮次和指标事实。

## 迁移说明

由 `clue_order_status_events` 迁移并补充业务 ID、来源键、优先级、终态标记和证据摘要。

## 使用接口

- `POST /api/v1/internal/clue-center/materializations` — 从线索、订单、核销和退款证据追加幂等状态事件。
- `POST /api/v1/internal/clue-center/order-status-transitions` — 按优先级消费事件并迁移主线索、轮次、总部池和指标。
- `POST /api/v1/admin/sync/clue-center/rebuilds` — 从原始事实重建可证明事件流。
- 不提供页面写接口；原事件禁止更新或删除。
