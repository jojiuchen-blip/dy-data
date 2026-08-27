# DYDATA-46 腾讯云正式生产升格任务看板

| Task | 子开发计划 | Owner | 前置 | 状态 | 完成日期 | 备注 |
|---|---|---|---|---|---|---|
| T1.1 | [生产环境与凭证隔离](sub-delivery-plan-dydata-46-production-promotion-T1.1-environment-isolation.md) | AI 执行 -> 人审核 | DYDATA-45 完成；生产域名确认 | 已完成（2026-08-27） | 2026-08-27 | 311 项组合回归通过；production 注册、旧 test 凭证拒绝、动态审计已闭合 |
| T1.2 | [官方入口与兼容策略切换](sub-delivery-plan-dydata-46-production-promotion-T1.2-official-entry-cutover.md) | AI 执行 -> 人审核 | T1.1 | 进行中 | - | manifest、Skill、文档、CLI 默认值、最低版本 |
| T2.1 | [生产发布与线上 UAT](sub-delivery-plan-dydata-46-production-promotion-T2.1-release-uat.md) | AI 执行 -> 人审核 | T1.2、PR CI | 待开始 | - | 腾讯云部署、smoke、CLI/MCP、审计、回滚 |
