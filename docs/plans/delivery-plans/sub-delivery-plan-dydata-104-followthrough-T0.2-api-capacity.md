# T0.2 API 内存归因与限额验证

## 任务来源

- [主计划](main-delivery-plan-dydata-104-followthrough.md) / [任务看板](task-kanban-dydata-104-followthrough.md)
- [DYDATA-104](https://linear.app/keith-lim/issue/DYDATA-104)

### T0.2 API 内存归因与限额验证

**Requirement ID**：DYDATA-104 A

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` 全局规则
- `docs/prd/subprd/02-subprd-store-settlement.md` §3–4
- `docs/prd/subprd/03-subprd-order-fee-details.md` 筛选与导出
- `docs/prd/subprd/05-subprd-finance-promotion.md` §3
- `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md` 账单/财务契约
- `docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md` 费用、调整与冻结来源
- `docs/api/dashboard-publications.md` 不可变发布与读取

**核心逻辑**：历史证据已证明 768 MiB API cgroup OOM，未证明具体接口。补充有界请求开始/结束观测，仅记录内部请求 ID、路由模板、进程 RSS、并发数和耗时，禁止 query/body/令牌/业务 ID。结合静态读取与导出的合成真实规模复现，找到峰值后最小修复；不得把增加内存或 HTTP 200 当作根因验收。

**核心文件**：
- `apps/api/dy_api/main.py`
- `apps/api/dy_api/dashboard_publications/`
- `apps/api/dy_api/ranking_export.py`
- `deploy/compose.yaml`
- `tests/`

**完成标准**：请求开始记录在可能的 OOM 前留下；成功、异常、断连后并发计数正确回收；日志无敏感字段且轮转有界。768 MiB 隔离容器内测代表性读/筛选/导出并发峰值，报告样本规模、基线、峰值、耗时与限制。没有复现则明确不确认历史事故根因。

**Verification Method**：ASGI 单元/集成测试、隔离容器合成数据峰值测量、既有静态发布回归；生产仅小范围只读请求和日志核对。

**Evidence**：`docs/devlog/20261020_dydata-104-followthrough.md`，对应最终 CI 与脱敏运行记录。

**Failure Handling**：证据不符、资源/配额不足或保护指纹变化时停止相关写入；保留真实状态并记录具体阻碍，不绕过门禁。未满足验收不标记完成。

**完成收尾：状态同步**：核对验证与 foundation 漂移；新增契约缺口只追加待改请求。由 ai-project-manager 调度 delivery-planner 同步主计划、看板、子计划与执行驾驶舱，重跑一致性和 route-check；生产结果没有实证时不能写完成。

**Owner**：Codex 执行与独立复核 → 用户业务验收

**前置**：统一 main；T0.1 可独立

**状态**：进行中

