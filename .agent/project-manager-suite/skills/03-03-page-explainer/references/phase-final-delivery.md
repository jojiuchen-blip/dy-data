# 最终 Phase：交付清单与回环判断

> 本文件在进入最终 Phase 时由 SKILL.md 指令加载。

## 触发条件

交互描述完成、全部语义条目 locked 后进入。

## 本 Phase 产物

`explainer-delivery-<slug>.md` —— 本环节收官文件，作为 page-chief 完工判据和下游入口索引。

模板：读取 `templates/delivery.md`。

## 产出步骤

1. 扫描宿主项目 `src/frontend/page-preview/` 目录，列出所有 `explainer-*-<slug>.md` 文件；旧项目尚未迁移时，再兼容扫描根级 `page-preview/` 和 `可操作页面/`
2. 对每个产物在"产物索引表"中记录真实路径与存在性
3. 读取交互文件，统计 locked / open 条目数，写入"冻结统计"
4. 读取差异文件（若存在），按分类统计未解决条目数，写入"差异摘要"
5. 根据 flow 中的场景列表，对每个场景列出涉及页面和对应交互条目 id 前缀，写入"流程 → 产物映射"
6. 检查交互文件是否记录运行页面证据、代码证据和原型 / mock 边界；若只从代码推断页面布局，不能产出 delivery
7. 执行一致性自查并写入结果；任一 ✗ 都必须先解决再产出 delivery

## 回环判断流程

1. 检查 delivery 中"差异摘要"：
   - 存在未解决 `design_gap` / `logic_conflict`：主动建议回环 page-designer，展示具体条目
   - 仅剩 `clarification`：向用户提问，获得答案后转为语义条目或标记 `resolved`
   - 用户拒绝回环：对应差异条目分类改为 `resolved`，并在「解决记录」字段写明 `用户拒绝回环（reason: user-declined）`
2. 无未解决差异：直接进入完工

## 回环后复查

page-designer 修改完页面后重新进入 page-explainer 时：
1. 仅复查差异文件中 `design_gap` 和 `logic_conflict` 类型的条目涉及的运行页面、页面代码和交互
2. 差异已闭环：对应条目分类改为 `resolved`，并在「解决记录」字段写明闭环方式（如 `回环#N 修复`）
3. 仍有差异：更新差异文件，再次建议回环
4. 每次复查结束都必须重新生成 `explainer-delivery-<slug>.md`，保持一致性自查表与产物状态同步

## 完成后状态标记

```
【Skill状态】page-explainer | DONE
```
