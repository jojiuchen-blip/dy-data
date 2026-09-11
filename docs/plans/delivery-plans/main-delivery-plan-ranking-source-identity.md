# Ranking source identity Main Delivery Plan

> **版本**：v1
> **发布日期**：2026-09-11
> **适用范围**：ranking-source-identity
> **开发模式**：solo-local
> **上游发现结论**：canProceed=true, slug=ranking-source-identity

## 0. 本计划使用指南

1. 先读取本主开发计划，确认阶段顺序、任务索引、发布闸门与风险。
2. 再打开任务看板，定位当前 Task 对应的子开发计划。
3. 执行前只加载当前 Task 的子开发计划和 `PRD 双链·读` 指向的真实文件。

### 0.1 PRD 加载约束

- 先读 `mainprd-dy-data.md` 建立全局地图。
- 每个 Task 只读取子开发计划中列出的 PRD 和相关章节。

### 0.2 读前门禁 / AI 自检清单

- 当前 Task 必须能从任务看板定位到一个子开发计划。
- 子开发计划必须声明 `PRD 双链·读`、`核心逻辑`、`核心文件` 和 `完成标准`。

### 0.3 完成前验证门禁

- 完成前必须执行子开发计划里的 `Verification Method`。
- 证据必须写入子开发计划的 `Evidence` 指定位置。

## 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Node.js | >= 18 | `node -v` |

> 表格必须符合环境自检脚本的可解析格式（第 3 列为反引号包裹的完整检测命令；工程依赖目录用两列表声明，写法见 `delivery-planner/references/plan-anatomy.md` 的「环境依赖声明」）。写成其他格式会被脚本当作 0 条声明，只提醒不拦截。

## 1. 差距基线

| 差距 | 影响 | 对应任务 | 状态 |
|---|---|---|---|
| Ranking source identity 功能尚未落地 | 无法完成归属证据核验 | T0.1 | 待处理 |

## 2. 分工与边界

| 角色 | 职责 |
|---|---|
| AI | 执行代码理解、实装、验证与计划状态回写 |
| 人类 Owner | 审核业务判断、验收关键结果 |

## 3. 执行阶段

### Phase 0：Ranking source identity 闭环

**Entry Criteria**：主 PRD、子开发计划和任务看板均存在。

**Exit Criteria**：T0.1 完成并留下验证证据。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T0.1 | [sub-delivery-plan-ranking-source-identity-T0.1-source-identity.md](sub-delivery-plan-ranking-source-identity-T0.1-source-identity.md) | 进行中 |

## 4. 任务看板

- 看板入口：[task-kanban-ranking-source-identity.md](task-kanban-ranking-source-identity.md)

## 5. 发布闸门

- [ ] T0.1 的 `Verification Method` 已执行
- [ ] T0.1 的 `Evidence` 已落盘
- [ ] 任务看板和子开发计划状态一致

## 6. 风险与应对

| 风险 | 影响 | 应对 | Owner | 状态 |
|---|---|---|---|---|
| PRD 章节缺失 | T0.1 不能开工 | 阻塞并补齐 PRD 链接 | AI -> 人类 Owner | 待观察 |

## 7. AI 执行示例

1. 从任务看板选择 T0.1。
2. 打开 T0.1 对应子开发计划。
3. 按子开发计划中的 PRD、核心文件和验证方法执行。

## 8. PRD → 任务反向索引

| PRD | Task | 子开发计划 |
|---|---|---|
| mainprd-dy-data.md §1 | T0.1 | [sub-delivery-plan-ranking-source-identity-T0.1-source-identity.md](sub-delivery-plan-ranking-source-identity-T0.1-source-identity.md) |

## 当前需求边界

本任务补充正式看板发布前的源证据，不代表看板全部验收。后续任务包括生产快照接线、2026-09-01 数据下限及 9 月 7 日默认日期、名单历史版本导入、迁移接续和正式部署。商家昵称只作精确且唯一的候选归属证据，不能绕过冲突或失效绑定；意向 POI 不能替代卖出门店。
