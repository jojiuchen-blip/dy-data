# T2.1 八月缺失日追查、九月 14 日恢复与费用对账

## 任务来源

- [主计划](main-delivery-plan-dydata-104-followthrough.md) / [任务看板](task-kanban-dydata-104-followthrough.md)
- [DYDATA-104](https://linear.app/keith-lim/issue/DYDATA-104)

### T2.1 八月缺失日追查、九月 14 日恢复与费用对账

**Requirement ID**：DYDATA-104 B / C

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` 全局规则
- `docs/prd/subprd/02-subprd-store-settlement.md` §3–4
- `docs/prd/subprd/03-subprd-order-fee-details.md` 筛选与导出
- `docs/prd/subprd/05-subprd-finance-promotion.md` §3
- `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md` 账单/财务契约
- `docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md` 费用、调整与冻结来源
- `docs/api/dashboard-publications.md` 不可变发布与读取

**核心逻辑**：以原根 range-sync-10562f3369ac7d31e9801d42d8db1d60 ledger 的固定 v2 请求键推进 9/14，旧 3/3 finalize 证据不变，恢复根身份和幂等键保持。同步只读定位 2026-08 尚缺的 1 个日任务（具体日期由生产只读证据确定，不猜），仅对该缺失日与 9/14 执行受控恢复；不得复活 7/24。不盲目移植整个运维分支。八月本轮已成为明确目标，不再要求八月所有未保护事实逐字不变，但非目标月份及已确认/锁定/开票事实必须保护；任何写入前先捕获当前基线。九月范围采用用户已确认的账号/渠道范围，规则按连续生效合同承接；不得把八月配置复制到九月，也不盲目使用旧 expected scope hash，须在写入前重新核对当前规则指纹。调用既有受控 scope 服务并在事务可见前写 settlement_month_scope_metadata；不得触发全局重建。根据当前版本核对来源→实收→两费→调整→当前投影→账单→页面/导出分金额。不自动确认、付款或改写开票事实。

**核心文件**：
- `apps/worker/day_recovery.py`
- `apps/worker/priority_scheduler.py`
- `apps/worker/settlement_rebuild.py`
- `apps/worker/settlement.py`
- `apps/worker/billing_statements.py`
- `docs/ops/settlement-compaction-recovery-runbook.md`
- `tests/test_job_recovery_and_evidence.py`

**完成标准**：只恢复八月缺失日与 9/14，当前生效代次日计数达到 2026-08 31/31、2026-09 30/30，source watermark 可验证；固定请求键重复执行返回同一恢复代且不额外消耗预算，不新增根、不重置 attempt。八月仅允许改动目标缺失日，非目标月份及已确认/开票/锁账等保护指纹保持。九月范围按连续生效规则选择，不复制八月配置、不盲目套用旧 expected scope hash；范围变更前核实当前规则指纹，不改期望值迎合差异。完成来源→实收→两费→调整→当前投影→账单→页面/导出的按分对账，完成月重发布并通过 UI/导出验收。只生成待确认账单，不自动确认、付款或改写开票事实。退款单位/范围或财务覆盖不明时停止相关写入，不能用累计金额填账。

**Verification Method**：先验证目标执行环境与只读通道，本地 Docker 不可用时不将 envReady 置真；有界 READ ONLY 预演及真实资源准入；写入前后捕获基线并核对保护指纹；运维工具真实 PG 事务/回滚/回执测试；显式受控操作、独立事后对账、月重发布与 UI/导出验收。固定恢复键 dydata102-sep14-recovery-20261016-v2；范围键 dydata102-september-scope-20261016-v1；资源/配额不允许则保留等待，不重置。

**Evidence**：`docs/devlog/20261020_dydata-104-followthrough.md`，对应最终 CI 与脱敏运行记录。

**Failure Handling**：证据不符、资源/配额不足或保护指纹变化时停止相关写入；保留真实状态并记录具体阻碍，不绕过门禁。目标执行环境未验证或 SSH 通道未建立时保持只读/等待，不把 TUN 接管路由的假设归因为根因，不删除 Docker 依赖。未满足验收不标记完成。

**完成收尾：状态同步**：核对验证与 foundation 漂移；新增契约缺口只追加待改请求。由 ai-project-manager 调度 delivery-planner 同步主计划、看板、子计划与执行驾驶舱，重跑一致性和 route-check；生产结果没有实证时不能写完成。

**Owner**：Codex 执行与独立复核 → 用户业务验收

**前置**：目标执行环境与只读通道验证；生产资源允许；受控工具与证据审阅通过；写入前基线已捕获

**状态**：进行中

2026-10-20 用户要求“实在恢复不了不要纠结”。保留恢复边界和历史证据，不再主动重试旧任务；当时优先 T3.1，通过明确未完成账期状态隔离历史缺口。此调整不代表九月已完成、金额已核准或失败任务可改成功。

2026-10-21 用户说“按这个顺序做”并明确恢复八月/九月恢复；本 Task 从暂缓恢复为进行中。上文 2026-10-20 暂缓只保留历史，不再代表当前状态。恢复范围限定八月缺失日与 9/14；7/24 不复活；不新增根、不重置预算；T3.1 已部署技术成功进入待验收，T2.1 对账、月重发布与 UI/导出验收仍须在 T3.1 关闭前完成。

2026-10-21 只读证据（新增）：当前文档工作树基线 `2175e45`；本地 Docker 不可用，`--env-check` 本地为 envReady=false，仅为本地事实，不写 envReady=true、不改依赖声明。2026-10-21 09:34 通过 GitHub SSH 固定只读中继执行 run `39528068946` 成功，无生产写入。八月缺失日定位为 2026-08-16，恢复根 `range-sync-fc2b2b15609abc673764b6f445c2daf4` 当前 pending；日期/父任务 success，finalize 3/3 失败，预算 0/2。九月 9/14 仍缺失，预算 1/2，已批准 rawv2 但尚未分配；当前深度 27，无 heavy 任务；九月现有 2 条费用各 198 但无账单；八月当前 443 条账单及双向各 5 条确认记录已保护；技术部署 `5da13df1` 成功保留。新确认代码阻塞：原任务 pending + 采集完成 + finalize 耗尽后被 `_assert_terminal_shape` 拒绝，需严格的新 eligibility 分支，不得用 SQL 重置状态绕过。尚无新应用代码。

