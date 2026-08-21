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
- `apps/web/src/pages/InvoiceGuidePage.tsx`
- `apps/web/src/pages/StoreSettlementPage.tsx`
- `apps/web/src/api/client.ts`
- `apps/web/src/types/dashboard.ts`
- `apps/web/src/styles.css`
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
- `<projectRoot>/pwScreenShot/dydata-19-*.png`。
- `docs/devlog/` 中 T5.6 浏览器矩阵、构建与接口回读记录。

**Failure Handling**：
- API 缺字段或失败时显示真实错误，不回退 mock 或在前端补算。
- 页面交互超出冻结原型和 PRD 时停止扩张并回到 DYDATA-19 记录决策。
- 路由迁移破坏旧书签时提供兼容跳转，不维护两套业务页面。

**完成收尾：状态同步**：
- 完成实现、验证与 Foundation 漂移判断后，把完成事实、证据、日期、漂移结论和建议下一 Task 提交给 `ai-project-manager`；由其同步主计划、看板和本子计划并重跑 S4 路由检查。三处未同步前不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T5.2～T5.5

**状态**：待审阅
