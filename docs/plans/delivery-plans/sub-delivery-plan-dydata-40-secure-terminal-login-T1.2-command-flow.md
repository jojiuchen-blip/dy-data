# DYDATA-40 T1.2 安全终端命令流程

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-40-secure-terminal-login.md](main-delivery-plan-dydata-40-secure-terminal-login.md)
- 任务看板：[task-kanban-dydata-40-secure-terminal-login.md](task-kanban-dydata-40-secure-terminal-login.md)

#### T1.2 实现 TTY 登录、身份确认、CAS 保存和浏览器回退

**Requirement ID**：DYDATA-40-TERM-COMMAND

**PRD 双链·读**：
- `docs/superpowers/specs/2026-07-22-secure-terminal-cli-login-design.md` §3、§4.1、§4.3、§5

**核心逻辑**：
- `dydata auth login` 默认要求真实交互 TTY，由用户输入 username 和隐藏 password，验证身份摘要后以 `y/N` 批准。
- `--browser` 保留既有设备授权；两种模式都在网络前阻止静默覆盖已有凭据。
- 最终凭据使用 `expected=None` 保存；竞态失败时不覆盖先写状态并尽力撤销本次新令牌。

**核心文件**：
- `apps/cli/src/dydata_cli/commands.py`
- `apps/cli/src/dydata_cli/parser.py`
- `apps/cli/src/dydata_cli/registry.py`
- `tests/cli/test_commands.py`
- `tests/cli/test_parser.py`
- `tests/cli/test_cli_security.py`

**完成标准**：
- 非 TTY 不调用输入函数或网络，明确失败；无密码参数、环境变量或管道入口。
- 用户取消时不批准、不换取 Token、不保存；密码不出现在 stdout/stderr 或异常。
- 终端确认后批准、换取并保存一次；已有凭据为无网络 no-op；并发保存不覆盖。
- `dydata auth login --browser` 保持原 URL、用户码和轮询行为。

**Verification Method**：
- RED/GREEN：`python -m pytest tests/cli/test_commands.py tests/cli/test_parser.py tests/cli/test_cli_security.py -q`
- 对解析器执行秘密参数负向用例并运行 `git diff --check`。

**Evidence**：
- 本子计划 `Evidence Log`；对应 git commit；pytest 终端输出。

**Failure Handling**：
- 若运行环境无法判断 TTY，默认拒绝而不是回退到可回显输入。
- 若 CAS 保存失败后的新令牌无法安全撤销，保留先写凭据并返回安全错误，不做覆盖。
- 代码与设计冲突时阻塞，先修订设计再继续。

**完成收尾：状态同步**：
- 完成后把事实、证据、日期、foundation 漂移结论和建议 T1.3 提交给 `ai-project-manager`，由其同步三处状态。
- 未完成三处同步前不得标记本 Task 已完成。

**Owner**：AI 执行 -> 人审核

**前置**：T1.1

**状态**：待开发

## Evidence Log

- 待生成。

