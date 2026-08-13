# T1.2 分佣规则页重组与视觉落地

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-71-admin-pages.md](main-delivery-plan-dydata-71-admin-pages.md)
- 任务看板：[task-kanban-dydata-71-admin-pages.md](task-kanban-dydata-71-admin-pages.md)

#### T1.2 把分佣规则页收敛为选择、确认比例、检查预选、确认发布的连续流程

**Requirement ID**：DYDATA-71-RULES

**PRD 双链·读**：

- Linear `DYDATA-71`“分佣规则页面重组”与 2026-08-12 用户确认记录
- `docs/prd/mainprd-dy-data.md`“双费用口径、管理端边界”
- `docs/prd/foundation/foundation-api-dy-data/sku-fee-admin.md` §1、§3～§11
- `docs/design-system/tokens.json` `navigation.tertiary`、`dataTable`、`dialog`

**核心逻辑**：

- 一级页签为“规则设置 / 发布记录 / 例外账号”；默认规则设置且切换不丢草稿。
- 规则设置按 1 选择 SKU、2 SKU-ID分佣比例确认、3 发布确认、4 确认发布组织；比例应用后滚动到第 3 步。
- 单个/批量输入支持换行、空格、中英文逗号和分号并去重；移除“批量选择当前筛选结果”。
- 手工发布对所选 SKU 逐条调用现有双费率版本 API并保留幂等；批量导入通过费率卡右上角抽屉进入。
- 发布记录统一展示费率版本和导入批次；例外账号完整保留。
- 页面底部提供“已启用分佣商品列表 / 未启用分佣商品列表”，沿用现有十列字段；当前已生效且状态启用的双费率规则判定为已启用。
- 不渲染商品人工分类、旧单费率兼容区和旧预选批量单费率编辑器。

**核心文件**：

- `apps/web/src/pages/AdminSkuRulesPage.tsx`
- `apps/web/src/components/AdminSkuRuleImportDrawer.tsx`
- `apps/web/src/styles.css`
- `tests/test_frontend_t3_3_admin_contracts.py`
- `tests/test_frontend_admin_rules_workflow.py`

**完成标准**：

- 页面包含三个一级页签和四步进度，第一步先于“SKU-ID分佣比例确认”。
- 比例应用按钮调用滚动/聚焦第 3 步；最终发布前确认卡汇总 SKU 数、两项费率、生效日、状态和原因。
- “批量导入设置”打开抽屉并保留上传、预校验、错误详情、结果下载和原子提交。
- 发布记录只用一张列表并支持来源筛选；例外账号显示数量、清单、保存和重建提示。
- 底部两个 SKU 子标签字段与现有列表一致；旧三个区块文案不在规则页运行时源码中。
- 相关 pytest、Web build、视觉 smoke 与浏览器主流程检查通过。

**Verification Method**：

- 先新增规则页工作流契约测试并确认因缺少三页签/四步流程失败，再实施。
- 运行后台规则 API/前端契约、设计系统、用户文案和视觉 smoke 测试。
- 浏览器检查 390、768、1440 主视口、步骤跳转、抽屉、确认卡和两个 SKU 子标签。

**Evidence**：

- `python -m pytest -q`：1176 passed、2 skipped，完整测试无失败（2026-08-13）。
- `npm --prefix apps/web run build`：TypeScript 检查与 Vite 生产构建通过；仅保留仓库既有的 500 kB chunk 提示。
- 规则页相关前端/API/视觉回归：92 passed；390/768/1440 视觉矩阵与真实 FastAPI 手工发布、冲突、CSV/XLSX 原子导入及幂等重试均通过。
- `git diff --check`：通过；未修改后端 API、数据库或财务板块。
- foundation 漂移结论：无；手工多 SKU 沿用现有逐条幂等发布，文件导入沿用现有全量预校验与原子提交。

**Failure Handling**：

- 若批量多 SKU 发布后端不支持单事务，不伪装为原子操作；界面明确逐条版本发布，文件导入才使用原子提交。
- 若已启用判定缺少当前有效版本接口证据，保留现有规则状态并记录 foundation 漂移，不在前端猜测日期覆盖。

**完成收尾：状态同步**：

- 完成实现、验证和 foundation 漂移判断后，将事实、证据、完成日期和漂移结论提交给 `ai-project-manager`。
- 由 `delivery-planner` 同步三份计划状态并重跑 S4 路由检查；随后更新 Linear 验证记录。

**Owner**：AI 执行 -> 人审核

**前置**：T1.1 完成

**状态**：进行中（实现与验证已完成，待用户验收）
