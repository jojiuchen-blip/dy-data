# DYDATA-46 T1.2 官方入口与兼容策略切换

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-46-production-promotion.md](main-delivery-plan-dydata-46-production-promotion.md)
- 任务看板：[task-kanban-dydata-46-production-promotion.md](task-kanban-dydata-46-production-promotion.md)

#### T1.2 将全部正式发现入口切到 production

**Requirement ID**：DYDATA-46-OFFICIAL-CUTOVER

**PRD 双链·读**：
- Linear `DYDATA-46` 的官方入口、公开发现和旧客户端验收标准
- `docs/prd/foundation/foundation-delivery-dy-data.md`
- DYDATA-45 Agent discovery、doctor 与部署计划

**核心逻辑**：
- README、Agent guide、Skill、manifest、示例和 CLI 默认环境只发布 production，不向正式用户提供 test 自动发现。
- manifest 的版本门禁与发布版本保持一致；旧 test 版 CLI 得到明确升级/重新授权指引，不静默继续使用旧环境。
- `/.well-known/dydata-agent.json`、`/agent.md`、OAuth metadata、MCP 与 Web 授权页均基于同一生产域和环境配置。
- 历史计划可保留 test 事实，但必须明确已结束，不能作为当前安装入口。

**核心文件**：
- `README.md`
- `docs/cli-agent-guide.md`
- `skills/dydata-agent/SKILL.md`
- `apps/api/dy_api/agent_contract.py`
- `apps/api/dy_api/agent_capabilities.py`
- `apps/cli/pyproject.toml`
- `tests/test_agent_discovery.py`
- `tests/test_deploy_agent_config.py`

**完成标准**：
- 所有当前官方入口只声明 production 与固定生产域；全仓正式路径扫描无 test 残留。
- manifest、doctor、CLI version/minimum version 和升级文案一致。
- 旧 test keyring 不被 production 自动读取；用户得到重新登录指引。
- 测试历史仅存在于明确的历史计划/证据，不参与当前运行或公开发现。

**Verification Method**：
- 运行 discovery、doctor、CLI 契约和部署契约测试。
- 全仓定向扫描 `test`、旧环境描述和公开 URL，逐条分类为历史证据或阻断残留。
- 执行 `python -m pytest -q`、`npm --prefix apps/web run build`、`git diff --check`。

**Evidence**：
- 本子计划 `Evidence Log`；扫描清单；全量测试和 Web build；开发日志。

**Failure Handling**：
- 任一公开入口仍能自动选择 test 时不得进入发布。
- 旧客户端无法获得明确升级路径时，提高 minimum CLI version 并在诊断响应中返回可操作错误。
- 文档与运行契约冲突时以测试锁定的运行契约为准，立即同步文档。

**完成收尾：状态同步**：
- 完成后同步主计划、看板、本子计划和 Linear；三处一致且全量门禁通过后推进 T2.1。

**Owner**：AI 执行 -> 人审核

**前置**：T1.1

**状态**：进行中

## Evidence Log

- 2026-08-27：T1.1 已完成并通过 311 项组合回归；开始切换官方 discovery、文档、CLI 版本和部署契约。
