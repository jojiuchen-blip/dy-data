# DYDATA-45 T1.1 CLI 命名环境、凭据隔离与共享注册表

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-45-test-agent-connect.md](main-delivery-plan-dydata-45-test-agent-connect.md)
- 任务看板：[task-kanban-dydata-45-test-agent-connect.md](task-kanban-dydata-45-test-agent-connect.md)

#### T1.1 建立命名环境、凭据隔离与单一能力目录

**Requirement ID**：DYDATA-45-CLI-ENV-REGISTRY

**PRD 双链·读**：
- `docs/superpowers/specs/2026-07-22-dydata-45-test-agent-connect-design.md` §4-§5、§10

**核心逻辑**：
- 固定解析命名环境 `test`，未知值快速失败；常规执行不允许通过任意 API URL 绕过环境边界。
- keyring account 使用 `env:test:<server_identity_hash>`，旧 `default` 凭据不自动迁移，避免测试/生产串号。
- `dydata_cli.registry` 成为命令、API 路径、MCP 工具和 agent-callable 属性的单一事实源；服务端映射从该目录派生。
- CLI 与 API 成功/失败 envelope 均显式返回 `environment=test`，schema 升级时保持严格验证。

**核心文件**：
- `apps/cli/src/dydata_cli/environments.py`
- `apps/cli/src/dydata_cli/credentials.py`
- `apps/cli/src/dydata_cli/client.py`
- `apps/cli/src/dydata_cli/registry.py`
- `apps/api/dy_api/cli_contract.py`
- `tests/cli/`

**完成标准**：
- `DYDATA_ENV=test` 或未设置时解析为固定测试端点；其他值返回稳定配置错误。
- keyring account 精确包含环境名与服务端身份哈希，并有两个虚拟环境不共享凭据的测试。
- API path/operation map 由注册表生成，移除 `cli_contract.py` 的重复硬编码。
- 两个只读业务命令保持 `agent_callable=true`，登录/退出保持不可由 Agent 调用；输出带 `environment=test`。

**Verification Method**：
- RED/GREEN：`python -m pytest tests/cli/test_environments.py tests/cli/test_credentials.py tests/cli/test_registry.py tests/cli/test_output.py tests/test_api_cli.py -q`
- 运行 `git diff --check`。

**Evidence**：
- 本子计划 `Evidence Log`；pytest 和 diff-check 终端输出；对应 git commit。

**Failure Handling**：
- 若现有严格 schema 与环境字段冲突，先更新 schema version 和契约测试，不允许放宽为接受任意字段。
- 若 keyring 后端不可用，保持现有稳定错误，不回退到明文文件。
- 若 API 无法导入 CLI registry，先修正镜像/PYTHONPATH 设计，不复制第二份映射。

**完成收尾：状态同步**：
- 完成实现、验证和 foundation 漂移判断后，把完成事实、证据、完成日期、漂移结论和建议 T1.2 提交给 `ai-project-manager`。
- 由其调度 `delivery-planner` 同步主计划、任务看板和本子计划；未同步前不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：无

**状态**：已完成（2026-07-22）

## Evidence Log

- RED：新增环境、凭据隔离和注册表派生测试后，测试收集因 `dydata_cli.environments` 与映射 helper 不存在而失败。
- GREEN：`python -m pytest tests/cli/test_environments.py tests/cli/test_credentials.py tests/cli/test_registry.py tests/cli/test_output.py tests/cli/test_client.py tests/cli/test_contracts.py tests/test_cli_contract_registry.py tests/test_api_cli_readonly.py tests/test_cli_audit.py -q`，`155 passed`。
- `git diff --check` 通过；仅有 Git 的 LF/CRLF 工作区提示，无 whitespace error。
- 生产代码中已无 `DYDATA_API_URL` 读取；固定测试环境为 `https://dy-business-engine.com`，keyring account 为 `env:test:<server_identity_hash>`。
- Foundation 漂移：无。本任务按已确认增量规格升级 CLI schema 至 `1.1`，未要求回改现有 Foundation 产物。
