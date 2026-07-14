# {项目名称} — mainprd

<!--
  本文件是 mainprd 模板。{} 中的内容为占位符，需替换为实际内容。

  ═══════════════════════════════════════════════════════════════
  核心定位
  ═══════════════════════════════════════════════════════════════

  mainprd 是纯索引枢纽，自身不产出实质内容。
  - 产品背景和功能全貌 → 在功能列表中
  - 术语/Schema/API → 在 foundation-builder 产物中
  - 详细规格 → 在各 subprd 中

  mainprd 的价值是：一个入口找到所有东西。

  ═══════════════════════════════════════════════════════════════
  机器校验锚点（不得改名 / 删除 / 改表头）
  ═══════════════════════════════════════════════════════════════

  必需章节：
  - ## 上游引用
  - ## subprd索引
  - ## 全局设计规则
  - ## 一致性自查结果
  - ## 待回溯缺口

  固定表头：
  - | # | 区块 | 所属页面 | subprd文件 | 状态 |
  - | 缺口 | 类型 | 回溯目标 | 状态 |

  注意：
  - 新增表格表头不得同时包含"区块/功能区块/subprd"和"subprd文件/subprd 文件/文件路径/链接"两组关键词，避免污染 route-check 的 PRD 索引解析。
-->

> 生成时间: {YYYY-MM-DD HH:MM}
> 来源: prd-writer Phase 3
> 技术栈: Vue 3

---

## 上游引用

<!--
  所有外部产物的文件路径集中在此。
  subprd 通过引用 mainprd 来获取这些路径。
  路径必须是真实存在的文件路径。
-->

| 产物 | 文件 | 来源 Skill |
|------|------|-----------|
| 功能列表 | [prd-feature-list-{slug}.md](...) | prd-writer |
| 用户流程 | [explainer-flow-{slug}.md](...) | page-explainer |
| 交互语义 | [explainer-b-interaction-{slug}.md](...) | page-explainer |
| 术语表 | [foundation-glossary-{slug}.md](foundation/foundation-glossary-{slug}.md) | foundation-builder |
| 数据库 Schema | [foundation-schema-{slug}.md](foundation/foundation-schema-{slug}.md) | foundation-builder |
| API 接口 | [foundation-api-{slug}.md](foundation/foundation-api-{slug}.md) | foundation-builder |
| BRD | [BRD-{slug}-*.md](...) | brd-writer |
| 页面交付清单 | [page-delivery-{slug}.md](...) | page-designer |

---

## subprd索引

<!--
  双向引用的锚点。每份 subprd 生成后回填此表。
  状态固定为：待开始 / 待确认 / 已确认
  只有所有 subprd 文件真实存在且状态均为已确认，才表示主索引闭合。
-->

| # | 区块 | 所属页面 | subprd文件 | 状态 |
|---|------|---------|-----------|------|
| 1 | {区块名} | {页面名} | [01-subprd-{区块英文短名}.md](subprd/01-subprd-{区块英文短名}.md) | {状态} |

---

## 全局设计规则

<!--
  唯一保留的实质内容区域。
  只放跨区块通用的规则，如统一的空状态处理、加载态、错误提示规范。
  区块内部的设计规则放在对应 subprd 中。
-->

| 规则 | 说明 |
|------|------|
| 空状态 | {统一的空状态展示方式} |
| 加载态 | {统一的加载态展示方式} |
| 错误提示 | {统一的错误提示规范} |

---

## 一致性自查结果

<!--
  Phase 5 完成后写入。
  使用 bullet 摘要，不写危险追溯表头，避免污染 route-check 的 PRD 索引解析。
-->

- 检查时间: {YYYY-MM-DD HH:MM}
- P1 数据链路覆盖: {x}/{x} ({percent}%)
- P2 接口引用覆盖: {x}/{x} ({percent}%)
- P3 术语覆盖: {已人工复核 / 待复核}
- P4 功能列表→subprd: {x}/{x} ({percent}%)
- P5 mainprd 索引完整: {✓ / 待修复}
- P6 交互语义一致: {x}/{x} ({percent}%)
- P8 流程覆盖: {已人工复核 / 待复核}
- P9 功能子区域 ↔ 验收对应性: {x}/{x} ({percent}%)
- 需回溯 foundation-builder: {无 / 列表}

---

## 待回溯缺口

<!--
  Phase 4/5 发现 foundation 或 page-explainer 缺口时写入。
  无缺口时保留一行 resolved，确保 crosscheck 可判定闭合。
-->

| 缺口 | 类型 | 回溯目标 | 状态 |
|---|---|---|---|
| 无 | — | — | resolved |
