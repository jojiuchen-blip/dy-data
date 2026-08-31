# 当前执行计划

> 本文件只记录当前执行入口。历史交付事实保留在各自正式交付计划和开发日志中。

## 1. 当前阶段

- 套包阶段：`S4 线索平台收口`。
- 当前 Linear issue：`DYDATA-58`。
- 当前需求序列：`DYDATA-56 -> DYDATA-8 -> DYDATA-14 -> DYDATA-15 -> DYDATA-34 -> DYDATA-58 基础能力 -> DYDATA-70 -> DYDATA-58 剩余能力与最终门禁`。
- 当前正式计划文件组：[主开发计划](delivery-plans/main-delivery-plan-dydata-clue-platform-completion.md)与[任务看板](delivery-plans/task-kanban-dydata-clue-platform-completion.md)。
- 当前子开发计划：[T2.4 全量、等价性和 8GB 最终门禁](delivery-plans/sub-delivery-plan-dydata-clue-platform-completion-T2.4-final-verification.md)。

## 2. 当前目标

- 完成 `DYDATA-56、8、14、15、34、70、58` 的代码、迁移、专项测试和用户视角验收证据收口。
- 保持当前产品决策：自动采集可以运行；自动正式分配与自动再分配保持关闭，现有有效正式轮次仍可由当前门店跟进。
- 将真实 PostgreSQL 和 4C/8GB Linux 三轮资源验证作为独立发布门禁，不用 SQLite、Windows 或合成数据替代。

## 3. 进行中任务

- `T2.4 / DYDATA-58`：完成全量回归、单迁移头、Web production build、Compose 解析和本地 shadow/checkpoint 验收。
- 修复本轮全量回归识别出的少量契约回归，并在聚焦测试通过后重新执行完整门禁。
- 保护未跟踪规格文件、旧隔离 worktree 和 `stash@{0}`；不执行生产部署、重启或数据写入。

## 4. 下一步任务

- 同步 T2.3 已完成证据，并把 T2.4 的本地结果和外部环境阻断项写回主计划、任务看板和子计划。
- 在独立、可丢弃的真实 PostgreSQL 测试库完成原子领取、租约、fencing、崩溃恢复和跨日统计验证。
- 在 4C/8GB Linux 环境连续运行三轮资源验收，验证 worker RSS、主机内存、swap/OOM 及 HTTPS、SSH、API、PostgreSQL 可用性。

## 5. 完成标准

- T0.1-T2.3 的代码、迁移、专项测试和文档证据全部闭合，运行时不再创建 `execution_mode=legacy` 轮次。
- 全量 pytest、Web production build、Alembic 单 head、Compose 配置和 `git diff --check` 全部通过。
- 真实 PostgreSQL 与 4C/8GB Linux 三轮资源门禁有可复现报告；在此之前 `DYDATA-58` 保持发布阻断，不宣称生产完成。
- 自动正式分配和自动再分配未被隐式开启，且未触碰腾讯云生产环境。
