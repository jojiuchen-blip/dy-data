# DYDATA-46 T2.1 生产发布与线上 UAT

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-46-production-promotion.md](main-delivery-plan-dydata-46-production-promotion.md)
- 任务看板：[task-kanban-dydata-46-production-promotion.md](task-kanban-dydata-46-production-promotion.md)

#### T2.1 合并、部署并验收腾讯云 production

**Requirement ID**：DYDATA-46-PROD-RELEASE-UAT

**PRD 双链·读**：
- Linear `DYDATA-46` 全部验收标准
- `docs/runbook.md` 与 `.github/workflows/tencent-lighthouse-deploy.yml`
- DYDATA-45 T3.1 测试部署与黑盒 UAT 证据

**核心逻辑**：
- 部署配置显式把 `DY_AGENT_ENVIRONMENT` 切换为 production，并在更新前备份远端 env 与上一生产镜像/版本。
- PR CI 通过并合入 main 后才允许触发腾讯云生产部署；部署 smoke 断言 production manifest、OAuth metadata、MCP、Agent 文档和 Web/API 健康。
- 生产受限账号必须重新授权；CLI 与 MCP 验证授权门店、跟进统计、越权整单拒绝和同口径结果。
- 审计按 request id 能查到 production；失败回滚上一 production 版本，不导向 test。

**核心文件**：
- `.github/workflows/tencent-lighthouse-deploy.yml`
- `deploy/tencent/deploy.sh`
- `deploy/.env.example`
- `deploy/compose.yaml`
- `deploy/nginx.conf`
- `docs/runbook.md`
- `tests/test_deploy_agent_config.py`

**完成标准**：
- PR 与 main CI 成功，部署 workflow 成功，生产域名全部健康。
- manifest 与 MCP initialize 报告 production；OAuth issuer/resource/callback 使用生产域。
- test 凭证访问 production 失败；重新授权后的 CLI/MCP 仅返回账号授权门店且结果等价。
- 日志/审计明确 environment=production 且无敏感信息。
- 回滚命令、备份位置与上一生产版本已核查；不会 fallback 到 test 数据。
- 验证、PR/commit、CI、部署和剩余风险回填 Linear，用户验收后才能关闭 DYDATA-46。

**Verification Method**：
- 合并前：全量 pytest、Web build、部署配置、迁移、`git diff --check`。
- 合并后：检查 main CI，手动触发腾讯云 workflow，保存 run URL 与 commit SHA。
- 部署后：公开端点 smoke、CLI doctor、CLI/MCP 两项只读能力、越权拒绝、审计和回滚核查。

**Evidence**：
- 本子计划 `Evidence Log`；GitHub PR/CI/deploy URL；脱敏 smoke/UAT；Linear `DYDATA-46` 验证记录。

**Failure Handling**：
- CI 或部署前门禁失败时不触发生产。
- 部署后 health、manifest、OAuth、MCP 或业务 smoke 任一失败，立即停止验收并回滚上一 production 版本。
- 旧 test 凭证仍可用、权限范围扩大或出现 test 数据 fallback 时视为 P0，回滚并阻塞关闭。

**完成收尾：状态同步**：
- 仅在全部证据齐全且用户接受后，同步三处计划为已完成并关闭 DYDATA-46；否则保持 In Progress 并记录剩余风险。

**Owner**：AI 执行 -> 人审核

**前置**：T1.2、PR CI

**状态**：待开始

## Evidence Log

- 待执行。

