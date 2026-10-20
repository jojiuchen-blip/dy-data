# T2.1 九月来源恢复、范围与费用对账

## 任务来源

- [主计划](main-delivery-plan-dydata-104-followthrough.md) / [任务看板](task-kanban-dydata-104-followthrough.md)
- [DYDATA-104](https://linear.app/keith-lim/issue/DYDATA-104)

### T2.1 九月来源恢复、范围与费用对账

**Requirement ID**：DYDATA-104 B / C

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` 全局规则
- `docs/prd/subprd/02-subprd-store-settlement.md` §3–4
- `docs/prd/subprd/03-subprd-order-fee-details.md` 筛选与导出
- `docs/prd/subprd/05-subprd-finance-promotion.md` §3
- `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md` 账单/财务契约
- `docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md` 费用、调整与冻结来源
- `docs/api/dashboard-publications.md` 不可变发布与读取

**核心逻辑**：以原根 range-sync-10562f3369ac7d31e9801d42d8db1d60 ledger 的固定 v2 请求键推进 9/14，旧 3/3 finalize 证据不变。不盲目移植整个运维分支。九月仅采用用户已确认的八月账号/渠道范围，调用既有受控 scope 服务并在事务可见前写 settlement_month_scope_metadata；不得触发全局重建。根据当前版本核对来源→实收→两费→调整→当前投影→账单→页面/导出分金额。

**核心文件**：
- `apps/worker/day_recovery.py`
- `apps/worker/priority_scheduler.py`
- `apps/worker/settlement_rebuild.py`
- `apps/worker/settlement.py`
- `apps/worker/billing_statements.py`
- `docs/ops/settlement-compaction-recovery-runbook.md`
- `tests/test_job_recovery_and_evidence.py`

**完成标准**：当前生效代次 30/30 成功且 source watermark 可验证；固定请求键重复执行返回同一恢复代且不额外消耗预算。只生成九月待确认账单；八月、非九月、已确认/开票/锁账等保护指纹保持。范围变更前核实当前规则指纹，不改期望值迎合差异。退款单位/范围或财务覆盖不明时停止相关写入，不能用累计金额填账。

**Verification Method**：有界 READ ONLY 预演及真实资源准入；运维工具真实 PG 事务/回滚/回执测试；显式受控操作、独立事后对账。固定恢复键 dydata102-sep14-recovery-20261016-v2；范围键 dydata102-september-scope-20261016-v1；资源/配额不允许则保留等待，不重置。

**Evidence**：`docs/devlog/20261020_dydata-104-followthrough.md`，对应最终 CI 与脱敏运行记录。

**Failure Handling**：证据不符、资源/配额不足或保护指纹变化时停止相关写入；保留真实状态并记录具体阻碍，不绕过门禁。未满足验收不标记完成。

**完成收尾：状态同步**：核对验证与 foundation 漂移；新增契约缺口只追加待改请求。由 ai-project-manager 调度 delivery-planner 同步主计划、看板、子计划与执行驾驶舱，重跑一致性和 route-check；生产结果没有实证时不能写完成。

**Owner**：Codex 执行与独立复核 → 用户业务验收

**前置**：生产资源允许；受控工具与证据审阅通过

**状态**：待开发

