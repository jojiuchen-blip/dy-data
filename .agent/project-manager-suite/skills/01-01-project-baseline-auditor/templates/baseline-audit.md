# 既有项目关键文件诊断清单

> 本文件只是结构示意，供人对照阅读：真实报告由 `scripts/collect-baseline-gaps.mjs` 里的 `buildAuditMarkdown` 函数直接生成，不读取本模板。要调整报告结构，请改脚本，并同步更新本示意。

- 模式：existing-project-baseline
- 范围：maintenance-docs-only
- slug：<slug>
- 推荐下一步：<recommended_next_skill>

## 1. 单焦点待确认

- <one_question_or_none>

## 2. 关键文件缺口

| 类型 | 状态 | 期望位置 | 推荐 skill | 原因 |
|---|---|---|---|---|
| PROJECT_PROFILE | <status> | project-profile.md | project-baseline-auditor | <reason> |
| BRD | <status> | docs/brd/ | brd-writer | <reason> |
| PAGE_EXPLAINER | <status> | src/frontend/page-preview/ | page-explainer | <reason> |
| FOUNDATION | <status> | docs/prd/foundation/ | foundation-builder | <reason> |
| PRD | <status> | docs/prd/ | prd-writer | <reason> |

## 3. 代码证据摘要

- 页面线索：<paths>
- 接口线索：<paths>
- 数据模型线索：<paths>
- 配置线索：<paths>

## 4. 边界

- 本清单不诊断测试用例。
- 本清单不诊断待开发任务。
- 本清单不推荐 delivery-planner 或 test-case 系列 skill。
