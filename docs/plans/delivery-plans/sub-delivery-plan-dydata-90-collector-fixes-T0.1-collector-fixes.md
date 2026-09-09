# T0.1 DYDATA-90 Sub Delivery Plan

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-90-collector-fixes.md](main-delivery-plan-dydata-90-collector-fixes.md)
- 任务看板：[task-kanban-dydata-90-collector-fixes.md](task-kanban-dydata-90-collector-fixes.md)

#### T0.1 修复采集状态更新

**Requirement ID**：DYDATA-90

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` §1

**核心逻辑**：
- 按用户已确认 DYDATA-90 范围修复订单修改窗口查询、订单/券/核销观察时间传递、退款 create_time/complete_time 别名和已存原始数据重放修复。保持旧快照保护和金额校验；不部署、不打开旧调度。

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
- 订单修改查询接入采集；新状态可更新、旧重放不回退；退款官方完成时间正确规范化；相关回归通过。

**Verification Method**：
- 执行 `python -m pytest tests/test_worker_source_updates.py tests/test_douyin_openapi_client.py tests/test_worker_refund_collector.py -q` 及完整回归。

**Evidence**：
- `output/dydata90-collector-fixes.md`

**Failure Handling**：
- PRD 或核心文件定位不到时阻塞。

**完成收尾：状态同步**：
- 本 Task 完成实现、验证和 foundation 漂移判断后，必须把 Task 完成事实、验证证据、完成日期、foundation 漂移结论和建议下一 Task 提交给 `ai-project-manager`。
- 由 `ai-project-manager` 调度 `delivery-planner` 同步 `main-delivery-plan-<slug>.md`、`task-kanban-<slug>.md` 和当前 `sub-delivery-plan-<slug>-<TaskID>-<short-name>.md` 的状态。
- 同步后重新运行 `node <suite-path>/tools/route-check.mjs <host> --target-stage S4 --json`（route-check 是套件的阶段门禁检查工具；`<suite-path>` 指套件根目录：源码仓库联调时为 `project-manager-suite/`，安装到宿主后为 `.agent/project-manager-suite/`，命令默认在宿主项目根目录执行），确认正式开发计划文件组三者一致；未通过前不得宣称本 Task 已完成。

**Owner**：AI 执行 -> 人审核

**前置**：无

**状态**：进行中

**2026-09-09 验收记录**：实现完成；94项专项通过；全仓2485通过/140跳过/1项界面失败，单独重跑可复现。状态保留进行中待验收；无foundation契约漂移。下一任务为新调度和受限单日生产试跑。详见Evidence。
