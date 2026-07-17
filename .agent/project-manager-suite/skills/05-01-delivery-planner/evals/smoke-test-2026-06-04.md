# delivery-planner smoke test

> 日期：2026-06-04
> 方式：轻量 smoke test（基于多文件结构、任务映射、执行前校验与路由门禁）
> 结论：主开发计划、任务看板、子开发计划三类文件的结构校验与 S4 路由测试通过。

## 1. 测试范围

本轮确认：
- 主开发计划位于 `docs/plans/delivery-plans/main-delivery-plan-<slug>.md`
- 任务看板位于 `docs/plans/delivery-plans/task-kanban-<slug>.md`
- 子开发计划位于 `docs/plans/delivery-plans/sub-delivery-plan-<slug>-<TaskID>-<short-name>.md`
- 主开发计划、任务看板、子开发计划中的 Task 一一对应
- `verify-task-context.mjs` 能从主开发计划经任务看板定位到子开发计划
- `route-check.mjs` 的 S4 门禁使用主开发计划入口做结构校验

## 2. 用例结果

| 用例 | 场景 | 期望 | 结果 | 结论 |
|---|---|---|---|---|
| E1 | 新建多文件开发计划 | 三类文件齐全，结构校验通过 | `validate-plan-structure.mjs` 返回 `passed: true` | 通过 |
| E2 | 看板任务缺少子开发计划 | 结构校验失败并指出缺失 Task | `validate-plan-structure.mjs` 返回 `missing_sub_delivery_plan` | 通过 |
| E3 | S4 路由门禁 | 主开发计划结构有效时进入 coding-standards | `route-check` 返回 `canEnter: true` | 通过 |
| E4 | 执行前任务校验 | 从主开发计划定位到当前 Task 的子开发计划 | `verify-task-context.mjs` 返回 `canExecute: true` | 通过 |

## 3. 结构要求

- 主开发计划保留全局方法、阶段索引、发布闸门、风险和 PRD 反向索引。
- 任务看板是独立文件，承接 Task 状态和子开发计划入口。
- 每个子开发计划只包含一个 Task 正文。
- coding-standards 执行单个 Task 时只需要加载主计划入口、任务看板行和对应子开发计划。
