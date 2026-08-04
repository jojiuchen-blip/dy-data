# T1.1 线索主档稳定关联与多标识历史

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-56-clue-identity-history.md](main-delivery-plan-dydata-56-clue-identity-history.md)
- 任务看板：[task-kanban-dydata-56-clue-identity-history.md](task-kanban-dydata-56-clue-identity-history.md)

#### T1.1 修复来源身份变化导致的物化阻断，并持久化历史标识

**Requirement ID**：DYDATA-56

**PRD 双链·读**：

- Linear `DYDATA-56` 的问题、范围、风险和验收标准。
- `docs/prd/foundation/foundation-schema-clue-center/clue_master_lead.md` 的稳定 `lead_key`、一主档多来源记录和迁移说明。
- `docs/prd/foundation/foundation-schema-clue-center/clue_source_record_link.md` 的原始记录唯一映射、版本和可追溯要求。

**核心逻辑**：

- 物化时优先用稳定的 `source_clue_row_key` 定位已有主档，再使用可变身份和代表性 `clue_id` 作为兼容回退。
- 同一来源记录和订单即使出现新的 `clue_id` 或 `source_identity_key`，也必须保持原 `lead_key`、订单、轮次、总部池和跟进关系。
- 新增来源标识历史表，分别记录 `clue_id` 与 `source_identity_key` 的历史值、首次/最近观测时间和当前状态；同一值重复物化必须幂等。
- `canonical_clue_id` 继续作为当前代表值，但不得覆盖或替代标识历史。
- 不改变订单状态机、分配策略、轮次创建、总部池规则、联系方式权限或前端字段。

**核心文件**：

- `apps/api/dy_api/models.py`
- `apps/worker/clue_allocation.py`
- `alembic/versions/20260804_0029_clue_source_identifier_history.py`
- `tests/test_clue_allocation_m1.py`
- `tests/test_alembic_migrations.py`

**完成标准**：

- 先观察到回归测试在旧代码上因重复来源记录主档或缺少历史表而失败。
- 同一 `source_clue_row_key` 的 `clue_id` 和身份键变化后，主档数量仍为 1，`lead_key` 不变且物化不抛唯一约束异常。
- 历史表同时保留新旧 `clue_id` 和新旧 `source_identity_key`，重复运行不产生重复记录。
- 不同来源记录或不同订单不得仅因可变身份相同而被静默合并。
- Alembic 升级、降级、单 head、聚焦回归、全量后端测试和 Web production build 均通过。

**Verification Method**：

- `python -m pytest tests/test_clue_allocation_m1.py -k "source_identity_history or source_row" -v`
- `python -m pytest tests/test_alembic_migrations.py -k clue_source_identifier_history -v`
- `python -m alembic heads`
- `git diff --check`
- `python -m pytest`
- `npm --prefix apps/web run build`

**Evidence**：

- 旧代码回归测试稳定复现 `uq_clue_master_leads_source_clue_row_key` 唯一约束冲突；修复后同一来源行变更 `clue_id` 和身份键仍保持一个主档与同一 `lead_key`。
- `tests/test_clue_allocation_m1.py` 25 项通过；线索相关测试 266 项通过；Alembic 迁移测试 24 项通过。
- 全量 `python -m pytest`：1160 passed、2 skipped；`npm --prefix apps/web run build` 通过。
- `python -m alembic heads` 返回唯一 head `20260804_0029`；`git diff --check` 通过。
- 生产部署与重建后的最新线索时间、失败窗口和主档计数作为独立生产证据追加到同一 issue。

**Failure Handling**：

- 如果新身份已绑定其他订单主档，停止自动合并并保留可诊断冲突，不覆盖现有轮次或跟进关系。
- 如果迁移无法无损回填现有主档标识，停止部署，不删除原列或唯一约束。
- 如果全量测试或构建失败，不提交完成状态；只修复与本任务直接相关的回归。

**完成收尾：状态同步**：

- 完成实现、验证和 foundation 漂移判断后，把完成事实、证据、日期、漂移结论和生产剩余步骤提交给 `ai-project-manager`。
- 由 `ai-project-manager` 调度 `delivery-planner` 同步主计划、任务看板和本子计划状态。
- 同步后重跑 S4 路由和一致性检查；未完成状态同步前不得标记 Task 完成。

**Owner**：AI 执行 -> Human Owner 审核

**前置**：无

**状态**：进行中；本地实现与验证已于 2026-08-04 完成，待提交、部署和生产重建验收
