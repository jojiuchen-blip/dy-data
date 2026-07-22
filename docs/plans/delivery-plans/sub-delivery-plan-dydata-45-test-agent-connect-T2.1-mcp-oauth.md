# DYDATA-45 T2.1 远程 MCP OAuth 2.1 与持久凭据

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-45-test-agent-connect.md](main-delivery-plan-dydata-45-test-agent-connect.md)
- 任务看板：[task-kanban-dydata-45-test-agent-connect.md](task-kanban-dydata-45-test-agent-connect.md)

#### T2.1 建立标准远程 MCP 与 OAuth 2.1 授权服务器

**Requirement ID**：DYDATA-45-MCP-OAUTH

**PRD 双链·读**：
- `docs/superpowers/specs/2026-07-22-dydata-45-test-agent-connect-design.md` §6、§10

**核心逻辑**：
- 使用稳定 MCP Python SDK v1 和 Streamable HTTP 暴露 `/mcp`；发布 RFC 9728 protected resource metadata 与授权服务器 metadata。
- 只接受 OAuth 2.1 authorization code + PKCE S256；动态注册仅允许 public clients，redirect URI 精确匹配。
- 授权请求、单次 code、access token hash、refresh token hash/family 均持久化；access token 30 分钟，refresh token 30 天且旋转重放即撤销 family。
- scope 固定 `mcp:read`，resource/audience 固定 `/mcp`，issuer 固定测试域名根。

**核心文件**：
- `apps/api/dy_api/mcp_oauth.py`
- `apps/api/dy_api/mcp_server.py`
- `apps/api/dy_api/models.py`
- `alembic/versions/20260722_0021_mcp_oauth.py`
- `tests/test_api_mcp_oauth.py`
- `tests/test_alembic_migrations.py`

**完成标准**：
- metadata、DCR、authorize、token、revoke 与 `/mcp` 路由符合设计中的固定 URL。
- plain/no PKCE、错误 verifier、错误 resource/audience/scope、过期/复用 code、refresh replay 全部被拒绝。
- 数据库不持久化明文 code/access/refresh token；重启后合法 token 仍可验证，撤销后立即失效。
- MCP 依赖锁定 `mcp>=1.27,<2`，父 FastAPI lifespan 正确管理 session manager。

**Verification Method**：
- RED/GREEN：`python -m pytest tests/test_api_mcp_oauth.py tests/test_migrations.py -q`
- 对迁移执行 upgrade/downgrade/upgrade；扫描日志和数据库断言无明文 token。

**Evidence**：
- 本子计划 `Evidence Log`；协议测试和迁移输出；脱敏数据库断言。

**Failure Handling**：
- SDK 行为与锁定版本不一致时阻塞并以官方 v1 API 修订，不切换到 v2 prerelease。
- 无法证明 token 哈希持久化、PKCE 或 audience 校验时不得进入 T2.2。
- 数据库迁移失败时回滚 0021，不复用 CLI refresh token 表。

**完成收尾：状态同步**：
- 完成后把事实、证据、完成日期、foundation 漂移结论和建议 T2.2 提交给 `ai-project-manager`，由其同步三处状态。
- 未完成状态同步前不得标记本 Task 完成。

**Owner**：AI 执行 -> 人审核

**前置**：T1.2

**状态**：已完成（2026-07-22）

## Evidence Log

- RED：新增协议测试最初因 MCP OAuth 模型、provider 与路由不存在而在收集阶段失败；补充弱 PKCE challenge/verifier 测试后分别观察到未拒绝和错误类型不符。
- GREEN：`python -m pytest tests/test_api_mcp_oauth.py -q`，`16 passed`；覆盖公开 DCR、固定 metadata、PKCE S256、错误/缺失 verifier、错误 resource/scope、过期与复用 code、摘要持久化、重启验证、撤销、账号失效、refresh rotation/replay 和真实 MCP initialize。
- 迁移：`python -m pytest tests/test_api_mcp_oauth.py tests/test_alembic_migrations.py -q`，覆盖 `20260722_0021` 的 upgrade -> downgrade -> upgrade；四张独立 MCP OAuth 表及关键唯一索引通过断言。
- 组合回归：`python -m pytest tests/cli tests/test_api_agent.py tests/test_cli_contract_registry.py tests/test_api_cli_readonly.py tests/test_cli_audit.py tests/test_api_mcp_oauth.py -q`，`256 passed`。
- 安全事实：客户端只允许显式 `token_endpoint_auth_method=none`；scope 固定 `mcp:read`，resource 固定测试环境 `/mcp`；数据库只保存 request/code/access/refresh 的 SHA-256 摘要；refresh 重放撤销完整 family。
- SDK 兼容：依赖锁定 `mcp>=1.27,<2`；针对 SDK v1 metadata 和 revoke handler 的 confidential-client 默认行为，父 FastAPI 显式发布 public-client metadata 和无密钥 revoke 端点，协议测试覆盖真实响应。
- 合并前安全复审：OAuth 协议文件现收集 47 项测试；DCR 在 16 KiB 首个超限 chunk 处立即停止读取，并限制 client metadata、拒绝 JWKS；畸形语法、空体、非法 UTF-8、非标准常量、深递归或非对象顶层 JSON 均返回不泄露细节的通用 OAuth 400；redirect URI 仅允许 HTTPS 或精确本机回环 HTTP，注册、存量客户端、授权请求、同意详情、批准/拒绝及浏览器导航前均 fail closed；同时覆盖 no-store 与 CLI/MCP token 双向隔离。opt-in PostgreSQL 用例验证授权码并发单次消费和 refresh rotation/replay，真实 PostgreSQL 连续 5 轮共 10 项并发断言全部通过。最终独立安全复审为 `ALLOW`，无 Critical、Important 或 Minor。
- `git diff --check` 与 Python compileall 通过，仅有 Git LF/CRLF 工作区提示，无 whitespace error。
- Foundation 漂移：无。本 Task 新增独立协议与持久化表，未复用 CLI token 表，也未改变既有业务 Schema/API 口径；建议 T2.2 直接复用现有 CLI 查询服务并补 Web 授权确认页。
