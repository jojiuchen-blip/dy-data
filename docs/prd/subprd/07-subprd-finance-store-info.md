# PRD 7: 门店与 SAP 信息查询

> **文档版本**: 1.0 | **最后更新**: 2026-08-20
> **关联文档**: [mainprd](../mainprd-dy-data.md) · [用户流程](../../../src/frontend/page-preview/explainer-flow-dy-data.md) · [交互语义](../../../src/frontend/page-preview/explainer-b-interaction-dy-data.md) · [术语表](../foundation/foundation-glossary-dy-data.md) · [Schema](../foundation/foundation-schema-dy-data.md) · [API](../foundation/foundation-api-dy-data.md)

## §1 文档范围

本文档覆盖**门店基础信息**（门店 ID 唯一匹配 + SAP 展示信息 + 查询筛选）。

### 需求清单

| # | 需求 | 需求简述 | 对应章节 |
|---|---|---|---|
| R1 | 门店查询 | 查询授权范围内门店财务基础信息 | §3 |
| R2 | 匹配边界 | 明确门店 ID 是唯一匹配键 | §3 |

## §2 页面整体布局

```
[门店搜索/筛选] [门店 ID | 名称 | SAP 展示信息 | 更新时间]
```

## §3 门店基础信息查询

### 3.1 用户体验

**数据来源**：`GET /api/v1/admin/finance/stores`。

**交互语义引用**：`dy19.routing.navigate.1`

**布局**：

```
[搜索][门店范围] [门店 ID][门店名称][SAP 编码（仅展示）][更新时间]
```

**前端职责**：只展示服务端返回的门店与 SAP 信息，不用 SAP 编码或名称执行导入匹配。

### 3.3 数据链路

| UI 元素 | API 字段 | 计算规则 | 数据源（服务端读取） | 配置源（服务端读取） |
|---|---|---|---|---|
| 门店 ID | `storeId` | 稳定唯一业务键 | `dim_stores.store_id` | — |
| 门店名称 | `storeName` | 展示值，不作为匹配键 | `dim_stores.store_name` | — |
| 财务汇总 | `statementAmountCent` | 当前筛选聚合 | `settlement_statement.promotion_net_fee_cent` | — |

### 3.4 异常与兜底

**服务端兜底**：

| 场景 | 处理 |
|---|---|
| 门店 ID 缺失或无法映射 | 返回迁移/导入异常，不按名称猜测 |
| 越权门店 | 过滤或 403 |

**前端渲染兜底**：

| 场景 | 处理 |
|---|---|
| SAP 字段缺失 | 显示“未维护”，门店 ID 仍可用于业务匹配 |
| 无结果 | 显示空态并保留筛选 |

### 3.6 验收

| # | 类型 | 场景 | 触发条件 | 预期结果 |
|---|---|---|---|---|
| 1 | 业务规则 | 唯一匹配 | SAP 编码与门店 ID 冲突 | 以门店 ID 为准，冲突进入异常而非模糊匹配 |
| 2 | UX 交互 | 展示缺失 | SAP 字段为空 | 显示未维护，不影响门店 ID 查询 |

## §4 接口契约

### 4.1 接口：`GET /api/v1/admin/finance/stores`

完整契约见 [账单发票 API §4.3](../foundation/foundation-api-dy-data/billing-invoice.md#43-管理员财务查询-3134)。
