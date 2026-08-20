# 抖音经营引擎（结算与财务） — mainprd

> 生成时间: 2026-08-20
> 来源: prd-writer Phase 3
> 技术栈: React + TypeScript/JavaScript + Vite + FastAPI + PostgreSQL

---

## 上游引用

| 产物 | 文件 | 来源 Skill |
|---|---|---|
| 功能列表 | [prd-feature-list-dy-data.md](prd-feature-list-dy-data.md) | prd-writer |
| 用户流程 | [explainer-flow-dy-data.md](../../src/frontend/page-preview/explainer-flow-dy-data.md) | page-explainer |
| 交互语义 | [explainer-b-interaction-dy-data.md](../../src/frontend/page-preview/explainer-b-interaction-dy-data.md) | page-explainer |
| 页面说明交付清单 | [explainer-delivery-dy-data.md](../../src/frontend/page-preview/explainer-delivery-dy-data.md) | page-explainer |
| 页面交付清单 | [page-delivery-dy-data.md](../../src/frontend/page-preview/page-delivery-dy-data.md) | page-designer |
| 冻结规格 | [2026-08-20-dydata-19-settlement-finance-design.md](../superpowers/specs/2026-08-20-dydata-19-settlement-finance-design.md) | 页面回环/用户确认 |
| 术语表 | [foundation-glossary-dy-data.md](foundation/foundation-glossary-dy-data.md) | foundation-builder |
| 数据库 Schema | [foundation-schema-dy-data.md](foundation/foundation-schema-dy-data.md) | foundation-builder |
| API 接口 | [foundation-api-dy-data.md](foundation/foundation-api-dy-data.md) | foundation-builder |
| Foundation 交付清单 | [foundation-delivery-dy-data.md](foundation/foundation-delivery-dy-data.md) | foundation-builder |
| BRD | [BRD-dy-data-20260716-1255.md](../brd/BRD-dy-data-20260716-1255.md) | brd-writer |

---

## subprd索引

| # | 区块 | 所属页面 | subprd文件 | 状态 |
|---|------|---------|-----------|------|
| 1 | 排名筛选与结果 | 全国门店榜单 | [01-subprd-store-ranking.md](subprd/01-subprd-store-ranking.md) | 已确认 |
| 2 | 账单版本、方向确认与订单下钻 | 月度账单确认 | [02-subprd-store-settlement.md](subprd/02-subprd-store-settlement.md) | 已确认 |
| 3 | 费用方向、筛选与明细 | 订单费用明细 | [03-subprd-order-fee-details.md](subprd/03-subprd-order-fee-details.md) | 已确认 |
| 4 | 发票登记、状态与历史 | 推广费发票登记 | [04-subprd-invoice-registration.md](subprd/04-subprd-invoice-registration.md) | 已确认 |
| 5 | 指标、发票与订单穿透 | 管理员推广服务费 | [05-subprd-finance-promotion.md](subprd/05-subprd-finance-promotion.md) | 已确认 |
| 6 | 指标、扣款与订单穿透 | 管理员管理服务费 | [06-subprd-finance-management.md](subprd/06-subprd-finance-management.md) | 已确认 |
| 7 | 门店与 SAP 信息查询 | 门店基础信息 | [07-subprd-finance-store-info.md](subprd/07-subprd-finance-store-info.md) | 已确认 |
| 8 | 门店提交与管理员处理 | 账单异议 | [08-subprd-finance-disputes.md](subprd/08-subprd-finance-disputes.md) | 已确认 |
| 9 | 四类模板、差异、错误与版本 | 财务导入 | [09-subprd-finance-imports.md](subprd/09-subprd-finance-imports.md) | 已确认 |

---

## 全局设计规则

| 规则 | 说明 |
|---|---|
| 权威来源 | 功能全貌以功能列表为准；术语、数据结构、API 分别以 Foundation 术语表、Schema、API 为准；详细行为以对应 subprd 为准。 |
| 系统边界 | 开票和厂端审核在系统外完成；系统不创建开票申请单、不执行真实开票、不创建审核任务、不执行资金划拨。 |
| 角色 | 门店账号提交确认、异议和推广费发票登记；财务人员使用管理员角色；管理员与最高管理员在本模块业务权限一致。 |
| 双费用 | 推广服务费与管理服务费独立确认、查询和追溯，异议均不阻断另一方向。 |
| 正式账期 | 单月只统计所选月；累计从 `2026-08` 起至所选月，排除 `2026-07` 测试数据；确认金额只显示单月。 |
| 不可变版本 | 账单、发票和导入更正生成新版本并切换当前指针；旧版本、确认和审计永久保留。 |
| 导入原子性 | 四类模板按业务唯一键全量校验，门店只用门店 ID；任一错误时正式业务表整批零写入。 |
| 并发 | 所有业务写请求携带读取版本和幂等键；版本冲突返回读取/当前版本、最近操作人和时间，刷新后重试。 |
| 金额 | 金额使用整数分；发票金额分配必须等于账期有效确认金额和发票金额，不允许部分扣款、跨账期或拆票。 |
| 权限 | 每次查询、写入和导出均由服务端校验页面权限与门店范围；URL、SAP 编码或展示字段不授予权限。 |
| 空状态 | 区分无数据、未确认、待开票、数据质量阻断、整批失败和版本冲突，不沿用上一筛选结果。 |
| 加载态 | 筛选、分页、预校验和提交期间保留上下文，阻止重复提交；可取消操作不得产生正式业务写入。 |
| 错误提示 | 错误说明位置、影响范围和下一步；导入逐行错误含行号、业务键、字段、原值、原因和修正建议。 |
| 导出一致性 | 查询与导出使用同一筛选、权限和口径；空结果不导出，失败可重试且不改变业务状态。 |

---

## 一致性自查结果

- 检查时间: 2026-08-20
- P1 数据链路覆盖: 75/75 (100%)
- P2 接口引用覆盖: 19/19 (100%)
- P3 术语覆盖: 已人工复核
- P4 功能列表→subprd: 9/9 (100%)
- P5 mainprd 索引完整: ✓
- P6 交互语义一致: 8/8 (100%)
- P8 流程覆盖: 已人工复核
- P9 功能子区域 ↔ 验收对应性: 14/14 (100%)
- 需回溯 foundation-builder: 无

---

## 待回溯缺口

| 缺口 | 类型 | 回溯目标 | 状态 |
|---|---|---|---|
| DYDATA-19 旧只读开票假设 | Foundation/API/PRD | 已由 2026-08-20 冻结规格和 Foundation 增量覆盖 | resolved |
