# T5.3 管理员财务查询与订单穿透

## 任务来源

- 主开发计划：[main-delivery-plan-dy-data.md](main-delivery-plan-dy-data.md)
- 任务看板：[task-kanban-dy-data.md](task-kanban-dy-data.md)

#### T5.3 提供推广费、管理费、门店与订单的统一财务查询

**Requirement ID**：DYDATA-19-FINANCE-QUERY

**PRD 双链·读**：
- `docs/prd/subprd/05-subprd-finance-promotion.md` §3
- `docs/prd/subprd/06-subprd-finance-management.md` §3
- `docs/prd/subprd/07-subprd-finance-store-info.md` §3
- `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md` §4.3

**核心逻辑**：
- 实现接口 #31～#34，费用方向强制单选，单月/累计从服务端聚合；正式累计从 2026-08 开始。
- 推广费按四态聚合；管理费已开票金额与厂家扣款金额使用同一当前有效事实，导入时间即审核通过/已结算时间。
- 门店 ID 是唯一匹配键，SAP 编码和名称只展示；订单明细按费用方向分开消费和导出。

**核心文件**：
- `apps/api/dy_api/routes/dashboard.py`
- `apps/api/dy_api/routes/_data.py`
- `apps/api/dy_api/schemas.py`
- `tests/test_api_dashboard.py`

**完成标准**：
- 4 个查询入口返回可核对的账单总额、单月确认、待开票、已开票、结算/扣款及口径定义。
- 累计、负向结转、当前发票版本、推广费四态和管理费厂端同一事实均有边界测试。
- 管理员和最高管理员本模块权限一致；越权门店不返回聚合值或明细。

**Verification Method**：
- 对固定账单/确认/发票 fixture 执行 API 测试并逐项对照整数分汇总；验证两角色、空态、非法筛选、分页和导出。

**Evidence**：
- `docs/devlog/` 中 T5.3 指标样例、权限矩阵与测试记录。

**Failure Handling**：
- 指标无法从当前有效事实确定时返回明确异常，不在 API 或页面猜测。
- 负向结转证据不足时阻断待开票累计发布，不回改历史开票/扣款。
- 查询计划出现无界扫描时先补索引或重写聚合再进入页面联调。

**完成收尾：状态同步**：
- 完成实现、验证与 Foundation 漂移判断后，把完成事实、证据、日期、漂移结论和建议下一 Task 提交给 `ai-project-manager`；由其同步主计划、看板和本子计划并重跑 S4 路由检查。三处未同步前不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T5.1、T5.2

**状态**：待审阅
