# dydata 正式生产 Agent CLI 验收

本文用于部署后验证 Agent 能否安全接入 `dydata` 正式生产环境。正式入口固定为 `https://dy-business-engine.com`，命名环境固定为 `production`。验收证据不得包含账号、密码、Cookie、Token、内部 `device_code` 或真实业务明细。

## 1. 验收边界

- Agent 可以自动执行公开契约检查，但不得代填凭据或读取系统凭据库。
- `auth.login` 和 `auth.logout` 的 `agent_callable` 必须为 `false`。
- 只有用户明确要求登录后，Agent 才能启动浏览器授权，并把页面控制权交给用户。
- 无法提供安全交互时必须返回 `INTERACTIVE_REQUIRED`，由用户执行 `dydata auth login --browser`。
- 旧测试环境或旧版本凭据不会迁移或复用；正式生产必须重新授权。

## 2. 公开契约检查

安装或升级到 `dydata-cli 0.4.0`，并将环境设为 `DYDATA_ENV=production`：

```powershell
$env:DYDATA_ENV="production"
dydata version --json
dydata commands --json
dydata agent doctor --json
```

通过条件：

1. CLI 版本为 `0.4.0`，Schema 版本为 `1.1`。
2. 环境为 `production`，服务根地址为 `https://dy-business-engine.com`。
3. manifest、OAuth metadata、MCP URL 和 CLI contract 均指向同一正式域名。
4. `auth.login.agent_callable=false`，且人工交接声明禁止 Agent 提供凭据。
5. 未登录调用受保护资源返回稳定的未授权结果，不回退到 `test`。

## 3. 用户接管正式授权

用户明确确认后运行：

```powershell
$env:DYDATA_ENV="production"
dydata auth login --browser
```

用户本人在正式页面核对域名、当前账号、角色、授权门店范围和 `mcp:read` 只读权限，再批准授权。不得将授权页面、回调参数或凭据内容复制到对话、日志或工单。

通过条件：

- 授权完成后 `dydata auth status --json` 返回 `environment: production`。
- 正式凭据保存在 production 专属槽位，不读取或覆盖旧 test 槽位。
- 取消、超时或授权失败时不留下新的可用凭据。

## 4. 登录后的只读业务验收

用户授权后，可在用户确认的门店和日期范围内运行：

```powershell
dydata auth status --json
dydata stores list --json
dydata clues follow-up-stats --from 2026-07-14 --to 2026-07-20 --output json
```

验收只记录命令名、版本、环境、退出码、门店数量、日期范围和脱敏汇总，不记录账号标识、门店名称、订单、线索或凭据材料。权限不足时停止，不扩大范围重试。

## 5. 回滚与失败处理

- 生产部署失败时保留当前运行容器，并使用部署前数据库备份和 `pre-production-cutover-*.env` 环境备份调查恢复。
- 不允许把正式域名静默切回 `test`；需要回退代码时仍保持 `DY_AGENT_ENVIRONMENT=production`。
- 若 manifest 或 CLI 版本不兼容，升级 `dydata-cli` 后重新执行正式授权。
