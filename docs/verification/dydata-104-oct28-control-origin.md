# DYDATA-104：公共 HTTPS 站点控制入口 Origin 修复

2026-10-28，基于 `94fb6f52a6f8c28bd8a10157baf382e132e4f2b9` 的独立工作树。写集仅为 operations 路由、专用安全回归和本文档；未修改结算、CI、部署、代理、CORS middleware 或全局文档，未操作生产。

## 根因与证据边界

主线程真实登录浏览器的 restart POST 返回 `403 / Control request origin denied`，随后命令读取为 `rows: []`。私有收据已只读核对错误字面值和空集合，不复制容器标识、请求元数据或其他私有值。拒绝发生在命令创建之前，不能把它解释为 ops-agent 已执行重启但失败。

主线程白名单运行证据显示 API 已配置正确的公共 HTTPS `DY_WEB_BASE_URL`，`DY_API_CORS_ORIGINS` 和 `FORWARDED_ALLOW_IPS` 均未设置，启动命令没有显式代理信任参数。具体容器元数据保留在主线程私有证据中，不提交 Git。

| 代码证据 | 结论 |
|---|---|
| 基线 `operations.py:83–97` 的 `_require_trusted_origin` | 只允许 `request.base_url` 及 `DY_API_CORS_ORIGINS`，不读取公共 Web 地址 |
| [Compose](../../deploy/compose.yaml) API environment，第 34–45 行 | 传入 `DY_WEB_BASE_URL`，没有把 CORS / forwarded 信任变量传给 API |
| [nginx](../../deploy/nginx.conf) 第 23、43–44 行 | 内层监听 HTTP，保留 Host，但以自身 `$scheme` 重写 `X-Forwarded-Proto`；公共 TLS 在外层终止时这里为 HTTP |
| [API Dockerfile](../../apps/api/Dockerfile) 第 42 行 | Uvicorn 默认启动命令没有显式 proxy / forwarded 信任参数 |
| [Web client](../../apps/web/src/api/client.ts) 的 `apiUrl`、`sendJson`、`submitAdminOpsCommand` | 默认从页面 origin 构造相对 API URL，带凭据发送 JSON；客户端没有构造或覆盖 Origin |
| 基线 `operations.py:806–866` | 管理员依赖先执行，随后 Origin、确认、幂等、冷却检查；最后才创建 `OpsCommand` |

这是内部 HTTP 地址与公共 HTTPS 地址不一致时可复现的配置/应用合同缺口。相关守卫自 `ed3ea733` 已存在；本基线与 `origin/main df4ffb8e` 的上述部署/守卫文件无差异，不能称候选中原本已经修复。未直接观察当次请求的 ASGI scope；公共 URL、Origin、Host 的额外别名/端口差异仍只能由主线程既有 Network 记录核对。

本地原始诊断从精确 AST 提取旧守卫，调用内存中的合成 `Request`，不启动服务器、不发 HTTP、不访问数据库。8 个案例确认：内部 HTTP scope 加正确 Web 配置仍被拒绝；单加 forwarded 头也不会改变 Request scope；显式准确允许项或 HTTPS scope 可通过；异源、cross-site 和 forwarded-host 伪造不获准。

## 最小修复

[operations 路由](../../apps/api/dy_api/routes/operations.py) 新增私有 `_configured_control_origin`，仅从服务端 `DY_WEB_BASE_URL` 提取规范 HTTPS origin，并作为既有允许集的额外一项。

- 验证 HTTPS、合法 DNS/IP hostname、合法端口；拒绝 userinfo、反斜杠、控制字符、无效 host/port 和 IPv6 scope 标识。配置中的路径可以去除，默认 443 归一省略，非默认端口保留。
- 非空但非法的配置对带 Origin 的控制调用返回通用 503，不回显配置原值，不回退读取客户端转发头。
- 保留原 `Sec-Fetch-Site` 顺序及拒绝规则、现有 request-base / 显式 CORS 允许项、无 Origin 兼容路径；没有扩大无 Origin 行为。
- 没有新增全局 CORS 信任、通配符或代理信任，也没有关闭 Origin 校验。现有管理员能力、显式确认、幂等、目标白名单、冷却及后续 ops-agent 保护保持原样。

没有直接复用其他路由私有函数：`cli_auth._verification_uri` 返回完整授权 URL，OAuth redirect 校验另有 loopback / 回调语义，都不适合作为通用 control-origin 提取器。`create_app` 原有 Agent 环境校验继续约束 Web 地址与注册环境一致。本任务无 foundation 漂移：没有新增端点、请求字段、持久化结构或业务操作资格。

## 回归与本地证据

专用 [安全回归](../../tests/test_operations_control_origin.py) 使用真实 FastAPI TestClient、真实登录依赖和隔离 SQLite；仅向本地 ASGI 应用发送合成请求，不访问生产，也不执行 Docker。拒绝场景逐项断言零 `OpsCommand`；正常场景确认 pending 命令和幂等重放只有一行。

- 旧源码红测：最初直接在未修改业务源码上三组均复现403。最终再用同一现有测试venv，将94fb6f52的精确旧守卫AST仅装入独立测试进程，保留真实应用/登录/数据库依赖：**3 failed / 36 deselected，3.43秒，exit1**；没有改动磁盘源码或弱化断言，收据 `red-same-venv.xml`。
- 新矩阵覆盖不同 scheme/domain/port、相似域名、userinfo、null Origin、forwarded 伪造、非法服务器配置、cross-site、非全局管理员和匿名访问，以及默认端口/IP/配置路径规范化、既有无 Origin 与显式 CORS 兼容。
- 现有测试venv执行 `python -m pytest tests/test_operations_control_origin.py tests/test_api_admin_sync_control_plane.py tests/test_ops_agent.py -q --tb=short --junitxml=.tmp/control-origin/green-final.xml`：**70 passed / 0 failed / 0 skipped，148.56秒，exit0**；其中新增39项，原control-plane及ops-agent31项。83条警告来自既有TestClient及MCP依赖弃用提示，未安装或升级依赖。
- `python -m bandit -f json -o .tmp/control-origin/bandit.json apps/api/dy_api/routes/operations.py`：exit0、0告警/0解析错误。
- suite锁、S4路由、计划三件套一致性、执行环境和任务上下文通过；全局文件校验0 errors / 0 warnings；`git diff --check`通过。运行收据保留在 `.tmp/control-origin/`，不提交运行产物。

## 交付边界

这项修复尚未由本执行单元部署或在生产重放。真实页面控制恢复仍需主线程在目标版本完成部署后验收；不能用本地成功替代目标运行版本证据，也不能伪造 Origin 绕过旧运行入口。独立发布、生产操作与 Linear / 全局日志回写由主线程承接。技能 usage/audit 按宿主规则记录，工作流 memory 未更新。
