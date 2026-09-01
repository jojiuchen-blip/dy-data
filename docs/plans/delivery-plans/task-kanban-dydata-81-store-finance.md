# DYDATA-81 门店端财务页面任务看板

| Task | 子开发计划 | Owner | 前置 | 状态 | 完成日期 | 备注 |
|---|---|---|---|---|---|---|
| T1.1 | [正式系统门店端页面实施](sub-delivery-plan-dydata-81-store-finance-T1.1-store-pages.md) | AI 执行 -> 人审核 | T1.2 已获用户验收；正式 API 契约和写操作授权已具备 | 进行中 | - | 完成正式合并前全量门禁；不得触碰 `/finance/*` |
| T1.2 | [隔离的门店端财务只读 UAT 预览](sub-delivery-plan-dydata-81-store-finance-T1.2-readonly-uat-preview.md) | AI 执行 -> 人审核 | 用户已确认 UAT 方案并明确“开始” | 已完成（2026-08-30） | 2026-08-30 | 用户已明确验收最新 UAT；证据保留为正式系统合同基线 |
| T1.3 | [主系统集成与生产发布](sub-delivery-plan-dydata-81-store-finance-T1.3-production-release.md) | AI 执行 -> 人审核 | T1.1 全量门禁、正式视觉回归和受保护范围检查通过 | 待开发 | - | 合并、CI/部署、生产 smoke、版本与回滚记录；Issue 保持打开待最终验收 |
