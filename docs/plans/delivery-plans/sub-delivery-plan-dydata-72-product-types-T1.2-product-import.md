# T1.2 商品口径原子导入子交付计划

## 任务来源

- [主开发计划](main-delivery-plan-dydata-72-product-types.md)
- [任务看板](task-kanban-dydata-72-product-types.md)

#### T1.2 商品口径原子导入

**Requirement ID**：DYDATA-72-IMPORT-01

**PRD 双链·读**：
- Linear `DYDATA-72` 的批量导入验收标准。
- `docs/prd/foundation/foundation-schema-dy-data/product-rule-source.md` §1、§5-§6 的原子导入模式。
- `docs/prd/foundation/foundation-api-dy-data/sku-fee-admin.md` §7-§11。

**核心逻辑**：
- 独立商品口径批次保存三列原始输入与逐行校验结果，不混入费率批次。
- `skuId` 必填；`productScope`、`productType` 各自只能是具体值或 `KEEP`，空白非法且不可同时 `KEEP`。
- 上传只预校验；确认提交时事务内重新校验，任一错误整批零写入。

**核心文件**：
- `apps/api/dy_api/models.py`
- `apps/api/dy_api/routes/fee_admin.py`
- `alembic/versions/*_add_sku_product_import_tables.py`
- `tests/test_api_fee_admin.py`

**完成标准**：
- 模板支持 UTF-8 CSV 与 XLSX，列为 `skuId,productScope,productType`。
- 上传返回批次、总数、有效数、失败数和逐行错误预览。
- 只有可提交批次可确认；成功后按 `KEEP` 语义更新且写入人工操作人/时间。
- 重复 SKU、不存在 SKU、空值、双 `KEEP`、格式错误和不兼容组合阻止整批提交。

**Verification Method**：
- 执行商品口径导入目标测试、`python -m pytest tests/test_api_fee_admin.py -q`，并运行 migration smoke。

**Evidence**：
- pytest/migration 输出与 Linear DYDATA-72 验证记录。

**Failure Handling**：
- 文件解析或持久化失败时批次标记失败且不改 SKU；迁移不可逆风险出现时停止并记录，不执行生产数据库操作。

**完成收尾：状态同步**：
- 完成实现、验证与 Foundation 漂移判断后，同步主计划、看板和本子计划的完成事实、证据和日期；未同步前不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：T1.1

**状态**：已完成（2026-08-13）

**完成记录**：新增独立商品口径导入批次/行模型与 Alembic revision `20260813_0030`；CSV/XLSX、KEEP、非法行和提交前变化原子回滚由 5 项目标测试覆盖，fee admin 24 项通过。
