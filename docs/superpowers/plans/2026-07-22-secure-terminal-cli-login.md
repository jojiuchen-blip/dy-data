# 安全终端 CLI 登录实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `agent-orchestrated-development` for bounded reviews and `test-driven-development` for every production change.

**Goal:** 让 `dydata auth login` 默认在安全交互 TTY 中由用户输入账号和隐藏密码，复用现有 Web Session + device grant 链签发 `cli:read` 凭据，并保留 `--browser` 回退。

**Architecture:** 新增独立 `InteractiveAuthSession`，只调用现有 `/auth/login` 与 `/auth/cli/device/approve`，严格验证响应并在上下文结束时清 Cookie。`commands.py` 负责 TTY 检查、提示、身份确认、设备码交换和 keyring compare-and-swap；`DyDataClient` 的业务只读表面保持不变。

**Tech Stack:** Python 3.12、argparse、getpass、httpx、keyring、pytest。

**Formal authority:** `docs/plans/delivery-plans/main-delivery-plan-dydata-40-secure-terminal-login.md`。本文件只提供逐步 TDD 执行程序，不替代正式计划状态。

---

### Task 1：隔离认证会话与错误契约

**Files:**
- Create: `apps/cli/src/dydata_cli/interactive_auth.py`
- Modify: `apps/cli/src/dydata_cli/constants.py`
- Create: `tests/cli/test_interactive_auth.py`
- Modify: `tests/cli/test_output.py`

1. 写失败测试：正确登录/批准共享 Cookie；异常响应额外字段被拒绝；401、429、5xx、网络错误不泄漏密码或服务端 detail；退出上下文清 Cookie 和 close。
2. 运行 `python -m pytest tests/cli/test_interactive_auth.py tests/cli/test_output.py -q`，确认 RED 来自模块/错误契约尚不存在。
3. 实现 `LoginIdentity` 和 `InteractiveAuthSession`，认证 POST 单次请求，响应只重建批准字段。
4. 再运行同一命令确认 GREEN；运行 `git diff --check`。
5. 提交：`feat(cli): add isolated interactive auth session`。

### Task 2：默认终端登录和浏览器回退

**Files:**
- Modify: `apps/cli/src/dydata_cli/commands.py`
- Modify: `apps/cli/src/dydata_cli/registry.py`
- Modify: `tests/cli/test_commands.py`
- Modify: `tests/cli/test_parser.py`
- Modify: `tests/cli/test_cli_security.py`

1. 先把旧浏览器用例改为显式 `--browser`，新增默认 TTY 成功、非 TTY、取消、已有凭据、无效密码、CAS 竞态和秘密不回显测试。
2. 运行目标测试，确认默认路径 RED。
3. 把 `_login` 拆成 guard、terminal 和 browser 三段；默认用 `getpass`，仅 `y/yes` 批准；保存使用 `expected=None`。
4. 生成新凭据但 CAS 失败时，尽力撤销新 refresh token，绝不清除先写入状态。
5. 运行目标测试确认 GREEN，并提交：`feat(cli): make secure terminal login the default`。

### Task 3：运行时发现、版本和文档

**Files:**
- Modify: `apps/cli/src/dydata_cli/constants.py`
- Modify: `apps/cli/pyproject.toml`
- Modify: `apps/cli/src/dydata_cli/registry.py`
- Modify: `tests/cli/test_registry.py`
- Modify: `tests/cli/test_docs.py`
- Modify: `README.md`
- Modify: `docs/cli-agent-guide.md`
- Regenerate: `docs/cli-command-reference.md`

1. 先更新测试，要求 `--browser`、人工 TTY handoff、两种输出和包/运行时版本一致；运行并确认 RED。
2. 更新注册表为运行时权威来源，CLI 版本升为 `0.2.0`，Schema 版本保持 `1.0`。
3. 指南写明 Agent 只可在用户指示下启动并交接；密码永不粘贴到对话；无 TTY 使用浏览器回退。
4. 运行 `python scripts/generate_cli_docs.py`，再运行文档与注册表测试及 `--check`。
5. 提交：`docs(cli): document secure terminal login handoff`。

### Task 4：独立审查与完整验证

**Files:**
- Review: `apps/cli/src/dydata_cli/`
- Review: `tests/cli/`
- Create: `docs/devlog/20260722_secure_terminal_cli_login_Keith_Chen.md`
- Modify: 正式计划三处状态和 Evidence

1. 派发只读规格审查子代理；主 Agent 修复并重新跑目标测试。
2. 派发只读代码质量/安全审查子代理；主 Agent 核实每条发现。
3. 新鲜运行：目标测试、`python -m pytest`、Web build、文档 `--check`、CLI smoke、`git diff --check`、项目套件结构/一致性/安全检查。
4. 生成不含真实凭据的 Agent CLI 使用测试说明；真实 TTY 密码验收只在部署后由用户输入。
5. 同步 devlog、正式计划和 Linear `DYDATA-40`，提交：`test(cli): verify secure terminal login`。

