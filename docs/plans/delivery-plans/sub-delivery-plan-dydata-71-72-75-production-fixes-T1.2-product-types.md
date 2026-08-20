# T1.2 商品口径自定义值 Sub Delivery Plan

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-71-72-75-production-fixes.md](main-delivery-plan-dydata-71-72-75-production-fixes.md)
- 任务看板：[task-kanban-dydata-71-72-75-production-fixes.md](task-kanban-dydata-71-72-75-production-fixes.md)
- Linear：DYDATA-72

#### T1.2 允许编辑产品范围和商品类型时创建新值

**Requirement ID**：DYDATA-72

**PRD 双链·读**：
- Linear DYDATA-72 §4-6 与 2026-08-20 用户补充
- `docs/prd/foundation/foundation-schema-dy-data/product-rule-source.md`
- `docs/prd/foundation/foundation-api-dy-data/sku-fee-admin.md`
- `docs/rules/backend-tasks.md`

**核心逻辑**：
- 编辑器由只读候选下拉改为可输入且保留已有建议值。
- 同时显式设置产品范围和商品类型时允许建立新组合；只更新单项时仍必须匹配已有组合或同 scope 的现有类型。
- 自定义值统一 trim，拒绝空白、`all`、`unknown`、`KEEP` 和超长输入。
- 单个、勾选批量、CSV/XLSX 预校验与提交使用同一组合规则；仍保持原子写入。

**核心文件**：
- `apps/web/src/pages/AdminProductTypeVisibilityPage.tsx`
- `apps/web/src/components/FormControls.tsx`
- `apps/api/dy_api/schemas.py`
- `apps/api/dy_api/routes/fee_admin.py`
- `tests/test_api_fee_admin.py`
- `tests/test_frontend_product_type_visibility.py`

**完成标准**：
- 用户可输入候选列表以外的新产品范围和商品类型并保存。
- 只改一个字段时不产生无效组合；同时提供新 scope/type 时形成显式合法组合。
- 导入预校验与最终提交规则一致，任一错误整批零写入。
- 保存后重新加载可在列表与筛选元数据中看到新值。

**Verification Method**：
- `python -m pytest tests/test_api_fee_admin.py tests/test_frontend_product_type_visibility.py -q`
- `npm --prefix apps/web run build`

**Evidence**：
- 2026-08-20：新增失败测试，确认旧实现拒绝显式新组合且前端只有下拉候选。
- `python -m pytest tests/test_api_fee_admin.py -q`：35 passed。
- `python -m pytest tests/test_frontend_product_type_visibility.py -q`：6 passed。
- 单个设置与导入提交均回读到同一 `dim_sku_product_rules` 行；提交 SHA 在 T1.3 发布阶段追加。

**Failure Handling**：
- 若真实数据存在冲突同名组合，保留现有数据并阻止仅改单字段；记录样本并拆分 Data Quality follow-up。

**完成收尾：状态同步**：
- 完成后同步主计划、看板、本子计划，并把证据回填 DYDATA-72。

**Owner**：AI 执行 -> 人审核

**前置**：T1.1

**状态**：已完成
