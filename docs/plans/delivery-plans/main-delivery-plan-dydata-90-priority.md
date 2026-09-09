# DYDATA-90 Main Delivery Plan

> **版本**：v1
> **发布日期**：2026-09-09
> **适用范围**：上海02:00昨日优先、两小时维表、分接口剩余额度补历史及9月9日生产采集
> **开发模式**：isolated-worktrees
> **上游发现结论**：canProceed=true, slug=dy-data

## 0. 本计划使用指南

1. 先读取本主开发计划，确认阶段顺序、任务索引、发布闸门与风险。
2. 再打开任务看板，定位当前 Task 对应的子开发计划。
3. 执行前只加载当前 Task 的子开发计划和 `PRD 双链·读` 指向的真实文件。

### 0.1 PRD 加载约束

- 先读 `docs/prd/mainprd-dy-data.md` 建立全局地图。
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
| Python | >= 3.12 | `python --version` |

> 表格必须符合环境自检脚本的可解析格式（第 3 列为反引号包裹的完整检测命令；工程依赖目录用两列表声明，写法见 `delivery-planner/references/plan-anatomy.md` 的「环境依赖声明」）。写成其他格式会被脚本当作 0 条声明，只提醒不拦截。

## 1. 差距基线

| 差距 | 影响 | 对应任务 | 状态 |
|---|---|---|---|
| DYDATA-90 缺少昨日优先调度与额度暂停 | 旧历史队列可抢占昨日，分页预算耗尽无法持续恢复 | T0.2 | 进行中 |

## 2. 分工与边界

| 角色 | 职责 |
|---|---|
| AI | 执行代码理解、实装、验证与计划状态回写 |
| 人类 Owner | 审核业务判断、验收关键结果 |

## 3. 执行阶段

### Phase 0：DYDATA-90 闭环

**Entry Criteria**：主 PRD、子开发计划和任务看板均存在。

**Exit Criteria**：T0.2 完成并留下验证证据。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T0.2 | [sub-delivery-plan-dydata-90-priority-T0.2-priority.md](sub-delivery-plan-dydata-90-priority-T0.2-priority.md) | 进行中 |

## 4. 任务看板

- 看板入口：[task-kanban-dydata-90-priority.md](task-kanban-dydata-90-priority.md)

## 5. 发布闸门

- [ ] T0.2 的 `Verification Method` 已执行
- [ ] T0.2 的 `Evidence` 已落盘
- [ ] 任务看板和子开发计划状态一致

## 6. 风险与应对

| 风险 | 影响 | 应对 | Owner | 状态 |
|---|---|---|---|---|
| 旧记录缺少平台版本 | 无法安全排序 | 保留原保护，不以抓取时钟强制覆盖 | AI | 持续保护 |
| 相同源时间内容冲突 | 状态可能误回退 | 保留当前状态并记录DQI | AI | 已覆盖 |
| 全量回归环境与顺序依赖 | 影响发布判断 | 分开记录专项/组合测试/部署验收 | AI | 新版本完整回归与生产验证待执行 |

## 7. AI 执行示例

1. 从任务看板选择 T0.2。
2. 打开 T0.2 对应子开发计划。
3. 按子开发计划中的 PRD、核心文件和验证方法执行。

## 8. PRD → 任务反向索引

| PRD | Task | 子开发计划 |
|---|---|---|
| docs/prd/mainprd-dy-data.md §1 | T0.2 | [sub-delivery-plan-dydata-90-priority-T0.2-priority.md](sub-delivery-plan-dydata-90-priority-T0.2-priority.md) |
