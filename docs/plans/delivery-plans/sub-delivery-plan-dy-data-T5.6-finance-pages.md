# T5.6 生产页面与跨页流程

## 任务来源

- 主开发计划：[main-delivery-plan-dy-data.md](main-delivery-plan-dy-data.md)
- 任务看板：[task-kanban-dy-data.md](task-kanban-dy-data.md)

#### T5.6 把已验证页面回环接入生产 API

**Requirement ID**：DYDATA-19-WEB

**PRD 双链·读**：
- `docs/prd/subprd/02-subprd-store-settlement.md` §3
- `docs/prd/subprd/04-subprd-invoice-registration.md` §3
- `docs/prd/subprd/05-subprd-finance-promotion.md` §3
- `docs/prd/subprd/06-subprd-finance-management.md` §3
- `docs/prd/subprd/07-subprd-finance-store-info.md` §3
- `docs/prd/subprd/08-subprd-finance-disputes.md` §3
- `docs/prd/subprd/09-subprd-finance-imports.md` §3
- `src/frontend/page-preview/page-delivery-dy-data.md`

**核心逻辑**：
- 复用现有 Shell、筛选、指标、表格、弹窗、错误态和已通过浏览器验证的原型交互，将 8 条路由接到真实 API。
- 替换旧 `/invoice` 五节点静态流程；页面明确系统只登记和回传状态，不开票、不审核、不发送企业微信。
- 推广费/管理费订单分为两个子页面；所有金额、权限、状态和累计值只消费服务端结果。

**核心文件**：
- `apps/web/src/App.tsx`
- `apps/web/src/components/Shell.tsx`
- `apps/web/src/components/FinanceImportActionPanel.tsx`
- `apps/web/src/pages/StoreInvoicePage.tsx`
- `apps/web/src/pages/FinanceFeePage.tsx`
- `apps/web/src/pages/FinanceOrderDetailsPage.tsx`
- `apps/web/src/pages/FinanceStoresPage.tsx`
- `apps/web/src/pages/FinanceDisputesPage.tsx`
- `apps/web/src/pages/FinanceImportsPage.tsx`
- `apps/web/src/pages/StoreSettlementPage.tsx`
- `apps/web/src/api/client.ts`
- `apps/web/src/types/dashboard.ts`
- `apps/web/src/utils/userFacingLabels.ts`
- `apps/web/src/styles.css`
- `tests/test_design_system_enforcement.py`
- `tests/test_frontend_user_facing_contracts.py`
- `tests/test_visual_smoke.py`

**完成标准**：
- 8 条生产路由覆盖加载、正常、空、错误、无权、冲突和提交后回读；旧五节点文案与静态审核流程彻底移除。
- 门店、管理员和最高管理员菜单/操作与权限矩阵一致；管理员与最高管理员在本模块业务权限相同。
- 390/768/1440 视口下关键表格、筛选、弹窗、错误下载和跨页上下文可用。

**Verification Method**：
- 执行前端契约测试和 `npm --prefix apps/web run build`；用真实 FastAPI 完成两角色主要成功场景及 403/409/422/空态。
- Playwright 逐路由验证并保存最终截图。

**Evidence**：
- `output/playwright/`（8 条路由 × 390/768/1440，共 24 张）。
- `docs/devlog/` 中 T5.6 浏览器矩阵、构建与接口回读记录。

**完成证据（2026-08-21）**：
- 设计系统、设计执行与前端契约：54 passed；财务样式只引用已注册 V0.2 令牌，所有选择控件复用共享可搜索选择器，内部财务枚举统一转为中文安全文案。
- `tests/test_api_store_billing.py`：22 passed；`tests/test_api_finance_imports.py`：5 passed。
- `npm --prefix apps/web run build`：通过；仅保留 545.96 kB chunk 体积提示，不影响功能验收。
- `tests/test_visual_smoke.py -k "finance or invoice"`：30 passed；含 8 路由 × 3 视口、旧 `/invoice` 兼容、真实 FastAPI 管理员空态/门店 403、发票 422 保留输入后回读及导入 409 重试。
- `git diff --check`：通过；仅有工作树既有 LF/CRLF 提示。
- 旧 `InvoiceGuidePage.tsx` 已删除；`/invoice` 仅保留到 `/settlement/invoice` 的兼容跳转，不保留第二套业务页面。
- 推广费页面可逐月选择同一门店一个或多个完整账期，提交 `allocations[]`；待厂端审核状态不允许重复登记。
- Foundation 漂移判断：本任务按当前 Foundation API/Schema 契约消费服务端结果，无新增 Schema、API 或术语漂移。

**Failure Handling**：
- API 缺字段或失败时显示真实错误，不回退 mock 或在前端补算。
- 页面交互超出冻结原型和 PRD 时停止扩张并回到 DYDATA-19 记录决策。
- 路由迁移破坏旧书签时提供兼容跳转，不维护两套业务页面。

**完成收尾：状态同步**：
- 完成实现、验证与 Foundation 漂移判断后，把完成事实、证据、日期、漂移结论和建议下一 Task 提交给 `ai-project-manager`；由其同步主计划、看板和本子计划并重跑 S4 路由检查。三处未同步前不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T5.2～T5.5

**状态**：已完成（2026-08-21；技术验收与页面浏览器门禁通过）
