# DYDATA-40 T1.1 独立终端认证会话

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-40-secure-terminal-login.md](main-delivery-plan-dydata-40-secure-terminal-login.md)
- 任务看板：[task-kanban-dydata-40-secure-terminal-login.md](task-kanban-dydata-40-secure-terminal-login.md)

#### T1.1 建立隔离的 Web 登录与设备批准会话

**Requirement ID**：DYDATA-40-TERM-AUTH-SESSION

**PRD 双链·读**：
- `docs/superpowers/specs/2026-07-22-secure-terminal-cli-login-design.md` §3、§4.2、§6
- `docs/superpowers/specs/2026-07-21-agent-first-read-only-cli-design.md` §10、§11

**核心逻辑**：
- 新建只承担 `/auth/login` 与 `/auth/cli/device/approve` 的短生命周期客户端；Web Cookie 不进入 `DyDataClient` 的业务请求会话。
- 对登录身份与批准响应执行严格字段白名单重建；服务端错误内容不得进入本地异常。
- 所有认证 POST 单次提交；退出上下文时清 Cookie 并关闭连接。

**核心文件**：
- `apps/cli/src/dydata_cli/interactive_auth.py`
- `apps/cli/src/dydata_cli/constants.py`
- `tests/cli/test_interactive_auth.py`
- `tests/cli/test_output.py`

**完成标准**：
- 正确登录请求只提交一次，密码仅存在于请求 JSON，不进入结果、异常或对象表示。
- 登录响应精确验证 username、role、store scope 和 Web session 元数据；额外秘密字段触发 `SCHEMA_MISMATCH`。
- 401 映射为稳定认证失败，429/5xx/网络异常映射为既有安全错误，不回显服务器 detail。
- 批准请求复用同一 Cookie；关闭时 Cookie 被清除且客户端关闭。

**Verification Method**：
- RED：`python -m pytest tests/cli/test_interactive_auth.py tests/cli/test_output.py -q`
- GREEN：同一命令全部通过，并运行 `git diff --check`。

**Evidence**：
- 本子计划 `Evidence Log`；对应 git commit；pytest 终端输出。

**Failure Handling**：
- 登录响应结构与现有 API 代码冲突时阻塞并以 `apps/api/dy_api/routes/auth.py` 的真实响应为准修订设计。
- 无法隔离 Cookie 或测试中出现秘密回显时不得进入 T1.2。
- 验证资产缺失时先补测试，不以人工目测替代。

**完成收尾：状态同步**：
- 完成实现、验证和 foundation 漂移判断后，把完成事实、证据、日期、漂移结论和建议 T1.2 提交给 `ai-project-manager`。
- 由其调度 `delivery-planner` 同步主计划、任务看板和本子计划；未同步前不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：无

**状态**：进行中

## Evidence Log

- 待生成。

