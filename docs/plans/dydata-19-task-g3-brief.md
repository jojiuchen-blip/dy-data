# DYDATA-19 G3 — 财务订单明细完整投影、筛选与导出

Status: Ready after G1/G2 shared-file slices
Owner: G3 implementer; controller reviews and integrates

## Goal

按 Linear DYDATA-19 §7 补齐推广服务费和管理服务费两个订单明细子页面的后端投影、完整筛选、分页、同口径全量导出与导出审计。页面只展示后端冻结事实，不自行重算费用。

## Binding requirements

- 推广服务费与管理服务费使用两个独立入口/子页面，但复用一致的查询、分页和导出交互。
- 费用结果和独立负数调整行由后端基于当前有效账单版本、冻结分录及不可变调整事实投影；React 不按费率重新计算。
- 退款/取消核销以独立负数调整行展示，不改写原始正数订单行。
- 不展示“认证主体”和“历史账期补充金额”。
- 不得把管理服务费伪装成推广费的厂家审核状态链。

## Required result fields

- 账单/分录 ID、门店 ID、服务店名称、有效 SAP、账期、费用方向。
- 订单 ID、券 ID、订单/券状态、商品、SKU ID/名称、销售渠道。
- 销售门店、核销门店、销售时间、核销时间。用户页面和标准导出只保留统一“账期”，不把原始业务月/调整入账月作为标准列重新暴露“调整来源账期”。
- 实收金额、冻结计费基数、实际费率、冻结费用金额。
- 退款时间；原费用和退款/取消核销负数调整分别成行。不得返回或展示已从正文删除的“调整来源账期、退款金额、调整后净基数、调整后净费用”列。
- 推广费：发票号码、提交/登记时间、审核状态、结算日期、不通过原因。
- 管理费：当前有效发票/厂家扣款事实及系统导入时间；不得生成推广费审核状态。
- 响应和页面需提供字段来源、取值逻辑或计算说明入口。

## Required filters and search

- 账期、费用方向、门店、SAP、发票号、订单 ID、SKU ID。
- 销售渠道、审核/结算状态、提交时间区间、核销时间区间。
- 所有筛选由后端执行；列表、总数和导出必须使用同一规范化查询条件。

## API and export contract

- 扩展现有 `/api/v1/admin/finance/order-details` 列表及 `/export`，保持管理员权限；不另建平行 `/finance/orders` 契约。
- 列表支持显式 `page`/`pageSize` 并返回准确 `total`。
- 导出忽略分页，导出全部命中行，字段/排序/筛选与列表一致；UTF-8 BOM 保持兼容。
- 导出成功或失败均写入 `FinanceOperationAudit`，记录规范化筛选、结果、行数、请求 ID 和操作者，不记录敏感原始数据。
- 空结果可导出只有表头的文件；超大结果必须采用流式/分块策略或设置明确安全上限并返回可恢复错误，不能静默截断。

## Data correctness boundaries

- 历史账单必须使用账单版本对应的冻结事实。当前 `dim_stores` 或当前 SAP profile 不能冒充历史快照，也不能以“当前值”降级通过发布门禁。
- 为账单版本增加不可变门店名称/SAP 快照及来源状态：新账单生成时冻结当时门店名称和当前有效 SAP；后续主数据导入不得刷新旧账单。
- 建议账单快照字段为 `store_name_snapshot`、`sap_code_snapshot`、`store_snapshot_status`、`store_snapshot_profile_id`；`store_snapshot_status` 只允许 `LIVE_CAPTURED`、`BACKFILLED_PROFILE`、`UNRESOLVED`。SAP 在生成时合法为空仍属于 `LIVE_CAPTURED`，不得误标为无法回填。
- 新账单只在首次创建时读取 `DimStore` 名称及 `profile_type=1` 的当前有效 `StoreFinanceProfile.sap_code`；未锁账单重建不得刷新快照，异议产生 Vn+1 时必须原样复制上一版本快照。
- 既有 2026-08 起账单只允许按精确 `store_id`、`profile_type=1`，选择 `profile.created_at < statement.created_at` 且导入批次已在账单生成前提交的最高稳定版本回填；同版本使用确定性键消除并列。禁止按 `is_current`、`gmt_modified`、当前 `DimStore`、当前 profile、名称或金额模糊回填，`profile_type=2` 的 `initial_sap_code` 也不得冒充有效 SAP。
- 无法稳定回填的账单写入 `settlement_statement_snapshot_migration_exception`，至少包含唯一 `statement_id`、`reason_code`、`evidence_json`、检测/解决时间和解决说明。原因码至少覆盖 `NO_PRIOR_BASIC_PROFILE`、`PROFILE_NOT_COMMITTED_BEFORE_STATEMENT`、`AMBIGUOUS_PROFILE_TIME`、`INVALID_PROFILE_VERSION_ORDER`。
- 迁移本身允许以 `UNRESOLVED` + 异常记录完成，以保持可逆和可审计；发布门禁必须断言未解决异常数为 0，在归零前不得给出可发布结论。
- SAP 在历史时点确实缺失可以作为合法空值，但必须以快照状态明确区分“当时为空”和“无法回填”。
- 修正 worker 锁账查询：必须显式限定当前有效账单版本，避免多版本账单被错误选择或产生多行结果。
- 推广发票通过当前有效 `promotion_invoice` + allocation + status events 投影。
- 管理费通过当前有效 `invoice_record`/厂家扣款事实投影。

## Frontend contract

- 筛选表单覆盖全部后端筛选；筛选、重置、分页、页大小和导出状态可见。
- 完整列可以使用分组列、详情抽屉或可配置列，移动端不得强行压缩成不可读表格。
- 导出 loading、成功、失败和空结果均有清晰反馈；不得出现未处理 Promise。
- 页面提供“字段来源与计算说明”。

## TDD gates

1. 先添加 API RED：完整字段、两费用方向、全部筛选、当前有效版本、调整负数行、列表/导出一致、导出审计、空结果、权限；并添加快照首次捕获、未锁重建不刷新、异议新版本继承、历史回填确定性、合法空 SAP、无法回填异常清单及锁账只选当前版本的 RED。
2. 实现最小后端投影与 CSV，确认 GREEN。
3. 先添加前端契约 RED：类型、筛选、分页、导出状态、说明入口，再实现页面。
4. 运行 focused API、frontend contracts、build、visual/browser checks 和 `git diff --check`。

## Write set

- `apps/api/dy_api/routes/dashboard.py`
- `apps/api/dy_api/models.py`
- `apps/worker/settlement.py`
- one reversible single-head Alembic migration and migration-exception evidence
- `apps/web/src/types/dashboard.ts`
- `apps/web/src/api/client.ts`
- `apps/web/src/pages/FinanceOrderDetailsPage.tsx`
- `tests/test_api_store_billing.py`
- relevant settlement/data/migration tests
- relevant frontend contract/visual tests only

## Non-goals

- 不新增认证主体或历史补充金额。
- 不改变原账单、原发票、原结算记录。
- 不进行生产迁移、部署、commit、push、reset、checkout 或全仓格式化。
- 不覆盖或回退并发改动。

## Required report

Return `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT` or `BLOCKED`, followed by changed files, exact red and green commands/results, self-review findings and remaining risks.
