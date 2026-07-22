# DYDATA-45 T3.1 测试环境部署与独立 Agent 黑盒验收

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-45-test-agent-connect.md](main-delivery-plan-dydata-45-test-agent-connect.md)
- 任务看板：[task-kanban-dydata-45-test-agent-connect.md](task-kanban-dydata-45-test-agent-connect.md)

#### T3.1 交付测试环境并完成跨 Agent 接入验收

**Requirement ID**：DYDATA-45-TEST-DEPLOY-UAT

**PRD 双链·读**：
- `docs/superpowers/specs/2026-07-22-dydata-45-test-agent-connect-design.md` §11-§12

**核心逻辑**：
- API 镜像包含 CLI registry 与稳定 MCP v1 依赖，Nginx 同域代理公开发现、OAuth、MCP 与 Agent API；compose 固定 `DY_AGENT_ENVIRONMENT=test`。
- 先运行迁移和自动化闸门，再部署到当前腾讯云测试环境，逐端点检查健康、metadata 和 manifest。
- 由独立测试子代理仅根据公开文档接入；人类 Owner 在浏览器/TTY 中亲自登录批准，子代理不得接触密码。
- 使用限定若干门店的测试账号验证只见授权门店、逐店统计、CLI/MCP 同口径以及越权拒绝。

**核心文件**：
- `requirements.txt`
- `apps/api/Dockerfile`
- `deploy/compose.yaml`
- `deploy/nginx.conf`
- `README.md`
- `docs/cli-agent-guide.md`
- `tests/test_deploy_agent_config.py`

**完成标准**：
- 镜像内可导入 `dydata_cli.registry` 和 `mcp`，迁移升级成功，Nginx 对固定公共端点转发正确。
- 腾讯云测试环境 manifest 的 environment、base URL、MCP URL 全为测试值；不存在可用 production 配置或任意覆盖入口，尚未部署的企业内网服务器不得被描述为当前可用。
- CLI 真实授权和远程 MCP OAuth 各成功一次；独立子代理列出测试账号授权门店及每店 total/pending/followed_up/follow_up_rate。
- 未授权 store_id 被拒绝；CLI/MCP 同账号同日期结果一致；审计可按 request id 回查。
- 回滚可通过撤下 MCP/Agent 路由并保留既有 CLI/API 完成，不影响当前只读 CLI 登录。

**Verification Method**：
- `python -m pytest -q`、`npm --prefix apps/web run build`、`docker compose -f deploy/compose.yaml config`、`git diff --check`。
- 部署后执行公开端点 smoke、`dydata agent doctor --json`、CLI 两条业务命令与 MCP 两项工具；保存脱敏结果。
- 指派独立测试子代理从 manifest 开始完成黑盒接入并给出 PASS/FAIL。

**Evidence**：
- 本子计划 `Evidence Log`；CI/构建/compose 输出；测试环境脱敏 smoke 结果；独立子代理测试报告。

**Failure Handling**：
- 任一自动化、迁移、metadata、OAuth 或 scope 检查失败即停止部署或回滚新路由。
- 测试账号范围不符合预期时由人类 Owner 修正账号门店授权后重测，不扩大 Agent 权限。
- 可用 production 配置或企业内网生产路由出现在本任务部署时立即阻塞，转交 DYDATA-46；文档中仅允许把它记录为未来尚未部署的目标环境。

**完成收尾：状态同步**：
- 完成后把事实、证据、完成日期、foundation 漂移结论和 DYDATA-46 前置建议提交给 `ai-project-manager`，由其同步三处状态并更新 Linear。
- 未完成状态同步和真实验收前不得标记本 Task 或 DYDATA-45 完成。

**Owner**：AI 执行 -> 人审核

**前置**：T2.2

**状态**：已完成（2026-07-23）

## Evidence Log

- 部署预检发现并修正：API 镜像未包含共享 CLI registry；Compose Nginx 与 Railway Web Nginx 未转发根路径 MCP、OAuth、manifest 和 Agent 文档。
- 新增部署契约测试，覆盖固定 `test` 环境、测试域名、镜像内容、两套反代与部署后 smoke；RED 后 GREEN，9 项通过。
- `docker compose --env-file deploy/.env.example -f deploy/compose.yaml config --quiet` 与 `bash -n deploy/tencent/deploy.sh` 通过。
- API/Web 镜像构建成功；API 镜像内 `dydata_cli.registry`、MCP SDK 与 `dy_api.main` 可导入，SQLite 空库从首个版本迁移到 `20260722_0022` 成功；两套 Nginx 配置均通过真实 `nginx -t`。
- 环境口径已锁定：`test` 是当前腾讯云部署，`production` 是未来尚未部署的企业内网服务器；本任务不写入可用 production 入口。
- 最新发布前回归：`python -m pytest -q` 为 916 passed、2 skipped、77 warnings；2 项 skipped 是 opt-in PostgreSQL 并发测试，已另在真实 PostgreSQL 18 连续 5 轮通过。`npm --prefix apps/web run build`、增量 Bandit Medium/High 扫描、基于 `requirements.txt` 的 `pip-audit`、API/Web 镜像构建、空库迁移、Compose、两套真实 `nginx -t`、部署脚本 Bash 语法与 `git diff --check` 均通过；部署后公网 smoke 追加发现并修复 DCR 畸形 JSON 500，最终独立安全复审仍为 `ALLOW`，Critical/Important/Minor 均为 0。
- 运行时代码已通过 `cab6aecbf1ae7a36ab262522b466bdd4e6b9017b` 合入远端 `main`；GitHub Actions `Tencent Lighthouse Deploy` run `29934737788` 的 Verify 与 Deploy Tencent Lighthouse 均成功，腾讯云测试环境部署完成。
- 部署后公开 smoke 通过：manifest、Agent guide、Skill、capabilities 与两份 OAuth metadata 均返回预期测试环境契约；未认证 MCP initialize 返回 401；畸形 JSON DCR 与非 loopback HTTP redirect 均返回通用 `invalid_client_metadata` 400，并保留 no-store/no-cache/CORS 头。
- 首轮独立黑盒验收如实发现本机遗留 `dydata-cli==0.2.0` 与 0.3.0 授权槽位不一致；由人类 Owner 通过 0.3.0 官方浏览器流程重新授权后，另起全新子代理重跑，最终 verdict 为 `PASS`。
- CLI 0.3.0 验收通过：doctor 3/3、测试账号授权门店数为 3；默认范围与 `2026-07-20..2026-07-23` 显式范围均返回 3 行、`partial=false`，`total = pending + followed` 与系统跟进率公式/舍入成立；不存在门店 ID 以 `SCOPE_DENIED` 整单拒绝且无 partial/data 载荷。
- MCP 使用官方 `@modelcontextprotocol/sdk` 1.29.0 完成 OAuth/PKCE、initialize、tools/list 与两项工具调用；工具严格为 `stores_list`、`clues_follow_up_stats`，公开参数严格为 `date_from`、`date_to`、`store_ids`，只读提示正确；门店数、统计行数与完整脱敏聚合元组和 CLI 一致。
- 全程未向 Agent 输出账号、密码、Cookie、授权码、Token、真实门店标识或原始经营指标；当前入口仍全部为腾讯云 `test`，未来企业内网 production 继续由 `DYDATA-46` 阻塞承接。
- 非阻断观察：CLI 0.3.0 顶层 `--help` / `--version` 返回 `INVALID_ARGUMENT`；manifest 声明的 `commands --json` 与 `version --json` 正常，机器发现与自然语言映射不受影响。
