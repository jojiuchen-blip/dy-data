# Page-Explainer 交付清单 - 抖音经营数据引擎（门店结算）

> 生成时间: 2026-07-17 14:42
> Skill: page-explainer

## 产物索引

| 产物 | 文件路径 | 存在 |
|------|---------|:---:|
| 用户流程图 | C:/Users/86138/Documents/抖音来客看板/src/frontend/page-preview/explainer-flow-dy-data.md | ✓ |
| 交互描述 | C:/Users/86138/Documents/抖音来客看板/src/frontend/page-preview/explainer-b-interaction-dy-data.md | ✓ |
| 差异文件 | C:/Users/86138/Documents/抖音来客看板/src/frontend/page-preview/explainer-b-gap-dy-data.md | ✓ |

> ✓ = 文件存在且内容合格；差异文件中的两个条目已在回环 #1 关闭。

## 语义条目冻结统计

| 文件 | locked | open | 冻结率 |
|------|:---:|:---:|:---:|
| explainer-b-interaction-dy-data.md | 9 | 0 | 100% |

## 差异摘要

| 分类 | 数量 | 是否建议回环 |
|------|:---:|:---:|
| design_gap | 0 | 否 |
| logic_conflict | 0 | 否 |
| clarification | 0 | 否 |
| out_of_scope | 0 | 否 |
| resolved | 2 | 否 |

## 流程 → 产物映射

| 流程 | 涉及页面 | 对应交互条目 id 范围 |
|------|---------|--------------------|
| 流程 1: 查看全国门店销售与结算排名 | 全国门店榜单 | `settlement-ranking.*` |
| 流程 2: 从单店分账核对订单级费用 | 单店分账、订单费用明细 | `store-settlement.*`, `order-fee-detail.*` |
| 流程 3: 查看账单确认与开票路径 | 开票确认 | `invoice-guide.*` |

## 一致性自查

| # | 检查项 | 结果 |
|---|--------|:---:|
| 1 | 所有产物文件路径真实存在 | ✓ |
| 2 | 交互文件中的路由与 page-delivery 一致 | ✓ |
| 3 | 所有语义条目 status = locked | ✓ |
| 4 | 差异文件无未解决的 design_gap / logic_conflict | ✓ |
| 5 | 页面布局和可操作元素已基于运行页面证据描述，而非只读源码推断 | ✓ |
| 6 | mock 样例、预置文件、占位数据未被直接误判为真实系统功能缺失 | ✓ |

## 运行证据摘要

- 使用 Codex 内置真实 Chromium 打开本地静态预览，完成四页可见元素检查和关键点击。
- 验证了榜单累计口径联动、单店费用下钻、订单双费用切换、开票五节点与五类准备指引。
- 回环 #1 后使用缓存隔离地址重新加载，确认修正文案与引导模块生效。
- `390 / 768 / 1440` 三档下四个路由均无 document 级横向溢出；修正后的单店分账与开票页再次通过三档检查。

> 一致性自查全部通过，page-chief 可据此判定页面环节完成。
