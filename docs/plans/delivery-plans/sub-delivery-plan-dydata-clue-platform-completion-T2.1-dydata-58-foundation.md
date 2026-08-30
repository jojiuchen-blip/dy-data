# T2.1 DYDATA-58 控制面与按日编排基础

## 任务来源
- 主开发计划：[main-delivery-plan-dydata-clue-platform-completion.md](main-delivery-plan-dydata-clue-platform-completion.md)
- 任务看板：[task-kanban-dydata-clue-platform-completion.md](task-kanban-dydata-clue-platform-completion.md)

#### T2.1 集成父子任务、租约、自然日编排和变化捕获

**Requirement ID**：DYDATA-58 T1.1-T3.1

**PRD 双链·读**：
- `docs/superpowers/specs/2026-08-06-dy-data-8gb-safe-sync-control-plane-design.md`
- `docs/prd/foundation/foundation-api-clue-center/jobs-security-and-migration.md`

**核心逻辑**：数据库持久化父子任务与阶段；PostgreSQL 原子领取、租约和 fencing；API 只入队；上海自然日串行执行；每阶段独立 session/可选子进程；采集写入影响集合和退款变化。

**核心文件**：`apps/api/dy_api/models.py`、`apps/worker/scheduler.py`、`apps/worker/pipeline.py`、任务控制面/执行器模块、0030-0033 迁移及对应测试。

**完成标准**：已成功日期跳过、失败有限重试、进程崩溃可续跑、同一天不重复领取、每阶段提交释放资源，迁移与 PostgreSQL 并发测试通过。

**Verification Method**：运行控制面、编排、阶段恢复、变化捕获和 Alembic 专项测试；真实 PostgreSQL 锁/租约测试；`python -m compileall apps`。

**Evidence**：逐片差异审查、RED/GREEN 输出、PG 并发结果和迁移头信息。

**Failure Handling**：旧 worktree 代码逐文件移植；任一迁移/模型不匹配立即停止后续集成。

**完成收尾：状态同步**：完成后同步三份计划并切换 T2.2。

**Owner**：主代理

**前置**：T1.1

**状态**：进行中
