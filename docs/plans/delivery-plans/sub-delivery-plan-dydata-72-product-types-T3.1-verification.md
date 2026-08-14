# T3.1 集成验证与交付回写子交付计划

## 任务来源

- [主开发计划](main-delivery-plan-dydata-72-product-types.md)
- [任务看板](task-kanban-dydata-72-product-types.md)

#### T3.1 集成验证与交付回写

**Requirement ID**：DYDATA-72-VERIFY-01

**PRD 双链·读**：
- Linear `DYDATA-72` 全部验收标准。
- `docs/prd/mainprd-dy-data.md` 的管理端边界与全局错误/空态规则。
- `docs/prd/foundation/foundation-api-dy-data/common-contract.md`。

**核心逻辑**：
- 验证商品口径更新后线索中心、核销表现和订单分佣继续读取同一 SKU 事实源。
- 验证商品不因商品口径状态被隐藏；订单分佣只在已有有效分佣规则时展示。
- 记录自动化、构建、视觉与剩余风险，回填 Linear，不执行生产部署。

**核心文件**：
- `tests/`
- `apps/web/src/`
- `apps/api/dy_api/`
- `docs/plans/delivery-plans/`

**完成标准**：
- `git diff --check`、完整 pytest、Web build 全部通过。
- 页面 smoke 覆盖待完善、已配置、单个设置、批量设置和导入入口。
- Linear DYDATA-72 记录测试、构建、截图、迁移和剩余风险；不提前关闭 issue。

**Verification Method**：
- 执行 `git diff --check`、`python -m pytest`、`npm --prefix apps/web run build` 与目标 Playwright smoke。

**Evidence**：
- `python -m pytest`：1181 passed、2 skipped、0 failed。
- `npm --prefix apps/web run build`：通过。
- 干净 SQLite 数据库升级至 `20260813_0030 (head)`；商品口径页面 visual smoke 与 `git diff --check` 通过。
- Linear DYDATA-72 评论 `0f9a89de-f2ae-4dba-a7d6-f6467e4385df`。

**Failure Handling**：
- 任一全量回归失败则保留 T4 进行中并定位根因；生产数据或外部部署不可用不以模拟结果冒充完成。

**完成收尾：状态同步**：
- 汇总完成事实、验证证据、日期、Foundation 漂移结论和剩余风险，三处计划状态同步后回填 Linear；由人类 Owner 决定最终验收与关闭。

**Owner**：AI 执行 -> 人审核

**前置**：T2.1

**状态**：已完成（2026-08-14）
