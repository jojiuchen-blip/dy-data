# T0.3 DYDATA-14 总部线索池验收

## 任务来源
- 主开发计划：[main-delivery-plan-dydata-clue-platform-completion.md](main-delivery-plan-dydata-clue-platform-completion.md)
- 任务看板：[task-kanban-dydata-clue-platform-completion.md](task-kanban-dydata-clue-platform-completion.md)

#### T0.3 核验总部池原因、权限和指标隔离

**Requirement ID**：DYDATA-14

**PRD 双链·读**：
- `docs/prd/foundation/foundation-schema-clue-center/clue_headquarters_pool_entry.md`
- `docs/prd/foundation/foundation-api-clue-center/allocation-runtime-and-headquarters.md`

**核心逻辑**：无锚点或策略耗尽进入总部池；总部池不属于门店、不进入门店指标；门店不可查看明文或登记跟进；终态关闭。

**核心文件**：`apps/api/dy_api/routes/clues.py`、`apps/web/src/pages/ClueCenterPage.tsx`、`tests/test_clue_headquarters_pool.py`、`tests/test_api_clue_allocation_m3.py`。

**完成标准**：最高管理员可按原因/时间/状态查看，总部池权限和门店指标隔离经 API 与前端契约验证。

**Verification Method**：`python -m pytest tests/test_clue_headquarters_pool.py tests/test_api_clue_allocation_m3.py tests/test_frontend_clue_allocation_m3.py -v`

**Evidence**：2026-08-31：修复 `get_current_admin` 角色校验；H01 对齐 `entry_status/reason_code/normalized_order_status/city_code/q`，标准化 8 类入池原因且保留历史原值；门店即使被误授 D08 仍返回 403。总部池/API/前端专项 22 项通过，权限与引擎回归 36 项通过，Web production build 通过。提交：`d784db1`、`e84449c`。

**Failure Handling**：任一手机号泄露或门店可写总部池即阻断完成。

**完成收尾：状态同步**：完成后同步三份计划并切换 T0.4。

**Owner**：主代理 -> Human Owner 验收

**前置**：T0.2

**状态**：已完成（2026-08-31）
