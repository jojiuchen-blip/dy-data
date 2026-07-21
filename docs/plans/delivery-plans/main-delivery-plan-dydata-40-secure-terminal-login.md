# DYDATA-40 安全终端 CLI 登录主开发计划

> **版本**：v1
> **发布日期**：2026-07-22
> **前序版本**：无（对既有 DYDATA-40 CLI 的增量计划）
> **适用范围**：`dydata auth login` 默认安全终端登录与浏览器回退
> **参与角色**：AI 执行 -> 人类 Owner 审核
> **执行约束**：隔离 worktree、TDD、小提交、不部署、不覆盖已有凭据
> **目标**：用户在 Agent 启动的安全交互 TTY 中亲自输入账号和隐藏密码，复用现有授权链取得 `cli:read` 凭据
> **当前需求基线**：Linear `DYDATA-40`；2026-07-22 用户明确要求“直接完成设计、计划，然后开发”
> **上游发现结论**：`canProceed=true`，fallback authority 为已确认 CLI 设计及本次设计修订

## 0. 本计划使用指南

1. 先读本主计划和任务看板，只允许一个 Task 处于“进行中”。
2. 再读当前 Task 子计划列出的设计章节与真实代码。
3. 每个实现任务严格执行 Red -> Green -> Refactor，并保留命令证据。
4. 用户已在 2026-07-22 明确批准计划后直接开发，因此 T1.1 已由“待审阅”转为“进行中”，其余任务为“待开发”。

### 0.1 PRD 加载约束

- 全局基线：`docs/superpowers/specs/2026-07-21-agent-first-read-only-cli-design.md` §6、§7、§10-§13。
- 增量权威：`docs/superpowers/specs/2026-07-22-secure-terminal-cli-login-design.md` 全文。
- 每个 Task 只补充读取其子计划列出的代码和测试，不重新解释已确认的指标口径。

### 0.2 读前门禁 / AI 自检清单

- 当前 Task 在主计划、看板、子计划三处状态一致。
- 当前 Task 的失败测试尚未由生产代码预先满足。
- 不在根工作树修改用户或其他线程的在途文件。
- 不接收、不记录、不请求真实账号密码。

### 0.3 完成前验证门禁

- 子计划的 `Verification Method` 已执行并记录 RED/GREEN 或最终证据。
- 密码、Cookie、设备码和 Token 未出现在输出、日志、文档示例和 git diff 中。
- 主计划、看板、子计划状态与完成日期同步。

## 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Python | >= 3.12 | `python --version` |
| Node.js | >= 18 | `node --version` |

| 工程目录 | 就绪标识 |
|---|---|
| `apps/cli/` | `pyproject.toml` 存在 |
| `tests/` | `cli/` 存在 |

## 1. 差距基线

| 差距 | 优先级 | 影响 | 对应任务 | 状态 |
|---|---|---|---|---|
| 登录只能通过浏览器当前会话授权，易绑定错账号 | P1 | 独立 CLI 账号授权不稳定 | T1.1、T1.2 | 待处理 |
| 默认登录没有安全 TTY、隐藏密码和身份二次确认 | P1 | Agent 无法安全把输入权交给用户 | T1.2 | 待处理 |
| 命令目录和文档只描述浏览器登录 | P1 | Agent 无法判断可用模式和边界 | T1.3 | 待处理 |
| 新路径尚无全量回归、安全审查与真实 TTY 验证 | P1 | 不能形成可发布证据 | T1.4 | 待处理 |

## 2. 分工与边界

| 角色 | 职责 |
|---|---|
| 主 Agent | 设计、代码理解、TDD 实装、状态回写和最终验证 |
| 审查子代理 | 规格符合性、代码质量和安全负向审查；不接触真实凭据 |
| 人类 Owner | 已批准开工；后续负责真实 TTY 输入和最终业务验收 |

高冲突文件由主 Agent 独占：`commands.py`、`registry.py`、生成命令参考和正式计划状态。子代理默认只读审查，未经重新分派不得写这些文件。

## 3. 执行阶段

### Phase 1：安全认证会话与交互闭环

**Entry Criteria**：设计修订、主计划、看板和子计划存在；基线测试通过。

**Exit Criteria**：终端认证会话、TTY 交互、身份确认、浏览器回退和 compare-and-swap 保存均有自动测试。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T1.1 | [sub-delivery-plan-dydata-40-secure-terminal-login-T1.1-auth-session.md](sub-delivery-plan-dydata-40-secure-terminal-login-T1.1-auth-session.md) | 进行中 |
| T1.2 | [sub-delivery-plan-dydata-40-secure-terminal-login-T1.2-command-flow.md](sub-delivery-plan-dydata-40-secure-terminal-login-T1.2-command-flow.md) | 待开发 |

### Phase 2：发现、文档与发布证据

**Entry Criteria**：T1.1、T1.2 已完成，命令行为冻结。

**Exit Criteria**：运行时目录、生成文档、Agent 指南、完整测试和安全检查全部一致。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T1.3 | [sub-delivery-plan-dydata-40-secure-terminal-login-T1.3-docs-contract.md](sub-delivery-plan-dydata-40-secure-terminal-login-T1.3-docs-contract.md) | 待开发 |
| T1.4 | [sub-delivery-plan-dydata-40-secure-terminal-login-T1.4-verification.md](sub-delivery-plan-dydata-40-secure-terminal-login-T1.4-verification.md) | 待开发 |

## 4. 任务看板

- 看板入口：[task-kanban-dydata-40-secure-terminal-login.md](task-kanban-dydata-40-secure-terminal-login.md)

## 5. 发布闸门

- [ ] 设计修订、注册表和实现行为一致
- [ ] 终端路径只接受真实 TTY，密码隐藏且没有参数/环境变量入口
- [ ] 临时 Web Cookie 与业务 HTTP 客户端隔离并在所有路径关闭
- [ ] 已有凭据和并发新凭据均不会被静默覆盖
- [ ] 浏览器回退和既有只读查询无回归
- [ ] 目标测试、全量 pytest、Web build、文档漂移、diff 和安全检查均通过
- [ ] 四个 Task 的 Evidence、完成日期和三处状态已同步

## 6. 风险与应对

| 风险 | 影响 | 应对 | Owner | 状态 |
|---|---|---|---|---|
| Agent 工具不提供用户可接管的 TTY | 无法隐藏输入 | 快速失败并使用 `--browser` | AI 执行 -> 人审核 | 已控制 |
| Python 字符串无法物理擦除 | 内存残留承诺不可验证 | 最小作用域、不记录、不持久化、尽快释放引用 | AI 执行 -> 人审核 | 已接受 |
| `/auth/login` 是共享 Web 攻击面 | CLI 无法独立实现服务端防爆破 | 认证 POST 不重试；共享限流作为平台风险单独治理 | 人类 Owner | 待观察 |
| 两个登录进程竞态 | 凭据被覆盖 | `expected=None` compare-and-swap，失败时尽力撤销新令牌 | AI 执行 -> 人审核 | 已控制 |
| 根工作树有并行文档改动 | 状态文件冲突 | 全程在隔离 worktree，正式合并前人工核对 | AI 执行 -> 人审核 | 已控制 |

## 7. AI 执行示例

1. 执行 T1.1 前读取增量设计 §3-§4 和对应子计划，先写响应漂移/秘密泄漏失败测试，再写临时认证会话。
2. 执行 T1.2 前把 T1.1 三处标记完成、T1.2 三处标记进行中，再先写非 TTY、取消、旧凭据和竞态测试。

## 8. PRD → 任务反向索引

| 需求依据 | Task | 子开发计划 |
|---|---|---|
| 终端登录设计 §3、§4.2 | T1.1 | [认证会话](sub-delivery-plan-dydata-40-secure-terminal-login-T1.1-auth-session.md) |
| 终端登录设计 §3、§4.1、§4.3 | T1.2 | [命令流程](sub-delivery-plan-dydata-40-secure-terminal-login-T1.2-command-flow.md) |
| 终端登录设计 §5、§7.5 | T1.3 | [文档契约](sub-delivery-plan-dydata-40-secure-terminal-login-T1.3-docs-contract.md) |
| 终端登录设计 §6、§7 | T1.4 | [验证与安全](sub-delivery-plan-dydata-40-secure-terminal-login-T1.4-verification.md) |
