# 结算查询既有只读依赖 Schema

> 所属索引: [foundation-schema-dy-data.md](../foundation-schema-dy-data.md)
> 增量原因: 2026-07-20 PRD Phase 5 发现 3 张既有依赖表只有主索引概述，缺少可校验的逐表字段定义
> 边界: 本文件记录当前代码和既有迁移中已经存在、被结算查询消费的字段；不新增字段、索引、外键或数据库迁移

## 1 `dim_stores` — 门店维表（既有·只读引用）

- **现状证据**：`apps/api/dy_api/models.py` 的 `DimStore` 与 `alembic/versions/20260612_0001_backend_production_mvp.py`。
- **本项目使用方式**：按用户门店授权范围读取业务 ID 和展示名称。
- **是否需改动**：否；本轮只补齐实际消费字段的文档定义。

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| store_id | text | NO | PK | — | 门店稳定业务 ID，用于权限过滤、查询条件和结果关联 |
| store_name | text | NO | | — | 门店展示名称 |

**使用接口**：
- `GET /api/v1/meta/filters` — 返回当前用户可选择的门店。
- `GET /api/v1/stores/{storeId}/monthly-settlement` — 返回当前门店 ID 和名称。
- `GET /api/v1/order-fee-details` — 补齐销售门店和核销门店展示名称。

## 2 `dim_store_poi_mappings` — POI 与门店映射（既有·只读引用）

- **现状证据**：`apps/api/dy_api/models.py` 的 `DimStorePoiMapping` 与 `alembic/versions/20260612_0001_backend_production_mvp.py`。
- **本项目使用方式**：服务层按核销 POI 查找核销门店；公开 API 不直接暴露映射表记录。
- **是否需改动**：否；本轮只补齐实际消费字段的文档定义。

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| store_id | text | NO | PK* / IDX | — | 映射后的门店业务 ID；应用层关联 `dim_stores.store_id` |
| poi_id | text | NO | PK* / UK | — | 抖音 POI ID；现有唯一约束保证一个 POI 只映射到一个门店 |

**现有约束与索引（记录，不是新增设计）**：
- 复合主键：`store_id + poi_id`。
- 唯一约束：`uq_dim_store_poi_mappings_poi_id` (`poi_id`)。
- 普通索引：`ix_dim_store_poi_mappings_store_id` (`store_id`)。

**使用边界**：
- 结算计算和订单费用查询在服务端完成 `raw_douyin_verify_records.poi_id` → `dim_store_poi_mappings.store_id` 映射。
- 未映射 POI 不猜测门店，应记录数据质量问题并按受影响费用方向阻断或降级。

## 3 `raw_douyin_verify_records` — 抖音核销原始记录（既有·只读引用）

- **现状证据**：`apps/api/dy_api/models.py` 的 `RawDouyinVerifyRecord` 与 `alembic/versions/20260612_0001_backend_production_mvp.py`。
- **本项目使用方式**：读取核销业务日、核销状态、券和 POI 原始事实；采集写入仍由既有 worker 负责。
- **是否需改动**：否；本轮只补齐实际消费字段的文档定义。

| 字段 | 类型 | 可空 | 键 | 默认值 | 说明 |
|------|------|------|-----|--------|------|
| verify_id | text | NO | PK | — | 核销记录稳定业务 ID |
| coupon_id | text | YES | IDX | NULL | 被核销的券业务 ID |
| verify_status | text | YES | IDX | NULL | 平台原始核销状态 |
| verify_time | datetime | YES | IDX | NULL | 带时区的核销时间；按上海时区形成管理服务费业务日和核销月份 |
| poi_id | text | YES | IDX | NULL | 实际核销 POI ID，用于映射核销门店 |

**使用接口**：
- `GET /api/v1/meta/filters` — 从核销时间派生可选核销月份。
- `GET /api/v1/order-fee-details` — 返回核销月份、核销时间和核销门店依据。
- `GET /api/v1/order-fee-details/export` — 按同一查询口径导出核销与费用依据。

**数据边界**：
- `verify_time` 缺失时不得推测核销月份或管理服务费规则匹配日。
- `poi_id` 缺失或无法映射时不得猜测核销门店。
- 本文件不改变原始表的既有复数命名、主键和索引；相关结构优化必须另行进入 Schema 变更流程。
