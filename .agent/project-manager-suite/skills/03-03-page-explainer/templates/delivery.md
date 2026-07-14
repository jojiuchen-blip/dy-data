# Page-Explainer 交付清单 - <项目名称>

> 生成时间: YYYY-MM-DD HH:MM
> Skill: page-explainer

## 产物索引

| 产物 | 文件路径 | 存在 |
|------|---------|:---:|
| 用户流程图 | explainer-flow-<slug>.md | ✓ |
| 交互描述 | explainer-b-interaction-<slug>.md | ✓ |
| 差异文件 | explainer-b-gap-<slug>.md | ✓ / — |

> ✓ = 文件存在且内容合格；— = 无差异时不产出差异文件。

## 语义条目冻结统计

| 文件 | locked | open | 冻结率 |
|------|:---:|:---:|:---:|
| explainer-b-interaction-<slug>.md | N | N | NN% |

> 进入最终 Phase 时所有条目必须 locked，open 列应为 0。

## 差异摘要

| 分类 | 数量 | 是否建议回环 |
|------|:---:|:---:|
| design_gap | N | 是/否 |
| logic_conflict | N | 是/否 |
| clarification | N | 是/否 |
| out_of_scope | N | 否 |
| resolved | N | 否 |

## 流程 → 产物映射

> 把 flow 中每条场景涉及的页面映射到对应交互条目 id 范围，便于下游按场景消费。

| 流程 | 涉及页面 | 对应交互条目 id 范围 |
|------|---------|--------------------|
| 流程 1: <任务名> | <页面A>, <页面B> | page-a.*, page-b.* |
| 流程 2: <任务名> | <页面C> | page-c.* |

## 一致性自查

| # | 检查项 | 结果 |
|---|--------|:---:|
| 1 | 所有产物文件路径真实存在 | ✓ |
| 2 | 交互文件中的路由与 page-delivery 一致 | ✓ |
| 3 | 所有语义条目 status = locked | ✓ |
| 4 | 差异文件无未解决的 design_gap / logic_conflict | ✓ |
| 5 | 页面布局和可操作元素已基于运行页面证据描述，而非只读源码推断 | ✓ |
| 6 | mock 样例、预置文件、占位数据未被直接误判为真实系统功能缺失 | ✓ |

> 任一项 ✗ 则不能标记 DONE；page-chief 观察此表判断本环节是否收官。
