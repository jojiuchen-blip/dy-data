# T0.1 9 月来源追查、账单生成与验收

## 任务来源

- Linear：[DYDATA-102](https://linear.app/keith-lim/issue/DYDATA-102/核查并修复推广服务费账期总览与订单明细不一致)
- 主开发计划：[main-delivery-plan-dydata-102-september.md](main-delivery-plan-dydata-102-september.md)
- 任务看板：[task-kanban-dydata-102-september.md](task-kanban-dydata-102-september.md)

### T0.1 修复 2026-09 推广费账期未形成

**Requirement ID**：DYDATA-102

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` 财务/结算目标
- `docs/prd/subprd/02-subprd-store-settlement.md` §3–§4：月度账单、无数据状态与账期展示
- `docs/prd/subprd/05-subprd-finance-promotion.md` §3：按账期总览
- `docs/prd/subprd/03-subprd-order-fee-details.md` §§4.2–4.6：核销月、费用来源与明细验收
- `docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md` §9、`docs/prd/foundation/foundation-schema-dy-data/billing-invoice.md`：冻结来源包和账单版本保护
- `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md` §2、`docs/prd/foundation/foundation-api-dy-data/settlement-reporting.md` §§1–4：账单生成、总览、明细、导出

**核心逻辑**：
- 先沿有效核销订单 → 当前佣金结果 → 月度投影 → 冻结账单来源 → `SettlementStatement` 当前版本 → 财务总览/明细/导出逐层核验 2026-09 的行数和金额，定位首次偏离处。
- 费用原始归属使用有效核销月份；退款/取消/重核销调整按事件月；禁止按销售月或累计总额直接补记。
- 如果现有生产安全重建入口覆盖范围过宽，先评估月份范围与保护事实，再决定代码最小改动；不得为触发任务而改分佣规则或直接写 SQL。
- 数据源必须由实际当前指针与公开账单/财务 API 对照；生产只读证据脱敏。
- 技术根因与操作范围由 DSH 取证、Codex 独立复核；金额、账期与是否形成非零结果由用户验收。

**核心文件**：
- `apps/worker/scheduler.py`
- `apps/worker/settlement_rebuild.py`
- `apps/worker/billing_source_capture.py`
- `apps/worker/billing_statements.py`
- `apps/worker/settlement.py`
- `apps/api/dy_api/routes/fee_admin.py`
- `apps/web/src/pages/AdminSkuRulesPage.tsx`
- `tests/test_billing_statement_generation.py`
- `tests/test_settlement_generation_api.py`
- `tests/test_worker_collection_pipeline.py`

**完成标准**：
1. 生产只读证据明确 2026-09 当前有效推广费来源/调整的行数与分金额，且账期严格按有效核销月；若无来源，列出阻断原因及符合资格为零的证据，不虚构非零账单。
2. 失败测试或可复现操作证明首个数据偏离点及原因；只有在根因证实后才改代码。
3. 若存在符合资格来源，2026-09 当前正式待确认账单包含对应门店/来源，逐门店及全局的源行、投影、账单行和金额一致；2026-10 数据仍归 2026-10。
4. 重跑生成流程不会重复累计、重复账单或无意义递增版本；同源重试保持幂等。
5. 已确认、锁账、存在发票或受保护异议的账单及历史版本保持不变；系统不自动确认或开票。
6. 财务总览、订单明细分页与全量导出在相同月份/方向/筛选下行数和金额一致。
7. 相关专项测试、`python -m pytest`、必要时 Web build 与 `git diff --check` 通过；生产发布后的只读核验留存请求范围、响应摘要、行数和金额，不记录可识别订单/门店标识。
8. 由用户确认业务结果后，DYDATA-102 才能关闭。

**Verification Method**：
- 首选现有 pytest：`tests/test_billing_statement_generation.py`、`tests/test_settlement_generation_api.py`、`tests/test_worker_collection_pipeline.py`。
- 加入针对核实根因的失败测试，覆盖 2026-09 资格来源、冲正/退款、保护状态、重复重跑和 2026-10 边界。
- 目标环境通过已认证只读页面/API核对 2026-09 总览、当前账单、订单明细和完整导出；生产生成只使用审阅后的受控任务路径。

**Evidence**：
- `docs/devlog/20261008_dydata-102-september-billing.md`
- Linear DYDATA-102 验证记录

**Failure Handling**：
- DSH 工作区未恢复时不得声称 DSH 执行；将失败记录给用户并停留在审阅阶段。
- 若来源、投影、账单三者金额不一致，停止生产生成与部署，返回首次偏离层继续排查。
- 若触发范围超出 2026-09 且无法证明保护边界，禁止触发全局任务；实现窄范围入口后重新审核。
- 若 2026-09 来源为零，仅报告证据与订单资格原因，不得用累计金额或人工 SQL 填充。

**完成收尾：状态同步**：
- 完成实现、验证和 foundation 漂移判断后，将完成事实、验证证据、日期、foundation 漂移结论及建议下一 Task 提交给 `ai-project-manager`。
- 由 `ai-project-manager` 调度 `delivery-planner` 同步主计划、看板和本子计划状态。
- 同步后运行 `node .agent/project-manager-suite/tools/route-check.mjs . --target-stage S4 --json`，确认正式计划文件组一致；未完成状态同步前不得标记 Task 完成。

**Owner**：DSH 执行 → Codex 技术验收 → 用户业务审核与验收

**前置**：DYDATA-102 In Progress；用户明确审阅通过；DSH 工作区连接可用；生产目标查询凭证在原运行环境可读。

**状态**：进行中
