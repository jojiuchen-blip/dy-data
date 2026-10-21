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

**核心逻辑**：以原根 range-sync-10562f3369ac7d31e9801d42d8db1d60 ledger 的固定 v2 请求键推进 9/14，旧 3/3 finalize 证据不变。不盲目移植整个运维分支。现行账号/渠道规则从生效月持续有效，不复制八月规则、不改变费率；九月月结使用既有 business_month 专月入口，不触发全局重建。正常退款按现有事件月合同处理，实际影响月份与保护事实须前后复核。根据当前版本核对来源→实收→两费→调整→当前投影→账单→页面/导出分金额。

**核心文件**：
- `apps/worker/day_recovery.py`
- `apps/worker/priority_scheduler.py`
- `apps/worker/settlement_rebuild.py`
- `apps/worker/settlement.py`
- `apps/worker/billing_statements.py`
- `docs/ops/settlement-compaction-recovery-runbook.md`
- `tests/test_job_recovery_and_evidence.py`

**完成标准**：当前生效代次 30/30 成功且 source watermark 可验证；固定请求键重复执行返回同一恢复代且不额外消耗预算。只生成九月待确认账单；八月、非九月、已确认/开票/锁账等保护指纹保持。范围变更前核实当前规则指纹，不改期望值迎合差异。退款单位/范围或财务覆盖不明时停止相关写入，不能用累计金额填账。

**Verification Method**：有界 READ ONLY 预演及真实资源准入；运维工具真实 PG 事务/回滚/回执测试；显式受控操作、独立事后对账。固定恢复键 dydata102-sep14-recovery-20261016-v2；旧范围配置脚本不执行；资源/配额不允许则保留等待，不重置。

**Evidence**：[九月恢复核验记录](../../ops/dydata-104-september-recovery-20261021.md)；历史记录 `docs/devlog/20261020_dydata-104-followthrough.md`。

**Failure Handling**：证据不符、资源/配额不足或保护指纹变化时停止相关写入；保留真实状态并记录具体阻碍，不绕过门禁。未满足验收不标记完成。

**完成收尾：状态同步**：核对验证与 foundation 漂移；新增契约缺口只追加待改请求。由 ai-project-manager 调度 delivery-planner 同步主计划、看板、子计划与执行驾驶舱，重跑一致性和 route-check；生产结果没有实证时不能写完成。

**Owner**：Codex 执行与独立复核 → 用户业务验收

**前置**：生产资源允许；受控工具与证据审阅通过

**状态**：待验收

2026-10-20 用户要求“实在恢复不了不要纠结”。保留恢复边界和历史证据，不再主动重试旧任务；当前优先 T3.1，通过明确未完成账期状态隔离历史缺口。此调整不代表九月已完成、金额已核准或失败任务可改成功。

2026-10-21 用户要求仅处理九月，解除本任务暂缓。当前会话已复核原根身份、剩余一次代次预算、旧恢复链完整 stopped shape、无未完成 manual 链、真实源码与资源。只读九月闭包为 2026-09，现有费用无跨月退款/撤销候选；保护账单及确认/发票/费率/范围规则已建立全字段指纹。固定 v2 已分配 range-sync-e823ef58439995e8b8a29e11e1bf8c07，正按真实资源门禁执行；不将创建成功当作日发布或月结完成。八月缺日不恢复，累计仍受其完整性门禁限制。


2026-10-21 11:23 技术核验完成：固定 v2 全链成功且回放同代不增加预算；九月30/30，自动专月月结成功，第二轮0新增、452张账单 unchanged。两费各1,003,268分；原始实收→费用→账单来源/行/头→投影→静态汇总/列表/导出来源差异均0。所有非九月和受保护事实指纹不变，历史失败尝试未改。真实页面已可见九月待确认账单，累计仍因八月缺日受保护；转业务待验收。
