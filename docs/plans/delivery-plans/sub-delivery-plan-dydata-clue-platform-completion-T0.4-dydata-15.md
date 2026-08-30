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

**核心文件**：`apps/api/dy_api/routes/admin.py`、`apps/web/src/pages/AdminClueRulesPage.tsx`、`tests/test_api_clue_allocation_m3.py`、`tests/test_frontend_admin_rules_workflow.py`。

**完成标准**：版本状态机、权限、审计和页面工作流符合已确认口径，且不自动开启分配/再分配。

**Verification Method**：`python -m pytest tests/test_api_clue_allocation_m3.py tests/test_frontend_admin_rules_workflow.py -v`

**Evidence**：2026-08-30：现有专项 16 项通过；独立规格审查确认仍缺新 cycle 详情/快照契约，旧 `/sync/clue-center/rebuild` 仍可达，且 admin 角色校验需收紧。

**Failure Handling**：发现普通管理员可写或发布后隐式触发分配时阻断完成。

**完成收尾：状态同步**：完成后同步三份计划并切换 T1.1。

**Owner**：主代理 -> Human Owner 验收

**前置**：T0.3

**状态**：进行中
