# 页面交付清单 - dy-data（抖音经营数据引擎）

> 生成时间: 2026-07-19 16:32 +08:00  
> Skill: page-designer  
> 技术栈: React 19 + TypeScript + Vite 7 + Solar Icons

## 交付边界

- 本次交付覆盖当前项目已有的 14 个页面组件，以现有运行页面为准，不新建第二套预览工程，不重设计无关业务页面。
- `docs/design-system/tokens.json` 是 V0.2 唯一规范源；`apps/web/src/design-tokens.css` 是运行时实现。
- 页面交付用于建立可运行页面索引和浏览器验收基线，不能替代线索中心 BRD、PAGE_EXPLAINER、FOUNDATION 或 PRD。
- 线索中心是本轮重点验证对象；其余页面确认当前可运行状态和 V0.2 基线，不扩展需求范围。

## 上游依赖

- BRD 文件: `C:\Own Docm\Coding\抖音结算中心\dy-data\docs\brd\BRD-dy-data-20260716-1255.md`
- V0.2 规范: `C:\Own Docm\Coding\抖音结算中心\dy-data\docs\design-system\tokens.json`
- V0.2 可视化规范: `C:\Own Docm\Coding\抖音结算中心\dy-data\docs\design-system\index.html`

## 工程目录

- 前端工程: `C:\Own Docm\Coding\抖音结算中心\dy-data\apps\web`
- 应用入口: `C:\Own Docm\Coding\抖音结算中心\dy-data\apps\web\src\App.tsx`
- 运行时 token: `C:\Own Docm\Coding\抖音结算中心\dy-data\apps\web\src\design-tokens.css`

## 本地预览

- 演示模式启动命令: `Set-Location -LiteralPath 'C:\Own Docm\Coding\抖音结算中心\dy-data\apps\web'; npm run dev:demo -- --port 4175 --strictPort`
- 演示模式访问地址: `http://127.0.0.1:4175/`
- 未登录认证页启动命令: `Set-Location -LiteralPath 'C:\Own Docm\Coding\抖音结算中心\dy-data\apps\web'; npm run dev -- --port 4176 --strictPort`
- 未登录认证页访问地址: `http://127.0.0.1:4176/login`
- mock 说明: 演示模式使用前端合成数据，不写数据库；线索中心当前包含 530 条合成线索，操作只在当前浏览器会话生效，刷新后重置。认证页在非 demo 模式且没有有效会话时展示。

## 交付产物

| 页面 | 路由 | 文件路径 | 状态 |
|------|------|---------|------|
| 产品入口 | `/`、`/login`（已有会话） | `C:\Own Docm\Coding\抖音结算中心\dy-data\apps\web\src\pages\HomePage.tsx` | 已在桌面与 390px 视口验证 |
| 认证页 | `/login`、`/auth/reset-password`、`/auth/activate`（未登录） | `C:\Own Docm\Coding\抖音结算中心\dy-data\apps\web\src\pages\AuthPage.tsx` | 三种模式已验证 |
| 门店榜单 | `/ranking` | `C:\Own Docm\Coding\抖音结算中心\dy-data\apps\web\src\pages\StoreRankingPage.tsx` | 已在桌面与 390px 视口验证 |
| 单店分账 | `/settlement` | `C:\Own Docm\Coding\抖音结算中心\dy-data\apps\web\src\pages\StoreSettlementPage.tsx` | 已在桌面与 390px 视口验证 |
| 线索中心 | `/clues`、`/clues/details` | `C:\Own Docm\Coding\抖音结算中心\dy-data\apps\web\src\pages\ClueCenterPage.tsx` | 重点页；看板、530 条明细及移动卡片已验证 |
| 订单明细 | `/details` | `C:\Own Docm\Coding\抖音结算中心\dy-data\apps\web\src\pages\OrderDetailsPage.tsx` | 已在桌面与 390px 视口验证 |
| 核销表现 | `/sales` | `C:\Own Docm\Coding\抖音结算中心\dy-data\apps\web\src\pages\SalesDashboardPage.tsx` | 已在桌面与 390px 视口验证 |
| 后台首页 | `/admin` | `C:\Own Docm\Coding\抖音结算中心\dy-data\apps\web\src\pages\AdminHomePage.tsx` | 已在桌面与 390px 视口验证 |
| 账号管理 | `/admin/accounts` | `C:\Own Docm\Coding\抖音结算中心\dy-data\apps\web\src\pages\AdminAccountsPage.tsx` | 已在桌面与 390px 视口验证 |
| 商品分账规则 | `/admin/rules`、`/rule-admin` | `C:\Own Docm\Coding\抖音结算中心\dy-data\apps\web\src\pages\AdminSkuRulesPage.tsx` | 主路由已在桌面与 390px 视口验证 |
| 数据同步 | `/admin/sync`、`/sync-admin` | `C:\Own Docm\Coding\抖音结算中心\dy-data\apps\web\src\pages\AdminSyncPage.tsx` | 主路由已在桌面与 390px 视口验证 |
| 线索分配后台 | `/admin/clue-allocation/rules`、`/trial`、`/records`、`/headquarters` | `C:\Own Docm\Coding\抖音结算中心\dy-data\apps\web\src\pages\AdminClueAllocationPage.tsx` | 四个子视图均已在桌面与 390px 视口验证 |
| 用户建议 | `/admin/feedback` | `C:\Own Docm\Coding\抖音结算中心\dy-data\apps\web\src\pages\AdminFeedbackPage.tsx` | 已在桌面与 390px 视口验证 |
| 商品口径控制 | `/admin/product-types` | `C:\Own Docm\Coding\抖音结算中心\dy-data\apps\web\src\pages\AdminProductTypeVisibilityPage.tsx` | 已在桌面与 390px 视口验证 |

## 设计系统

- 页面交付索引: `C:\Own Docm\Coding\抖音结算中心\dy-data\design-system\dy-data\MASTER.md`
- 正式规范源: `C:\Own Docm\Coding\抖音结算中心\dy-data\docs\design-system\tokens.json`
- 风格: V0.2 浅色、高密度运营工作台、克制层级、表格与筛选优先
- 图标: `@iconify/react` + `@iconify-icons/solar`
- 参考截图: 有；见 `C:\Own Docm\Coding\抖音结算中心\dy-data\src\frontend\page-preview\screenshots`

## 浏览器验收证据

- 桌面视口 `1440 x 900`: 17 个有效运行路由逐页打开，均渲染唯一 `h1`，页面根节点无横向溢出。
- 移动视口 `390 x 844`: 同一批 17 个路由逐页打开，页面根节点无横向溢出。
- 认证页: 登录、重置密码、账号激活三种模式均渲染表单和对应标题。
- 线索中心截图:
  - `C:\Own Docm\Coding\抖音结算中心\dy-data\src\frontend\page-preview\screenshots\clue-dashboard-desktop.png`
  - `C:\Own Docm\Coding\抖音结算中心\dy-data\src\frontend\page-preview\screenshots\clue-details-desktop.png`
  - `C:\Own Docm\Coding\抖音结算中心\dy-data\src\frontend\page-preview\screenshots\clue-details-mobile.png`

## 当前边界与非承诺

- 本清单确认页面可运行和当前响应式边界，不把 V0.2 中标记为 `future-DYDATA-5-not-runtime-active` 的移动端样例写成已完成产品承诺。
- 演示数据不用于证明生产接口、数据库写入、权限矩阵或分配业务逻辑已经满足新 BRD。
- 后续 `page-explainer` 必须逐页沉淀角色、数据权限、交互语义、异常态和业务规则；线索中心还必须通过 DYDATA-36 形成专项 BRD V1.0。

## 下游可消费信息

| 下游 Skill | 建议读取 | 用途 |
|-----------|---------|------|
| page-explainer | 本清单、本地预览地址、14 个页面文件 | 沉淀页面交互语义和现状边界 |
| brd-writer | 本清单中的线索中心现状及非承诺边界 | 形成 DYDATA-36 线索中心 BRD V1.0 |
| foundation-builder | 路由表、页面文件和 V0.2 权威源 | 反推数据模型、API、权限和状态机 |
| prd-writer | 本清单与后续专项 BRD/PAGE_EXPLAINER | 形成可验收功能规格 |
