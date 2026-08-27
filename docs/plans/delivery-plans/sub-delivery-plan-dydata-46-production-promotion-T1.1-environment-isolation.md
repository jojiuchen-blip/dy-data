# DYDATA-46 T1.1 生产环境与凭证隔离

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-46-production-promotion.md](main-delivery-plan-dydata-46-production-promotion.md)
- 任务看板：[task-kanban-dydata-46-production-promotion.md](task-kanban-dydata-46-production-promotion.md)

#### T1.1 建立 production 环境契约并拒绝旧 test 凭证

**Requirement ID**：DYDATA-46-PROD-ISOLATION

**PRD 双链·读**：
- Linear `DYDATA-46` 的 production/test 隔离验收标准
- `docs/prd/mainprd-dy-data.md` 全局权限与数据范围规则
- `docs/prd/foundation/foundation-api-dy-data/common-contract.md`
- `docs/superpowers/specs/2026-07-22-dydata-45-test-agent-connect-design.md` 的命名环境、keyring、OAuth 和审计基线

**核心逻辑**：
- CLI 声明受控 `production` 环境，基地址固定为 `https://dy-business-engine.com`，并将默认环境切换为 production；不接受任意 URL。
- API 运行环境允许且要求 production；manifest、MCP initialize、业务响应和审计从统一运行环境读取，不再硬编码 test。
- OAuth access/refresh token、authorization code 和 consent 必须绑定运行环境或等价的 issuer/resource 身份；服务切换后 test 凭证一律拒绝。
- keyring 继续按命名环境与规范化 server identity 隔离；production 首次使用必须重新授权。

**核心文件**：
- `apps/cli/src/dydata_cli/environments.py`
- `apps/cli/src/dydata_cli/credentials.py`
- `apps/api/dy_api/agent_environment.py`
- `apps/api/dy_api/agent_contract.py`
- `apps/api/dy_api/mcp_oauth.py`
- `apps/api/dy_api/mcp_server.py`
- `apps/api/dy_api/cli_audit.py`
- `apps/api/dy_api/models.py`
- `alembic/versions/`
- `tests/test_cli_environment.py`
- `tests/test_mcp_oauth.py`
- `tests/test_mcp_server.py`

**完成标准**：
- production 是唯一默认环境且 URL 固定；未知环境和任意 URL 快速失败。
- test 与 production 生成不同 keyring 槽位；没有 production 凭证时明确要求重新登录。
- test 签发/保存的授权码、access token、refresh token 在 production 运行环境被拒绝。
- Agent manifest、MCP initialize、CLI/MCP 业务结果和审计记录均报告 `environment=production`。
- 任何日志和错误均不包含 token、Cookie、密码或内部授权码。

**Verification Method**：
- 先运行目标测试并确认新增 production / 跨环境拒绝用例 RED，再最小实装至 GREEN。
- 执行 CLI、OAuth、MCP、审计相关测试集和迁移往返测试。
- 执行 `git diff --check`。

**Evidence**：
- 本子计划 `Evidence Log`；目标 pytest 输出；迁移结果；`docs/devlog/2026-08-27-dydata-46-production-promotion.md`。

**Failure Handling**：
- 若现有 token 数据模型无法无损绑定环境，新增可逆迁移；无法保证旧 test 凭证失效时阻塞发布。
- 若 OAuth issuer/resource 与固定生产域不一致，停止进入 T1.2 并先修复契约。
- 若验证需要真实凭证，只允许用户在浏览器/TTY 输入；测试与日志使用脱敏数据。

**完成收尾：状态同步**：
- 完成实现、验证和 foundation 漂移判断后，同步主计划、看板、本子计划与 Linear；一致性检查通过后再推进 T1.2。

**Owner**：AI 执行 -> 人审核

**前置**：DYDATA-45 完成；用户确认生产域名

**状态**：已完成（2026-08-27）

## Evidence Log

- 2026-08-27：代码审计确认 CLI、API guard、MCP initialize、审计和部署 smoke 仍存在 test 硬编码；进入 TDD 修复。
- 2026-08-27：按 RED -> GREEN 完成 production 默认环境、test/production 独立 keyring、动态 API/MCP/CLI/审计环境与跨环境 token 拒绝；目标组合回归 `311 passed`，`git diff --check` 通过。
- OAuth 数据模型原本已在 client、authorization request、access token、refresh token 中持久化 `environment`，无需 Schema 迁移；切换 production 后旧 test 凭证自然失配。
- Foundation 漂移结论：无。现有 API/权限契约可承载生产升格，不需要回改 Foundation。
