# 抖音经营引擎（门店结算） — mainprd

> 生成时间: 2026-07-20 13:11
> 来源: prd-writer Phase 3
> 技术栈: React 19 + TypeScript + Vite + FastAPI + PostgreSQL

---

## 上游引用

| 产物 | 文件 | 来源 Skill |
|------|------|-----------|
| 功能列表 | [prd-feature-list-dy-data.md](prd-feature-list-dy-data.md) | prd-writer |
| 用户流程 | [explainer-flow-dy-data.md](../../src/frontend/page-preview/explainer-flow-dy-data.md) | page-explainer |
| 交互语义 | [explainer-b-interaction-dy-data.md](../../src/frontend/page-preview/explainer-b-interaction-dy-data.md) | page-explainer |
| 页面说明交付清单 | [explainer-delivery-dy-data.md](../../src/frontend/page-preview/explainer-delivery-dy-data.md) | page-explainer |
| 页面交付清单 | [page-delivery-dy-data.md](../../src/frontend/page-preview/page-delivery-dy-data.md) | page-designer |
| 已确认交互原型 | [commission-dashboard-navigation-mock.html](../commission-dashboard-navigation-mock.html) | page-designer |
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
| 2 | 费用汇总与订单下钻 | 单店分账 | [02-subprd-store-settlement.md](subprd/02-subprd-store-settlement.md) | 已确认 |
| 3 | 费用类型、筛选与明细表 | 订单费用明细 | [03-subprd-order-fee-details.md](subprd/03-subprd-order-fee-details.md) | 已确认 |
| 4 | 开票流程引导 | 开票确认 | [04-subprd-invoice-guide.md](subprd/04-subprd-invoice-guide.md) | 已确认 |

---

## 全局设计规则

| 规则 | 说明 |
|------|------|
| 权威来源 | 产品背景与页面全貌以功能列表为准；术语、数据结构和接口契约分别以 Foundation 术语表、Schema 和 API 文件为准；区块细节只写入对应 subprd。 |
| 当前能力与目标能力 | 已确认原型用于锁定布局和交互语义，不代表生产接口、真实数据、在线开票或资金划拨能力已经完成。 |
| 双费用口径 | 推广服务费与管理服务费是两个独立费用方向；页面、筛选、下钻、导出和验收均不得继续用单一“分佣”金额代替。 |
| 正式账期 | 正式累计从 `2026-08` 开始；`2026-07` 只作为测试账期，不进入正式累计或开票准备范围。 |
| 时间与规则匹配 | 业务时区统一为 `Asia/Shanghai`；推广服务费按销售业务日匹配规则并归入销售月份，管理服务费按核销业务日匹配规则并归入核销月份。 |
| 退款与锁账 | 原费用结果和已锁账结果不可被后续费率或退款覆盖；退款、取消核销等后续事件通过独立调整记录计入调整入账月份，同时保留原始发生月份。 |
| 金额与费率展示 | 金额按分进行业务计算、按统一货币格式展示；费率按实际规则版本展示。同一汇总行存在多个日级费率或版本时，展示区间或集合，不伪装成单一费率。 |
| 业务标识 | 订单、券、SKU、账单和规则版本始终使用稳定业务 ID 对外展示与追溯；内部自增主键不作为页面、导出或业务交互编号。 |
| 权限 | 服务端按角色、组织和数据范围重新校验每次查询与导出；URL、来源上下文和全国榜单前 20 例外均不能授予其他门店明细权限。 |
| 来源上下文 | 汇总页传入明细页的月份、门店、产品维度、费用方向、费率和规则版本只用于恢复筛选；真实权限和计算依据必须以服务端核验结果为准。 |
| 空状态 | 无匹配数据时保留当前有效筛选和口径说明，明确区分“无订单”“未配置费率”“数据质量阻断”和“正式累计尚未开始”，不得沿用旧结果。 |
| 加载态 | 筛选、下钻和分页期间保留页面骨架及当前条件，阻止重复提交；加载完成后由真实结果替换占位内容。 |
| 错误提示 | 错误信息应说明发生位置、影响范围和可执行的下一步；权限失败、上下文过期、数据质量阻断和导出失败不得使用同一笼统提示。 |
| 导出一致性 | 导出与当前明细使用同一筛选、权限和费用口径；空结果不导出，失败可重试且不得改变业务状态。 |
| 开票边界 | 开票确认页保持只读，不提供账单确认、锁账、发票提交或财务审核操作；未确认的材料和支持入口必须明确标记为待财务确认或待上线通知。 |
| 管理端边界 | SKU 双费率、批量导入、结算范围和商品同步作为四页的全局规则与数据依赖；当前没有已确认的独立管理端页面，因此本组 subprd 不新增管理端页面规格。 |

---

## 一致性自查结果

- 检查时间: 2026-07-20 14:59
- P1 数据链路覆盖: 96/96 (100%)
- P2 接口引用覆盖: 5/5 (100%)
- P3 术语覆盖: 已人工复核
- P4 功能列表→subprd: 4/4 (100%)
- P5 mainprd 索引完整: ✓
- P6 交互语义一致: 9/9 (100%)
- P8 流程覆盖: 已人工复核
- P9 功能子区域 ↔ 验收对应性: 14/14 (100%)
- 需回溯 foundation-builder: 无；3 张既有只读依赖表的逐字段定义已在 Foundation Phase 3 增量中补齐
- Phase 5 用户确认: 2026-07-20；`prd-writer | DONE`

---

## 待回溯缺口

抖音商品在线 API 脱敏样例、目标商品归属账号稳定 ID、真实渠道枚举和正式开票材料口径已在 Foundation 交付清单中作为生产外部依赖持续跟踪，不属于本阶段新增的 Foundation 或页面说明回溯缺口。Phase 5 首轮发现的 3 张既有只读依赖表字段定义缺口已完成 Foundation Phase 3 增量并复检通过。

| 缺口 | 类型 | 回溯目标 | 状态 |
|---|---|---|---|
| `dim_stores`、`dim_store_poi_mappings`、`raw_douyin_verify_records` 缺少逐字段定义 | Schema | foundation-builder Phase 3 增量 | resolved |
