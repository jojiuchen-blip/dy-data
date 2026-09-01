# DYDATA-81 门店端财务页面主交付计划

> **版本**：v1.2
> **发布日期**：2026-08-30
> **前序版本**：DYDATA-80 v2-clean 与 `main-delivery-plan-dy-data.md` 系统生产发布计划
> **适用范围**：将用户已验收的 UAT 页面合同合并到正式系统门店端，完成真实 API 联调、权限验证、全量测试、视觉回归、主分支集成和生产部署；推广费明细、管理费明细和账单异议是单店分账内模块，不是二级页面
> **参与角色**：AI 执行 -> 人审核
> **执行约束**：独立工作树 `codex/dydata-81-store-finance`；财务端工作树、页面、路由、组件、API、测试、导航与权限均受保护
> **当前需求基线**：Linear DYDATA-81、DYDATA-19、DYDATA-31、PRD 2/4、账单发票 Foundation、冻结临时看板 commit `codex/dydata-19-finance-mock@9a574fa`、页面合同矩阵，以及用户 2026-08-30 对最新 UAT 的验收通过和“请完成到生产部署环节”授权

> **2026-08-30 状态更新**：T1.2 独立 UAT 已完成专项测试、构建和 390/768/1440 视觉证据，用户明确验收通过，并授权进入正式系统合并与生产部署。T1.1 转为唯一进行中任务；T1.3 仅在 T1.1 全部门禁通过后执行。`/finance/*` 页面、接口、导航、权限和测试始终受保护；DYDATA-81 在用户最终验收前保持打开。

## 0. 本计划使用指南

1. 先读取本计划和任务看板，只执行唯一进行中的 T1.1；T1.3 必须等待 T1.1 的全量门禁和合并前证据全部通过。
2. 页面层级、视觉与组件使用正式系统；模块、字段与交互以已锁定临时看板和页面合同矩阵为结构基线；金额、状态、权限和可写能力以真实 API 与用户最新明确确认的基准资料为准。
3. T1.1 只修改门店端正式页面及其正式 API 契约；T1.3 按仓库发布 runbook 合并和部署。任何 `/finance/*` 页面、接口、导航、权限或测试 diff 均阻断发布。

### 0.1 PRD 加载约束

- 先读 `docs/prd/mainprd-dy-data.md`，再读 `docs/prd/subprd/02-subprd-store-settlement.md` 与 `docs/prd/subprd/04-subprd-invoice-registration.md`。
- API 与数据口径以 `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md`、`docs/prd/foundation/foundation-schema-dy-data/billing-invoice.md` 为准。
- 页面视觉读取 `docs/design-system/README.md`、`docs/design-system/tokens.json`、`apps/web/src/design-tokens.css`。

### 0.2 读前门禁 / AI 自检清单

- Linear DYDATA-81 为 In Progress，用户已明确授权本轮门店端开发。
- 最新 UAT 页面合同已获用户验收通过；正式页面不得继承 UAT 演示运行态或虚构数据。
- `.worktrees/dydata-81-finance-nav` 及所有 `/finance/*` 代码和测试列为受保护范围。
- 当前 Task 必须从看板定位到唯一子计划，且三处状态一致。

### 0.3 完成前验证门禁

- 执行 `git diff --check`、门店端专项测试、全量 `python -m pytest`、正式前端 build、正式 API 联调、权限验证、演示数据扫描和受保护路径 diff 检查。
- 使用真实浏览器对 UAT 与正式系统四页做 390/768/1440 并排视觉回归，证据保存到 `pwScreenShot/dydata-81-store-finance/`。
- 仅当所有合并前门禁为零失败时进入 T1.3；部署后执行生产页面、静态资源、健康接口、门店权限与回滚入口 smoke。
- 生产部署完成后仍不得关闭 DYDATA-81，等待用户最终验收。

## 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Node.js | >= 18 | `node -v` |
| Python | >= 3.11 | `python --version` |

| 工程目录 | 就绪标识 |
|---|---|
| `apps/web/` | `node_modules/` 存在 |

## 1. 差距基线

| 差距 | 优先级 | 影响 | 对应任务 | 状态 |
|---|---|---|---|---|
| 正式页面需逐项落实已验收 UAT 的结构、模块、字段、动作与跳转 | P0 | 不一致时不能部署 | T1.1 | 进行中 |
| 独立 UAT 四页结构、空态和响应式需由用户验收 | P0 | 未验收不能改正式系统 | T1.2 | 已完成（2026-08-30） |
| 临时看板演示数据、日期、状态和提示不得进入正式页面 | P0 | 可能污染真实业务 | T1.1 | 门禁验证中 |
| 全量 pytest 合并运行存在 Playwright 同步 API 与事件循环冲突 | P0 | 全量门禁失败则不得上线 | T1.1 | 阻断中，按根因修复 |
| 主分支集成、生产部署、smoke 与回滚记录尚未形成 | P0 | 无法交付生产版本 | T1.3 | 待 T1.1 通过 |

## 2. 分工与边界

| 角色 | 职责 |
|---|---|
| AI | 基线取证、代码理解、TDD 实装、浏览器与回归验证、计划和 Linear 证据回填 |
| 人类 Owner | 逐页审核结构/功能一致性，确认任何批准差异 |

受保护范围：所有 `/finance/*` 页面、路由行为、导航、权限、API、测试及 `.worktrees/dydata-81-finance-nav` 未提交内容。仅允许对既有门店账单/发票接口做最小契约补充；不新增数据库迁移。生产部署只允许在全部门禁通过后按现有发布 runbook 执行。

## 3. 执行阶段

### Phase 1：门店端四页一致性闭环

**Entry Criteria**：Linear 范围锁已记录；4181 三页基线已落盘；真实 API、PRD、Foundation 与设计系统已读取；独立工作树建立。

**Exit Criteria**：四个二级页面以及单店分账内费用明细/异议模块在正式系统与已验收 UAT 一致，真实 API、权限、全量测试、构建和三档视觉证据全部通过，受保护财务端 diff 为零；随后才可进入生产发布。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T1.1 | [正式系统门店端页面实施](sub-delivery-plan-dydata-81-store-finance-T1.1-store-pages.md) | 进行中 |
| T1.2 | [隔离的门店端财务只读 UAT 预览](sub-delivery-plan-dydata-81-store-finance-T1.2-readonly-uat-preview.md) | 已完成（2026-08-30） |
| T1.3 | [主系统集成与生产发布](sub-delivery-plan-dydata-81-store-finance-T1.3-production-release.md) | 待开发 |

## 4. 任务看板

- 看板入口：[task-kanban-dydata-81-store-finance.md](task-kanban-dydata-81-store-finance.md)

## 5. 发布闸门

- [x] T1.2 四页、费用明细/异议模块、开票提醒与时间节奏已获用户验收通过
- [x] UAT 专项 pytest、独立 Vite build、390/768/1440 截图、无写请求和受保护范围检查通过
- [ ] T1.1 门店端专项、全量 pytest、正式 build、API 联调、权限、演示数据扫描和 `/finance/*` 受保护范围检查全部通过
- [ ] 正式系统与 UAT 的 390/768/1440 四页并排证据完成且不存在未批准偏差
- [ ] T1.3 主分支集成、CI/部署、生产 smoke、版本与回滚记录全部成功
- [ ] 生产部署后保持 DYDATA-81 打开，等待用户最终验收

## 6. 风险与应对

| 风险 | 影响 | 应对 | Owner | 状态 |
|---|---|---|---|---|
| 共享 `Shell.tsx` 同时承载财务导航 | 误伤财务端或产生合并冲突 | 只追加 settlement 路径/导航，测试锁定 `/finance/*` 文本与行为不变 | AI -> 人审核 | 受控 |
| 临时看板逻辑与 PRD/Foundation 冲突 | 把演示能力带入生产 | 业务权威优先，差异写入基线矩阵；不新增红冲/作废假动作，既有真实生命周期登记与替换闭环保持不变 | AI -> 人审核 | 已处理 |
| 异议上传 API 未开放 | 无法实现真实提交 | 使用业务空态，不做假成功或开发 Issue 文案 | AI -> 人审核 | 已知 |
| 全量 pytest 合并运行触发 Playwright 同步 API 与事件循环冲突 | 无法通过全量发布门禁 | 先最小复现并修复测试运行时根因；全量命令零错误前不得上线 | AI -> 人审核 | 阻断中 |
| 4181 当前是旧原型 | 最终入口指错版本 | 验证完成后停止旧进程，以本独立工作树启动主应用 | AI -> 人审核 | 已切换并完成根页面/API 鉴权 smoke |
| 全局执行驾驶舱当前由 DYDATA-46 占用 | 修改其状态会误伤其他 Issue | 不改 `docs/plans/execution-plan.md`；仅对本计划文件组执行一致性门禁并记录全局路由检查差异 | AI -> 人审核 | 受控 |
| 生产发布成功被误认为 Issue 已完成 | 跳过最终业务验收 | 部署与 Issue 关闭解耦；生产 smoke 通过后仍等待用户最终验收 | AI -> 人审核 | 受控 |

## 7. AI 执行示例

1. 从看板打开 T1.1，先重现全量测试阻断并形成最小失败用例，再修复根因、重跑定向与全量门禁。
2. T1.1 完成后同步三份计划状态并切换到 T1.3；发布前再次检查 `git diff --name-only` 未触碰受保护范围。

## 8. PRD → 任务反向索引

| PRD / 权威来源 | Requirement ID | Task | 子开发计划 |
|---|---|---|---|
| PRD 2 §2—§3；账单发票 API §2 | DYDATA-81-STORE-SETTLEMENT | T1.1 | [T1.1](sub-delivery-plan-dydata-81-store-finance-T1.1-store-pages.md) |
| PRD 4 §2—§4；账单发票 API §4 | DYDATA-81-STORE-INVOICE | T1.1 | [T1.1](sub-delivery-plan-dydata-81-store-finance-T1.1-store-pages.md) |
| DYDATA-81 本轮范围锁；4181 发票状态页基线 | DYDATA-81-INVOICE-STATUS | T1.1 | [T1.1](sub-delivery-plan-dydata-81-store-finance-T1.1-store-pages.md) |
| UAT 设计规格 §1—§9；页面合同矩阵 | DYDATA-81-UAT-PREVIEW | T1.2 | [T1.2](sub-delivery-plan-dydata-81-store-finance-T1.2-readonly-uat-preview.md) |
| DYDATA-81 生产发布授权；`main-delivery-plan-dy-data.md` 系统生产发布计划 | DYDATA-81-RELEASE | T1.3 | [T1.3](sub-delivery-plan-dydata-81-store-finance-T1.3-production-release.md) |
