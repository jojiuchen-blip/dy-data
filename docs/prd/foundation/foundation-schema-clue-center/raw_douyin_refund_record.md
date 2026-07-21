# `raw_douyin_refund_record` - 抖音退款原始记录

## 业务用途

保存退款接口的原始证据，为“已退款”终态、历史回补和指标对账提供独立来源。该表属于追加型原始层，不直接决定门店轮次；状态归一化后由 `clue_order_status_event` 驱动业务状态。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `source_record_key` | varchar(128) | NO | - | 源记录稳定幂等键 |
| `account_id` | varchar(64) | YES | NULL | 抖音账户标识 |
| `order_id` | varchar(64) | NO | - | 订单编号 |
| `refund_id` | varchar(64) | YES | NULL | 平台退款编号 |
| `raw_refund_status` | varchar(128) | YES | NULL | 平台原始退款状态 |
| `normalized_refund_status` | smallint | NO | 0 | 0未知、1处理中、2退款成功、3退款取消 |
| `refund_amount_cent` | bigint | YES | NULL | 退款金额，单位分 |
| `refund_applied_at` | timestamptz | YES | NULL | 申请退款时间 |
| `refund_completed_at` | timestamptz | YES | NULL | 退款完成时间 |
| `source_observed_at` | timestamptz | NO | - | 平台状态被观察到的时间 |
| `source_run_id` | varchar(64) | YES | NULL | 采集运行标识 |
| `payload_hash` | char(64) | NO | - | 原文 SHA-256，用于变更检测 |
| `raw_payload` | jsonb | NO | `{}` | 接口原始对象，不在日志输出 |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 更新时间 |

## 索引

- `pk_raw_douyin_refund_record` (`id`)
- `uk_raw_douyin_refund_record_source_record_key` (`source_record_key`)
- `idx_raw_douyin_refund_record_order_observed` (`order_id`, `source_observed_at` DESC)
- `idx_raw_douyin_refund_record_source_run` (`source_run_id`)

## 关系与约束

- `order_id` 逻辑关联 `clue_master_lead.order_id`；不创建数据库外键。
- 同一 `source_record_key` 重跑时只更新原始层观测内容；退款状态变化通过新的状态事件保留历史。
- `normalized_refund_status=2` 才是当前 V1 的退款终态证据。

## 页面与任务映射

- 不直接供页面读取。
- 由退款采集任务写入，由订单状态归一化任务读取。

## 迁移说明

当前仓库只有退款接口客户端和订单券退款字段，没有独立退款原始表。本表为新增共享事实源；历史数据可先由 `raw_douyin_order_coupons` 回填并标记证据来源。

## 使用接口

Phase 4 回填。该表不提供通用前端接口。
