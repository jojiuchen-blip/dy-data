# T2.1 商品口径管理页面子交付计划

## 任务来源

- [主开发计划](main-delivery-plan-dydata-72-product-types.md)
- [任务看板](task-kanban-dydata-72-product-types.md)

#### T2.1 商品口径管理页面

**Requirement ID**：DYDATA-72-WEB-01

**PRD 双链·读**：
- Linear `DYDATA-72` 的页面结构、字段、筛选、跨页选择和展示影响说明。
- `docs/prd/mainprd-dy-data.md` 全局空态、加载态、错误提示和管理端边界。
- `docs/prd/foundation/foundation-api-dy-data/common-contract.md` 分页与错误契约。

**核心逻辑**：
- 页面标题“商品口径”，顶部以“待完善 / 已配置”按钮切换并同步 URL；待完善默认打开。
- 表格只围绕 SKU 编码、商品名称、产品范围、商品类型、配置状态、修改信息和操作展开。
- 单个设置、跨页批量设置均使用右侧抽屉；未编辑字段明确显示“保持原值”。
- 导入沿用已确认的模板下载、预校验、错误预览、确认提交流程。

**核心文件**：
- `apps/web/src/pages/AdminProductTypeVisibilityPage.tsx`
- `apps/web/src/api/client.ts`
- `apps/web/src/types/dashboard.ts`
- `apps/web/src/styles.css`
- `tests/test_frontend_product_type_visibility.py`
- `tests/test_visual_smoke.py`

**完成标准**：
- 默认待完善、每页 50；支持 SKU/商品名称查询、产品范围/商品类型/状态筛选。
- 勾选跨页保留，筛选变化后已选数量仍可见，可统一清空；无选择时批量设置禁用。
- 单个与批量抽屉允许更新一项或两项，不以空白代替“保持原值”。
- 页面说明明确三处均使用商品口径，订单分佣还要求存在有效分佣规则。

**Verification Method**：
- 执行前端契约 pytest、`npm --prefix apps/web run build`，并在 `/admin/product-types` 做 Playwright smoke。

**Evidence**：
- pytest/build 输出；页面截图存放 `pwScreenShot/dydata-72-product-types.png`。

**Failure Handling**：
- 若现有组件不支持右侧抽屉，使用同一可访问 Dialog 基础实现 drawer 变体；不复制一套缺少焦点管理的弹层。

**完成收尾：状态同步**：
- 完成实现、验证与 Foundation 漂移判断后，同步主计划、看板和本子计划；未同步前不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T1.2

**状态**：已完成（2026-08-13）

**完成记录**：页面已重构为待完善/已配置双入口，支持 URL 状态、默认 50、查询筛选、跨页勾选、单个/批量右侧抽屉和导入预校验；Web build、4 项前端契约测试、9 项多视口/主题 smoke 与 1 项抽屉 smoke 通过。
