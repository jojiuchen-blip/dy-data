# T1.1 商品口径查询与更新 API 子交付计划

## 任务来源

- [主开发计划](main-delivery-plan-dydata-72-product-types.md)
- [任务看板](task-kanban-dydata-72-product-types.md)

#### T1.1 商品口径查询与更新 API

**Requirement ID**：DYDATA-72-API-01

**PRD 双链·读**：
- Linear `DYDATA-72` 的列表状态、单个设置与批量设置验收标准。
- `docs/prd/foundation/foundation-schema-dy-data/product-rule-source.md` §1。
- `docs/prd/foundation/foundation-api-dy-data/sku-fee-admin.md` 的 SKU 商品规则接口。
- `docs/prd/foundation/foundation-api-dy-data/common-contract.md` §2-§5。

**核心逻辑**：
- `UNCONFIGURED` 表示两个字段均无有效值，`PARTIAL` 表示仅一个字段有效，`CONFIGURED` 表示两者均有效。
- 待完善查询合并前两种状态，按未配置、部分配置排序；默认每页 50。
- 单个和批量更新允许只提交一个字段，未提交字段保持原值；空值与未知额外字段拒绝。
- 批量更新先校验全部 SKU 和合并后的字段组合，再在一个事务中更新，不能部分成功。

**核心文件**：
- `apps/api/dy_api/routes/fee_admin.py`
- `apps/api/dy_api/schemas.py`
- `tests/test_api_fee_admin.py`

**完成标准**：
- 列表返回 `configurationStatus` 与三个状态计数，并支持 `configurationStatus=PENDING|CONFIGURED`。
- 默认 `pageSize=50`；待完善结果先未配置后部分配置。
- 单条只传 `productScope` 或 `productType` 时另一字段保持原值。
- `PUT /api/v1/admin/sku-products/bulk` 支持 SKU ID 数组和单字段/双字段更新，任一 SKU 不存在时零写入。

**Verification Method**：
- 先运行新增目标测试并确认失败，再执行 `python -m pytest tests/test_api_fee_admin.py -q`。

**Evidence**：
- pytest 输出与本子计划完成记录；最终汇总写入 Linear DYDATA-72。

**Failure Handling**：
- 若现有 product scope/type 映射不能证明组合非法，不猜测新枚举；保留非空校验并在 T4 风险中说明。
- 若当前接口兼容测试依赖 `isServiceProduct`，保留可选兼容字段但新页面与导入不得发送它。

**完成收尾：状态同步**：
- 完成实现、验证与 Foundation 漂移判断后，提交完成事实、证据、日期和建议下一 Task 给 `ai-project-manager`，同步主计划、看板和本子计划；三处同步前不得标记完成。

**Owner**：AI 执行 -> 人审核

**前置**：无

**状态**：已完成（2026-08-13）

**完成记录**：新增配置三态与计数、待完善排序、默认 50、单字段保留和批量原子更新；`python -m pytest tests/test_api_fee_admin.py -q` 为 19 passed。
