# T5.2 门店确认与推广费发票登记

## 任务来源

- 主开发计划：[main-delivery-plan-dy-data.md](main-delivery-plan-dy-data.md)
- 任务看板：[task-kanban-dy-data.md](task-kanban-dy-data.md)

#### T5.2 完成门店账单、分方向确认与系统外发票登记

**Requirement ID**：DYDATA-19-STORE-BILLING

**PRD 双链·读**：
- `docs/prd/subprd/02-subprd-store-settlement.md` §3～§4
- `docs/prd/subprd/04-subprd-invoice-registration.md` §3～§4
- `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md` §2、§4.1～§4.2

**核心逻辑**：
- 实现接口 #23～#25、#29～#30；确认成功时间取服务端校验无误后的时间，推广费与管理费确认互不阻断。
- 推广费只登记系统外开票事实；校验 20 位号码、可覆盖多个完整账期的分配集合、当前账单版本和有效确认金额。
- 发票初始状态为 `SUBMITTED_PENDING_FACTORY_REVIEW`；驳回后重新登记生成新版本并保留事件历史。

**核心文件**：
- `apps/api/dy_api/routes/dashboard.py`
- `apps/api/dy_api/routes/`
- `apps/api/dy_api/schemas.py`
- `apps/api/dy_api/main.py`
- `tests/test_api_dashboard.py`
- `tests/`

**完成标准**：
- 6 个接口覆盖正常、空数据、无权、422、409、幂等重放和提交后回读。
- 系统不产生申请单、真实开票、验真、企业微信发送或系统内厂端审核任务。
- 一个门店一个账期仅有一条当前有效推广费发票分配；历史版本和四态事件可查询。

**Verification Method**：
- TDD 执行新增 API 测试；使用真实 FastAPI 应用验证门店范围、确认后登记、驳回重登和版本冲突。

**Evidence**：
- `docs/devlog/` 中 T5.2 的接口响应、数据库回读与测试记录。

**Failure Handling**：
- 账单金额、版本或门店范围无法由后端确认时拒绝写入，不用前端值兜底。
- 幂等键相同但内容不同返回冲突；事务失败时确认/发票/事件/审计全部回滚。
- 契约与 Foundation 冲突时先登记漂移并停止扩展接口。

**完成收尾：状态同步**：
- 完成实现、验证与 Foundation 漂移判断后，把完成事实、证据、日期、漂移结论和建议下一 Task 提交给 `ai-project-manager`；由其同步主计划、看板和本子计划并重跑 S4 路由检查。三处未同步前不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T5.1

**状态**：已完成（2026-08-21）
