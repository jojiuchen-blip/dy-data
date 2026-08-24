# T5.7 系统测试与用户验收

## 任务来源

- 主开发计划：[main-delivery-plan-dy-data.md](main-delivery-plan-dy-data.md)
- 任务看板：[task-kanban-dy-data.md](task-kanban-dy-data.md)

#### T5.7 完成 DYDATA-19 系统回归与用户验收闭环

**Requirement ID**：DYDATA-19-UAT

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` §4～§6
- `docs/prd/prd-feature-list-dy-data.md` 的 9 个已确认功能块
- `docs/prd/foundation/foundation-delivery-dy-data.md`
- Linear DYDATA-19 验收标准

**核心逻辑**：
- 串联账单生成/版本、分方向确认、异议、推广费登记、管理员状态/管理费导入、指标查询、订单穿透和审计。
- 系统测试覆盖功能、权限、并发、原子性、迁移、响应式和回归；UAT 由门店和财务管理员按真实业务样例确认。
- 系统验收发现 Linear 正文与既有 T5.2～T5.6 计划存在实现差额时，以 Linear 当前正文为准，在本 Task 内先以 TDD 关闭发布阻塞项，再重跑三层验收。
- 仅在验证证据、剩余风险和用户接受均回填后关闭 DYDATA-19。

**核心文件**：
- `tests/`
- `apps/api/`
- `apps/web/`
- `alembic/`
- `docs/devlog/`
- `output/playwright/`

**完成标准**：
- 最低验收矩阵覆盖系统外开票边界、推广费四态、管理费当期导入上期、两个方向互不阻断、成立异议新账单版本、四类导入五结果和版本冲突。
- 发布阻塞差额全部关闭：推广费购买方/6% 税率、10/11 日批次边界、红冲/作废/替换重开、负数账期结转；锁定月退款/取消核销顺延；管理费直接更正；SAP 建议/确认；逐业务键导入反向批次；历史门店/SAP 快照；订单明细完整字段/筛选/导出。
- `python -m pytest`、Web build、治理/计划检查、目标数据库升级、真实浏览器和 smoke test 全部通过。
- Linear 回填测试、commit/PR/CI/部署或未部署原因、UAT 结论和剩余风险；责任人接受后才可 Done。

**Verification Method**：
- 执行 `git diff --check`、`python -m pytest`、`npm --prefix apps/web run build`、治理门禁、计划一致性和目标环境 smoke。
- 按 UAT 脚本分别以门店账号和管理员角色完成端到端操作并核对审计记录。

**Evidence**：
- `docs/uat/dydata-19-uat-checklist.md` 业务验收矩阵、`docs/devlog/` 最终系统测试记录、`output/playwright/` 最终截图、Linear DYDATA-19 验证评论及 CI/部署链接。

**Failure Handling**：
- 任一数据正确性、权限、迁移、并发或原子性场景失败即阻断发布与关闭。
- 无目标环境或业务样例时只报告本地完成，不把缺失证据写成已验收。
- 新发现问题按是否阻断拆分 Linear follow-up，并保留主 Issue 风险记录。

**完成收尾：状态同步**：
- 完成系统测试、UAT 和 Foundation 漂移判断后，把完成事实、证据、日期、漂移结论和关闭建议提交给 `ai-project-manager`；由其同步主计划、看板、本子计划及 Linear，并重跑 S4/Done 门禁。三处未同步且用户未接受前不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T5.1～T5.6

**状态**：进行中（2026-08-24；Owner 已授权在全部硬门禁通过后无需二次确认，直接执行生产迁移与部署；任一硬门禁失败仍停止发布）

**最新验证**：G1a、G0、G1b/G1c、G2 与 G3 已完成并通过独立代码审查。G3 已关闭账单 Vn+1 明细快照继承、历史明细快照回填/异常清单和部署前异常归零门禁；迁移隔离专项 `3 passed`，Alembic/部署/前端契约完整相关回归 `52 passed`，Web build、Alembic 单头 `20260824_0043` 和 `git diff --check` 通过，定向复审为 Critical 0、Important 0、`Ready: yes`。当前进入最新主线干净集成、财务迁移链重建和发布前全量门禁；目标 PostgreSQL 真实升级与两会话并发仍为发布阻断条件。
