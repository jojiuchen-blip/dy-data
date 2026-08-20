# 页面交付清单 - dy-data（抖音经营数据引擎）

> 初始交付: 2026-07-19
> DYDATA-19 回环: 2026-08-20，loop 1
> Skill: page-designer
> 技术栈: React 19 + JavaScript + Vite 8 + Solar Icons

## 交付边界

- 本次回环只更新 DYDATA-19 月度账单、发票确认和管理员财务流程原型；生产应用 `apps/web` 未在页面回环阶段修改。
- 原型用于冻结页面结构、跨页行为、业务状态和异常反馈，不连接真实 API、数据库、认证、开票、审核、打款或生产数据。
- Linear DYDATA-19 和 `docs/superpowers/specs/2026-08-20-dydata-19-settlement-finance-design.md` 是业务规则来源；原型合成数据不是财务政策来源。
- 既有 14 个生产页面的 2026-07-19 页面基线保持有效；本清单以本节新增路由为 DYDATA-19 loop 1 增量交付。

## 上游依赖

- BRD: `docs/brd/BRD-dy-data-20260716-1255.md`
- DYDATA-19 设计规格: `docs/superpowers/specs/2026-08-20-dydata-19-settlement-finance-design.md`
- 设计系统: `design-system/dy-data/MASTER.md`
- 回环差距: `src/frontend/page-preview/explainer-b-gap-dy-data.md`
- 页面台账: `src/frontend/page-preview/page-ledger-dy-data.json`

## 工程目录与本地预览

- 原型工程: `docs/prototypes/dydata-19-finance-flow-dashboard`
- 应用入口: `docs/prototypes/dydata-19-finance-flow-dashboard/src/App.jsx`
- 样式入口: `docs/prototypes/dydata-19-finance-flow-dashboard/src/styles.css`
- 启动命令: 在原型工程目录运行 `npm run dev -- --port 4319`
- 访问地址: `http://127.0.0.1:4319/finance/promotion`
- 验证命令: `npm test`、`npm run build`
- mock 边界: 所有写操作均标记为演示动作，只修改当前页面内存状态，刷新后重置。

## DYDATA-19 loop 1 页面路由

| 角色 | 页面 | 路由 | 页面组件 | 本轮状态 |
|---|---|---|---|---|
| 门店 | 月度账单确认 | `/settlement` | `src/pages/StoreBillsPage.jsx` | 已验证 |
| 门店 | 推广费发票登记 | `/settlement/invoice` | `src/pages/StoreInvoicesPage.jsx`、`src/pages/StoreHistoryPage.jsx` | 已验证 |
| 管理员 | 管理员推广服务费 | `/finance/promotion` | `src/pages/FinancePromotionPage.jsx` | 已验证 |
| 管理员 | 管理员管理服务费 | `/finance/management` | `src/pages/FinanceManagementPage.jsx` | 已验证 |
| 管理员 | 管理员推广服务费 | `/finance/orders/promotion` | `src/pages/FinanceOrderDetailsPage.jsx` | 已验证 |
| 管理员 | 管理员管理服务费 | `/finance/orders/management` | `src/pages/FinanceOrderDetailsPage.jsx` | 已验证 |
| 管理员 | 门店基础信息 | `/finance/stores` | `src/pages/FinanceBaseInfoPage.jsx` | 已验证 |
| 管理员 | 账单异议 | `/finance/disputes` | `src/pages/FinanceDisputesPage.jsx` | 已验证 |
| 管理员 | 财务导入 | `/finance/imports` | `src/pages/FinanceImportsPage.jsx` | 已验证 |

以上组件路径均相对于 `docs/prototypes/dydata-19-finance-flow-dashboard/`。

## 页面代码文件

| 页面/入口 | 文件路径 |
|---|---|
| 原型应用入口 | docs/prototypes/dydata-19-finance-flow-dashboard/src/App.jsx |
| 门店月度账单 | docs/prototypes/dydata-19-finance-flow-dashboard/src/pages/StoreBillsPage.jsx |
| 门店发票登记 | docs/prototypes/dydata-19-finance-flow-dashboard/src/pages/StoreInvoicesPage.jsx |
| 门店发票历史 | docs/prototypes/dydata-19-finance-flow-dashboard/src/pages/StoreHistoryPage.jsx |
| 管理员推广服务费 | docs/prototypes/dydata-19-finance-flow-dashboard/src/pages/FinancePromotionPage.jsx |
| 管理员管理服务费 | docs/prototypes/dydata-19-finance-flow-dashboard/src/pages/FinanceManagementPage.jsx |
| 管理员订单明细 | docs/prototypes/dydata-19-finance-flow-dashboard/src/pages/FinanceOrderDetailsPage.jsx |
| 管理员门店信息 | docs/prototypes/dydata-19-finance-flow-dashboard/src/pages/FinanceBaseInfoPage.jsx |
| 管理员异议 | docs/prototypes/dydata-19-finance-flow-dashboard/src/pages/FinanceDisputesPage.jsx |
| 管理员导入记录 | docs/prototypes/dydata-19-finance-flow-dashboard/src/pages/FinanceImportsPage.jsx |
| 导入结果组件 | docs/prototypes/dydata-19-finance-flow-dashboard/src/components/ImportTemplatePanel.jsx |
| 指标口径组件 | docs/prototypes/dydata-19-finance-flow-dashboard/src/components/MetricScopeToggle.jsx |

## 本轮冻结的页面行为

- 使用 History API 表达稳定深链；角色、侧栏和订单穿透会更新 URL，浏览器返回可恢复页面。
- 推广费与管理服务费页面默认单月；可切换累计。已确认金额始终只显示单月，累计明确从 2026 年 8 月起且不含 7 月演示数据。
- 推广费状态为“待开票 → 提交成功，待厂端审核 → 审核通过，已结算 / 审核不通过，请重新上传”。
- 页面明确标注：审核发生在系统外，管理员只导入已完成结果，系统内不创建待审核任务。
- 管理服务费只显示“待开票 / 已开票”，不复用推广费审核状态。
- 四类导入共用首次成功、无变化、差异待确认、整批失败和版本冲突反馈；错误态展示错误行摘要、分页和“下载全部错误”，冲突态展示读取版本、当前版本、最近操作人/时间和刷新动作。
- 管理员财务角色沿用现有管理员权限模型；页面不新增“财务”独立角色。

## 浏览器验收证据

- 真实浏览器: Playwright CLI，Chromium，桌面视口 `1440 × 1024`。
- 深链: `/finance/promotion` 可直接打开；点击管理服务费后 URL 更新为 `/finance/management`。
- 交互: 已操作累计口径、完整推广费状态筛选、管理服务费导入、整批失败与版本冲突场景。
- 浏览器控制台: 0 errors，0 warnings。
- 自动化: 74/74 tests passed；Vite production build passed。
- 截图:
  - `src/frontend/page-preview/screenshots/dydata-19-loop1-promotion-cumulative.png`
  - `src/frontend/page-preview/screenshots/dydata-19-loop1-import-failed.png`
  - `src/frontend/page-preview/screenshots/dydata-19-loop1-management-final.png`

## 当前边界与非承诺

- 原型中的累计倍数用于展示口径切换，不是生产金额算法；生产实现必须使用后端冻结结果和规格公式。
- 原型不保存原始导入文件，不实现真实并发、事务、幂等、版本表或错误文件流式生成；只冻结用户可见反馈。
- 页面回环不等于生产代码已完成。进入开发前仍需完成规格冻结、技术方案、任务拆分和开发门禁。

## 下游可消费信息

| 下游 | 读取内容 | 用途 |
|---|---|---|
| page-explainer | 路由表、页面行为、浏览器证据与回环差距 | 复查 GAP-P3-03 至 GAP-P3-06 并冻结交互语义 |
| prd-chief / prd-writer | 页面路由、状态、指标口径和异常反馈 | 冻结规格正文 |
| foundation-builder | 路由、页面状态、版本冲突和导入反馈 | 设计数据模型、API、任务与审计结构 |
| planner | 验收证据和非承诺边界 | 拆分可独立验证的开发任务 |
