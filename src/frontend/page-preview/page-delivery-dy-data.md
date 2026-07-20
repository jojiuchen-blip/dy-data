# 页面交付清单 - dy-data（DYDATA-32 账号权限配置）

> 生成时间: 2026-07-20
> Skill: page-designer
> 技术栈: React 19 + TypeScript + Vite 7；现有 V0.2 浅色设计系统
> 本轮范围: page-designer 第 1 轮回环；在 `/admin/accounts?preview=dydata32` 提供隔离交互预览，补齐并关闭 11 项页面差距
> 用户确认: 2026-07-20

## 上游依赖

- BRD 文件: `C:\Users\86138\Documents\抖音来客看板-dydata-32-rules\docs\brd\BRD-dy-data-20260716-1255.md`
- 需求规则: `C:\Users\86138\Documents\抖音来客看板-dydata-32-rules\docs\rules\account-access-control.md`
- Linear issue: `DYDATA-32`

## 工程目录

- 前端工程: `C:\Users\86138\Documents\抖音来客看板-dydata-32-rules\apps\web`
- 路由入口: `C:\Users\86138\Documents\抖音来客看板-dydata-32-rules\apps\web\src\App.tsx`
- 导航入口: `C:\Users\86138\Documents\抖音来客看板-dydata-32-rules\apps\web\src\components\Shell.tsx`

## 本地预览

- API 启动命令: 在仓库根目录配置本地测试数据库和测试最高管理员后，运行 `python -m uvicorn dy_api.main:app --app-dir apps/api --host 127.0.0.1 --port 8000`
- Web 启动命令: 在仓库根目录配置 `VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1` 后，运行 `npm --prefix apps/web run dev -- --port 5173`
- 现状地址: `http://127.0.0.1:5173/admin/accounts`
- 回环预览地址: `http://127.0.0.1:5173/admin/accounts?preview=dydata32`
- 数据说明: 运行验证使用独立临时 SQLite 数据库和本地测试最高管理员；预览组件使用前端演示数据，交互只写浏览器内存，不调用账号保存 API，不写入生产数据。
- 验证结果: 前端生产构建通过；1280px 视口下整页无水平溢出，角色 × 页面矩阵在自身区域滚动；账号列表、角色权限、默认变更确认、单账号例外、门店范围、最高管理员治理、变更记录和自助激活说明均已通过 DOM 与交互检查。

## 交付产物

| 页面 | 路由 | 文件路径 | 状态 |
|---|---|---|---|
| 账号管理 | `/admin/accounts` | `C:\Users\86138\Documents\抖音来客看板-dydata-32-rules\apps\web\src\pages\AdminAccountsPage.tsx` | 现有运行页面已确认，作为 DYDATA-32 设计基线 |
| 账号权限交互预览 | `/admin/accounts?preview=dydata32` | `C:\Users\86138\Documents\抖音来客看板-dydata-32-rules\apps\web\src\pages\AdminAccountsDydata32PreviewPage.tsx` | 第 1 轮回环已实现、验证并获用户确认 |

## 第 1 轮回环覆盖

| page-explainer 差距 | 预览中的处理 |
|---|---|
| GAP-001 | 统一为最高管理员、管理员、门店账号三角色 |
| GAP-002 | 固定“账号列表 / 角色权限”两个页签；角色纵向、已登记页面横向 |
| GAP-003 | 展示角色默认、额外允许、额外禁止、最终有效权限和单账号恢复默认 |
| GAP-004 | 保存默认权限前展示继承账号、自定义账号影响和可选重置项 |
| GAP-005 | 以页面头部入口打开变更记录，不增加第三页签；支持筛选，不提供导出 |
| GAP-006 | 显式区分全部门店与指定门店，并呈现角色约束和至少选择 1 家门店规则 |
| GAP-007 | 区分当前与其他最高管理员，呈现创建、重置密码、失效、自失效禁用和不直接降级规则 |
| GAP-008 | 明确后台手工新建与双 ID 自助激活是两条路径，自助激活自动绑定唯一门店 |
| GAP-009 | 保留现有已激活账号列表、右侧新建/编辑账号窗口、密码重置窗口、未激活门店查询与列表；权限能力只做叠加，不替换现有模块 |
| GAP-010 | 将已激活账号与未激活门店合并到同一个账号列表板块，通过带数量的内部页签切换；右侧新建/编辑窗口保持不变 |
| GAP-011 | 账号列表的“编辑 / 页面权限”会选中对应账号、平滑跳转到下方账号配置区，并以聚焦边框和状态提示明确反馈 |

## 现有模块保留校正

用户于 2026-07-20 检查第 1 轮预览后指出：DYDATA-32 是在现有账号管理页上增加权限配置，不能删除或用说明块替代现有账号模块。本轮已按真实 `/admin/accounts` 页面重新对齐：

- 已激活账号列表继续展示账号名、所属账户编号、角色、状态、门店范围、激活状态、更新时间以及编辑、重置密码等操作；新增“页面权限”入口只作为叠加列和操作。
- 右侧继续保留新建/编辑账号窗口；角色调整为目标三角色，门店范围规则叠加到原表单中。
- 重置密码继续使用独立确认窗口，不记录密码内容。
- 未激活门店继续提供查询、重置和表格结果；双 ID 自助激活说明放在列表下方，不替代列表。
- 已激活账号与未激活门店不再上下重复占用两个大板块；左侧列表卡片通过“已激活账号 / 未激活门店”内部页签切换，切换后替换筛选条件、表头和说明，右侧新建/编辑账号窗口始终保留。
- 浏览器交互验证：编辑账号、新建账号复位、密码重置窗口、POI ID 筛选、门店账号至少选择 1 家门店均可操作；1280px 下整页无水平溢出。
- 账号列表跳转验证：点击“编辑”后页面从顶部滚动到 `scrollY=1113`，账号配置区停在顶栏下方 `82px` 并获得焦点；“页面权限”入口使用同一跳转，提示文本包含所选账号名称。

## 当前页面模块

| 模块 | 当前运行页面事实 |
|---|---|
| 账号列表 | 展示账号名、所属账户编号、角色、状态、门店范围、激活状态、更新时间和操作 |
| 新建账号 | 支持账号名、显示名称、所属账户编号、角色、状态、门店权限、密码和确认密码 |
| 未激活门店 | 支持按所属账户编号或门店位置编号（POI ID）查询 |
| 当前角色选项 | 门店账号、全局查看、最高管理员 |
| 尚未出现的 DYDATA-32 目标入口 | “角色权限”页签、角色 × 页面权限矩阵、单账号差异权限入口、权限变更记录入口 |

## DYDATA-32 页面登记参考

本表只用于后续权限矩阵登记，不表示本轮重新设计或确认这些业务页面。

| 编号 | 页面 | 路由或别名 | 当前文件 |
|---|---|---|---|
| A01 | 线索看板 | `/clues` | `apps/web/src/pages/ClueCenterPage.tsx` |
| A02 | 线索明细 | `/clues/details` | `apps/web/src/pages/ClueCenterPage.tsx` |
| B01 | 全国门店榜单 | `/ranking` | `apps/web/src/pages/StoreRankingPage.tsx` |
| B02 | 单店结算 | `/settlement` | `apps/web/src/pages/StoreSettlementPage.tsx` |
| B03 | 订单费用明细 | `/details` | `apps/web/src/pages/OrderDetailsPage.tsx` |
| C01 | 核销表现 | `/sales` | `apps/web/src/pages/SalesDashboardPage.tsx` |
| D01 | 后台首页 | `/admin` | `apps/web/src/pages/AdminHomePage.tsx` |
| D02 | 账号管理 | `/admin/accounts` | `apps/web/src/pages/AdminAccountsPage.tsx` |
| D03 | 分佣规则 | `/admin/rules`、`/rule-admin` | `apps/web/src/pages/AdminSkuRulesPage.tsx` |
| D04 | 商品口径 | `/admin/product-types` | `apps/web/src/pages/AdminProductTypeVisibilityPage.tsx` |
| D05 | 线索分配规则 | `/admin/clue-allocation`、`/admin/clue-allocation/rules` | `apps/web/src/pages/AdminClueAllocationPage.tsx` |
| D06 | 分配试运行 | `/admin/clue-allocation/trial` | `apps/web/src/pages/AdminClueAllocationPage.tsx` |
| D07 | 分配记录 | `/admin/clue-allocation/records` | `apps/web/src/pages/AdminClueAllocationPage.tsx` |
| D08 | 总部线索池 | `/admin/clue-allocation/headquarters` | `apps/web/src/pages/AdminClueAllocationPage.tsx` |
| D09 | 用户建议 | `/admin/feedback` | `apps/web/src/pages/AdminFeedbackPage.tsx` |
| D10 | 数据同步 | `/admin/sync`、`/sync-admin` | `apps/web/src/pages/AdminSyncPage.tsx` |

## 设计系统

- 当前运行时权威规范: `C:\Users\86138\Documents\抖音来客看板-dydata-32-rules\docs\design-system\tokens.json`
- 当前运行时样式入口: `C:\Users\86138\Documents\抖音来客看板-dydata-32-rules\apps\web\src\design-tokens.css`
- page-designer 检索记录: `C:\Users\86138\Documents\抖音来客看板-dydata-32-rules\design-system\dy-data\MASTER.md`
- 风格: 沿用 V0.2 `runtime-active` 浅色运营后台规范；不新增暗色模式，不覆盖现有品牌与组件规则。
- 参考截图: 无；用户已确认按现有系统页面继续。

## 下游可消费信息

| 下游 Skill | 建议读取 | 用途 |
|---|---|---|
| page-explainer | 本清单、`AdminAccountsPage.tsx` 和真实运行页面 | 沉淀现状流程与交互语义，识别 DYDATA-32 目标差距 |
| foundation-builder | 本清单的账号管理页面、页面登记参考和规则文档 | 设计角色、页面目录、门店范围、差异权限和审计的 Schema/API |
| prd-writer | 本清单、规则文档和 foundation 产物 | 形成可开发、可验收的 DYDATA-32 功能规格 |
