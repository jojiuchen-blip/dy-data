# T0.2 DYDATA-90 Sub Delivery Plan

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-90-priority.md](main-delivery-plan-dydata-90-priority.md)
- 任务看板：[task-kanban-dydata-90-priority.md](task-kanban-dydata-90-priority.md)

#### T0.2 启用昨日优先调度

**Requirement ID**：DYDATA-90

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` §1

**核心逻辑**：
- 按用户确认实现独立 priority_daily 模式：上海02:00昨日完整窗口优先、两小时维表和每日商品刷新、昨日成功发布后使用分接口剩余额度补历史；保留平台硬限额、租约和旧快照保护。页级断点保障退款预算耗尽后可续跑；部署后启动9月9日完整闭环。禁止无界旧drain抢占昨日任务。

**核心文件**：
- `apps/worker/priority_scheduler.py`
- `apps/worker/priority_budget.py`
- `apps/worker/paged_collection.py`
- `apps/worker/publication_scope.py`
- `apps/worker/scheduler.py`
- `apps/worker/daily_task.py`
- `apps/worker/task_control.py`
- `apps/worker/subprocess_supervisor.py`
- `apps/worker/repositories.py`
- `apps/api/dy_api/models.py`
- `apps/api/dy_api/routes/admin.py`
- `alembic/versions/20260910_0053_quota_pause_attempts.py`
- `deploy/compose.yaml`
- `tests/test_priority_scheduler.py`
- `tests/test_paged_collection.py`
- `tests/test_priority_budget_pause.py`

**完成标准**：
- 时区边界、优先级、重启幂等、历史预算保护、分页恢复、发布闭环测试通过；生产启用新模式并有9月9日真实任务状态证据。

**Verification Method**：
- 执行新priority、paging、budget pause、publication scope专项和既有worker/control/API回归；完整pytest、Web build、真实PostgreSQL升级与约束检查、生产模式与任务读取验证。

**Evidence**：
- `docs/devlog/2026-09-10-priority-daily.md`

**Failure Handling**：
- PRD 或核心文件定位不到时阻塞。

**完成收尾：状态同步**：
- 本 Task 完成实现、验证和 foundation 漂移判断后，必须把 Task 完成事实、验证证据、完成日期、foundation 漂移结论和建议下一 Task 提交给 `ai-project-manager`。
- 由 `ai-project-manager` 调度 `delivery-planner` 同步 `main-delivery-plan-<slug>.md`、`task-kanban-<slug>.md` 和当前 `sub-delivery-plan-<slug>-<TaskID>-<short-name>.md` 的状态。
- 同步后重新运行 `node <suite-path>/tools/route-check.mjs <host> --target-stage S4 --json`（route-check 是套件的阶段门禁检查工具；`<suite-path>` 指套件根目录：源码仓库联调时为 `project-manager-suite/`，安装到宿主后为 `.agent/project-manager-suite/`，命令默认在宿主项目根目录执行），确认正式开发计划文件组三者一致；未通过前不得宣称本 Task 已完成。

**Owner**：AI 执行 -> 人审核

**前置**：无

**状态**：进行中


## 完成交接（2026-09-10）

- T0.2实现、启用与启动分项验收：CI 2723 passed/155 skipped，PostgreSQL额度暂停3项通过，构建、0053迁移及生产健康检查通过。实际运行代码e35787ff，API与worker均为priority_daily。
- 9月9日all计划range-sync-30c5cbdc07baa45aef0f1a8b4db53b24自动启动；02:26上海时间采集已提交67页，心跳正常、无错误。门店/职人资料成功。该证据证明已启动，不表示统一发布已完成。
- Foundation漂移：S4-FCR-001仍待评审，未直接修改foundation。建议下一任务：核验整日finalize/publish结果、72小时稳定性及状态回补覆盖；DYDATA-90保持进行中。
- ai-project-manager交接事实与delivery-planner三文件状态同步于本节留证，证据详见指定devlog；收尾重新执行route-check。

- 收尾说明：启用及指定日期启动已验证；正式T0.2保留进行中，等待实际整日发布结果收口。完成态检查发现S4门禁要求活跃任务，因此未虚构新任务或宣称整日发布完成。
