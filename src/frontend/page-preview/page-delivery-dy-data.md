# 页面交付清单 - 抖音经营数据引擎（门店结算）

> 生成时间: 2026-07-17 14:42（回环 #1 更新）
> Skill: page-designer
> 技术栈: 生产工程为 React 19 + TypeScript + Vite；本轮已确认页面基线为原生 HTML/CSS/JavaScript 单文件交互原型

## 上游依赖

- BRD 文件: C:/Users/86138/Documents/抖音来客看板/docs/brd/BRD-dy-data-20260716-1255.md
- 需求来源: Linear DYDATA-23（四页视觉规范已确认），并作为 DYDATA-33 的生产集成基线

## 工程目录

- 前端工程: C:/Users/86138/Documents/抖音来客看板/apps/web
- 已确认交互原型: C:/Users/86138/Documents/抖音来客看板/docs/commission-dashboard-navigation-mock.html

## 本地预览

- 启动命令: 在 `C:/Users/86138/Documents/抖音来客看板` 执行 `python -m http.server 4174 --bind 127.0.0.1`
- 访问地址: http://127.0.0.1:4174/docs/commission-dashboard-navigation-mock.html#/ranking
- mock 说明: 四页的指标、门店、订单与费用均为视觉评审 Mock，不连接生产 API 或数据库；原型用于确认信息架构、交互状态、响应式表现与生产实现目标，不代表正式结算数据。

## 交付产物

| 页面 | 路由 | 文件路径 | 状态 |
|------|------|---------|------|
| 全国门店榜单 | `#/ranking` | C:/Users/86138/Documents/抖音来客看板/docs/commission-dashboard-navigation-mock.html | 已确认、浏览器复核通过 |
| 单店分账 | `#/store` | C:/Users/86138/Documents/抖音来客看板/docs/commission-dashboard-navigation-mock.html | 已确认、浏览器复核通过 |
| 订单费用明细 | `#/orders` | C:/Users/86138/Documents/抖音来客看板/docs/commission-dashboard-navigation-mock.html | 已确认、浏览器复核通过 |
| 开票确认 | `#/invoice` | C:/Users/86138/Documents/抖音来客看板/docs/commission-dashboard-navigation-mock.html | 已确认、浏览器复核通过 |

## 生产实现目标

| 页面 | 目标文件 | 当前说明 |
|------|---------|---------|
| 全国门店榜单 | C:/Users/86138/Documents/抖音来客看板/apps/web/src/pages/StoreRankingPage.tsx | 在 DYDATA-33 中按本基线集成生产数据 |
| 单店分账 | C:/Users/86138/Documents/抖音来客看板/apps/web/src/pages/StoreSettlementPage.tsx | 在 DYDATA-33 中按本基线集成生产数据 |
| 订单费用明细 | C:/Users/86138/Documents/抖音来客看板/apps/web/src/pages/OrderDetailsPage.tsx | 在 DYDATA-33 中补齐费用上下文与双费用视图 |
| 开票确认 | C:/Users/86138/Documents/抖音来客看板/apps/web/src/pages/InvoiceGuidePage.tsx | 在 DYDATA-33 中新增引导页，不接发票 API |

## 设计系统

- 路径: C:/Users/86138/Documents/抖音来客看板/docs/design-system/tokens.json
- 说明: 宿主项目已将 `docs/design-system/tokens.json` 定义为唯一视觉事实源；本交付不另建重复 `MASTER.md`。
- 风格: Data-Dense Dashboard / V0.2 运营后台 / 浅色模式 / 品牌橙强调
- 参考截图: 无新增外部截图；沿用 DYDATA-23 已确认原型

## 运行验证记录

- 工具: Codex 内置浏览器自动化（真实 Chromium 页面）
- 全国门店榜单: 日期范围切换为“累计”后，标题、累计口径说明和门店数量徽标联动更新。
- 单店分账: “查看订单”链接携带月份、门店、产品范围、商品类型、费用方向、比例、规则版本与工作台焦点上下文。
- 订单费用明细: 下钻上下文可恢复；“推广费订单明细 / 管理服务费订单明细”切换后标题、比例与订单行同步变化。
- 开票确认: 展示 5 个流程节点，明确“当前功能暂未开放”，并补充前置条件、材料、预计开票范围、支持渠道和 FAQ。
- 响应式: `390 / 768 / 1440` 三档宽度下，四个路由均无 document 级横向溢出；已采集 390px 榜单页与 1440px 开票页运行态截图证据。

## 回环修正记录

- 回环 #1 已按 DYDATA-31 将管理服务费说明从“所有抖音渠道”修正为“直播、短视频渠道有效商品订单”；生产实现仍需同时落实渠道、商品状态和归属账号过滤。
- 回环 #1 已按 DYDATA-33 在 5 节点流程下补充开票准备指引；未确认的发票抬头、税号、类目、税率、接收方式与正式支持入口均明确标记待财务通知，不虚构在线开票能力。
- 修正后使用缓存隔离地址重新加载真实页面，相关文案与 5 类引导模块均可见；`390 / 768 / 1440` 下单店分账和开票页仍无 document 级横向溢出。

## 下游可消费信息

| 下游 Skill | 建议读取 | 用途 |
|-----------|---------|------|
| page-explainer | 本清单（含本地预览段）+ 已确认交互原型 | 沉淀交互语义、识别最新需求口径差异 |
| foundation-builder | 本清单中的页面路由表 + 生产实现目标 | 反推数据模型与 API |
| prd-writer | 本清单 + Linear DYDATA-21/30/31/33 | 基于已确认页面与最新需求反推 PRD |
