# `clue_order_metric_fact` - 订单经营指标事实

## 业务用途

按唯一订单固化完整主池分母、历史核销分子、下单自然月和 30 天成熟窗口，为 2026 年 1 至 6 月基线、过渡月及上线后对比提供稳定口径。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `order_id` | varchar(64) | NO | - | 唯一订单键 |
| `lead_key` | varchar(64) | NO | - | 主线索业务键 |
| `order_created_at` | timestamptz | NO | - | 用户下单时间 |
| `cohort_month` | date | NO | - | 下单自然月首日 |
| `is_complete_pool` | smallint | NO | 1 | 是否计入完整主池分母 |
| `complete_pool_entered_at` | timestamptz | NO | - | 首次进入完整主池时间 |
| `first_store_pool_at` | timestamptz | YES | NULL | 首次进入门店跟进池时间 |
| `first_headquarters_pool_at` | timestamptz | YES | NULL | 首次进入总部池时间 |
| `is_ever_verified` | smallint | NO | 0 | 历史上是否曾核销 |
| `first_verified_at` | timestamptz | YES | NULL | 首次核销时间 |
| `is_refunded` | smallint | NO | 0 | 当前是否退款终态 |
| `first_refunded_at` | timestamptz | YES | NULL | 首次退款终态时间 |
| `terminal_status` | smallint | NO | 0 | 0未终态、1已核销、2已退款 |
| `maturity_at` | timestamptz | NO | - | 下单后 30 天观察点 |
| `maturity_status` | smallint | NO | 0 | 0观察中、1已成熟 |
| `cohort_type` | smallint | NO | 0 | 0普通、1基线、2过渡月、3上线后观察 |
| `operation_launch_date` | date | YES | NULL | 计算当前周期所用正式运营日期 |
| `metric_definition_version` | varchar(32) | NO | `v1` | 指标定义版本 |
| `last_status_observed_at` | timestamptz | YES | NULL | 最近订单状态证据时间 |
| `fact_refreshed_at` | timestamptz | NO | CURRENT_TIMESTAMP | 最近事实刷新时间 |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 更新时间 |

## 索引

- `pk_clue_order_metric_fact` (`id`)
- `uk_clue_order_metric_fact_order_id` (`order_id`)
- `idx_clue_order_metric_fact_cohort` (`cohort_month`, `maturity_status`)
- `idx_clue_order_metric_fact_verified` (`cohort_month`, `is_ever_verified`)
- `idx_clue_order_metric_fact_type` (`cohort_type`, `maturity_status`)
- `idx_clue_order_metric_fact_lead` (`lead_key`)

## 关系与指标约束

- 一条非空订单只出现一次，不按轮次或跟进记录扩张。
- 总体核销率分子使用 `is_ever_verified=1`，退款不会抹除“历史曾核销”的事实。
- 基线固定为 2026-01-01 至 2026-06-30 的全部成熟订单合并计算，不取月度百分比平均。
- 总部池订单仍属于完整主池；只有门店级指标查询才排除总部池。
- `maturity_at=order_created_at+30 days`，成熟前只能显示观察中。

## 页面字段映射

- 线索看板：线索总数、核销数、总体核销率及后续经营对比。
- 分配效果分析：基线、过渡月和连续三个成熟月。
- 门店评分的核销转化分母从实际轮次和成熟订单另行聚合，不直接把总部池归入门店。

## 迁移说明

本表为新增。首次建立时从完整主池、订单、核销和退款状态事件全量回算；后续状态事件增量回补。不得从现有轮次看板百分比倒推历史事实。

## 使用接口

Phase 4 回填，覆盖看板指标和经营效果查询。
