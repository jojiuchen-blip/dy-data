# DYDATA-72 商品口径实施计划

> 执行位置：`.worktrees/dydata-72-product-types`；分支：`codex/dydata-72-product-types`。

目标是把 `/admin/product-types` 从旧的“商品展示口径”开关页改成 SKU 人工商品口径工作台。商品口径由 `SKU 编码 + 产品范围 + 商品类型` 表达；所有商品仍可进入线索中心和核销表现，订单分佣额外要求存在有效分佣规则。

## 实施顺序

1. 在 `tests/test_api_fee_admin.py` 先补配置状态、默认排序、单字段更新和批量原子更新失败测试。
2. 修改 `apps/api/dy_api/schemas.py` 与 `apps/api/dy_api/routes/fee_admin.py`，实现 `PENDING/CONFIGURED` 查询、状态计数、默认 50、可选字段更新和 `/sku-products/bulk`。
3. 为商品口径导入补测试；新增独立导入批次/行模型与 Alembic migration，实现模板、上传预校验、详情和原子提交端点。
4. 更新 `apps/web/src/types/dashboard.ts` 与 `apps/web/src/api/client.ts` 对接新契约。
5. 先改 `tests/test_frontend_product_type_visibility.py`，再重构 `AdminProductTypeVisibilityPage.tsx`：顶部双入口、查询筛选、配置状态、跨页选择、单个/批量抽屉、导入流程。
6. 在 `apps/web/src/styles.css` 增加页面局部样式，复用现有 token、Button、DataTable、Dialog 和 TablePagination。
7. 运行目标测试、完整 pytest、Web build、diff check 与页面 smoke，并把证据写回 DYDATA-72。

## 关键测试

- 未配置、部分配置、已配置三态判断与待完善排序。
- 单个更新仅改产品范围或商品类型，未提交字段不变。
- 批量更新中任一 SKU 不存在时全部不写入。
- CSV/XLSX 中空白、双 KEEP、重复/不存在 SKU、格式错误导致批次不可提交；提交失败整批回滚。
- URL 恢复当前顶部入口、查询与筛选；默认 pageSize 50；跨页选择保持。
- 商品口径文案不再暗示控制展示资格；订单分佣限制说明准确。
