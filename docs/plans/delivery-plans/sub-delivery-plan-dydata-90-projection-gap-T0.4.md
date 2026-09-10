# T0.4 DYDATA-90 缺中心投影回补

- 主开发计划：[main-delivery-plan-dydata-90-projection-gap.md](main-delivery-plan-dydata-90-projection-gap.md)
- 任务看板：[task-kanban-dydata-90-projection-gap.md](task-kanban-dydata-90-projection-gap.md)

#### T0.4 有界中心投影回补与首次正式分配

**Requirement ID**：DYDATA-90

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` §1
- `docs/brd/BRD-clue-center-20260721-2134.md` §3
- `docs/prd/foundation/foundation-api-clue-center/jobs-security-and-migration.md` J01、J03
- `docs/prd/foundation/foundation-api-clue-center/lead-query-and-contact.md` 状态解析约束

**核心逻辑**：
- 增量物化只消费当前 JobImpact closure 时，正式分配补偿批次按独立持久 cursor 扫描缺中心的 active/pending 主线索，每批最多 100 条。
- 回补先复用 `materialize_clue_master_leads`，再复用 `refresh_clue_center_projection`；物化器继续负责来源时间、防旧快照覆盖、订单/券/核销状态解析。
- 回补后仍通过原 `_eligible()`，保留中心存在、有效券证据、无 formal/legacy 历史轮次、非总部池、无当前轮次及首次分配防重门禁。
- 回补与首次分配共享排他锁和批次 deadline；超时或异常不前移 cursor，批次结果记录 `center_repair_scanned`、`center_repair_deferred`、`center_repair_failed`。

**核心文件**：
- `apps/worker/formal_allocation_runtime.py`
- `apps/worker/clue_allocation.py`
- `apps/worker/clue_center.py`
- `tests/test_formal_allocation_runtime.py`
- `tests/test_formal_allocation_runtime_postgres.py`

**完成标准**：
- 支付成功且有有效券证据的缺中心订单创建中心行并进入正式分配。
- 支付成功但无券、退款、核销、关闭、旧终态快照及已有 formal/legacy 轮次均不误入。
- 首次分配重跑不创建重复正式轮次；cursor 能越过不可处理行并回绕。
- 不改 API 路由、前端和生产数据；不取消总部池限制、重复分配保护或券证据检查。

**Verification Method**：
- `python -m pytest -q tests/test_formal_allocation_runtime.py`
- `DYDATA_CLUE_TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55490/dydata_formal_test python -m pytest -q tests/test_formal_allocation_runtime_postgres.py -k missing_center_with_coupon`
- `python -m pytest -q tests/test_clue_allocation_eligibility.py tests/test_formal_allocation_runtime.py tests/test_worker_clue_center.py`
- `git diff --check`

**Evidence**：
- 实现提交：`c69072ec53ba40ae4392b3d7ce0ac71c370c8290`
- 本次增补的 PostgreSQL 回归在独立 schema 中通过；测试命令与结果记录于交接消息。

**Failure Handling**：
- 物化锁、投影、游标或数据库阶段超时不执行后续首次分配；已投影的既有中心行仍可继续走正式分配。
- 缺来源、来源冲突或当前证据不足的行保留待复核，不手工写入中心事实；cursor 在可安全推进的页尾更新并于末尾回绕。

**Owner**：AI

**前置**：DYDATA-90 T0.3 正式分配闭环

**状态**：进行中

**完成收尾：状态同步**：
- 代码、专项 SQLite 回归和独立 PostgreSQL 缺中心回归已完成；等待主代理整合提交和最终状态回写。
- 本任务不修改 API 路由、前端、全局 cockpit 或生产数据。
