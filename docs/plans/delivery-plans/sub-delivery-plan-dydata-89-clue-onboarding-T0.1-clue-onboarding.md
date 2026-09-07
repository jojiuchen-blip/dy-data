# T0.1 线索中心逐步聚焦新手引导子开发计划

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-89-clue-onboarding.md](main-delivery-plan-dydata-89-clue-onboarding.md)
- 任务看板：[task-kanban-dydata-89-clue-onboarding.md](task-kanban-dydata-89-clue-onboarding.md)

#### T0.1 实现真实线索页面逐步聚焦新手引导

**Requirement ID**：DYDATA-89-TOUR-FLOW / DYDATA-89-TOUR-SAFETY / DYDATA-89-TOUR-PERMISSION / DYDATA-89-TOUR-A11Y-VISUAL

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` 全局权威边界与技术栈
- `docs/brd/BRD-clue-center-20260721-2134.md` §3.2、§3.5、§5.1、§10
- `docs/prd/foundation/foundation-api-clue-center.md` §1、§3.1、§3.2、§5
- `docs/prd/foundation/foundation-schema-clue-center.md` §5、§6、§8
- `src/frontend/page-preview/explainer-delivery-dy-data.md` 线索流程索引
- `docs/design-system/README.md`、`docs/design-system/tokens.json`、`apps/web/src/design-tokens.css`
- `apps/web/README.md`、Linear DYDATA-89 已审阅范围

**核心逻辑**：
- 在真实 `/clues` 与 `/clues/details` 上提供七步逐步聚焦：①可见的“线索明细”导航；②“线索状态”筛选并解释“待跟进”；③“查看详情”；④手机号查看/复制控件的权限边界说明；⑤跟进结果与备注；⑥“保存本次跟进”说明；⑦“线索跟进历史”。每步提供 spotlight、说明 popover、上一步/下一步/跳过/进度；首用显示邀请，完成后可从页面入口重播。
- 引导只允许阅读、打开详情和导航。它不自动 reveal/copy 手机号、不提交跟进、不删除历史、不导出、不修改筛选、不改业务值；当前筛选保持原样，目标行在当前结果中优先选择可操作行。
- 当结果为空时，在列表解释后结束；加载中、目标缺失、详情失败或目标只读时显示可结束的 fallback，跳过不可用的写操作说明，不等待用户提交或创建虚假数据。
- 复用共享 `Dialog` 承载 modal 语义。引导与线索详情叠加时，由 `Dialog.tsx` 统一维护层级、inert、Escape、焦点捕获和恢复；`GuidedTour.tsx` 不自行声明 `role="dialog"` / `aria-modal`，也不引入第二套 modal/focus trap。若既有 Dialog 已满足某项能力，仅做必要的最小扩展。
- 以现有设计 token 支持浅色/深色、1440/768/390 视口和 `prefers-reduced-motion`；滚动、resize、移动筛选面板与详情 Dialog 变化后重新定位或安全结束，不遮死页面。
- 引导偏好按账号与浏览器隔离；存储不可用时仍保留当前会话可结束和可重播的安全行为。键盘操作、Escape、焦点恢复和触摸目标需在真实浏览器验证。

**核心文件**：
- `apps/web/src/components/GuidedTour.tsx`（新增逐步聚焦组件；不声明独立 modal 语义）
- `apps/web/src/hooks/useClueOnboarding.ts`（页面流程编排、当前账号偏好与只读/空态/失败回退）
- `apps/web/src/components/Dialog.tsx`（共享层级、inert、焦点捕获/恢复的最小扩展；详情 Dialog 既有行为需回归）
- `apps/web/src/pages/ClueCenterPage.tsx`（两路由锚点、当前筛选内目标选择、邀请/重播与 fallback 接入）
- `apps/web/src/components/Shell.tsx`（仅在现有移动详情/页面层协调确有需要时接入；不重排导航）
- `apps/web/src/components/GuidedTour.css`、`apps/web/src/pages/ClueOnboarding.css`（spotlight、popover、邀请入口、响应式与 reduced-motion 样式，复用设计 token）
- `apps/web/src/design-system/DesignSystemCatalog.tsx`、`docs/design-system/components.json`、`docs/design-system/tokens.json` 及生成的设计系统目录（注册共享引导组件与可运行示例）
- `tests/test_visual_clue_onboarding.py`（新增真实浏览器七步/回退/三档视口/主题证据）
- `tests/test_frontend_clue_center.py`、`tests/test_design_system_enforcement.py`（既有线索与共享 modal/accessibility 回归）
- `apps/web/README.md`（记录真实页面引导与重播/无写操作边界，如实现需要更新）

**完成标准**：
- `/clues` 和 `/clues/details` 首次进入均能显示邀请；用户接受后按批准顺序定位七个真实页面目标，进度、上一步、下一步、跳过、完成与重播入口可由按钮/键盘操作核查。
- 引导只读/开详情/导航；浏览器网络与页面状态证据表明未因引导触发手机号 reveal/copy、跟进保存、历史删除、导出或筛选/业务值写入。
- 当前筛选不被重置或改写，目标行只从当前结果选择并优先可操作行；空结果在列表说明后结束，加载/目标缺失/详情错误/只读详情均能在一次操作内结束或跳过，不出现无限 loading。
- 共享 `Dialog.tsx` 保持 `role="dialog"`、`aria-modal`、inert、Tab 循环、Escape 和 return focus 契约；叠加引导与详情时只保留正确的顶层焦点与层级。`test_design_system_enforcement.py` 不发现业务组件自行声明 modal 语义。
- 1440x900、768x1024、390x844 的真实浏览器证据覆盖列表与详情、滚动/resize、移动详情 Dialog、浅色、深色和 reduced-motion；spotlight/popover 不被视口裁切，触摸目标满足现有设计系统规则。
- `python -m pytest tests/test_visual_clue_onboarding.py tests/test_frontend_clue_center.py tests/test_design_system_enforcement.py -q`、`npm --prefix apps/web run build`、`git diff --check` 均以退出码 0 完成；证据写入由 `DYDATA_TOUR_ARTIFACT_DIR` 指定的本地验证产物目录（不入库），未指定时使用 pytest `tmp_path`，并与相关测试输出一起保留。

**Verification Method**：
- 先运行 `python -m pytest tests/test_visual_clue_onboarding.py tests/test_frontend_clue_center.py tests/test_design_system_enforcement.py -q`，确认专项、线索既有行为和 Dialog/modal 集中化回归结果。
- 运行 `npm --prefix apps/web run build` 与 `git diff --check`。
- 用真实 Playwright 浏览器在 1440x900、768x1024、390x844 逐页验证 `/clues` 与 `/clues/details`，覆盖首次邀请、重播、七步控制、空/只读/加载错误 fallback、Escape/Tab/return focus、滚动/resize、浅深色和 reduced-motion；截图保存到由 `DYDATA_TOUR_ARTIFACT_DIR` 指定的本地验证产物目录（不入库），未指定时使用 pytest `tmp_path`。
- 检查引导期间网络请求和页面数据快照，确认没有手机号、跟进、删除、导出或筛选/业务值写请求；复跑设计系统 modal 语义断言。

**Evidence**：
- 由 `DYDATA_TOUR_ARTIFACT_DIR` 指定的本地验证产物目录（不入库），未指定时使用 pytest `tmp_path`：按 `light`、`dark`、`reduced-motion` 与 `1440x900`、`768x1024`、`390x844` 组织的真实浏览器截图
- `tests/test_visual_clue_onboarding.py`、`tests/test_frontend_clue_center.py`、`tests/test_design_system_enforcement.py` 的通过输出
- `npm --prefix apps/web run build` 输出与 `git diff --check` 结果
- Linear DYDATA-89 验证记录（由主代理在实现后回填）

**Failure Handling**：
- 真实页面元素、加载状态或详情结果无法定位时，停止该步并进入可见的跳过/完成 fallback；不得通过修改筛选、构造业务数据或静默触发写请求来“修复”引导。
- 若详情为失效/只读轮次，保留状态、脱敏联系方式和历史说明，跳过完整手机号与保存跟进相关步骤；手机号和跟进权限仍以当前页面/后端结果为准。
- 若引导与详情 Dialog 的层级、inert、Escape、Tab 或焦点恢复回归失败，阻塞 Task 并修正 `Dialog.tsx`；不得在 GuidedTour 或页面内复制 modal 语义。
- 若 1440/768/390、浅深色、reduced-motion、浏览器测试、build 或 diff check 任一失败，保留 Task `进行中` 并记录精确失败证据；不宣称实现完成、不部署、不推送。
- 若实现判断需要 API/Schema、财务页面或全局导航重构，停止并提交范围裁决，保持本 T0.1 仅为前端引导增量。

**完成收尾：状态同步**：
- 本 Task 完成实现、验证和 foundation 漂移判断后，把完成事实、验证证据、完成日期、漂移结论和建议下一 Task 提交给 `ai-project-manager`。
- 由 `ai-project-manager` 调度 `delivery-planner` 同步本主计划、任务看板和当前子开发计划三处状态；同步前保持 `进行中`。
- 同步后重新运行 `node .agent/project-manager-suite/tools/route-check.mjs . --target-stage S4 --json`，并确认本专项主计划、看板、子计划一致；未完成状态同步前不得标记 Task 已完成。

**Owner**：AI 执行 -> 人审核

**前置**：Linear DYDATA-89 In Progress；用户已明确授权开发；`collect-upstream-context.mjs` 返回 `canProceed=true`；现有 `ClueCenterPage`、`Dialog`、`Shell`、设计系统、线索前端测试和真实浏览器基线已读取；无 API/Schema/部署变更依赖。

**状态**：进行中

**执行状态更新（2026-09-07）**：实现与本地技术验证已完成，提交 Linear In Review；T0.1 在主计划、看板和本子计划均保持 `进行中`，等待用户验收后同步完成状态与完成日期。

**验证结果**：引导专项 17 passed；线索前端、演示模式、设计系统、用户文案与图标回归 119 passed；既有线索导航、筛选折叠、分页与目录浏览器回归 6 passed。Web build、设计系统 build、`git diff --check` 均通过。完整命令和边界见主计划 §5.1。

**实现收口**：修复了隐藏桌面锚点误选、手机端滚动后仍测量旧坐标、窗口缩放后定位恢复及列表刷新时可能打开旧行的问题。引导不设置表单值或调用业务 API；退出后的手动保存已用真实 FastAPI 路由和合成数据回读验证。

**Foundation 漂移判断**：本任务无 foundation 漂移；没有 API、Schema 或后端业务规则变更。未运行真实 PostgreSQL 或生产环境验证，不涉及部署。

**提交推进（2026-09-07）**：用户要求继续后，功能代码已形成本地提交 `95dff72`。复审未发现阻断问题；治理套包 122 项测试及协议对齐通过。完整 `python -m pytest -q` 为 2418 passed / 129 skipped，退出码 0；本地未配置专用 PostgreSQL 测试库，相关集成用例按环境条件跳过。完整证据见主计划 §5.2，PR 与 CI 最新证据以 Linear DYDATA-89 为准。保留 In Review 与三处 `进行中` 状态，不把继续推进解释为生产部署或最终验收。

**下一步**：用户检查本地七步文案、聚焦位置和移动端效果；验收通过后由主代理同步 Task 与 Linear 完成状态。当前没有下一开发 Task。
