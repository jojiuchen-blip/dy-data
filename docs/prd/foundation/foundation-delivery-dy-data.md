# Foundation 交付清单 - dy-data（抖音经营引擎）

> 生成时间: 2026-07-20 12:31
> Skill: foundation-builder
> 模式: 增量更新
> 范围: DYDATA-1/21/30/31/33/38 的商品治理、双费率、原子导入、商品同步、双费用结算、订单/券主键迁移设计与四页生产查询地基
> 增量修订: 2026-07-20 14:54 补齐 3 张结算查询既有只读依赖表的逐表字段定义；不改变数据库结构或 API 契约

## 上游依赖

| 上游 Skill | 产物文件 |
|-----------|---------|
| brd-writer | docs/brd/BRD-dy-data-20260716-1255.md |
| page-designer | src/frontend/page-preview/page-delivery-dy-data.md |
| page-explainer | src/frontend/page-preview/explainer-flow-dy-data.md<br>src/frontend/page-preview/explainer-b-interaction-dy-data.md<br>src/frontend/page-preview/explainer-delivery-dy-data.md |

## 交付产物

| 产物 | 文件路径 | 行数 | 拆分子文件 |
|------|--------|------|----------|
| 术语表 | docs/prd/foundation/foundation-glossary-dy-data.md | 150 | — |
| 数据库 Schema | docs/prd/foundation/foundation-schema-dy-data.md | 120 | docs/prd/foundation/foundation-schema-dy-data/product-rule-source.md<br>docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md<br>docs/prd/foundation/foundation-schema-dy-data/existing-read-dependencies.md |
| API 接口设计 | docs/prd/foundation/foundation-api-dy-data.md | 187 | docs/prd/foundation/foundation-api-dy-data/common-contract.md<br>docs/prd/foundation/foundation-api-dy-data/product-sync.md<br>docs/prd/foundation/foundation-api-dy-data/settlement-reporting.md<br>docs/prd/foundation/foundation-api-dy-data/sku-fee-admin.md |

## 产物摘要

| 指标 | 数值 |
|------|------|
| 术语总数 | 91 |
| 数据表总数 | 17 张目标设计表 + 5 张结构不变的既有依赖表 |
| API 接口数 | 22 |
| 锁定交互语义 | 9 |
| 正式账期起点 | `2026-08` |

## 一致性自查结果

- 检查时间: 2026-07-20 12:20
- 页面可写字段覆盖率: 22/22 (100%)
- API 总览 ↔ 详细契约覆盖率: 22/22 (100%)
- Schema 定义 ↔ 使用边界覆盖率: 17/17 (100%)
- 结算查询既有依赖逐表字段定义覆盖率: 3/3 (100%)
- 术语一致性: 全部通过
- 交互语义 → API 覆盖率: 9/9 (100%)
- 交互校验 → Schema / 服务层覆盖率: 9/9 (100%)
- 孤立目标表: 无
- Foundation 本地断链: 无
- 文件拆分约束: 主文件及全部子文件均少于 400 行

## 已确认的关键边界

- 批量费率导入支持 `.xlsx` 和 UTF-8 `.csv`，单文件不超过 10 MiB、数据行不超过 5000；任一行非法时正式规则零写入，并返回行号、字段和原因。
- 首批费率自 `2026-08-01` 生效，后续可选择到自然日；同一 SKU + 生效日冲突拒绝写入，费率通过新增不可变版本调整。
- 已锁账结果不被后续费率改写；退款、部分退款和取消核销通过调整记录进入事件发生月份，保留原始发生月份和调整入账月份。
- 原始订单/券表保留平台字符串业务 ID，同时分阶段增加自增内部主键并迁移内部引用；Foundation 不生成或执行真实 DDL。
- 开票确认页和已锁账账单保持只读，本轮不新增在线开票、锁账、解锁或修改接口。
- 订单双费用查询使用 `/api/v1/order-fee-details`；旧 `/api/v1/order-details` 保留通用订单查询语义。

## 未关闭的外部依赖

| 依赖 | 当前边界 | 阻断范围 |
|------|----------|----------|
| 抖音商品在线 API 脱敏样例和正式文档 | 不猜测 URL、鉴权、游标和真实枚举 | 阻断外部适配器生产验收，不阻断内部 API/Schema 与 PRD |
| 目标商品归属账号稳定 ID、直播/短视频真实枚举 | Schema 保存稳定 ID 和原始/标准化值，未知渠道默认不计费 | 阻断正式生产配置与数据正确性验收 |
| 发票抬头、税号、类目、税率、接收方式和正式支持入口 | 页面继续标记待财务确认/待上线通知，不设计发票写接口 | 阻断真实开票功能，不阻断只读准备指引 |

## 下游可消费信息

| 下游 Skill | 应读取 | 用途 |
|-----------|--------|------|
| prd-writer | 本清单 + glossary + schema + api 及全部拆分子文件 | 统一术语、补齐字段来源、接口契约、验收边界和外部依赖 |

## 下游进入条件

- 下游必须以本清单声明的相对路径为准，不从对话记录重新拼接 Foundation 文件。
- API 和 Schema 文档描述目标契约与目标结构，不代表运行代码、数据库迁移或生产外部适配已经实现。
- 外部依赖未关闭的能力必须在 PRD 中保持依赖状态，不得把 Mock、历史字段或推测枚举写成生产验收事实。
