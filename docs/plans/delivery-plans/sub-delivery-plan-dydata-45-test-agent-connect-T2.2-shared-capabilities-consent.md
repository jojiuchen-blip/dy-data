# DYDATA-45 T2.2 共享只读能力、MCP 工具与 Web 授权页

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-45-test-agent-connect.md](main-delivery-plan-dydata-45-test-agent-connect.md)
- 任务看板：[task-kanban-dydata-45-test-agent-connect.md](task-kanban-dydata-45-test-agent-connect.md)

#### T2.2 复用同一权限和统计口径并闭合用户授权

**Requirement ID**：DYDATA-45-MCP-CAPABILITIES

**PRD 双链·读**：
- `docs/superpowers/specs/2026-07-22-dydata-45-test-agent-connect-design.md` §7、§10
- `docs/superpowers/specs/2026-07-21-agent-first-read-only-cli-design.md` 跟进率与门店范围章节

**核心逻辑**：
- 从 CLI 路由抽取共享只读能力服务，统一当前用户重载、门店 scope、日期校验、跟进率计算和 envelope。
- MCP 只注册 `stores_list`、`clues_follow_up_stats` 两项工具，使用 OAuth subject 重新加载当前账号和授权门店。
- 新增 Web 授权确认页和 `/api/v1/auth/mcp/approve`，用户登录后明确看到 Agent 名称、redirect URI、scope、环境和数据范围再批准或拒绝。
- CLI 与 MCP 审计包含环境、账号、能力、范围、结果和 request id，且不记录 token。

**核心文件**：
- `apps/api/dy_api/agent_capabilities.py`
- `apps/api/dy_api/routes/cli.py`
- `apps/api/dy_api/mcp_server.py`
- `apps/api/dy_api/routes/mcp_auth.py`
- `apps/web/src/App.tsx`
- `apps/web/src/pages/McpAuthorizePage.tsx`
- `tests/test_api_agent_capabilities.py`
- `tests/test_api_mcp_tools.py`

**完成标准**：
- 同一测试用户、日期和 store_id 通过 CLI/API 与 MCP 返回相同 total/pending/followed_up/follow_up_rate。
- 未授权门店、禁用用户、环境不符、错误日期和缺失 `mcp:read` 均以稳定错误拒绝。
- MCP 工具清单严格等于两项，无资源写入类工具；工具说明明确只读和 scope。
- 授权页支持登录回跳、批准、拒绝、过期和重复提交，密码仅由现有 Web 登录处理。

**Verification Method**：
- RED/GREEN：`python -m pytest tests/test_api_agent_capabilities.py tests/test_api_mcp_tools.py tests/test_api_cli.py -q`
- 执行 `npm --prefix apps/web run build` 和授权页组件测试。

**Evidence**：
- 本子计划 `Evidence Log`；CLI/MCP 等价响应断言；Web build/test 输出；脱敏审计样例。

**Failure Handling**：
- 若抽取改变现有 CLI 口径，保留现有 route 为基线并先补回归断言，未一致不得注册 MCP 工具。
- 若账号或门店在授权后变更，每次工具调用必须以数据库当前状态为准；无法重载则拒绝。
- 前端授权上下文缺失或过期时拒绝，不自动批准。

**完成收尾：状态同步**：
- 完成后把事实、证据、完成日期、foundation 漂移结论和建议 T3.1 提交给 `ai-project-manager`，由其同步三处状态。
- 未完成状态同步前不得标记本 Task 完成。

**Owner**：AI 执行 -> 人审核

**前置**：T2.1

**状态**：已完成（2026-07-22）

## Evidence Log

- RED：新增共享能力、MCP 工具、Web 授权页与审计迁移测试后，分别因 `dy_api.agent_capabilities`、两项 MCP 工具和 `McpAuthorizePage.tsx` 尚不存在而失败。
- GREEN：`apps/api/dy_api/agent_capabilities.py` 成为 CLI/MCP 共用的门店范围、日期校验、跟进统计与跟进率口径；默认日期按 `Asia/Shanghai` 自然日计算。
- MCP：`tools/list` 严格只有 `stores_list` 与 `clues_follow_up_stats`，均声明只读、非破坏、幂等和封闭数据源；同一账号、门店和日期与 CLI 返回相同 scope、filters、stores 与 totals。
- 权限负向：未授权门店、禁用用户、环境不符、错误日期、过期/重复授权均稳定拒绝；授权失效竞态使用普通内部异常，避免冻结 SDK 异常穿越事务上下文。
- Web：`/auth/mcp/authorize` 在登录后展示 Agent 名称、当前账号、测试环境、`mcp:read`、可读门店和回调地址，支持批准与拒绝，页面不采集密码。
- 审计：`cli_audit_events` 新增 `environment`、`channel`、`authorization_scopes`，CLI/MCP 均记录账号、能力、数据范围、结果和 request id，不记录 access/refresh token。
- 验证：T2.2 定向 72 项通过；新增授权竞态测试与 MCP 工具回归 5 项通过；Alembic 前进/回退/再前进通过；`npm run build` 通过；全量回归 869 项通过；`compileall` 与 `git diff --check` 通过。
- Foundation 漂移：无。只复用现有只读统计口径和账号门店范围，不改变线索中心业务状态或写入流程。
- 下一步：T3.1 检查镜像、反向代理和迁移路径，部署测试环境后由独立 Agent 使用公开文档和测试账号执行 CLI/MCP 黑盒验收。
