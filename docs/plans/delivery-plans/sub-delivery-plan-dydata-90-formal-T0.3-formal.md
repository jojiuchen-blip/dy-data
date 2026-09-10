# T0.3 DYDATA-90 正式分配闭环

- 主开发计划：[main-delivery-plan-dydata-90-formal.md](main-delivery-plan-dydata-90-formal.md)
- 任务看板：[task-kanban-dydata-90-formal.md](task-kanban-dydata-90-formal.md)

#### T0.3 正式分配与严格订单资格

**Requirement ID**：DYDATA-90

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` §1
- `docs/brd/BRD-clue-center-20260721-2134.md` §3及2026-09-10修订
- `docs/prd/foundation/foundation-api-clue-center/jobs-security-and-migration.md` J03
- `docs/prd/foundation/foundation-api-clue-center/lead-query-and-contact.md` 状态解析约束

**核心逻辑**：
- 每批状态处理后首次正式分配并定时有界补偿，不等待结算；仅分配已确认可促核销、无活动轮次、非总部池、待首次分配线索。仅支付成功不可放行。真实分配时间，不倒填。自动超期保持关闭，日期UI不变，总部池不再投放。

**核心文件**：
- `apps/worker/clue_allocation_engine.py`
- `apps/worker/clue_allocation.py`
- `apps/worker/order_status.py`
- `apps/worker/clue_center.py`
- `apps/worker/daily_task.py`
- `apps/worker/scheduler.py`

**完成标准**：
- BRD记录用户确认；严格订单状态统一；每批触发和独立补偿实现；幂等、排他、终态、总部池、超期关闭及已分配保护测试通过。代码修复与生产部署分开记录。

**Verification Method**：
- 状态解析、线索物化、正式分配引擎、调度接入及PostgreSQL并发回归；git diff --check；治理三文件一致性。

**Evidence**：
- `docs/devlog/2026-09-10-formal-allocation.md`

**Failure Handling**：
- 测试失败修复后重跑；不得以数据入库代替页面可见验收。

**Owner**：AI

**前置**：无

**状态**：进行中