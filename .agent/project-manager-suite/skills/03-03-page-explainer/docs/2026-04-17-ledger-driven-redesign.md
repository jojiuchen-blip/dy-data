# page-explainer 台账驱动改造设计（历史稿）

> 日期: 2026-04-17
> 状态: 已被 v2.0.0 单线页面解释流程替代

## 当前结论

这份文件只保留为历史索引，不再作为 page-explainer 的读取入口或实现依据。

当前权威规则以以下文件为准：

- `../SKILL.md`
- `../templates/flow.md`
- `../templates/interaction.md`
- `../templates/gap.md`
- `../templates/delivery.md`
- `../references/phase-final-delivery.md`
- `../../page-chief/SKILL.md`
- `../../../PIPELINE.md`

## v2.0.0 后的设计口径

- page-explainer 只沉淀流程、交互语义、差异和交付清单。
- 必需产物写入 `<host>/src/frontend/page-preview/`。
- `explainer-flow-<slug>.md` 描述流程语义。
- `explainer-b-interaction-<slug>.md` 描述已确认的交互语义；文件名前缀只为兼容既有下游引用。
- `explainer-b-gap-<slug>.md` 只在存在差异时生成。
- `explainer-delivery-<slug>.md` 是 page-chief 判断页面解释环节收口的入口索引。

## 历史价值

这份历史稿的有效价值只剩一条：page-explainer 产出的语义状态必须能被 page-chief 和下游 skill 稳定读取，不能只靠对话承诺。
