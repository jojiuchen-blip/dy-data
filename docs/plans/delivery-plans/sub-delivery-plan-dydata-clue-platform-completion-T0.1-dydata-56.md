# T0.1 DYDATA-56 主档多标识验收闭环

## 任务来源
- 主开发计划：[main-delivery-plan-dydata-clue-platform-completion.md](main-delivery-plan-dydata-clue-platform-completion.md)
- 任务看板：[task-kanban-dydata-clue-platform-completion.md](task-kanban-dydata-clue-platform-completion.md)

#### T0.1 核验稳定主档和来源标识历史

**Requirement ID**：DYDATA-56

**PRD 双链·读**：
- `docs/prd/foundation/foundation-schema-clue-center/clue_master_lead.md`
- `docs/prd/foundation/foundation-schema-clue-center/clue_source_record_link.md`

**核心逻辑**：稳定来源行和非空订单优先关联原 `lead_key`；同一主档保留多个 `clue_id`/身份版本，重复物化幂等。

**核心文件**：
- `apps/api/dy_api/models.py`
- `apps/worker/clue_allocation.py`
- `alembic/versions/20260804_0029_clue_source_identifier_history.py`
- `tests/test_clue_allocation_m1.py`

**完成标准**：代码、迁移、聚焦/相关回归和当前数据只读证据共同证明不重复主档、不丢历史标识、不跨订单误合并。

**Verification Method**：
- `python -m pytest tests/test_clue_allocation_m1.py -k "source_identity_history or source_row" -v`
- `python -m pytest tests/test_alembic_migrations.py -k clue_source_identifier_history -v`
- `python -m alembic heads`

**Evidence**：2026-08-30：来源行/跨订单冲突 2 项通过；0029 迁移升级/降级 1 项通过；`python -m alembic heads` 返回唯一 `20260824_0043`；模型和物化器均保留来源标识历史映射。

**Failure Handling**：发现身份冲突或生产数据仍阻断时保留 issue 进行中，先修代码，不合并主档数据。

**完成收尾：状态同步**：完成后同步主计划、看板和本子计划，并将 T0.2 切换为进行中。

**Owner**：主代理 -> Human Owner 验收

**前置**：远端 main 同步

**状态**：已完成（2026-08-30）
