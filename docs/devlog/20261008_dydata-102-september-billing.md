# DYDATA-102：9 月账期生成链路

2026-10-08：在隔离 worktree `codex/dydata-102-fee-details` 推进 T0.1。DSH 本地服务 `127.0.0.1:3080` 连接拒绝，无法下发或声称由 DSH 执行；用户要求继续后由 Codex 在隔离工作区完成代码修复与复核。

## 只读生产证据

- `/finance/promotion?month=2026-09`：推广费总额、已确认、待开票、已开票、审核通过已结算均为 ¥0.00，列表暂无记录。
- `/finance/orders/promotion?month=2026-09`：此前只读查看为 0 行。
- 当前榜单 2026-10 当期推广费为 ¥0.00，正式账期累计 ¥11,700.92。累计额不能证明 9 月存在佣金来源。
- 生产原始核销/佣金来源的行数与金额尚未能只读核验；不据此推造非零账单。

## 根因与改动

常规采集结算路径调用 `rebuild_settlement` 更新佣金结果后即结束，没有排队调用负责冻结来源、发布结算投影并生成待确认账单的 `settlement_rebuild` 流程。现于成功完成采集结算后，在同一事务中登记稳定、幂等的发布任务；直接结算任务成功时也登记发布任务。结算失败不排队；账单生成仍由现有冻结来源、差异校验及已确认/锁账/发票/异议保护逻辑执行，不自动确认或开票。

改动：`apps/worker/pipeline.py`、`apps/worker/settlement.py`；回归测试：`tests/test_worker_collection_pipeline.py`、`tests/test_data_settlement.py`。

## 验证与限制

- 新回归先验证失败：结算成功后没有 `settlement_rebuild` 任务；加入排队逻辑后通过。
- worker 调度、采集管线、账单来源、账单生成及结算生成 API：192 passed、10 skipped。
- 费用重建：115 passed。
- 2026-10-09 复核 DSH 提出的队列并发回归：相同 `started_at` 时，自动发布任务的 job_id 字典序排在管理任务之后，因而错误地被选为最新槽位并将管理任务标记为 superseded。排序现改为时间优先；时间并列时显式管理重建优先于自动发布任务，无数据库迁移。新增并先观察到失败的并列时间戳回归测试，以及结算异常不排发布任务测试。
- 定向复验 `tests/test_worker_collection_pipeline.py`、`tests/test_data_settlement.py`、`tests/test_billing_publication_locks.py`：167 passed；其中并列时间戳、队列合并、失败不排队与锁保护均通过。`git diff --check` 通过。
- 2026-10-09 继续复验结算生成 API、门店账单 API、实收佣金基数、费用管理和账单生成：301 passed、2 skipped。只检查环境变量是否存在，`DY_DATABASE_URL`、`DATABASE_URL`、`DY_READONLY_DATABASE_URL` 均未设置；本机无 PostgreSQL/API 监听端口，生产 2026-09 来源仍不可只读核验。
- `git diff --check` 通过。
- 全仓 pytest 3510 项因 Windows 本地迁移测试初始化段耗时过长，在约 7% 时中止；不得记为全仓通过。
- DSH 服务不可用；生产 9 月来源行数/金额、账单发布结果尚未核验。本轮没有生产数据写入、部署或推送，DYDATA-102 保持进行中。

## 下一步

恢复 DSH 和生产只读查询后，核对 2026-09 有效核销来源、佣金结果、投影、冻结来源及受保护账单状态；确认符合资格数据与生成范围后，再按受控流程发布并复核总览、明细、导出行数和金额。若 9 月有效来源为零，只报告资格与数据缺口，不造数。
