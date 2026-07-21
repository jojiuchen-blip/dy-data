# dydata Agent CLI 使用验收

本文用于部署后验证 Agent 能否安全接入 `dydata`。验收分为“Agent 可自动执行的契约检查”和“必须由用户接管的真实登录”两段；任何证据都不得包含账号、密码、Cookie、Token 或内部 `device_code`。

## 1. 子代理执行边界

- 子代理先执行 `dydata version --json` 与 `dydata commands --json`，不得猜测未声明的命令。
- `auth.login` 和 `auth.logout` 的 `agent_callable` 必须为 `false`。只有用户明确要求登录后，子代理才可以启动登录命令，并在出现凭据提示前把真实 TTY 完整交给用户。
- 子代理不得通过命令参数、环境变量、配置文件、脚本、管道、剪贴板或对话内容提供账号、密码、Cookie 或 Token。
- 如果工具不能把真实交互 TTY 交给用户，子代理不得尝试明文降级，必须报告 `INTERACTIVE_REQUIRED` 并建议由用户执行 `dydata auth login --browser`。
- 未经用户单独确认，不执行 `auth.logout`，不清理或覆盖已有本地凭据。

## 2. Agent 契约检查

```powershell
dydata version --json
dydata commands --json
```

通过条件：

1. CLI 版本为 `0.2.0`，Schema 版本为 `1.0`。
2. `auth.login.agent_callable=false`，默认模式为 `secure_terminal`。
3. `human_handoff` 同时声明 `requires_explicit_user_request=true`、`requires_user_input=true`、`agent_may_launch=true` 和 `agent_must_not_supply_credentials=true`。
4. 浏览器回退命令为 `dydata auth login --browser`。
5. `stores.list` 与 `clues.follow-up-stats` 可被发现，均为只读业务命令。

这一段不得执行 `auth.login`、`auth.status`、`auth.logout`、门店查询或线索查询，不读取或刷新已有凭据。

## 3. 用户接管登录

仅在用户明确说“现在登录”且 Agent 工具支持用户接管真实 TTY 时启动：

```powershell
dydata auth login
```

子代理启动后立即停止输入。用户本人完成以下动作：

1. 在 `Username:` 后输入账号。
2. 在隐藏的 `Password:` 后输入密码。
3. 核对终端显示的 username、role 和 store scope。
4. 仅在信息正确时输入 `y` 或 `yes` 批准本机只读 CLI 凭据。

通过条件：密码不回显；批准前不创建设备授权；成功后只显示身份摘要与 `Authorization complete.`。取消、密码错误或交互能力不足时不得留下新的本地 CLI 凭据。

若本机已有凭据，命令应无网络、无覆盖地提示先退出。切换测试账号必须由用户明确决定是否执行 `dydata auth logout`；更稳妥的多账号验收方式是使用独立 OS 用户、虚拟机或隔离的系统凭据库。

## 4. 登录后的只读业务验收

用户完成登录后，可明确授权子代理执行：

```powershell
dydata auth status --json
dydata stores list --json
dydata clues follow-up-stats --from 2026-07-14 --to 2026-07-20 --output json
```

通过条件：

- `stores list` 只返回测试账号被授权的门店。
- 线索统计只覆盖这些门店，并返回待跟进、已跟进和系统跟进率等既有契约字段。
- 汇总范围、日期和门店明细可以相互核对；权限失败时停止，不扩大门店或日期范围重试。
- 子代理的验收记录只保留命令名、退出码、版本、门店数量、日期范围和统计结果，不记录任何凭据材料。

## 5. 推荐子代理提示词

> 你是 dydata 只读 CLI 验收代理。先执行 `dydata version --json` 和 `dydata commands --json` 核对运行时契约。不得执行或代填任何登录凭据，不得访问 keyring；只有我明确说“现在登录”后，你才可以启动 `dydata auth login`，并必须在出现凭据提示前把真实交互终端交给我。如果不能提供可接管的安全 TTY，停止并建议我使用 `dydata auth login --browser`。登录成功后，仅在我确认的门店和日期范围内执行目录声明为 `agent_callable: true` 的只读命令。不得执行退出、写入、部署、推送或合并操作，不得在输出中记录密码、Cookie、Token 或内部设备码。
