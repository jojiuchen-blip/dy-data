# T4.1 端到端核验与生产发布

## 任务来源

- 主开发计划：[main-delivery-plan-dy-data.md](main-delivery-plan-dy-data.md)
- 任务看板：[task-kanban-dy-data.md](task-kanban-dy-data.md)

#### T4.1 完成数据正确性、权限、全量回归、部署与业务验收闭环

**Requirement ID**：DYDATA-RELEASE

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` §4-§6
- `docs/prd/foundation/foundation-delivery-dy-data.md` 的已确认边界与未关闭依赖
- 4 份 subprd 的验收章节
- Linear DYDATA-1/21/30/31/33/38 的验收标准和风险

**核心逻辑**：
- 将数据库迁移、商品同步、费率发布、双费用计算、调整、账单投影、API、Web 与权限串成一条可复现验收链。
- 使用脱敏样例和目标环境数据做数量与金额对照；将外部依赖、剩余异常和排除记录显式写入验收。
- 按 runbook 执行目标环境迁移和部署，保留前滚/回退路径；不在本 Task 扩张新功能。

**核心文件**：
- `tests/`
- `alembic/`
- `apps/api/`
- `apps/worker/`
- `apps/web/`
- `deploy/`
- `docs/runbook.md`
- `docs/api-contract.md`
- `docs/devlog/`

**完成标准**：
- 外部商品 API 成功/空页/错误样例、稳定归属账号 ID、真实渠道枚举和 DYDATA-32 最终权限矩阵均有证据，或 Owner 书面接受明确受限发布。
- 迁移前后订单/券行数、内部 ID、孤儿、重复采集、结算明细和关键金额对照通过；异常/排除记录有原因和处置。
- 财务样例覆盖正常、日级多费率、部分退款、全额退款、取消核销、锁账后调整；运营/门店角色覆盖榜单、单店、下钻、导出和开票只读边界。
- 全量 pytest、Web build、三档浏览器、目标环境 migration、CI/deploy、API/Web smoke test 通过；回退步骤可执行。
- 测试、commit/PR/CI/部署、业务验收和剩余风险回填 Linear，用户或责任人接受后才可 Done。

**Verification Method**：
- 执行 `git diff --check`、`python -m pytest`、`npm --prefix apps/web run build`、治理和计划一致性校验。
- 在目标环境执行 `alembic upgrade head`、采集/同步/结算 smoke、5 个目标查询/导出入口和四页浏览器核验；记录 CI/部署日志与恢复演练。

**Evidence**：
- `docs/devlog/` 当日发布记录、`pwScreenShot/` 最终截图、Linear 验证评论、commit/PR/CI/deploy 链接和脱敏 SQL/样例对照摘要。

**Failure Handling**：
- 任一数据正确性、权限、迁移或外部依赖闸门未通过即阻断生产放行，不用“代码完成”替代业务验收。
- 生产迁移或 smoke 失败按 runbook 前滚修复/回退，保留日志和影响范围；不得直接修改历史迁移或生产数据掩盖问题。
- 新问题拆分 Linear follow-up，明确是否阻断当前发布；未接受剩余风险不得关闭主 issue。

**完成收尾：状态同步**：
- 完成实现、验证和 foundation 漂移判断后，将完成事实、证据、日期、漂移结论和建议下一 Task 提交给 `ai-project-manager`，由其调度 `delivery-planner` 同步主计划、看板和本子计划；同时回填各 Linear issue 的测试、PR/commit、CI/部署和剩余风险。未完成三处状态同步与用户验收不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T3.1、T3.2、T3.3；外部生产依赖关闭

**状态**：进行中（等待外部依赖）；依赖关闭前仅进行发布准备，不执行生产迁移或部署
