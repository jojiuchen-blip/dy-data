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
- `src/dy_data/douyin_client.py`
- `apps/worker/collectors/orders.py`
- `apps/worker/collectors/verify_records.py`
- `apps/worker/collectors/refunds.py`
- `apps/worker/collectors/normalizers.py`
- `apps/worker/repositories.py`
- `tests/test_worker_source_updates.py`
- `tests/test_douyin_openapi_client.py`

**完成标准**：
- 时区边界、优先级、重启幂等、历史预算保护、分页恢复、发布闭环测试通过；生产启用新模式并有9月9日真实任务状态证据。

**Verification Method**：
- 执行 `python -m pytest tests/test_worker_source_updates.py tests/test_douyin_openapi_client.py tests/test_worker_refund_collector.py -q` 及完整回归。

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


新增核心文件：apps/worker/priority_scheduler.py、apps/worker/scheduler.py、apps/worker/daily_task.py、apps/worker/paged_collection.py、tests/test_priority_scheduler.py、tests/test_paged_collection.py。

