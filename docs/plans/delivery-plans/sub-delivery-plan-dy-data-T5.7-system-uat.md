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
- 仅在验证证据、剩余风险和用户接受均回填后关闭 DYDATA-19。

**核心文件**：
- `tests/`
- `apps/api/`
- `apps/web/`
- `alembic/`
- `docs/devlog/`
- `pwScreenShot/`

**完成标准**：
- 最低验收矩阵覆盖系统外开票边界、推广费四态、管理费当期导入上期、两个方向互不阻断、成立异议新账单版本、四类导入五结果和版本冲突。
- `python -m pytest`、Web build、治理/计划检查、目标数据库升级、真实浏览器和 smoke test 全部通过。
- Linear 回填测试、commit/PR/CI/部署或未部署原因、UAT 结论和剩余风险；责任人接受后才可 Done。

**Verification Method**：
- 执行 `git diff --check`、`python -m pytest`、`npm --prefix apps/web run build`、治理门禁、计划一致性和目标环境 smoke。
- 按 UAT 脚本分别以门店账号和管理员角色完成端到端操作并核对审计记录。

**Evidence**：
- `docs/devlog/` 最终系统测试与 UAT 记录、`pwScreenShot/` 最终截图、Linear DYDATA-19 验证评论及 CI/部署链接。

**Failure Handling**：
- 任一数据正确性、权限、迁移、并发或原子性场景失败即阻断发布与关闭。
- 无目标环境或业务样例时只报告本地完成，不把缺失证据写成已验收。
- 新发现问题按是否阻断拆分 Linear follow-up，并保留主 Issue 风险记录。

**完成收尾：状态同步**：
- 完成系统测试、UAT 和 Foundation 漂移判断后，把完成事实、证据、日期、漂移结论和关闭建议提交给 `ai-project-manager`；由其同步主计划、看板、本子计划及 Linear，并重跑 S4/Done 门禁。三处未同步且用户未接受前不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T5.1～T5.6

**状态**：待审阅
