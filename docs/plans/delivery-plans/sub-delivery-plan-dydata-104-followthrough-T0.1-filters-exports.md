# T0.1 账期默认值与现有下载反馈

## 任务来源

- [主计划](main-delivery-plan-dydata-104-followthrough.md) / [任务看板](task-kanban-dydata-104-followthrough.md)
- [DYDATA-104](https://linear.app/keith-lim/issue/DYDATA-104)

### T0.1 账期默认值与现有下载反馈

**Requirement ID**：DYDATA-104 E

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` 全局规则
- `docs/prd/subprd/02-subprd-store-settlement.md` §3–4
- `docs/prd/subprd/03-subprd-order-fee-details.md` 筛选与导出
- `docs/prd/subprd/05-subprd-finance-promotion.md` §3
- `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md` 账单/财务契约
- `docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md` 费用、调整与冻结来源
- `docs/api/dashboard-publications.md` 不可变发布与读取

**核心逻辑**：门店结算默认使用上海上一完整自然月，显式选择当月仍有效；复用已有 statementMonth helper。仅修复当前五个 SKU 下载入口的失败反馈与重复点击保护。按当前页面重新盘点主范围 14 类及相关入口，不以旧的 25 数量替代逐入口核对。销售榜单的销售月份不自动套用财务账期规则。

**核心文件**：
- `apps/web/src/pages/StoreSettlementPage.tsx`
- `apps/web/src/pages/AdminProductTypeVisibilityPage.tsx`
- `apps/web/src/components/AdminSkuRuleImportDrawer.tsx`
- `apps/web/src/components/AdminSkuGovernancePanel.tsx`
- `apps/web/src/utils/statementMonth.ts`
- `tests/test_finance_export_browser.py`

**完成标准**：上海 10 月无 URL 月份时首次结算查询为 9 月，显式 10 月与 8→9→10→8 切换准确；选择项仍保留真实当月。五处下载分别覆盖成功文件、403/500/断网可见反馈、忙碌保护和重试。列表与完整导出按同筛选、权限、版本核对，空数据不沿用上一账期。

**Verification Method**：定向真实浏览器/API 测试、下载字节/文件名/编码校验、前端 build；不以 route mock 单独替代真实内容核验。

**Evidence**：`docs/devlog/20261020_dydata-104-followthrough.md`，对应最终 CI 与脱敏运行记录。

**Failure Handling**：证据不符、资源/配额不足或保护指纹变化时停止相关写入；保留真实状态并记录具体阻碍，不绕过门禁。未满足验收不标记完成。

**完成收尾：状态同步**：核对验证与 foundation 漂移；新增契约缺口只追加待改请求。由 ai-project-manager 调度 delivery-planner 同步主计划、看板、子计划与执行驾驶舱，重跑一致性和 route-check；生产结果没有实证时不能写完成。

**Owner**：Codex 执行与独立复核 → 用户业务验收

**前置**：PR #50 / #51 合入统一 main

**状态**：并行实施

