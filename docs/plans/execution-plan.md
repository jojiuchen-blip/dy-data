# 当前执行计划

> 本文件只记录当前执行入口。历史交付事实保留在各自正式交付计划和开发日志中。

## 1. 当前阶段

- 套包阶段：`S4 线索平台收口`。
- 当前需求序列：`DYDATA-56 -> DYDATA-8 -> DYDATA-14 -> DYDATA-15 -> DYDATA-34 -> DYDATA-58 基础能力 -> DYDATA-70 -> DYDATA-58 剩余能力与最终门禁`。
- 当前 Task：`T0.4 / DYDATA-15`，状态为“进行中”；T0.1-T0.3 已完成本地代码与专项验收。
- 正式计划：[main-delivery-plan-dydata-clue-platform-completion.md](delivery-plans/main-delivery-plan-dydata-clue-platform-completion.md)。
- 任务看板：[task-kanban-dydata-clue-platform-completion.md](delivery-plans/task-kanban-dydata-clue-platform-completion.md)。
- 当前子计划：[sub-delivery-plan-dydata-clue-platform-completion-T0.4-dydata-15.md](delivery-plans/sub-delivery-plan-dydata-clue-platform-completion-T0.4-dydata-15.md)。

## 2. 当前目标

- 逐项完成并验证 `DYDATA-56、8、14、15、34、70、58`，先关闭已有实现的验收缺口，再移除旧线索分配引擎，最后集成可恢复、增量、受控的 8GB 安全同步链路。
- 保持当前产品决策：自动采集可以运行；自动分配与自动再分配保持关闭，现有有效线索仍可由当前门店跟进。

## 3. 执行约束

- 同一时刻只有一个 Task 进行中；每个 Task 完成后同步主计划、任务看板和子计划。
- 不覆盖当前未跟踪规格文件，不清理旧隔离 worktree，不丢弃 `stash@{0}`。
- 生产部署、重启、数据迁移和真实重建必须在对应发布门禁中单独核验；未获得明确生产授权时只完成本地代码和只读验证。
- Linear 仍是需求状态权威；浏览器中的状态变更和评论属于外部写操作，代码与证据闭合后再执行。

## 4. 下一步

- 补齐新试运行/批次查询契约，移除旧线索物化重建入口，并复核规则后台权限与高风险确认。
- 完成 T0.4 后进入 DYDATA-34；不得用现有绿色测试替代 Foundation 验收。
