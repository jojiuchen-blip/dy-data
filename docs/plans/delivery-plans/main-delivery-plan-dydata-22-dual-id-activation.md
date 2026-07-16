# DYDATA-22 双 ID 账号激活主开发计划

> **版本**：v1
> **发布日期**：2026-07-16
> **前序版本**：无
> **适用范围**：账号激活前端、认证 API、静态激活指南与 PDF
> **参与角色**：AI 执行，人类 Owner 审核与验收
> **开发模式**：solo-local
> **执行约束**：按 TDD 顺序实施；登录标识保持兼容；账号激活和忘记密码统一使用双 ID 核验；不得扩大到 OAuth、MFA 或登录标识改造
> **目标**：把账号激活改为两阶段流程：第一屏使用“账户所属 ID + 所属账户关联 POI ID”核验子机构账号资格和激活状态，第二屏仅为可激活账户设置账号名和密码，并提供可访问的独立激活指南入口
> **当前需求基线**：Linear `DYDATA-22`（2026-07-16 已更新）及当前用户确认的双 ID 激活口径
> **上游发现结论**：`collect-upstream-context.mjs` 于 2026-07-16 扫描失败，原因是 `docs/prd/` 不存在；本计划按 Linear `DYDATA-22`、`docs/brd/BRD-dy-data-20260716-1255.md` 和已确认的静态指南实现作为权威输入，不补造 PRD 事实

## 0. 本计划使用指南

1. 先读取本主开发计划和任务看板，确认当前唯一可执行 Task。
2. 再打开该 Task 的子开发计划，只读取列出的需求、代码和测试文件。
3. 初始 Task 均为 `待审阅`；人类 Owner 明确回复“审阅通过”后才能翻为 `待开发`。
4. 每个 Task 均执行“测试先失败、最小实现、测试通过、状态回写”的闭环。

### 0.1 PRD 加载约束

- 本项目当前无 `docs/prd/`，不得假设不存在的 PRD 章节。
- 需求口径以 Linear `DYDATA-22`、`docs/brd/BRD-dy-data-20260716-1255.md` 和 `../account-activation-guide/docs/superpowers/specs/2026-07-16-dual-id-account-activation-design.md` 为准。
- 若上述来源冲突，立即阻塞并交由人类 Owner 裁决，不得自行选择。

### 0.2 读前门禁 / AI 自检清单

- 当前 Task 能从任务看板定位到唯一子开发计划。
- 主计划、看板、子计划三处状态一致，且同一时刻最多一个 Task 为 `进行中`。
- 激活接口与忘记密码接口的数据模型分离，但两者复用同一套双 ID 资格核验；忘记密码不得再要求认证主体全称。
- 应用源码修改前先写对应失败测试并确认失败原因是目标行为尚未实现。

### 0.3 完成前验证门禁

- 执行每个子计划声明的 `Verification Method`。
- 前端必须完成桌面和移动端真实浏览器验证；截图存入 `pwScreenShot/`。
- 后端必须覆盖同记录成功、跨记录失败、缺字段失败和既有登录/重置兼容回归。
- 指南 HTML 与 PDF 必须使用真实激活页截图，且双 ID 文案一致。

## 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Node.js | 项目当前支持版本 | `node -v` |
| npm | 项目当前支持版本 | `npm -v` |
| Python | >= 3.11 | `python --version` |

| 工程目录 | 就绪标识 |
|---|---|
| `apps/web/` | `node_modules/` 存在 |

## 1. 差距基线

| 差距 | 优先级 | 影响 | 对应任务 | 状态 |
|---|---|---|---|---|
| 激活页仍是一次性长表单，未先核验双 ID 和激活状态 | P0 | 用户无法在设置账号前确认门店资格 | T1.1 | 已完成（2026-07-16） |
| 激活 API 仍按单标识和认证主体核验，无法证明两个 ID 来自同一条认证成功的子机构账号记录 | P0 | 存在错误绑定和权限错配风险 | T1.2 | 已完成（2026-07-16） |
| 登录页未提供完整独立指南入口，指南也未回填真实新表单截图 | P1 | 外部访问受限时用户难以自助完成激活 | T1.3 | 已完成（2026-07-16） |

## 2. 分工与边界

| 角色 | 职责 |
|---|---|
| AI | 执行代码取证、测试先行、前后端实装、静态指南打包、浏览器与回归验证、状态回写 |
| 人类 Owner | 审阅计划、确认业务口径、验收页面交互和最终产物 |

## 3. 执行阶段

### Phase 1：双 ID 激活闭环

**Entry Criteria**：Linear `DYDATA-22` 已更新；本计划、任务看板和三个子开发计划通过结构校验；人类 Owner 明确回复“审阅通过”。

**Exit Criteria**：双 ID 核验第一屏、账号密码第二屏、激活状态 API 和独立指南入口形成可验证闭环；自动化测试通过；桌面和移动端截图、PDF 证据落盘。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T1.1 | [sub-delivery-plan-dydata-22-dual-id-activation-T1.1-frontend.md](sub-delivery-plan-dydata-22-dual-id-activation-T1.1-frontend.md) | 已完成（2026-07-16） |
| T1.2 | [sub-delivery-plan-dydata-22-dual-id-activation-T1.2-backend.md](sub-delivery-plan-dydata-22-dual-id-activation-T1.2-backend.md) | 已完成（2026-07-16） |
| T1.3 | [sub-delivery-plan-dydata-22-dual-id-activation-T1.3-integration-guide.md](sub-delivery-plan-dydata-22-dual-id-activation-T1.3-integration-guide.md) | 已完成（2026-07-16） |

## 4. 任务看板

- 看板入口：[task-kanban-dydata-22-dual-id-activation.md](task-kanban-dydata-22-dual-id-activation.md)

## 5. 发布闸门

- [x] Linear `DYDATA-22` 与前端字段、API 请求结构、同记录核验规则一致
- [x] T1.1、T1.2、T1.3 的 `Verification Method` 均已执行并留下证据
- [x] 忘记密码使用账户所属 ID 与关联 POI ID 核验，成功后只修改密码并保持原账号名；登录仍支持既有账号名、账户 ID 和 POI ID
- [x] 第一屏只在认证成功的子机构账号记录中核验两个 ID，并准确处理“不匹配 / 已激活 / 可激活”三种状态
- [x] 非同一记录的账户所属 ID 与 POI ID 组合无法进入第二屏或完成激活
- [x] 第二屏账号名只接受数字和英文字母，不展示认证主体全称或显示名称
- [x] `/account-activation-guide/index.html` 可由未登录激活页新标签打开，并随 Web 构建产物发布
- [x] 指南 HTML/PDF 已使用真实脱敏的新激活表单截图
- [x] 主计划、任务看板和子开发计划状态一致

## 6. 风险与应对

| 风险 | 影响 | 应对 | Owner | 状态 |
|---|---|---|---|---|
| `docs/prd/` 缺失 | 缺少仓库内 PRD 导航 | 仅采用已确认的 Linear issue、BRD 和指南规格；冲突时阻塞 | AI -> 人类 Owner | 已知 |
| 激活与重置密码的状态分支相反 | 将未激活账号错误放入重置流程 | 复用双 ID 核验接口，但按模式分别解释 `ready` 和 `activated`，并补分支测试 | AI -> 人类 Owner | 已验证 |
| 仅按两个独立映射表求交集可能接受历史脏数据 | 错误账号绑定 | 使用同一条 `raw_aweme_bindings` 记录核验账户 ID、关联 POI、账号类型和认证状态 | AI -> 人类 Owner | 已验证 |
| 指南源目录与 Web 公共目录产生漂移 | 线上指南版本落后 | 明确同步入口并在构建/测试中检查关键文件和 PDF 哈希一致 | AI -> 人类 Owner | 已验证 |

## 7. AI 执行示例

1. 开始 T1.1 前，先把三处状态同步为 `进行中`，运行 S4 一致性和环境门禁，再修改前端测试并观察预期失败。
2. T1.1 完成后，将验证证据和 foundation 漂移结论提交给 `ai-project-manager`，同步状态后再进入 T1.2。

## 8. PRD → 任务反向索引

| 需求来源 | Requirement ID | Task | 子开发计划 |
|---|---|---|---|
| Linear `DYDATA-22`：激活表单与指南入口 | DYDATA-22-FE | T1.1 | [T1.1 前端计划](sub-delivery-plan-dydata-22-dual-id-activation-T1.1-frontend.md) |
| Linear `DYDATA-22`：双 ID 同记录核验 | DYDATA-22-BE | T1.2 | [T1.2 后端计划](sub-delivery-plan-dydata-22-dual-id-activation-T1.2-backend.md) |
| Linear `DYDATA-22`：独立指南发布与真实截图 | DYDATA-22-GUIDE | T1.3 | [T1.3 联调与指南计划](sub-delivery-plan-dydata-22-dual-id-activation-T1.3-integration-guide.md) |
