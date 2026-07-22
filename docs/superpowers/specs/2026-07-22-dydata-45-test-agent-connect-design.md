# DYDATA-45 测试环境 Agent 一句话接入层设计

- 日期：2026-07-22
- 状态：已确认并获准实施
- 需求来源：Linear `DYDATA-45`
- 上游能力：`DYDATA-40` Agent-first 严格只读 CLI
- 发布边界：本设计只启用已部署在腾讯云的 `test`；`production` 是未来尚未部署的企业内网服务器版本，生产切换由 `DYDATA-46` 单独阻塞跟踪

## 1. 目标

让门店或管理者可以把一句自然语言交给 WorkBuddy、Codex、Manus、OpenClaw 或其他 Agent，由 Agent 自动选择下列接入路径：

1. 有持久终端时，安装测试版 `dydata` CLI，并把登录输入交还用户本人。
2. 支持远程 MCP 时，连接测试环境 `/mcp`，由用户在官方网页完成 OAuth 授权。
3. 两条路径只暴露同一份注册表中批准的只读能力，并由服务端实时重算账号门店范围。

Agent 不接触账号密码、Cookie、访问令牌、刷新令牌或内部设备码。首期业务工具仍只有：

- `stores.list` / MCP `stores_list`
- `clues.follow-up-stats` / MCP `clues_follow_up_stats`

## 2. 已确认决策

| 决策项 | 结论 |
| --- | --- |
| 测试环境 | `test` 明确指当前已部署的腾讯云版本，官方根地址为 `https://dy-business-engine.com` |
| 生产环境 | `production` 明确指未来尚未部署的企业内网服务器版本；本设计不声明可用生产入口，也不把任何内网地址当成已上线端点 |
| CLI 环境选择 | 默认 `test`；`DYDATA_ENV` 只接受已声明名称，不再接受任意远程 API 地址 |
| 凭据隔离 | OS keyring key 同时包含环境名和规范化服务端身份摘要；旧 `default` 凭据不自动迁移 |
| 共享事实源 | 扩展 `dydata_cli.registry`，同时声明 CLI、HTTP 和 MCP 映射；API 与 MCP 直接读取该注册表 |
| MCP SDK | 使用官方 Python SDK 稳定 v1，依赖范围 `mcp>=1.27,<2`，采用 Streamable HTTP |
| MCP OAuth | OAuth 2.1 authorization code + PKCE S256、动态客户端注册、RFC 9728 资源发现、刷新令牌轮换 |
| OAuth 部署 | 授权服务器与 MCP 资源服务器同域部署，但令牌类型、scope、audience、存储表均与 CLI 隔离 |
| 用户授权 | `/authorize` 跳转到 `/auth/mcp/authorize`；用户复用现有 Web 登录会话并明确确认只读授权 |
| Agent 入口 | `/.well-known/dydata-agent.json`、`/agent.md`、`/agent/SKILL.md` 和 `/api/v1/agent/capabilities` |
| 诊断 | `dydata agent doctor --json` 返回版本、环境、官方端点可达性、登录状态和门店范围，不返回凭据 |
| 生产切换 | 不在本次加入可用 production 配置；DYDATA-46 必须一次性切换环境注册表、域名/入口、OAuth issuer/resource、客户端与回调策略、部署变量、keyring、文档和 smoke |

## 3. 架构

```text
自然语言请求
  ├─ 终端型 Agent
  │    └─ dydata CLI
  │         ├─ 命名环境注册表（test）
  │         ├─ 环境隔离 OS keyring
  │         └─ 现有 cli:read API
  └─ MCP 型 Agent
       └─ HTTPS /mcp（Streamable HTTP）
            ├─ RFC 9728 / OAuth 发现
            ├─ authorization code + PKCE
            ├─ 独立 mcp:read token family
            └─ 共享只读能力执行服务

共享能力注册表
  ├─ CLI commands --json
  ├─ Agent capabilities manifest
  ├─ HTTP 路径/审计映射
  └─ MCP tool 注册
```

禁止链路：

```text
Agent -> 账号密码 / Cookie / Token
Agent -> 任意 API URL
Agent -> 通用 HTTP / SQL / shell 执行工具
MCP token -> CLI API
CLI token -> MCP resource
test token / keyring -> production
```

## 4. 命名环境与 CLI 凭据

新增不可变 `EnvironmentConfig`：

```json
{
  "name": "test",
  "web_url": "https://dy-business-engine.com",
  "api_url": "https://dy-business-engine.com/api/v1",
  "mcp_url": "https://dy-business-engine.com/mcp",
  "oauth_issuer": "https://dy-business-engine.com"
}
```

规则：

- 默认环境为 `test`，所有 JSON 成功与错误信封均包含 `environment: "test"`。
- `DYDATA_ENV` 只能选择注册表中的环境；未知值在发起网络请求前返回 `INVALID_ARGUMENT`。
- CLI 正式路径不读取 `DYDATA_API_URL`。测试与嵌入调用仍可通过构造函数注入 loopback URL，但这不是 Agent 命令入口。
- keyring service 保持 `dydata-cli`，account 改为 `env:test:<server_identity_hash>`。
- 锁文件名使用相同命名空间，避免不同环境的并发刷新互相阻塞。
- 旧 `default` 凭据不读取、不复制、不删除；用户须在新命名空间重新授权。

## 5. 共享能力注册表

`dydata_cli.registry` 继续是 Agent 能力的唯一事实源，并为已批准业务命令增加：

- HTTP method、path、operation
- MCP tool name
- MCP 参数映射
- 环境要求
- 只读标记和业务副作用

API 镜像把 `apps/cli/src` 加入运行路径，因此 API、CLI 和 MCP 使用同一个 Python 模块，不维护复制的 JSON 或第二份命令表。

适配器允许有各自的协议代码，但必须满足：

- 工具名称和用途由注册表读取。
- 参数边界、输出 schema、错误码、角色、数据范围和副作用与注册表一致。
- MCP 只注册同时满足 `agent_callable=true`、`business_side_effect=none` 且声明了 MCP 映射的命令。
- `auth.login`、`auth.logout`、通用 HTTP、SQL 和脚本能力永远不注册为 MCP tool。

## 6. MCP OAuth 与凭据模型

### 6.1 公共端点

| 端点 | 用途 |
| --- | --- |
| `/mcp` | MCP Streamable HTTP 资源服务器 |
| `/.well-known/oauth-protected-resource/mcp` | RFC 9728 资源元数据 |
| `/.well-known/oauth-authorization-server` | OAuth 授权服务器元数据 |
| `/register` | RFC 7591 动态客户端注册，仅支持 public client |
| `/authorize` | OAuth authorization code + PKCE 起点 |
| `/token` | authorization code / refresh token 交换 |
| `/revoke` | token family 撤销 |
| `/api/v1/auth/mcp/approve` | 已登录用户确认本次只读授权 |

### 6.2 隔离边界

- scope 固定为 `mcp:read`；MCP 不接受 `cli:read`。
- resource/audience 固定为当前环境的规范化 `/mcp` URL。
- OAuth issuer 固定为当前环境官方根地址。
- 每条授权请求、访问令牌和刷新令牌记录 `environment=test`。
- access token 和 refresh token 使用高熵随机值，数据库只保存 SHA-256 摘要。
- access token 30 分钟失效；refresh token 30 天失效并单次轮换；重放会撤销同 family。
- 账号停用、初始化状态变化、权限代次变化时，服务端拒绝旧令牌。
- 动态注册只接受 public client 与精确 redirect URI；服务端不保存 OAuth client secret。

### 6.3 持久化表

- `mcp_oauth_clients`：public client 元数据。
- `mcp_authorization_requests`：PKCE、redirect URI、state、resource、用户确认和一次性 code 摘要。
- `mcp_access_tokens`：访问令牌摘要、client、用户、scope、resource、环境、过期和撤销状态。
- `mcp_refresh_tokens`：刷新令牌 family、轮换关系、用户、scope、resource、环境和撤销状态。

所有原始 code/token 只在协议响应的最小作用域中存在，不进入日志、审计、异常或 `repr`。

## 7. 权限与业务执行

CLI HTTP 路由和 MCP tool 调用同一组服务函数：

1. 从令牌主体重新加载当前账号。
2. 重新计算当前角色、账号状态和门店范围。
3. 对请求的门店集合执行全有或全无授权；包含任一越权门店即 `SCOPE_DENIED`。
4. 复用现有门店列表和线索跟进统计计算，不在 MCP 中复制指标公式。
5. 返回同一 schema 版本、指标版本和错误语义，并标注 `environment=test`、`channel=cli|mcp`。

MCP 工具参数：

```text
stores_list()

clues_follow_up_stats(
  date_from?: YYYY-MM-DD,
  date_to?: YYYY-MM-DD,
  store_ids?: string[]
)
```

日期仍按北京时间自然日，默认含当天最近 7 天，最长 366 天；开始和结束必须成对提供。

## 8. Agent 发现、安装与 Skill

`/.well-known/dydata-agent.json` 是稳定机器入口，至少返回：

- 环境和版本
- CLI 安装 spec 与发现命令
- MCP URL、OAuth issuer 和 transport
- capability manifest URL
- Agent Skill URL
- 人机授权和敏感信息边界

`/agent.md` 给通用 Agent 一个最短决策流程：

1. 读取 manifest。
2. 有持久终端则安装 CLI，执行 `dydata agent doctor --json`。
3. CLI 未授权时，只启动并把输入权交给用户；不得让用户把凭据贴进聊天。
4. 支持远程 MCP 则优先添加 manifest 中的 MCP URL，由用户在官方页面授权。
5. 只调用 capability manifest 中批准的只读能力。

`/agent/SKILL.md` 使用通用 Markdown Skill 结构，不依赖某一家 Agent 的私有格式；平台适配器可以引用它，但不得复制并改写能力契约。

## 9. CLI 诊断

`dydata agent doctor --json` 不要求已登录。返回：

- CLI/schema/manifest 版本
- environment 名称和官方 public URLs
- API manifest 是否可达
- MCP protected-resource metadata 是否可达
- 本环境 keyring 是否存在凭据
- 凭据可用时的当前账号摘要和实时门店范围
- 每项检查的稳定状态与建议下一步

诊断不得返回 header、Cookie、token、refresh token、device code、授权 code 或 keyring 原文。未登录是可诊断状态，不作为内部错误。

## 10. 审计与错误

- CLI 继续使用现有审计路径；MCP 每次 tool 调用记录 channel、tool/command、request id、用户、日期范围、请求门店、实际门店、结果和耗时。
- 审计不记录完整响应、OAuth code、token、Cookie 或密码。
- CLI 使用既有稳定退出码；MCP 返回同名结构化错误码。
- MCP transport 的无效/过期 bearer token 返回 OAuth 401 challenge；业务范围错误返回 `SCOPE_DENIED` 工具结果，不降级为部分数据。

## 11. 测试与验收

### 自动化

- 环境白名单、未知环境拒绝、正式路径不读取任意 API URL。
- 两个环境身份产生不同 keyring account；旧 `default` 不被读取。
- CLI/API/MCP 注册表映射一致，MCP 只有两个批准工具。
- 所有成功和错误信封含 `environment=test`。
- Agent manifest、agent.md、Skill 和 capability endpoint 内容互相一致。
- OAuth discovery、public DCR、PKCE、授权确认、code 单次消费、refresh rotation、replay revoke、resource/scope/environment 隔离。
- MCP 工具只返回实时授权门店；混入越权门店整单失败。
- MCP Streamable HTTP 初始化、tools/list 和两个工具调用 smoke。
- 迁移、全量 pytest、Web build、Docker compose config、Nginx route 和 `git diff --check`。

### 真实接入

腾讯云测试环境部署后保留三类记录：

1. 本地终端 Agent：CLI 发现、用户授权、门店列表、跟进统计。
2. 云端 MCP Agent：OAuth 网页授权、tools/list、两项只读查询。
3. Claw/网关型 Agent：远程 MCP 添加、OAuth 回调、同样的权限负向用例。

真实账号输入只由用户在 TTY 或官方网页完成；验收记录只保留非秘密结果和 request id。

## 12. 发布与回滚

- 本次部署目标只是在腾讯云运行的测试版本，只把测试域名的 Nginx MCP/OAuth/Agent 入口代理到 API。
- 部署配置显式写入 `DY_AGENT_ENVIRONMENT=test`，issuer/resource 均从官方 `DY_WEB_BASE_URL` 派生。
- 回滚可移除 Nginx MCP/OAuth 路由并回滚 API/Web 镜像；新增 OAuth 表保留不会影响现有 CLI/Web。
- 企业内网生产服务器尚未部署；本任务不创建 production 环境条目、不迁移 test 凭据，也不把测试域名或任何内网地址写成未来生产默认值。
- DYDATA-46 上线企业内网生产版时，必须对注册表、issuer/resource、OAuth 客户端和回调、keyring、反向代理、部署变量、文档与 smoke 做彻底切换，不能只替换单个域名。
- `DYDATA-46` 完成前，本设计不能被解释为生产接入已完成。
