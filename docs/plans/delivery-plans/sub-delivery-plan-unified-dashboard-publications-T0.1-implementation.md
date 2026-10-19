# T0.1 统一静态发布实现

## 任务来源

[主计划](main-delivery-plan-unified-dashboard-publications.md) / [看板](task-kanban-unified-dashboard-publications.md)

#### T0.1 统一静态发布实现

**Requirement ID**：PUB-01 至 PUB-07

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` 全局设计规则
- `docs/prd/foundation/foundation-api-dy-data/common-contract.md`
- `docs/prd/foundation/foundation-api-dy-data/settlement-reporting.md`
- `docs/api/dashboard-publications.md` 用户确认增量与实现契约

**核心逻辑**：
- 后台构建不可变分析版本，完整提交后切换；页面筛选、排序、分页和导出只读取指定版本。
- 分析展示接统一元数据；操作状态保留即时读写。每个请求仍执行当前权限判断。
- 五分钟后台刷新、导入变更尽早处理，失败保留旧版；保留两版及显式关键版本，读取与清理互斥。
- 各独立模块新文件实现后由主代理串行接入共享 routes，避免并行覆盖。

**核心文件**：
- 新增 `apps/api/dy_api/dashboard_publications/` 与新 Alembic 迁移
- 新增 `apps/worker/dashboard_publications.py`
- `apps/api/dy_api/routes/dashboard.py`、`routes/clues.py`、`routes/_data.py`
- `apps/web/src/pages/`、`apps/web/src/api/client.ts`、`apps/web/src/types/dashboard.ts`
- `tests/test_dashboard_publications.py` 及模块对照测试

**完成标准**：
- 静态读请求不调用源事实解释器、构建器或写事务；无版本与过期版本返回可识别状态。
- 查询结果、图表、筛选元数据、导出带同一版本；日期、订单去重与分位对照测试通过。
- 现有门店授权及 A03 全局可见例外保持；发布 ID 不能扩大权限。
- 失败不切换 active，清理不删除 active、pin、读取中的版本或业务事实。
- 页面区分数据截至、结果更新、更新中和失败；全年为所选年度，另有全部历史。

**Verification Method**：定向 pytest；前端 build；新模块真实 PG 测试；GET 禁止构建哨兵测试。

**Evidence**：`docs/devlog/20261019_unified_dashboard_publications.md`。

**Failure Handling**：口径对照失败保留旧读链且不发布；实现缺口记录在日志，不掩盖为完成。

**Owner**：Codex 主代理负责集成；隔离 worker 负责指定写集合；人类 Owner 审核

**前置**：用户已审阅方向并确认开发；代码基线处理完成

**状态**：进行中

**完成收尾：状态同步**：
完成实现、验证和 foundation 漂移判断后，将 Task 完成事实、验证证据、日期、漂移结论与建议下一 Task 提交 ai-project-manager；由其调度 delivery-planner 同步主计划、看板和子计划。重跑 `node .agent/project-manager-suite/tools/route-check.mjs . --target-stage S4 --json`；未完成同步不得标记完成。
