# DYDATA-89 线索中心逐步聚焦新手引导主开发计划

> **最新发布授权（2026-09-07）**：用户明确要求“提交、推送、部署”，本次交付扩展为 CI 通过后的合并与生产发布；下文“不部署”措辞保留为此前开发阶段的范围记录。沿用现有腾讯云发布流程，核对目标 SHA、备份、服务健康与线上静态资源；发布结果及最终状态以 Linear DYDATA-89 为准。失败时保留日志，并按运行手册回退应用版本，不执行未经评估的数据库降级。

> **版本**：v1
> **发布日期**：2026-09-07
> **前序版本**：无（Issue 专项并行增量）
> **适用范围**：Linear DYDATA-89；真实页面 `/clues` 与 `/clues/details` 的逐步聚焦新手引导
> **开发模式**：solo-local / isolated worktree
> **参与角色**：AI 执行 -> 人审核
> **执行约束**：只改本专项列出的前端、测试和说明落点；不改 API、Schema、部署、财务主线或其他并行驾驶舱状态
> **目标**：在真实线索页面提供可跳过、可重播、可访问且不改变业务数据的新手引导，帮助首次使用者理解线索明细入口、筛选、详情、联系方式、跟进表单和历史
> **开工需求基线**：Linear DYDATA-89（In Progress，项目“线索跟进中心”，负责人 Keith）；用户已审阅并授权进入开发的七步范围；线索中心 BRD/Foundation；现有 `ClueCenterPage`、共享 `Dialog`、设计 token 与浏览器回归基线
> **上游发现结论**：`collect-upstream-context.mjs` 于 2026-09-07T07:41:23.156Z 返回 `canProceed=true`，slug=`dy-data`，pipeline 模式；主 PRD 以结算与财务为主，线索专项业务语义以线索中心 BRD/Foundation 补充
> **当前交付状态（2026-09-07）**：功能代码已本地提交为 `95dff72`；完整回归及专项验证通过，交付进入草稿 PR 评审准备。PR 与 CI 最新证据以 Linear DYDATA-89 为准。Linear 保持 In Review；T0.1 在三处计划中保留 `进行中`，验收后再同步完成日期。本次不部署生产。

## 0. 本计划使用指南

1. 先读取本主计划、任务看板和唯一进行中的 T0.1 子计划，再按 `PRD 双链·读` 读取线索业务与页面依据。
2. 只在真实 `/clues` 与 `/clues/details` 页面接入引导；保留现有筛选、详情、跟进、权限和移动端行为作为业务真相。
3. 引导只执行阅读、打开详情和导航动作。任何手机号查看/复制、跟进保存、历史删除、导出或业务字段修改都必须由用户主动操作，不能由引导代触发。
4. 计划与现有 DYDATA-81、DYDATA-46、DYDATA-45、DYDATA-58 全局 cockpit 并行；本专项只新增一个紧凑入口，不覆盖其他主线状态。

### 0.1 PRD 加载约束

- 先读 `docs/prd/mainprd-dy-data.md`，仅用于确认宿主技术栈、页面权威边界与通用加载/空态规则。
- 线索业务语义读 `docs/brd/BRD-clue-center-20260721-2134.md` §3.2、§3.5、§5.1、§10；其中“当前有效轮次可操作、失效轮次仍可查看历史但不能查看/复制完整手机号”是详情 fallback 的依据。
- 线索 API/权限和页面覆盖读 `docs/prd/foundation/foundation-api-clue-center.md` §1、§3.1、§3.2、§5；本 Task 只消费现有只读/详情结果，不新增接口。
- 线索状态与页面字段读 `docs/prd/foundation/foundation-schema-clue-center.md` §5、§6、§8；不把状态字段改造成引导状态。
- 页面与视觉边界读 `src/frontend/page-preview/explainer-delivery-dy-data.md` 相关线索流程、`docs/design-system/README.md`、`docs/design-system/tokens.json`、`apps/web/src/design-tokens.css`。
- 真实实现与验证落点读 `apps/web/src/pages/ClueCenterPage.tsx`、`apps/web/src/components/Dialog.tsx`、`apps/web/src/components/Shell.tsx`、`apps/web/README.md` 及现有线索前端/视觉测试。

### 0.2 读前门禁 / AI 自检清单

- DYDATA-89 已存在于 Linear 且为 In Progress；用户已明确授权本次开发范围，不得重新扩展为线索业务模型或财务 PRD 工作。
- 计划组的主计划、看板和子计划必须各自把 T0.1 标为 `进行中`，并保持唯一 active Task。
- 目标页面仍由 `ClueCenterPage` 承载：`/clues` 是总览，`/clues/details` 是明细；当前筛选必须保留，目标行在当前结果内优先选择可操作行。
- 空结果在完成列表解释后结束；加载中、目标缺失、目标只读或详情不可用时必须有可结束的降级路径，不能等待或阻塞用户。
- 引导复用共享 `Dialog` 的 modal 语义。`role="dialog"`、`aria-modal`、inert、焦点捕获与恢复只能由 `components/Dialog.tsx` 维护；若引导与详情弹层叠加，先在共享组件内处理层级、inert 和焦点所有权，不新建独立 modal 实现。
- 下一步、上一步、跳过、进度和 Escape 必须可用；滚动、resize、窄屏筛选面板和详情 Dialog 不能让 spotlight 或 popover 失去可达性。
- 不触碰 API、Schema、生产部署、财务页面/接口/测试，亦不因本 Task 改写现有全局 cockpit 的当前阶段。

### 0.3 完成前验证门禁

- 执行 `git diff --check`。
- 执行 `python -m pytest tests/test_visual_clue_onboarding.py tests/test_frontend_clue_center.py tests/test_design_system_enforcement.py -q`，覆盖引导流程、线索既有行为与共享 Dialog/modal 语义。
- 执行 `npm --prefix apps/web run build`。
- 用真实浏览器验证 `/clues` 与 `/clues/details` 的 1440/768/390 视口；至少覆盖首次邀请、重播入口、七步推进/回退/跳过、空列表、只读详情、Escape、焦点恢复、滚动/resize、浅色/深色和 reduced-motion。
- 证据落到由 `DYDATA_TOUR_ARTIFACT_DIR` 指定的本地验证产物目录（不入库），未指定时使用 pytest `tmp_path`，并与测试输出一起保留；任一验证缺失或失败时保持 Task `进行中`，不得把计划写成实现完成。

## 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Node.js | >= 18 | `node -v` |
| Python | >= 3.11 | `python --version` |
| Git | >= 2.40 | `git --version` |

| 工程目录 | 就绪标识 |
|---|---|
| `apps/web/` | `node_modules/` 存在 |

## 1. 差距基线

| 差距 | 优先级 | 影响 | 对应任务 | 状态 |
|---|---|---|---|---|
| 真实线索页面没有逐步聚焦的新手入口与重播入口 | P0 | 首次用户难以从明细入口进入可复核工作流 | T0.1 | 进行中 |
| 线索列表、详情与跟进工作台跨层级，现有 Dialog 需要与引导层协调 | P0 | 叠加层可能遮挡目标或破坏焦点/inert | T0.1 | 进行中 |
| 当前账号/浏览器没有引导完成偏好与安全降级约定 | P1 | 重复打扰或无法再次查看 | T0.1 | 进行中 |
| 390/768/1440、加载/空/只读和 reduced-motion 的引导证据缺失 | P0 | 页面变体可能卡住或不可访问 | T0.1 | 进行中 |

## 2. 分工与边界

| 角色 | 职责 |
|---|---|
| AI | 读取真实页面与规则、实现引导组件/接入、编写专项浏览器验证、运行构建与回归并提交证据 |
| 人类 Owner | 审核七步文案与目标锚点、审核交互和响应式证据，确认完成或后续裁决 |

受保护边界：不修改后端 API/Schema/迁移/部署；不把手机号、跟进、删除、导出等业务动作塞进引导；不改财务和其他并行主线的页面、状态或 cockpit。

## 3. 执行阶段

### Phase 0：线索中心逐步聚焦引导闭环

**Entry Criteria**：DYDATA-89 为 In Progress 且用户范围已确认；上游发现可继续；`ClueCenterPage`、共享 `Dialog`、设计系统和现有线索测试已读取；无 API/Schema 变更依赖。

**Exit Criteria**：两个真实路由完成七步引导、首次邀请与重播、当前筛选内目标选择、空/加载/只读降级、键盘/焦点/inert、滚动/resize、三档视口、浅色/深色和 reduced-motion 验证；专项测试、相关回归、build、diff check 和证据均通过。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T0.1 | [sub-delivery-plan-dydata-89-clue-onboarding-T0.1-clue-onboarding.md](sub-delivery-plan-dydata-89-clue-onboarding-T0.1-clue-onboarding.md) | 进行中 |

## 4. 任务看板

- 看板入口：[task-kanban-dydata-89-clue-onboarding.md](task-kanban-dydata-89-clue-onboarding.md)

## 5. 发布闸门

- [x] `/clues` 和 `/clues/details` 均能以真实页面元素完成七步或按 fallback 结束；进度、上一步、下一步、跳过和重播入口可核查
- [x] 首次邀请与完成偏好按账号/浏览器隔离；当前筛选、业务字段和列表数据不被引导改写
- [x] 引导不会触发手机号 reveal/copy、跟进保存、历史删除、导出或其他写操作；只读目标和空/加载/缺失目标可结束
- [x] modal 语义仍集中于 `Dialog.tsx`，叠加详情时层级、inert、Escape 和焦点恢复有自动化证据
- [x] 1440/768/390 真实浏览器证据覆盖浅色、深色、reduced-motion、滚动/resize 与移动详情 Dialog
- [x] `python -m pytest ...`、`npm --prefix apps/web run build` 和 `git diff --check` 全部通过
- [x] 实现、验证、foundation 漂移判断和待验收状态已由 `ai-project-manager` 同步到本主计划、看板和子计划
- [ ] 用户验收通过后，按仓库 Done Gate 同步 T0.1 完成状态与 Linear；发布不在本次范围内

### 5.1 本地验证记录（2026-09-07）

- `python -m pytest tests/test_visual_clue_onboarding.py -q`：17 passed；使用本地 FastAPI 真实路由和合成数据，覆盖七步、三档视口、浅深色、reduced-motion、Tab/Escape/焦点、只读与失败路径、账号偏好、无 A02 权限、缺失目标、加载超时和列表刷新期间禁止打开旧行。
- `python -m pytest tests/test_frontend_clue_center.py tests/test_frontend_clue_demo_mode.py tests/test_design_system_docs.py tests/test_design_system_enforcement.py tests/test_frontend_user_facing_contracts.py tests/test_frontend_app_icon.py -q`：119 passed。
- `python -m pytest tests/test_visual_smoke.py -q -k 'clue_secondary_navigation or clue_filter_collapse or desktop_detail_pages_keep_pagination or design_system_catalog_examples_render'`：6 passed，239 deselected。
- `npm --prefix apps/web run build:design-system`、`npm --prefix apps/web run build`、`git diff --check`：退出码 0；保留既有构建体积提示。设计系统 manifest 与运行目录已再生成。
- 已检查手机端浅深色跟进步骤截图；说明卡和实际控件不重叠。截图保存在 `DYDATA_TOUR_ARTIFACT_DIR` 指定的仓库外目录，未写入仓库。
- 引导期间无手机号、导出或业务写请求；退出后手动保存经真实 FastAPI 路由与合成数据回读验证。未连接真实 PostgreSQL 或生产服务，不作为生产验收证据。
- 本任务无 foundation 漂移。下一步为用户检查七步文案与交互；验收前不关闭 DYDATA-89。
- 收口门禁：suite lock 有效；全局文件检查 0 errors / 0 warnings；计划结构 13/13、一致性检查与 S4 route-check 均通过。文档索引已刷新，链接验证仍报告 33 条历史 broken_link（退出码 1）；逐条比较基线 HEAD 后确认 33 条均已存在，本次新增 0 条，不扩大本次范围修复历史文档。

### 5.2 提交前完整回归（2026-09-07）

- `python -m pytest -q`：退出码 0，**2418 passed, 129 skipped, 8407 warnings in 2634.35s**；包含引导专项及全站浏览器回归。本地未配置专用 PostgreSQL 测试库，相关集成用例按既有环境条件跳过；保留依赖弃用警告，不作为真实 PostgreSQL 或生产验证。
- `npm --prefix .agent/project-manager-suite run test:ai-pm`：122 passed；协议对齐 0 errors / 0 warnings。功能复审未发现阻断问题。
- 功能提交 `95dff72` 基于 `86a8171`；测试期间功能代码未变更。文档索引的 33 条历史失效链接均已与该基线核对，本次新增 0 条。
- 交付记录同步后推送隔离分支并创建草稿 PR；PR 链接、远端提交与 CI 状态回填 Linear DYDATA-89。用户验收前维持 In Review 和三处 `进行中`，不合并或部署生产。

## 6. 风险与应对

| 风险 | 影响 | 应对 | Owner | 状态 |
|---|---|---|---|---|
| 引导与详情 Dialog 同时存在 | 可能出现错误层级、双重 inert 或焦点丢失 | 复用并最小扩展 `Dialog.tsx` 的层级/焦点所有权；引导组件不声明独立 modal 语义；先跑共享语义回归 | AI -> 人审核 | 受控 |
| 当前筛选下没有可操作行 | 七步无法自然进入详情/跟进 | 不清空或修改筛选；优先当前结果中的可操作行，无行时在列表解释后结束，只读详情跳过不可用写控件 | AI -> 人审核 | 受控 |
| 页面加载、接口错误或目标元素被移动 | 引导可能等待、遮挡或无法结束 | 监听目标可见性与 resize/scroll；目标缺失、只读或加载超时进入可见的结束/跳过状态，不执行写操作 | AI -> 人审核 | 受控 |
| 390px 窄屏筛选和近全屏详情改变布局 | popover 溢出、目标不可达或详情层被错误接管 | 使用现有 Dialog/移动工作台约束，按 390/768/1440 实测并保留自然滚动；不把桌面表格压成新布局 | AI -> 人审核 | 受控 |
| 深色主题或 reduced-motion 未覆盖 | 可读性和可访问性回归 | 只复用现有语义 token；对 `prefers-reduced-motion` 关闭位移/过渡并做浅深色截图验证 | AI -> 人审核 | 受控 |

## 7. AI 执行示例

1. 先从 T0.1 子计划读取线索 BRD/Foundation、`ClueCenterPage`、`Dialog` 和已有测试，确认当前筛选与可操作轮次约束，再实现引导锚点和共享层管理。
2. 先用专项浏览器测试证明首次邀请、重播、七步与 fallback，再运行线索前端/设计系统回归、build、diff check 和三档截图；任何业务写动作、modal 语义或受保护路径异常都停止并记录证据。

## 8. PRD → 任务反向索引

| 需求 / 权威来源 | Requirement ID | Task | 子开发计划 |
|---|---|---|---|
| Linear DYDATA-89 已审阅七步范围 | DYDATA-89-TOUR-FLOW | T0.1 | [T0.1](sub-delivery-plan-dydata-89-clue-onboarding-T0.1-clue-onboarding.md) |
| 线索中心 BRD §3.2、§3.5、§5.1：状态、当前有效轮次与跟进边界 | DYDATA-89-TOUR-SAFETY | T0.1 | [T0.1](sub-delivery-plan-dydata-89-clue-onboarding-T0.1-clue-onboarding.md) |
| 线索 API Foundation §3.1、§3.2、§5：详情、手机号与跟进权限 | DYDATA-89-TOUR-PERMISSION | T0.1 | [T0.1](sub-delivery-plan-dydata-89-clue-onboarding-T0.1-clue-onboarding.md) |
| 设计系统 Dialog、主题与三档视口约束 | DYDATA-89-TOUR-A11Y-VISUAL | T0.1 | [T0.1](sub-delivery-plan-dydata-89-clue-onboarding-T0.1-clue-onboarding.md) |
