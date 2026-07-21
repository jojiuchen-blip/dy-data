# `clue_source_record_link` - 原始线索映射

## 业务用途

确保每一条 `raw_douyin_clues` 原始行都能追溯到一条主线索，包括缺失订单 ID、身份冲突或暂时隔离的记录，消除原始数据与业务主池之间的静默遗漏。

## 字段

| 字段 | PostgreSQL 类型 | 可空 | 默认值 | 说明 |
|------|-----------------|------|--------|------|
| `id` | bigint identity | NO | identity | 数字主键 |
| `source_system` | smallint | NO | 1 | 1抖音线索接口 |
| `source_table` | varchar(64) | NO | `raw_douyin_clues` | 原始表名 |
| `source_record_key` | varchar(128) | NO | - | 原始行稳定键 |
| `source_clue_id` | varchar(64) | YES | NULL | 平台线索 ID |
| `source_order_id` | varchar(64) | YES | NULL | 原始行中的订单 ID |
| `lead_key` | varchar(64) | NO | - | 目标主线索业务键 |
| `order_id` | varchar(64) | YES | NULL | 归一化订单 ID |
| `link_status` | smallint | NO | 1 | 1订单关联、2缺订单隔离、3身份冲突隔离 |
| `link_method` | smallint | NO | 1 | 1订单键、2确定性源键、3人工修复 |
| `link_version` | integer | NO | 1 | 映射算法版本 |
| `linked_at` | timestamptz | NO | CURRENT_TIMESTAMP | 首次建立映射时间 |
| `source_observed_at` | timestamptz | YES | NULL | 原始行业务观测时间 |
| `source_run_id` | varchar(64) | YES | NULL | 采集运行标识 |
| `source_payload_hash` | char(64) | YES | NULL | 原始行内容摘要 |
| `conflict_reason` | varchar(255) | YES | NULL | 冲突或隔离原因 |
| `gmt_create` | timestamptz | NO | CURRENT_TIMESTAMP | 创建时间 |
| `gmt_modified` | timestamptz | NO | CURRENT_TIMESTAMP | 更新时间 |

## 索引

- `pk_clue_source_record_link` (`id`)
- `uk_clue_source_record_link_source` (`source_table`, `source_record_key`)
- `idx_clue_source_record_link_lead` (`lead_key`)
- `idx_clue_source_record_link_order` (`order_id`)
- `idx_clue_source_record_link_status` (`link_status`, `gmt_modified` DESC)

## 关系与约束

- 每条原始线索行必须且只能出现一次；每条映射必须指向存在的 `lead_key`。
- `link_status=1` 时 `order_id` 非空并与主线索一致；状态 2/3 不进入完整主池或分配。
- 人工修复不得覆盖旧映射证据，应记录操作审计并增加 `link_version`。

## 页面与任务映射

- 不直接展示给门店。
- 数据质量和重建预览可按 `link_status` 汇总未映射、隔离和冲突数。

## 迁移说明

从 `clue_master_leads.source_clue_row_key` 和 `source_identity_key` 回填初始映射，再对 `raw_douyin_clues` 做全量反连接检查。历史 204 条未映射原始行必须进入隔离主线索或修复映射，不能忽略。

## 使用接口

Phase 4 回填。仅数据质量和受控修复接口可访问。
