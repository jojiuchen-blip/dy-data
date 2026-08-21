# T5.4 账单异议生命周期

## 任务来源

- 主开发计划：[main-delivery-plan-dy-data.md](main-delivery-plan-dy-data.md)
- 任务看板：[task-kanban-dy-data.md](task-kanban-dy-data.md)

#### T5.4 完成门店异议提交、撤回与管理员内部处理

**Requirement ID**：DYDATA-19-DISPUTE

**PRD 双链·读**：
- `docs/prd/subprd/08-subprd-finance-disputes.md` §3～§4
- `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md` §3

**核心逻辑**：
- 实现接口 #26～#28、#35～#36；异议状态为待处理、审核中、待管理员审批、成立并调整、不成立、撤回。
- 异议只冻结本费用方向；两个方向均不互相阻断。成立并调整同事务生成新账单版本，旧版本与旧确认永久保留。
- 结果前撤回解除冻结；结果后撤回不逆转金额调整，纠正必须新建异议；手机号加密存储、脱敏展示。

**核心文件**：
- `apps/api/dy_api/routes/`
- `apps/api/dy_api/schemas.py`
- `apps/worker/settlement.py`
- `tests/test_data_settlement.py`
- `tests/`

**完成标准**：
- 5 个接口覆盖四类异议、订单归属校验、证明对象键、状态并发、结果前后撤回及方向隔离。
- 成立调整能回读新账单版本，旧账单、旧确认、异议和审计均可追溯。
- 管理员处理页不存在“外部结果”字段或不需要的结果枚举。

**Verification Method**：
- TDD 执行 API 与结算版本测试；并发提交同一读取版本只允许一个成功，另一请求返回 409。

**Evidence**：
- `docs/devlog/` 中 T5.4 状态迁移、账单版本与并发测试记录。

**Failure Handling**：
- 订单无法精确映射到账单版本时 422，不按名称、金额或月份猜测。
- 新账单版本生成失败时异议状态、调整和审计全部回滚。
- 证明资料尚未取得受控对象键时不接受正式提交。

**完成收尾：状态同步**：
- 完成实现、验证与 Foundation 漂移判断后，把完成事实、证据、日期、漂移结论和建议下一 Task 提交给 `ai-project-manager`；由其同步主计划、看板和本子计划并重跑 S4 路由检查。三处未同步前不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T5.1、T5.2

**状态**：进行中
