# dy-data 商品治理与双费用结算任务看板

> 人类 Owner 已于 2026-07-20 确认全部计划。T1.1～T3.3 已完成本地实现与验证；T4.1 为唯一 `进行中（等待外部依赖）` Task，依赖关闭前只进行发布准备，不执行生产迁移或部署。

| Task | 子开发计划 | Owner | 前置 | 状态 | 完成日期 | 备注 |
|---|---|---|---|---|---|---|
| T1.1 | [原始订单/券兼容 ID 扩展](sub-delivery-plan-dy-data-T1.1-raw-id-compat.md) | AI 执行 -> 人审核 | 无 | 已完成（2026-07-20） | 2026-07-20 | 本地回归 38 passed；目标 PostgreSQL 数据副本核验保留到 T4.1 |
| T1.2 | [商品、双费率与导入 Schema](sub-delivery-plan-dy-data-T1.2-product-rule-schema.md) | AI 执行 -> 人审核 | T1.1 | 已完成（2026-07-20） | 2026-07-20 | 目标测试 23 passed、受影响回归 54 passed；PostgreSQL 离线 DDL 通过，真实库核验保留到 T4.1 |
| T1.3 | [双费用结算与报表 Schema](sub-delivery-plan-dy-data-T1.3-settlement-schema.md) | AI 执行 -> 人审核 | T1.2 | 已完成（2026-07-20） | 2026-07-20 | 目标测试 19 passed、受影响回归 29 passed；PostgreSQL 离线 DDL 通过，真实库核验保留到 T4.1 |
| T2.1 | [商品在线同步与历史](sub-delivery-plan-dy-data-T2.1-product-sync.md) | AI 执行 -> 人审核 | T1.2；生产验收需外部样例 | 已完成本地实现与验证（2026-07-20） | 2026-07-20 | 目标测试 37 passed、受影响回归 47 passed；4 个管理接口、历史/当前写入、幂等并发、游标脱敏与失败边界完成；真实 API 生产验收待外部样例 |
| T2.2 | [SKU 商品、双费率与原子导入 API](sub-delivery-plan-dy-data-T2.2-sku-fee-admin.md) | AI 执行 -> 人审核 | T1.2 | 已完成（2026-07-20） | 2026-07-20 | 目标测试 28 passed、受影响回归 41 passed；13 个接口、5000 行边界、CSV/XLSX、幂等与整批回滚通过 |
| T2.3 | [不可变双费用结果与调整](sub-delivery-plan-dy-data-T2.3-dual-fee-engine.md) | AI 执行 -> 人审核 | T1.3、T2.1、T2.2 | 已完成（2026-07-20） | 2026-07-20 | 目标测试 20 passed；受影响结算、采集、Schema、迁移与 Dashboard 回归 65 passed；商品归属与销售归属独立、日级双规则、跨月、同/跨店、退款、取消核销、锁账与未知数据阻断通过 |
| T2.4 | [账单冻结与月度/榜单投影](sub-delivery-plan-dy-data-T2.4-statement-projections.md) | AI 执行 -> 人审核 | T2.3 | 已完成（2026-07-20） | 2026-07-20 | 目标测试 45 passed、受影响回归 86 passed；三层锁账、血缘冻结、事件月调整、月度/累计投影、共享账期锁、失败审计与锁账后迟到数据阻断通过；PostgreSQL 双会话与大数据量门禁保留到 T4.1 |
| T2.5 | [原始订单/券应用与约束切换](sub-delivery-plan-dy-data-T2.5-raw-id-cutover.md) | AI 执行 -> 人审核 | T2.4 | 已完成本地实现与验证（2026-07-20） | 2026-07-20 | 目标回归 66 passed；迁移离线 DDL、应用内部关联、影子核对和序列同步完成；真实 PostgreSQL 双会话与副本验收保留到 T4.1 |
| T3.1 | [结算筛选、榜单、单店与订单费用 API](sub-delivery-plan-dy-data-T3.1-reporting-api.md) | AI 执行 -> 人审核 | T2.2、T2.4、T2.5 | 已完成本地实现与验证（2026-07-20） | 2026-07-20 | 目标回归 30 passed、全 API 135 passed；独立审查 Critical/Important 均为 0；Foundation 无漂移 |
| T3.2 | [四个门店结算生产页面](sub-delivery-plan-dy-data-T3.2-settlement-pages.md) | AI 执行 -> 人审核 | T3.1 | 已完成（2026-07-21） | 2026-07-21 | 前端契约 65 passed、API 17 passed、浏览器 102 passed（含真实 FastAPI 两角色/空/403/422/409/导出）、Web build 通过、独立复审 Critical/Important/Minor 均为 0；Foundation 无漂移 |
| T3.3 | [商品、费率、导入与同步后台](sub-delivery-plan-dy-data-T3.3-admin-console.md) | AI 执行 -> 人审核 | T2.1、T2.2 | 已完成（2026-07-21） | 2026-07-21 | 后端/迁移 56 passed、完整浏览器/视觉 112 passed、真实商品同步路径 1 passed、Web build 与 diff check 通过；独立复审无 Critical/Important；Foundation 无业务漂移 |
| T4.1 | [端到端核验与生产发布](sub-delivery-plan-dy-data-T4.1-release-verification.md) | AI 执行 -> 人审核 | T3.1、T3.2、T3.3；外部依赖关闭 | 进行中（等待外部依赖） | - | 等待外部商品 API 样例、稳定归属账号 ID、真实渠道枚举、DYDATA-32 权限矩阵和目标 PostgreSQL/生产环境；当前仅做发布准备 |
