# T1.2 门店端财务只读 UAT 预览子交付计划

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-81-store-finance.md](main-delivery-plan-dydata-81-store-finance.md)
- 任务看板：[task-kanban-dydata-81-store-finance.md](task-kanban-dydata-81-store-finance.md)
- 可执行实现计划：[2026-08-30 DYDATA-81 门店端财务只读 UAT 预览实施计划](../../superpowers/plans/2026-08-30-dydata-81-store-finance-uat-preview.md)

#### T1.2 实现隔离的门店端财务只读 UAT 预览

**Requirement ID**：DYDATA-81-UAT-PREVIEW

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` 中门店端页面、权限和响应式全局规则。
- `docs/prd/subprd/02-subprd-store-settlement.md` 门店结算结构与状态章节。
- `docs/prd/subprd/04-subprd-invoice-registration.md` 推广开票登记与状态查询章节。
- `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md` 门店账单、推广发票与管理服务费只读字段章节。
- `docs/prd/foundation/foundation-schema-dy-data/billing-invoice.md` 账单、发票、台账字段章节。
- `docs/superpowers/specs/2026-08-29-dydata-81-store-finance-uat-design.md` §1—§9。
- `docs/uat/dydata-81-page-contract-matrix-2026-08-29.md`，以及用户 2026-08-30 对 UAT 方案的“确认按 UAT 方案制作”“开始”。

**核心逻辑**：
- T1.2 只交付独立本地 UAT 入口，采用主系统设计 token 与共享组件的视觉语言，不替换正式 `apps/web` 入口、路由或权限骨架。
- 严格展示四个二级页面和单店分账内费用明细/异议模块的顺序、字段、合法空态、响应式和跨页导航；不使用临时看板的演示金额、账期、状态或提示。
- 所有写动作均禁用且不会发请求；只有未来正式 API 返回推广账单确认成功后，正式实现才可打开真实开票跳转。
- 用户已明确保留 `/finance/*` 全部页面、接口、导航、权限和测试，本 Task 不读取、改动或调用该范围。

**核心文件**：
- `apps/web/uat.html`
- `apps/web/vite.uat.config.ts`
- `apps/web/src/uat/main.tsx`
- `apps/web/src/uat/UatPreviewApp.tsx`
- `apps/web/src/uat/uat-preview.css`
- `apps/web/src/design-tokens.css`
- `apps/web/src/components/Button.tsx`
- `apps/web/src/components/FormControls.tsx`
- `apps/web/src/components/TertiaryNav.tsx`
- `tests/test_frontend_dydata81_uat_preview.py`

**完成标准**：
- 独立 UAT 地址可显示四个二级入口，顺序为：全国门店榜单、单店分账、开票确认、发票状态查看；不再存在独立“订单费用明细”入口或 hash 路由。
- 榜单显示四张确认指标卡和六列空表，并在表格标题右侧提供只含业务指标的“排行依据”；单店分账在桌面保留推广/管理服务费左右确认结构，确认区后固定出现推广费明细/管理费明细页签和账单异议空态，且所有无数据值为“暂无数据”或“尚未生成”。
- 开票确认在两栏上方显示用户确认的开票提醒与非状态化业务时间节奏；不显示固定账期/门店错误条、静态校验规则、推广账单表或左栏账期说明；右栏恰有八个确认字段，390px 单列。
- 发票状态为五张推广服务费指标卡，其中第五张为“待开票金额”；推广记录、管理服务费发票信息、差额台账保留合法空态。
- UAT 源码和网络记录没有 API 写请求、`/finance/*` 请求、`¥0.00`、演示账期、伪造状态或“测试/预览/试运行”业务文案。
- 1440、768、390 三档四页截图及单店分账内嵌模块截图、UAT 专项测试和独立构建均通过；正式页面、真实 API、`/finance/*` 与其测试 diff 为零。

**Verification Method**：
- 先后运行 `python -m pytest tests/test_frontend_dydata81_uat_preview.py -q`。
- 运行 `npm --prefix apps/web exec vite build -- --config vite.uat.config.ts`。
- 使用真实浏览器对四个 UAT hash 路由做 1440、768、390 截图与请求方法检查。
- 运行 `git diff --check` 与受保护路径 `git diff --name-only` 检查。

**Evidence**：
- `docs/uat/dydata-81-page-contract-matrix-2026-08-29.md`
- `output/playwright/dydata-81-uat/`
- `docs/devlog/20260830_dydata-81-readonly-uat-preview.md`
- UAT 专项 pytest 与 Vite 构建退出报告。

**Failure Handling**：
- 若任何页面需要真实金额、日期、状态、确认成功或服务端写入才能完整呈现，保留“暂无数据”“尚未生成”或“待确认”，不造值。
- 若读取或实现触及 `/finance/*`、正式页面、真实 API、权限或现有测试，立即停止该项，保留变更并向 Owner 报告。
- 若合同、PRD、Foundation、正式 API 或用户最新确认相冲突，标记 `BLOCKED`，不自行选择。
- 若 UAT 构建或三档视觉验证失败，不提供 UAT 地址，不推进 T1.1 正式系统实施。

**完成收尾：状态同步**：
- 本 Task 完成实现、验证和 Foundation 漂移判断后，必须把完成事实、验证证据、完成日期、漂移结论和建议下一 Task 提交给 `ai-project-manager`。
- 由 `ai-project-manager` 调度 `delivery-planner` 同步主计划、任务看板和本子计划状态。
- 同步后重新运行 `node .agent/project-manager-suite/skills/05-01-delivery-planner/scripts/check-plan-consistency.mjs docs/plans/delivery-plans/main-delivery-plan-dydata-81-store-finance.md --json`；未获用户逐页验收前，禁止进入 T1.1 或关闭 DYDATA-81。

**Owner**：AI 执行 -> 人审核

**前置**：用户已审阅 UAT 规格并于 2026-08-30 明确“开始”；DYDATA-81 页面合同矩阵已更新；T1.1 正式系统实施处于待开发。

**状态**：已完成（2026-08-30）

**完成记录（2026-08-30）**：UAT 专项 pytest、独立 Vite build、390/768/1440 四页截图、无写请求与受保护范围检查已形成证据；用户随后明确确认最新 UAT 验收通过并授权进入正式系统合并与生产部署。Foundation 漂移：无，T1.2 只实现隔离只读预览，不改变正式 Schema/API。
