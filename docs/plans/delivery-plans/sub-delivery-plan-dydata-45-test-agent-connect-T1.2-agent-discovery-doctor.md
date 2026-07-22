# DYDATA-45 T1.2 Agent 发现入口、Skill 与诊断

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-45-test-agent-connect.md](main-delivery-plan-dydata-45-test-agent-connect.md)
- 任务看板：[task-kanban-dydata-45-test-agent-connect.md](task-kanban-dydata-45-test-agent-connect.md)

#### T1.2 发布稳定 Agent 发现契约并提供一键诊断

**Requirement ID**：DYDATA-45-AGENT-DISCOVERY

**PRD 双链·读**：
- `docs/superpowers/specs/2026-07-22-dydata-45-test-agent-connect-design.md` §8-§9

**核心逻辑**：
- 同域发布 `/.well-known/dydata-agent.json`、`/agent.md`、`/agent/SKILL.md` 和 `/api/v1/agent/capabilities`。
- manifest 从共享注册表和命名环境生成 CLI 安装、MCP URL、OAuth 元数据、可调用能力和只读边界。
- 新增 `dydata agent doctor --json`，在不泄露凭据的情况下检查环境、发现文档、MCP resource metadata、CLI 凭据状态和版本兼容性。

**核心文件**：
- `apps/api/dy_api/routes/agent.py`
- `apps/cli/src/dydata_cli/commands.py`
- `apps/cli/src/dydata_cli/parser.py`
- `apps/cli/src/dydata_cli/docs.py`
- `tests/cli/test_agent_doctor.py`
- `tests/test_api_agent.py`

**完成标准**：
- 四个公开入口无需登录可读取，环境固定为 `test`，能力列表只含两项只读业务能力。
- manifest 同时提供远程 MCP 首选路径和 CLI fallback 安装/执行说明，不包含生产地址。
- `agent doctor --json` 对正常、不可达、manifest 环境不符、schema 不兼容、未登录分别输出稳定机器可读结果。
- `agent/SKILL.md` 明确 Agent 不得索取账号密码，需把授权交还给用户浏览器或真实 TTY。

**Verification Method**：
- RED/GREEN：`python -m pytest tests/cli/test_agent_doctor.py tests/test_api_agent.py -q`
- 生成 CLI 文档并执行文档漂移测试。

**Evidence**：
- 本子计划 `Evidence Log`；pytest、文档生成/漂移检查输出；公开入口响应样例。

**Failure Handling**：
- 发现内容与注册表不一致时阻塞，不允许手工修正文档绕过生成源。
- 网络不可达仅在 doctor 中标记诊断失败，不读取或打印 keyring token。
- Agent 平台不支持 MCP 时明确降级到 CLI，不扩大能力或引入写操作。

**完成收尾：状态同步**：
- 完成后把事实、证据、完成日期、foundation 漂移结论和建议 T2.1 提交给 `ai-project-manager`，由其同步三处状态。
- 未完成状态同步前不得标记本 Task 完成。

**Owner**：AI 执行 -> 人审核

**前置**：T1.1

**状态**：已完成（2026-07-22）

## Evidence Log

- RED：公开 manifest/capabilities/Markdown/Skill 均返回 404，CLI parser 不识别 `agent doctor`，共 `7 failed`。
- GREEN：`python -m pytest tests/test_api_agent.py tests/cli/test_agent_doctor.py -q`，`7 passed`；覆盖未登录、已登录、端点不可达和环境不兼容。
- 组合回归：`python -m pytest tests/cli tests/test_api_agent.py tests/test_cli_contract_registry.py tests/test_api_cli_readonly.py tests/test_cli_audit.py -q`，`243 passed`。
- `docs/cli-command-reference.md` 已由注册表重新生成；README 与 Agent 指南已指向稳定 manifest、MCP 和 doctor。
- `git diff --check` 通过；仅有 Git 的 LF/CRLF 工作区提示，无 whitespace error。
- Foundation 漂移：无。发现契约是本 issue 新增交付物，未发现既有 Foundation Schema/API 与代码现实冲突。
