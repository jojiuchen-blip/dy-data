# T0.1 DYDATA-91 Clue Visibility Sub Delivery Plan

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-91-visibility.md](main-delivery-plan-dydata-91-visibility.md)
- 任务看板：[task-kanban-dydata-91-visibility.md](task-kanban-dydata-91-visibility.md)

#### T0.1 实现线索可见分配日期下界

**Requirement ID**：DYDATA-91-VISIBILITY-001

**PRD 双链·读**：
- [mainprd-clue-center.md](../../prd/mainprd-clue-center.md)
- [foundation-api-clue-center.md](../../prd/foundation/foundation-api-clue-center.md) Q01/Q02/Q05/Q06/Q07/Q08
- [clue_assignment_round.md](../../prd/foundation/foundation-schema-clue-center/clue_assignment_round.md)
- [clue_center_order.md](../../prd/foundation/foundation-schema-clue-center/clue_center_order.md)
- [lead-query-and-contact.md](../../prd/foundation/foundation-api-clue-center/lead-query-and-contact.md)
- [follow-up-and-rounds.md](../../prd/foundation/foundation-api-clue-center/follow-up-and-rounds.md)

**核心逻辑**：
- 以上海时间 `2026-09-01 00:00:00` 作为正式分配 `assigned_at` 的包含式下界。
- `/clues`、`/clues/details` 对应的 filters、门店选项、overview、轮次分页、CSV、订单详情和脱敏/完整手机号读取使用同一下界。
- 同一订单有新旧轮次时只返回下界内轮次及其跟进记录；只有下界外正式轮次的用户直达详情返回 404，试运行-only 的既有空详情契约保持不变。
- 线索门店汇总使用相同轮次下界；不修改线索来源、首次分配资格、跟进写入、财务查询或后台审计 ORM 路径。
- 前端静态 mock 与 demo repository 使用同一可见判断，并提供 9 月演示样例；演示写入只作用于合成状态。

**核心文件**：
- `apps/api/dy_api/routes/_data.py`
- `apps/web/src/utils/clueVisibility.ts`
- `apps/web/src/api/client.ts`
- `apps/web/src/demo/clueDemoRepository.ts`
- `apps/web/src/demo/clueDemoGenerator.ts`
- `apps/web/src/data/mock/clue_center.json`
- `tests/test_api_clues.py`
- `tests/test_api_product_type_visibility.py`
- `tests/test_clue_store_follow_up_summary.py`

**完成标准**：
- 正式轮次 `2026-08-31 23:59:59` 被 filters、overview、分页、导出、详情和汇总排除。
- 正式轮次 `2026-09-01 00:00:00` 被上述查询保留；8 月来源但 9 月正式分配的订单可见。
- 清空日期筛选和更早日期筛选均不会返回旧正式轮次；同订单旧轮次不进入详情或跟进记录。
- 账号门店范围、试运行隔离、手机号权限和后台审计既有行为保持；财务相关测试不受 clue 下界条件影响。
- API 专项测试、前端 clue 静态契约测试和 web TypeScript/Vite 构建完成并留下结果。

**Verification Method**：
- `python -m pytest -q tests/test_api_clues.py tests/test_clue_store_follow_up_summary.py`
- `python -m pytest -q tests/test_frontend_clue_center.py tests/test_frontend_clue_demo_mode.py tests/test_frontend_clue_allocation_consolidation.py`
- `npm run build`（工作目录 `apps/web`）
- `node .agent/project-manager-suite/skills/05-01-delivery-planner/scripts/validate-plan-structure.mjs docs/plans/delivery-plans/main-delivery-plan-dydata-91-visibility.md`
- `node .agent/project-manager-suite/skills/05-01-delivery-planner/scripts/check-plan-consistency.mjs docs/plans/delivery-plans/main-delivery-plan-dydata-91-visibility.md --json`

**Evidence**：
- API 与汇总专项：`python -m pytest -q tests/test_api_clues.py tests/test_clue_store_follow_up_summary.py`，38 passed。
- 前端 clue 静态契约：`python -m pytest -q tests/test_frontend_clue_center.py tests/test_frontend_clue_demo_mode.py tests/test_frontend_clue_allocation_consolidation.py`，49 passed。
- 合并专项回归：以上 API、汇总和前端测试合并执行，87 passed。
- 相关权限与产品可见性回归：`python -m pytest -q tests/test_api_access_control.py tests/test_api_agent_capabilities.py tests/test_api_clue_phone_resolution.py tests/test_api_clue_scope_regression.py tests/test_api_product_type_visibility.py`，51 passed。
- 时区边界：SQLite 使用真实 UTC 等价时刻 `2026-08-31T15:59:59Z` 隐藏、`2026-08-31T16:00:00Z` 保留；PostgreSQL 分支保留带 `+08:00` 的同一业务时刻，dialect bind 检查通过。
- Web 构建：`npm run build`（`apps/web`），TypeScript 与 Vite 构建通过。
- 计划门禁：`validate-plan-structure.mjs` passed；`check-plan-consistency.mjs --json` passed；隔离 worktree 的 `route-check.mjs --target-stage S4 --json` `canEnter=true`。
- 当前待主代理完成：集成 worktree 合并、全仓回归与最终计划收尾；本子计划保持进行中以便集成阶段继续追踪。

**Failure Handling**：
- 若 API 下界、详情记录过滤或清空筛选任一路径不一致，先定位实际 SQL/前端 repository 调用，不通过测试 mock 关闭生产下界。
- 若 web 依赖缺失，安装锁定依赖后重跑构建并记录实际错误；不以静态检查代替 TypeScript 构建。
- 若计划门禁不一致，只修改本 DYDATA-91 计划组和本分支 cockpit，不回写旧 DYDATA-81/DYDATA-90 计划。

**完成收尾：状态同步**：
- 本 Task 完成实现、验证和 foundation 漂移判断后，把事实、命令结果、commit 和剩余风险提交给主代理。
- 主代理集成前复核实际变更文件、分支隔离和财务/后台审计不受影响；集成后按主任务决定正式计划收尾状态。

**Owner**：本 Task worker 执行 -> 主代理验收集成

**前置**：用户已确认按分配日期显示；主代理已授权隔离实现；DYDATA-90 worker 不修改本 Task 文件。

**状态**：进行中
