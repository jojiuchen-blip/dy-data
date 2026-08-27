# DYDATA-46 腾讯云正式生产升格主开发计划

> **版本**：v1  
> **发布日期**：2026-08-27  
> **前序版本**：DYDATA-45 测试环境 Agent 接入计划  
> **适用范围**：将现有腾讯云入口 `https://dy-business-engine.com` 升格为正式生产，并切换全部官方 CLI / MCP / OAuth / Agent 入口  
> **参与角色**：AI 执行 -> 人类 Owner 审核；GitHub Actions 执行受控部署  
> **执行约束**：隔离 worktree、TDD、严格只读 Agent 能力、生产与测试凭证不得复用、任一发布硬门禁失败即停止  
> **目标**：让正式用户和 Agent 只发现并使用 production 配置，旧 test 凭证在 production 失效，部署、审计、烟测和回滚均有可复核证据  
> **当前需求基线**：Linear `DYDATA-46`；用户于 2026-08-27 明确确认现有腾讯云域名直接升格为正式生产  
> **上游发现结论**：`canProceed=true`，`slug=dy-data`，`mode=pipeline`，`scannedAt=2026-08-27T05:15:14.488Z`

## 0. 本计划使用指南

1. 先读本主计划和任务看板；同一时刻只允许一个 Task 为“进行中”。
2. 开工前只加载当前子计划、其中列出的 PRD / Foundation 与真实代码。
3. 实现任务执行 Red -> Green -> Refactor；发布任务先合并并确认 CI，再触发生产部署。
4. 每个 Task 完成后同步主计划、看板、子计划和 Linear；证据不足不得推进下一 Task。

### 0.1 PRD 加载约束

- 产品边界：`docs/prd/mainprd-dy-data.md` 的全局权限、只读查询和正式业务口径。
- 术语与交付：`docs/prd/foundation/foundation-glossary-dy-data.md`、`foundation-delivery-dy-data.md`。
- API 与权限：`docs/prd/foundation/foundation-api-dy-data.md`、`foundation-api-dy-data/common-contract.md`。
- Agent 增量基线：`docs/superpowers/specs/2026-07-22-dydata-45-test-agent-connect-design.md` 与 DYDATA-45 正式计划文件组。
- 生产切换范围、验收和状态以 Linear `DYDATA-46` 为权威；本计划不复制 Backlog。

### 0.2 读前门禁 / AI 自检清单

- 当前 Task 在主计划、看板、子计划三处状态一致。
- 生产域名固定为 `https://dy-business-engine.com`；不得提供任意域名覆盖或静默回退到 test。
- test 与 production 的 keyring 槽位、OAuth issuer/resource/audience、服务端 token 环境和审计环境必须可验证隔离。
- 不读取、不记录、不输出密码、Cookie、access token、refresh token 或部署密钥。

### 0.3 完成前验证门禁

- 执行子计划中的 `Verification Method`，并把命令、CI、部署和线上 smoke 证据写入 Evidence。
- 全仓扫描确认正式用户入口不再声明 test；内部历史记录可保留但必须明确为历史。
- 生产 CLI 与 MCP 使用受限账号完成重新授权、门店范围、统计等价和越权拒绝验收。
- 失败回滚只能恢复上一生产版本，不得把正式用户流量导回测试配置或测试数据。

## 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Python | >= 3.12 | `python --version` |
| Node.js | >= 18 | `node --version` |
| Git | >= 2.40 | `git --version` |
| GitHub CLI | >= 2 | `gh --version` |

| 工程目录 | 就绪标识 |
|---|---|
| `apps/cli/` | `pyproject.toml` 存在 |
| `apps/api/` | `Dockerfile` 存在 |
| `apps/web/` | `package.json` 存在 |
| `deploy/` | `compose.yaml` 存在 |

## 1. 差距基线

| 差距 | 优先级 | 影响 | 对应任务 | 状态 |
|---|---|---|---|---|
| CLI、API guard、MCP initialize 与审计仍硬编码 `test` | P0 | 正式入口仍被识别为测试，且无法证明环境隔离 | T1.1 | 处理中 |
| OAuth token / refresh family 与运行环境的服务端校验需确认并补齐 | P0 | 旧测试凭证可能在 production 被接受 | T1.1 | 处理中 |
| README、Agent guide、manifest、Skill 和默认 CLI 环境仍公开 test | P0 | 正式用户会继续连入测试语义 | T1.2 | 待处理 |
| 部署脚本 smoke 仍要求 `environment=test` | P0 | 无法受控切换生产配置并验收 | T2.1 | 待处理 |
| 缺少 production CLI/MCP 重新授权、审计和回滚证据 | P0 | 不满足 Release Gate | T2.1 | 待处理 |

## 2. 分工与边界

| 角色 | 职责 |
|---|---|
| 主 Agent | 技术判断、TDD 实装、计划与 Linear 回写、PR/CI、部署和 smoke |
| GitHub Actions | 构建、验证和腾讯云受控部署 |
| 人类 Owner | 已确认生产目标；审核最终业务结果和生产验收证据 |

高冲突文件由本任务独占：CLI 环境注册表、API Agent 环境与 OAuth、Agent discovery、部署脚本/工作流及本计划状态文件。DYDATA-55 的企业内网安全基线保持独立，不在本计划内实施。

## 3. 执行阶段

### Phase 1：生产环境契约与官方入口

**Entry Criteria**：Linear `DYDATA-46` 为 In Progress；用户已确认生产域名；计划文件组三处状态一致。  
**Exit Criteria**：production 环境、凭证隔离、动态审计、官方 discovery/文档与升级策略均通过自动化测试。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T1.1 | [生产环境与凭证隔离](sub-delivery-plan-dydata-46-production-promotion-T1.1-environment-isolation.md) | 已完成（2026-08-27） |
| T1.2 | [官方入口与兼容策略切换](sub-delivery-plan-dydata-46-production-promotion-T1.2-official-entry-cutover.md) | 进行中 |

### Phase 2：正式发布与生产验收

**Entry Criteria**：T1.1、T1.2 完成；全量本地门禁通过；PR 已获 CI 成功。  
**Exit Criteria**：main 已部署腾讯云；线上 production smoke、CLI/MCP 受限账号 UAT、审计与回滚核查通过并回填 Linear。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T2.1 | [生产发布与线上 UAT](sub-delivery-plan-dydata-46-production-promotion-T2.1-release-uat.md) | 待开始 |

## 4. 任务看板

- 看板入口：[task-kanban-dydata-46-production-promotion.md](task-kanban-dydata-46-production-promotion.md)

## 5. 发布闸门

- [ ] 所有官方安装入口、Agent 文档、Skill、manifest 和 CLI 默认值只指向 production。
- [ ] test 凭证不能用于 production，首次生产使用必须重新授权。
- [ ] production issuer/resource/audience、回调、审计环境和服务端校验一致。
- [ ] 旧 CLI 有最低版本/升级失败提示，不会静默留在 test。
- [ ] 全量 pytest、Web build、部署契约、迁移、配置和 `git diff --check` 通过。
- [ ] PR、CI、生产部署、线上 smoke、CLI/MCP UAT 和回滚核查均有链接或脱敏证据。
- [ ] 生产故障不会 fallback 到测试域或测试数据。

## 6. 风险与应对

| 风险 | 影响 | 应对 | Owner | 状态 |
|---|---|---|---|---|
| 同域名从 test 升格 production | 旧 token 可能继续有效 | 服务端凭证绑定环境并在切换后拒绝 test；客户端使用独立 production keyring 槽位并重新授权 | AI 执行 -> 人审核 | 处理中 |
| 远端 env 修改失败或遗漏 | manifest/审计仍报告 test | 部署脚本显式写入并校验 `DY_AGENT_ENVIRONMENT=production`，smoke 断言 production | AI 执行 -> 人审核 | 待处理 |
| 旧 CLI 继续默认 test | 正式用户留在旧语义 | 提升最低版本并提供明确升级提示；官方发现入口只发布 production | AI 执行 -> 人审核 | 待处理 |
| 发布失败 | 正式入口不可用 | 保留上一生产镜像和 env 备份；回滚 production 版本并重跑 smoke，不导向 test | AI 执行 -> 人审核 | 待处理 |
| 敏感信息进入日志 | 凭证泄露 | 仅保存脱敏聚合、request id 和状态；全程禁止回显 token/cookie/password | AI 执行 -> 人审核 | 持续控制 |

## 7. AI 执行示例

1. 开始 T1.1：先运行计划一致性和环境门禁，再为 production 注册、旧 test token 拒绝和动态审计写失败测试，随后最小实装。
2. 开始 T2.1：仅在 T1.1/T1.2 和 PR CI 全部通过后触发部署；任一 smoke 失败立即停止并执行 production 版本回滚。

## 8. PRD → 任务反向索引

| 需求依据 | Task | 子开发计划 |
|---|---|---|
| DYDATA-46：环境、凭证、issuer/audience、审计隔离 | T1.1 | [生产环境与凭证隔离](sub-delivery-plan-dydata-46-production-promotion-T1.1-environment-isolation.md) |
| DYDATA-46：官方入口、文档、manifest、旧客户端策略 | T1.2 | [官方入口与兼容策略切换](sub-delivery-plan-dydata-46-production-promotion-T1.2-official-entry-cutover.md) |
| DYDATA-46：生产发布、smoke、受限账号 UAT、回滚 | T2.1 | [生产发布与线上 UAT](sub-delivery-plan-dydata-46-production-promotion-T2.1-release-uat.md) |
