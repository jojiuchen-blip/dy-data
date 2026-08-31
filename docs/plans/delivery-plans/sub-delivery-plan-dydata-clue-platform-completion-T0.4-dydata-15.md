# T0.4 DYDATA-15 规则版本与管理控制台验收

## 任务来源
- 主开发计划：[main-delivery-plan-dydata-clue-platform-completion.md](main-delivery-plan-dydata-clue-platform-completion.md)
- 任务看板：[task-kanban-dydata-clue-platform-completion.md](task-kanban-dydata-clue-platform-completion.md)

#### T0.4 核验规则草稿、版本、发布和权限

**Requirement ID**：DYDATA-15

**PRD 双链·读**：
- `docs/prd/foundation/foundation-api-clue-center/allocation-runtime-and-headquarters.md`
- `docs/prd/foundation/foundation-api-clue-center/jobs-security-and-migration.md`

**核心逻辑**：最高管理员可配置固定轮次模板参数、发布/退役版本并审计；普通管理员只读；门店无入口；高风险动作有确认。

**核心文件**：`apps/api/dy_api/routes/admin.py`、`apps/worker/clue_allocation_cycles.py`、`apps/web/src/pages/AdminClueAllocationPage.tsx`、`tests/test_api_clue_allocation_m3.py`、`tests/test_frontend_clue_allocation_m3.py`。

**完成标准**：版本状态机、权限、审计和页面工作流符合已确认口径，且不自动开启分配/再分配。

**Verification Method**：`python -m pytest tests/test_api_clue_allocation_m3.py tests/test_api_clue_rule_versions.py tests/test_clue_allocation_cycles.py tests/test_frontend_clue_allocation_m3.py -q`；线索、账号和权限宽回归；`python -m pytest tests/test_alembic_migrations.py -q`；`npm --prefix apps/web run build`。

**Evidence**：
- 2026-08-31：补齐 cycle/item/candidate 证据模型、预览签名、幂等冲突、试运行详情、决策候选、规则绑定、操作审计和 D05-D08 范围权限；试运行不创建正式轮次，也不改变线索业务状态。
- 旧 `/sync/clue-center/rebuild` 入口已移除；普通管理员只读，最高管理员写操作均记录操作者、角色、范围、请求 ID 和前后快照；自动失效默认关闭。
- 专项 `35 passed`；线索、账号和权限宽回归 `266 passed`；Alembic `48 passed`；Web production build 通过；`git diff --check` 通过（仅换行提示）。
- 自动正式分配与自动再分配仍保持关闭；旧引擎创建路径作为 DYDATA-34 的唯一下一阶段阻断项处理。

**Failure Handling**：发现普通管理员可写或发布后隐式触发分配时阻断完成。

**完成收尾：状态同步**：完成后同步三份计划并切换 T1.1。

**Owner**：主代理 -> Human Owner 验收

**前置**：T0.3

**状态**：已完成（2026-08-31）
