# DYDATA-40 T1.4 完整验证与安全审查

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-40-secure-terminal-login.md](main-delivery-plan-dydata-40-secure-terminal-login.md)
- 任务看板：[task-kanban-dydata-40-secure-terminal-login.md](task-kanban-dydata-40-secure-terminal-login.md)

#### T1.4 完成规格审查、全量回归和验收交接

**Requirement ID**：DYDATA-40-TERM-VERIFY

**PRD 双链·读**：
- `docs/superpowers/specs/2026-07-22-secure-terminal-cli-login-design.md` §6、§7
- `docs/superpowers/specs/2026-07-21-agent-first-read-only-cli-design.md` §11-§14

**核心逻辑**：
- 由独立子代理分别做规格符合性和代码质量/安全审查，主 Agent 逐项核验证据并负责最终结论。
- 执行目标、全量、Web 构建、文档漂移、治理和 diff 检查；真实密码只由人类在部署后的 TTY 验收输入。

**核心文件**：
- `apps/cli/src/dydata_cli/`
- `tests/cli/`
- `docs/cli-agent-guide.md`
- `docs/cli-agent-acceptance.md`
- `docs/cli-command-reference.md`
- `docs/security/2026-07-22-secure-terminal-cli-login-security-scan.md`
- `docs/devlog/20260722_refactor_log_Keith_Chen.md`

**完成标准**：
- 规格审查和代码质量审查无未解决的 P0/P1；任何安全问题均有代码或明确阻塞记录。
- `python -m pytest`、`npm --prefix apps/web run build`、文档 `--check`、`git diff --check` 全部通过。
- Agent 使用测试脚本/提示词不包含真实凭据，并能覆盖命令发现、身份范围和线索统计；真实 TTY 生产验收留给部署后人工执行。
- Linear `DYDATA-40` 有设计、分支、提交和验证记录，但未经用户要求不部署、不推送、不合并。

**Verification Method**：
- `python -m pytest`
- `npm --prefix apps/web run build`
- `python scripts/generate_cli_docs.py --check`
- `python -m dydata_cli.main commands --json`
- `python -m dydata_cli.main version --json`
- `git diff --check`
- 项目套件结构、一致性、路由和安全检查命令。

**Evidence**：
- 本子计划 `Evidence Log`；`docs/devlog/20260722_secure_terminal_cli_login_Keith_Chen.md`；审查子代理结果；Linear 评论。

**Failure Handling**：
- 全量回归、构建或安全检查失败时保持进行中并修复，不以目标测试代替。
- 项目全局路由若因无关并行计划阻塞，记录精确工具输出并单独证明本计划结构与状态一致，不篡改其他计划。
- 真实生产 TTY 需要部署时只交付验证步骤，未经用户新授权不执行部署。

**完成收尾：状态同步**：
- 完成后把事实、证据、日期、foundation 漂移结论和后续部署建议提交给 `ai-project-manager`，由其同步三处状态。
- 未完成三处同步和最终新鲜验证前不得宣称功能完成。

**Owner**：AI 执行 -> 人审核

**前置**：T1.3

**状态**：已完成（2026-07-22）

## Evidence Log

- 目标回归：`python -m pytest tests/cli/test_interactive_auth.py tests/cli/test_terminal_login.py tests/cli/test_commands.py tests/cli/test_parser.py tests/cli/test_registry.py tests/cli/test_docs.py tests/cli/test_cli_security.py tests/test_api_auth.py tests/test_api_cli_auth.py -q` -> 137 passed。
- 全量回归：`python -m pytest -q` -> 817 passed，69 个既有 Alembic/SQLite deprecation warnings。
- Web 构建：`npm --prefix apps/web run build` -> TypeScript 与 Vite production build 通过。
- 运行时 smoke：editable install 指向当前工作树；`dydata version --json` 为 CLI `0.2.0` / Schema `1.0`；`commands --json` 的安全人工交接字段符合设计。
- 文档与静态门槛：生成文档 `--check`、compileall、`git diff --check`、`git diff main --check` 通过；Bandit 为 0 High / 0 Medium / 2 个既有 Low。
- 依赖与秘密：根项目和 CLI 的 `pip-audit` 均为 0 已知漏洞；`npm audit` 为 1 个既有 Low、0 Moderate/High/Critical；生产代码未命中高置信秘密模式。
- 独立审查：安全/规格代理最终 `APPROVE`，CLI Agent 契约验收 `PASS`（61 tests passed）；已按 TDD 修复 cleanup 异常掩盖原始 CAS/save 结果的问题。
- 安全结论：`docs/security/2026-07-22-secure-terminal-cli-login-security-scan.md` -> `PASS`，无阻断项或 waiver。
- 治理门槛：suite lock、global files、计划结构和 T1.4 进行中时的三处一致性均通过；日志追加后全局 S7 的阶段写回检查已通过，`route-check --target-stage S7` 仅因并行 FOUNDATION 主线没有 `docs/test-case/reports` 发布输入而保持 `security_scan_inputs_missing`，未伪造该无关主线材料。
- Agent 验收交接：`docs/cli-agent-acceptance.md` 不含真实凭据；真实 TTY、keyring、生产门店范围和线索数据验收明确留给部署后用户本人执行。
