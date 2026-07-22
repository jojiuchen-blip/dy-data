# DYDATA-45 测试环境 Agent 一句话接入层主开发计划

> **版本**：v1
> **发布日期**：2026-07-22
> **前序版本**：无（基于 DYDATA-40 只读 CLI 的增量计划）
> **适用范围**：已部署在腾讯云的测试环境 `https://dy-business-engine.com` 的 CLI + 远程 MCP 接入；不包含尚未部署的企业内网生产服务器
> **参与角色**：AI 执行 -> 人类 Owner 审核；独立测试子代理执行黑盒验收
> **执行约束**：隔离 worktree、TDD、小提交、只读能力、测试环境限定、不得接收或输出用户密码
> **目标**：让 WorkBuddy、Codex、Manus 与其他兼容 Agent 通过一个稳定发现入口选择 CLI 或 MCP，并只能读取账号授权门店及线索跟进统计
> **当前需求基线**：Linear `DYDATA-45`；用户已于 2026-07-22 明确要求开始开发
> **上游发现结论**：`canProceed=true`，`mode=fallback`，`docs-dir=docs/superpowers/specs`，`scannedAt=2026-07-22T06:43:27.192Z`；权威输入为本任务设计规格与现有 CLI 实现

## 0. 本计划使用指南

1. 先读本主计划和任务看板；同一时刻只允许一个 Task 为“进行中”。
2. 开工前只加载当前子计划、其 `PRD 双链·读` 和列出的真实代码。
3. 每个实现任务执行 Red -> Green -> Refactor，并把命令或真实联调结果写入子计划 Evidence Log。
4. 用户已授权本计划直接开发，因此 T1.1 初始状态为“进行中”；其余任务完成三处状态同步后顺序推进。

### 0.1 PRD 加载约束

- 增量权威：`docs/superpowers/specs/2026-07-22-dydata-45-test-agent-connect-design.md` 全文。
- 既有只读 CLI 基线：`docs/superpowers/specs/2026-07-21-agent-first-read-only-cli-design.md`。
- `production` 指未来尚未部署的企业内网服务器版本；其入口切换、OAuth issuer/resource 与客户端迁移、keyring、部署、文档和 smoke 不属于本计划，由 `DYDATA-46` 一次性承接。

### 0.2 读前门禁 / AI 自检清单

- 当前 Task 在主计划、看板、子计划三处状态一致。
- 测试先于生产代码，失败必须来自本 Task 尚未具备的目标行为。
- 所有 Agent 可调用能力均来自共享注册表，禁止在 CLI、MCP 和 API 各维护一份路径映射。
- 不读取、不记录、不向 Agent 上下文传递用户密码、Web Cookie、access token 或 refresh token。

### 0.3 完成前验证门禁

- 子计划中的 `Verification Method` 全部执行并记录证据。
- OAuth 必须校验 PKCE S256、resource/audience、scope、过期和 refresh rotation。
- CLI 与 MCP 对相同账号、门店和日期范围返回同口径业务数据，并留下自动化与真实测试证据。
- 主计划、看板、当前子计划的状态及完成日期同步。

## 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Python | >= 3.12 | `python --version` |
| Node.js | >= 18 | `node --version` |
| Docker | >= 24 | `docker --version` |

| 工程目录 | 就绪标识 |
|---|---|
| `apps/cli/` | `pyproject.toml` 存在 |
| `apps/web/` | `package.json` 存在 |
| `apps/api/` | `Dockerfile` 存在 |

## 1. 差距基线

| 差距 | 优先级 | 影响 | 对应任务 | 状态 |
|---|---|---|---|---|
| CLI 仅有默认环境与默认 keyring 槽位 | P1 | 测试/生产可能串凭据或误连 | T1.1 | 已处理 |
| 命令目录与服务端路径映射重复维护 | P1 | Agent 文档、CLI、MCP 契约漂移 | T1.1、T1.2 | 已处理 |
| 缺少稳定 Agent 发现入口和一键诊断 | P1 | Agent 无法自然语言自助接入 | T1.2 | 已处理 |
| 服务端没有标准远程 MCP 与 OAuth 2.1 | P1 | 手机 Agent、Manus、Claw 等无法直接授权 | T2.1 | 已处理 |
| CLI 路由业务逻辑无法由 MCP 安全复用 | P1 | 两条接入口径或权限可能不一致 | T2.2 | 已处理 |
| 镜像、反代、部署和跨 Agent 实测尚未覆盖新入口 | P1 | 测试环境不可交付 | T3.1 | 待处理 |

## 2. 分工与边界

| 角色 | 职责 |
|---|---|
| 主 Agent | 技术判断、设计落地、TDD 实装、部署与状态回写 |
| 独立测试子代理 | 仅使用公开接入文档和测试账号做黑盒 CLI/MCP 测试，不接触代码实现细节 |
| 人类 Owner | 在浏览器或 TTY 中亲自输入凭据、批准授权、审核真实业务数据和生产切换 |

高冲突文件由主 Agent 独占：`apps/cli/src/dydata_cli/registry.py`、`apps/api/dy_api/main.py`、数据库迁移、Nginx 配置及本计划状态文件。生产域名和生产发布不在本任务内。

## 3. 执行阶段

### Phase 1：统一 CLI 环境与 Agent 发现契约

**Entry Criteria**：设计规格、现有 CLI/Auth/API 代码和正式计划文件组存在，T1.1 三处状态一致。

**Exit Criteria**：测试环境命名配置、环境隔离凭据、共享注册表、公开 manifest/Skill 和 `agent doctor` 均有自动化测试。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T1.1 | [sub-delivery-plan-dydata-45-test-agent-connect-T1.1-cli-environment-registry.md](sub-delivery-plan-dydata-45-test-agent-connect-T1.1-cli-environment-registry.md) | 已完成（2026-07-22） |
| T1.2 | [sub-delivery-plan-dydata-45-test-agent-connect-T1.2-agent-discovery-doctor.md](sub-delivery-plan-dydata-45-test-agent-connect-T1.2-agent-discovery-doctor.md) | 已完成（2026-07-22） |

### Phase 2：远程 MCP OAuth 与只读能力复用

**Entry Criteria**：T1.1、T1.2 已完成，注册表、环境标识和公开发现契约冻结。

**Exit Criteria**：标准 Streamable HTTP MCP、OAuth 2.1/PKCE、持久化 token rotation、Web 授权确认与两项只读工具通过协议级测试。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T2.1 | [sub-delivery-plan-dydata-45-test-agent-connect-T2.1-mcp-oauth.md](sub-delivery-plan-dydata-45-test-agent-connect-T2.1-mcp-oauth.md) | 已完成（2026-07-22） |
| T2.2 | [sub-delivery-plan-dydata-45-test-agent-connect-T2.2-shared-capabilities-consent.md](sub-delivery-plan-dydata-45-test-agent-connect-T2.2-shared-capabilities-consent.md) | 已完成（2026-07-22） |

### Phase 3：测试环境交付与独立 Agent 验收

**Entry Criteria**：Phase 1、2 自动化通过，镜像依赖和反代入口已纳入版本控制。

**Exit Criteria**：测试环境健康、CLI 和 MCP 分别完成真实授权，独立子代理验证范围隔离与统计口径，回滚步骤可执行。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T3.1 | [sub-delivery-plan-dydata-45-test-agent-connect-T3.1-deploy-agent-uat.md](sub-delivery-plan-dydata-45-test-agent-connect-T3.1-deploy-agent-uat.md) | 进行中 |

## 4. 任务看板

- 看板入口：[task-kanban-dydata-45-test-agent-connect.md](task-kanban-dydata-45-test-agent-connect.md)

## 5. 发布闸门

- [x] 共享注册表唯一声明 CLI/API/MCP 能力与只读属性
- [x] 测试环境与未来生产环境凭据槽位可证明隔离，未知环境快速失败
- [x] OAuth 2.1、PKCE S256、DCR、resource/audience 与 token rotation 有负向测试
- [x] `/mcp` 只暴露 `stores_list` 和 `clues_follow_up_stats`
- [x] manifest、Agent 文档、Skill、doctor 与真实端点一致
- [x] Python 全量测试、Web build、迁移、Docker/Nginx 配置检查通过
- [ ] 独立 Agent 对测试账号仅看到授权门店，CLI/MCP 同口径
- [ ] 五个 Task 的 Evidence、完成日期与三处状态全部同步

## 6. 风险与应对

| 风险 | 影响 | 应对 | Owner | 状态 |
|---|---|---|---|---|
| MCP Python SDK v2 仍为预发布 | 协议接口漂移 | 生产依赖锁定 `mcp>=1.27,<2` 并写协议测试 | AI 执行 -> 人审核 | 已控制 |
| OAuth token 或授权码泄漏 | 账号数据越权 | 仅存哈希、短 access token、单次 code、refresh family rotation、日志脱敏 | AI 执行 -> 人审核 | 已验证 |
| 公开 DCR/OAuth 写入口被滥用 | 腾讯云测试库或服务资源持续增长 | 测试环境限制请求体、元数据和每 IP 速率；DYDATA-46 上生产前补过期数据清理、容量指标、告警与生产限流标定 | AI 执行 -> 人审核 | 测试版已控制，生产待 DYDATA-46 |
| 不同接入面复制业务统计逻辑 | 跟进率口径漂移 | 抽取共享能力服务并执行 CLI/MCP 等价测试 | AI 执行 -> 人审核 | 已验证 |
| 腾讯云测试版与未来企业内网生产版是不同部署环境 | 误用测试凭据访问生产，或把未部署的内网版描述成已上线 | 固定命名环境与 server identity keyring；DYDATA-46 对入口、OAuth、keyring、部署、文档和 smoke 做彻底切换 | 人类 Owner | 已隔离 |
| Agent 不支持远程 MCP OAuth | 无法自动接入 | manifest 同时提供 CLI fallback 和复制即用 Skill | AI 执行 -> 人审核 | 待验证 |

## 7. AI 执行示例

1. 开始 T1.1：读取设计 §4-§5，运行环境和一致性门禁，先写未知环境、凭据槽位隔离及注册表派生的失败测试，再实装。
2. 完成 T2.2：先同步 T2.1 三处为已完成、T2.2 三处为进行中，再对同一用户执行 CLI/MCP 契约等价测试；证据不足时不得进入部署。

## 8. PRD → 任务反向索引

| 需求依据 | Task | 子开发计划 |
|---|---|---|
| 设计 §4-§5 | T1.1 | [CLI 环境与注册表](sub-delivery-plan-dydata-45-test-agent-connect-T1.1-cli-environment-registry.md) |
| 设计 §8-§9 | T1.2 | [Agent 发现与诊断](sub-delivery-plan-dydata-45-test-agent-connect-T1.2-agent-discovery-doctor.md) |
| 设计 §6 | T2.1 | [MCP OAuth](sub-delivery-plan-dydata-45-test-agent-connect-T2.1-mcp-oauth.md) |
| 设计 §7、§10 | T2.2 | [共享能力与授权页](sub-delivery-plan-dydata-45-test-agent-connect-T2.2-shared-capabilities-consent.md) |
| 设计 §11-§12 | T3.1 | [部署与 Agent UAT](sub-delivery-plan-dydata-45-test-agent-connect-T3.1-deploy-agent-uat.md) |
