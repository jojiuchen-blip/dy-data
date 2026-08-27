# DYDATA-80 页面结构与业务交互验收基线 v2-clean

## 定位

本文件冻结财务看板的页面结构与业务交互验收面。历史原型仍保留在 `docs/prototypes/dydata-19-finance-flow-dashboard/`，但不再把会议演示控件、原型边界提示或场景切换器作为产品界面的一部分。

本文件不另建视觉规范。颜色、字体、间距、圆角、阴影、导航、表格、状态和交互组件统一继承主系统 V0.2：规范权威为 `docs/design-system/tokens.json` 与 `docs/design-system/README.md`，运行时以 `apps/web/src/design-tokens.css` 及主系统共享组件为准。验收时以页面结构、信息层级、角色上下文和业务动作命名为准，不以历史原型中的私有样式或演示文案为准。

## 保留的验收面

| 范围 | 路由 | 验收重点 |
| --- | --- | --- |
| 门店账单 | `/settlement` | 月度账期、推广费/管理费双方向、确认与异议入口 |
| 门店开票 | `/settlement/invoice` | 发票信息登记、校验结果、提交状态 |
| 推广服务费 | `/finance/promotion` | 财务指标、筛选、导入结果、订单明细入口 |
| 管理服务费 | `/finance/management` | 管理服务费结果导入与审核状态 |
| 订单明细 | `/finance/orders/promotion`、`/finance/orders/management` | 双费用方向拆分与导出 |
| 门店基础信息 | `/finance/stores` | SAP / 门店信息导入与覆盖关系 |
| 账单异议 | `/finance/disputes` | 异议处理结果与账单版本关系 |
| 导入记录 | `/finance/imports` | 批次、校验、覆盖和操作审计 |

## 明确移除

- 页面顶部 `DYDATA-19 · Mock` 版本标记。
- “需求讨论原型 / 非生产能力”可见边界横幅。
- “会议演示 / F01—F10 验收场景”选择器及跳转按钮。
- “门店端 / 财务端”角色切换演示控件；当前角色仅作为页面上下文展示。
- “演示动作”“模拟导入成功”“演示数据”等产品界面文案。
- 未被业务页面引用的 `ScenarioSwitcher` 与 `ImportDialog` 组件。

## 验收方式

1. 先在清理版原型逐个打开上表路由，确认页面结构、信息层级和业务动作命名；再在 `apps/web` 对照同一路由完成生产实现追踪。
2. 页面可见文本不得出现 `Mock`、`会议演示`、`演示动作`、`演示数据` 或“原型边界”等演示专用内容。
3. 页面必须保留正式的角色上下文、V0.2 主题切换、筛选、导入、异议和导出动作；正式写操作必须接入真实 API，未开放能力必须明确只读或不可操作。
4. 生产页面只能复用 V0.2 token 与共享组件，不得复制原型私有颜色、字体、间距、圆角、阴影、导航、表格或状态样式。
5. 原型只验证页面结构与业务交互基线，不把它视为真实 API、数据库、权限、结算能力或生产视觉实现的证据。

## 证据记录

- 原型测试：`npm test -- --reporter=dot --maxWorkers=1 --no-file-parallelism`
- 原型构建：`npm run build`
- 浏览器检查：访问 `/finance/promotion`，确认演示控件不存在，财务角色上下文存在。
- 历史基线来源：`docs/prototypes/dydata-19-finance-flow-dashboard/`；其非生产约束继续由该目录的 `AGENTS.md` 管理。
