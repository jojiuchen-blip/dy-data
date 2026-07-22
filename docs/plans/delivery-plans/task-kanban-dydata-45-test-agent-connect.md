# DYDATA-45 测试环境 Agent 接入任务看板

| Task | 子开发计划 | Owner | 前置 | 状态 | 完成日期 | 备注 |
|---|---|---|---|---|---|---|
| T1.1 | [CLI 环境与注册表](sub-delivery-plan-dydata-45-test-agent-connect-T1.1-cli-environment-registry.md) | AI 执行 -> 人审核 | 无 | 已完成（2026-07-22） | 2026-07-22 | 155 项目标回归通过；环境、凭据与 API 映射已隔离 |
| T1.2 | [Agent 发现与诊断](sub-delivery-plan-dydata-45-test-agent-connect-T1.2-agent-discovery-doctor.md) | AI 执行 -> 人审核 | T1.1 | 已完成（2026-07-22） | 2026-07-22 | 四个公开发现入口与 doctor；243 项组合回归通过 |
| T2.1 | [MCP OAuth](sub-delivery-plan-dydata-45-test-agent-connect-T2.1-mcp-oauth.md) | AI 执行 -> 人审核 | T1.2 | 已完成（2026-07-22） | 2026-07-22 | 16 项 OAuth 协议测试、可逆迁移和 256 项组合回归通过 |
| T2.2 | [共享能力与授权页](sub-delivery-plan-dydata-45-test-agent-connect-T2.2-shared-capabilities-consent.md) | AI 执行 -> 人审核 | T2.1 | 已完成（2026-07-22） | 2026-07-22 | 两项 MCP 工具、共享统计口径、Web 同意页、审计迁移；869 项全量回归与 Web build 通过 |
| T3.1 | [部署与 Agent UAT](sub-delivery-plan-dydata-45-test-agent-connect-T3.1-deploy-agent-uat.md) | AI 执行 -> 人审核 | T2.2 | 进行中 | - | 测试环境部署、独立 Agent 黑盒验收 |
