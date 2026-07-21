# DYDATA-40 T1.3 命令发现与 Agent 文档契约

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-40-secure-terminal-login.md](main-delivery-plan-dydata-40-secure-terminal-login.md)
- 任务看板：[task-kanban-dydata-40-secure-terminal-login.md](task-kanban-dydata-40-secure-terminal-login.md)

#### T1.3 同步注册表、版本与 Agent 登录说明

**Requirement ID**：DYDATA-40-TERM-DOCS

**PRD 双链·读**：
- `docs/superpowers/specs/2026-07-22-secure-terminal-cli-login-design.md` §1、§2、§5、§7.5
- `docs/superpowers/specs/2026-07-21-agent-first-read-only-cli-design.md` §8

**核心逻辑**：
- 运行时注册表仍是命令事实源，声明 `--browser`、默认终端模式、人类交接和两种输出变体。
- Agent 指南明确区分“可由 Agent 启动并交给用户”与“Agent 自主可调用”，严禁把密码粘贴进对话。
- 自动生成命令参考，避免手工事实漂移；同步 CLI 包版本和 README。

**核心文件**：
- `apps/cli/src/dydata_cli/registry.py`
- `apps/cli/src/dydata_cli/constants.py`
- `apps/cli/pyproject.toml`
- `docs/cli-agent-guide.md`
- `docs/cli-command-reference.md`
- `README.md`
- `tests/cli/test_registry.py`
- `tests/cli/test_docs.py`

**完成标准**：
- `commands --json` 声明默认 terminal、`--browser` 回退、`agent_callable=false` 和人工安全 TTY 交接。
- 指南明确密码隐藏、非 TTY 回退、已有凭据切换规则和 Agent 禁止行为。
- 生成命令参考无漂移，CLI 包版本与运行时版本一致。

**Verification Method**：
- `python scripts/generate_cli_docs.py`
- `python -m pytest tests/cli/test_registry.py tests/cli/test_parser.py tests/cli/test_docs.py -q`
- `python scripts/generate_cli_docs.py --check`

**Evidence**：
- 本子计划 `Evidence Log`；生成文档 diff；pytest 和生成器输出。

**Failure Handling**：
- 注册表不能表达人工交接时先扩展元数据和生成器测试，不写只存在于说明文的隐藏规则。
- 版本事实源不一致时阻塞发布验证。
- 文档生成漂移未清零时不得进入 T1.4。

**完成收尾：状态同步**：
- 完成后把事实、证据、日期、foundation 漂移结论和建议 T1.4 提交给 `ai-project-manager`，由其同步三处状态。
- 未完成三处同步前不得标记本 Task 已完成。

**Owner**：AI 执行 -> 人审核

**前置**：T1.2

**状态**：待开发

## Evidence Log

- 待生成。

