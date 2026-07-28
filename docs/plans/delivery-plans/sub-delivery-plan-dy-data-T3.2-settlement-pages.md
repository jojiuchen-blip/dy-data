# T3.2 四个门店结算生产页面

## 任务来源

- 主开发计划：[main-delivery-plan-dy-data.md](main-delivery-plan-dy-data.md)
- 任务看板：[task-kanban-dy-data.md](task-kanban-dy-data.md)

#### T3.2 将 DYDATA-23 设计基线接入真实双费用 API

**Requirement ID**：DYDATA-33-WEB

**PRD 双链·读**：
- `docs/prd/subprd/01-subprd-store-ranking.md` §2-§6
- `docs/prd/subprd/02-subprd-store-settlement.md` §2-§8
- `docs/prd/subprd/03-subprd-order-fee-details.md` §2-§8（按章节读取）
- `docs/prd/subprd/04-subprd-invoice-guide.md` §2-§7
- `src/frontend/page-preview/explainer-b-interaction-dy-data.md` 的 9 条 locked 语义
- Linear DYDATA-33；DYDATA-23 只作已完成设计证据

**核心逻辑**：
- 榜单实现月度/正式累计、两级产品、门店搜索、排序、七项 totals 和权限模式。
- 单店页实现授权门店、五卡、双方向汇总、多费率/版本与账单/预览下钻。
- 订单页使用新 `/order-fee-details`，恢复服务端规范化上下文、互斥费用方向、筛选、调整展开、分页和同口径导出。
- 新增只读开票指引，无业务 API/写按钮。当前 history 路由 `/ranking`、`/settlement`、`/details` 映射 PRD 的 `#/ranking/#/store/#/orders` 语义，并新增 `/invoice`；旧内部链接需兼容或重定向。

**核心文件**：
- `apps/web/src/App.tsx`
- `apps/web/src/api/client.ts`
- `apps/web/src/types/dashboard.ts`
- `apps/web/src/pages/StoreRankingPage.tsx`
- `apps/web/src/pages/StoreSettlementPage.tsx`
- `apps/web/src/pages/OrderDetailsPage.tsx`
- `apps/web/src/components/`
- `tests/test_frontend_settlement_privacy.py`
- `tests/test_frontend_user_facing_contracts.py`
- `tests/test_visual_smoke.py`

**完成标准**：
- 四页使用真实 camelCase API；Mock 仅在 `VITE_USE_MOCKS=true` 启用，真实错误不静默回退。
- 加载、空、错误、无权限和正常状态齐全；页面不重算费用、排名、退款、权限或账单状态。
- 下钻参数可逆且只作上下文；多费率不显示平均值；导出空结果禁用并能处理 403/409/422。
- 开票页持续显示暂未开放、五节点、准备材料、推广费范围、7 月排除、管理费排除和待财务确认，不出现写操作。
- 390/768/1440 无 document 级横向溢出，表格区域可横向滚动且全部指标可访问。

**Verification Method**：
- 执行 `npm --prefix apps/web run build` 及相关 pytest 前端契约/视觉测试。
- 连接真实本地 API，以至少两种角色验证成功、空态、权限失败、上下文过期与导出；用 Playwright 检查四页和三档视口。

**Evidence**：
- `<projectRoot>/pwScreenShot/dy-data-ranking-1440.png`、`dy-data-store-1440.png`、`dy-data-orders-1440.png`、`dy-data-invoice-1440.png` 及 390/768 关键截图。
- `docs/devlog/` 联调与构建记录。

**Failure Handling**：
- API 字段与 Foundation 不一致时阻断页面补算，先修复契约或登记漂移。
- 路由映射破坏既有书签/内部链接时保留兼容跳转，不同时维护两套页面逻辑。
- 未确认财务信息保持“待财务确认/待上线通知”，不得填示例真值。

**完成收尾：状态同步**：
- 完成实现、验证和 foundation 漂移判断后，将完成事实、证据、日期、漂移结论和建议下一 Task 提交给 `ai-project-manager`，由其调度 `delivery-planner` 同步主计划、看板和本子计划；未完成三处同步不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T3.1

**完成记录**：前端契约 65 passed、API dashboard 17 passed、浏览器/视觉 102 passed（包含真实 FastAPI 两角色、空态、403、422 requestId、409 导出），`npm --prefix apps/web run build` 通过；390/768/1440 截图已复核；独立代码复审 Critical/Important/Minor 均为 0；Foundation 无漂移。

**状态**：已完成（2026-07-21）
