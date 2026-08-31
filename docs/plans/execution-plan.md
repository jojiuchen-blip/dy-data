# 当前执行计划

> 本文件只记录当前执行入口。历史交付事实保留在各自正式交付计划和开发日志中。

## 1. 当前阶段

- 套包阶段：`S4 线索平台收口`。
- 当前 Linear issue：`DYDATA-58`。
- 当前需求序列：`DYDATA-56 -> DYDATA-8 -> DYDATA-14 -> DYDATA-15 -> DYDATA-34 -> DYDATA-58 基础能力 -> DYDATA-70 -> DYDATA-58 剩余能力与最终门禁`。
- 当前正式计划：[主开发计划](delivery-plans/main-delivery-plan-dydata-clue-platform-completion.md)与[任务看板](delivery-plans/task-kanban-dydata-clue-platform-completion.md)。
- 当前子开发计划：[T2.4 全量、等价性和 8GB 最终门禁](delivery-plans/sub-delivery-plan-dydata-clue-platform-completion-T2.4-final-verification.md)。

## 2. 当前目标

- 完成 `DYDATA-56、8、14、15、34、70、58` 的代码、迁移、专项测试和用户视角验收证据收口。
- 保持当前产品决策：自动采集可以运行；自动正式分配与自动再分配保持关闭，现有有效正式轮次仍可由当前门店跟进。
- 将真实 PostgreSQL 和 4C/8GB Linux 三轮资源验证作为独立发布门禁，不用 SQLite、Windows 或合成数据替代。

## 3. 进行中任务

- `T2.4 / DYDATA-58`：本地代码、真实 PostgreSQL 候选子任务和 4C/8GB 三轮资源门禁已完成，状态为 `LOCAL PG + 4C/8GB GREEN / SERVICE-PROBE RELEASE BLOCKED`。
- 本地证据包括全量 `2227 passed / 128 skipped`、Web production build、Alembic 单 head、真实 PostgreSQL 空库/带数据升级、日任务心跳/租约，以及 155,000 行在 4C/8GB Linux 下的三轮 shadow 与资源报告。
- 保护未跟踪规格文件、旧隔离 worktree 和 `stash@{0}`；不执行生产部署、重启或数据写入。

## 4. 下一步任务

- 在已填充大量脱敏数据的真实 PostgreSQL 测试库完成原子领取、租约抢占、epoch fencing、崩溃恢复和跨日统计验证。
- 在三轮资源运行期间同步探测 HTTPS、SSH、API 和 PostgreSQL 可用性；已完成的本地文件级 4C/8GB benchmark 不替代该服务栈门禁。
- Linear OAuth 恢复后，将本地完成证据回写对应 issue；`DYDATA-58` 在外部发布门禁通过前不改为完成。

## 5. 完成标准

- T0.1-T2.3 的代码、迁移、专项测试和文档证据全部闭合，运行时不再创建 `execution_mode=legacy` 轮次。
- 全量 pytest、Web production build、Alembic 单 head、Compose 配置和 `git diff --check` 全部通过。
- 真实 PostgreSQL 与 4C/8GB Linux 三轮资源门禁有可复现报告；在此之前 `DYDATA-58` 保持发布阻断，不宣称生产完成。

## 6. DYDATA-81 门店端财务交付记录

- 当前正式计划文件组：`docs/plans/delivery-plans/main-delivery-plan-dydata-81-store-finance.md`、`task-kanban-dydata-81-store-finance.md` 与对应子开发计划。
- 当前子开发计划：`sub-delivery-plan-dydata-81-store-finance-T1.3-production-release.md`。
- 本记录仅保存 DYDATA-81 已合入主线的发布证据，不改变当前主线 Linear 交付序列；生产发布仍以本轮门禁和用户最终验收为准。
- 自动正式分配和自动再分配未被隐式开启，且未触碰腾讯云生产环境。
