# T1.3 订单明细直接访问与生产发布 Sub Delivery Plan

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-71-72-75-production-fixes.md](main-delivery-plan-dydata-71-72-75-production-fixes.md)
- 任务看板：[task-kanban-dydata-71-72-75-production-fixes.md](task-kanban-dydata-71-72-75-production-fixes.md)
- Linear：DYDATA-75

#### T1.3 支持订单费用明细直接访问并发布生产

**Requirement ID**：DYDATA-75

**PRD 双链·读**：
- Linear DYDATA-75
- `docs/prd/subprd/03-subprd-order-fee-details.md`
- `docs/prd/foundation/foundation-api-dy-data/settlement-reporting.md`
- `docs/rules/backend-tasks.md`
- `docs/rules/frontend-tasks.md`

**核心逻辑**：
- 无来源参数时仍请求订单费用明细，按当前账号授权门店范围展示默认列表。
- 有下钻来源时保留 statement 或 store/month 上下文及返回入口；部分筛选参数独立生效。
- 后端始终执行页面权限和门店范围约束；导出复用相同过滤条件。
- 完成全部需求后执行全量验证、评审、推送、合并、腾讯云生产部署与公开 smoke。

**核心文件**：
- `apps/web/src/pages/OrderDetailsPage.tsx`
- `apps/api/dy_api/routes/dashboard.py`
- `apps/api/dy_api/routes/_data.py`
- `tests/test_api_dashboard.py`
- `tests/test_api_account_permissions.py`
- `tests/test_visual_smoke.py`
- `.github/workflows/tencent-lighthouse-deploy.yml`

**完成标准**：
- 直接点击 `/details` 能加载当前授权范围内的数据或正常空态，不再显示必须从单店分账进入的阻断提示。
- 下钻链接仍带来源上下文并可返回；无来源时不显示误导性的返回按钮。
- 指定门店账号无法读取或导出授权范围之外的明细。
- 全量本地门禁、远端 CI、生产部署和目标页面 smoke 通过。

**Verification Method**：
- `python -m pytest tests/test_api_dashboard.py tests/test_api_account_permissions.py tests/test_visual_smoke.py -q`
- `git diff --check`
- `python -m pytest`
- `npm --prefix apps/web run build`
- GitHub Verify 与 Tencent Lighthouse Deploy 成功；生产 `/`、`/details`、`/admin/rules`、`/admin/product-types`、`/admin/accounts` 返回预期状态。

**Evidence**：
- 2026-08-20 RED：新增直达 API、指定门店范围与直达浏览器用例，旧实现稳定出现 3 failures（无来源请求均被阻断）。
- 2026-08-20 GREEN：`python -m pytest tests/test_api_dashboard.py::test_order_fee_details_allows_direct_access_without_source_context tests/test_api_account_permissions.py::test_store_user_permissions_are_enforced tests/test_visual_smoke.py::test_order_details_direct_url_loads_authorized_default_scope -q`：3 passed。
- `python -m pytest tests/test_api_dashboard.py tests/test_api_account_permissions.py -q`：28 passed。
- 复审修复新增：数据库 `COUNT + LIMIT/OFFSET` 分页、调整项分块批量读取、无来源残留费率/版本忽略、MANAGEMENT 以核销门店授权、空门店范围列表/导出拒绝。
- `python -m pytest tests/test_visual_smoke.py -k "order_fee_details or order_details" -q`：10 passed，181 deselected。
- `python -m pytest tests/test_frontend_clue_center.py tests/test_frontend_product_type_visibility.py tests/test_frontend_settlement_privacy.py tests/test_frontend_user_facing_contracts.py -q`：54 passed。
- `npm --prefix apps/web run build`：通过；仅保留既有大 chunk 警告。
- 最终本地门禁：`python -m pytest` 为 1216 passed、2 skipped、0 failed（157 条既有弃用警告）；`npm --prefix apps/web run build` 与 `git diff --check` 通过。
- 全量回归曾暴露增量采集测试误触真实商品同步的环境污染；四个仅验证采集的用例已显式关闭商品同步，专项 4 passed，生产 Worker 逻辑未变更。
- 独立最终评审：Critical / Important / Minor 均为 0，Ready to merge = Yes。
- commit、CI/deploy URL、部署 SHA 和公开 smoke 结果待发布阶段追加。

**Failure Handling**：
- 任一权限测试、全量门禁、CI、部署或 smoke 失败时停止发布并保留上一生产 SHA；将失败证据回填 Linear，不宣称上线。

**完成收尾：状态同步**：
- 完成后同步主计划、看板、本子计划并运行 S4 route-check；回填三个 Linear issue，等待人类 Owner 最终验收后再 Done。

**Owner**：AI 执行 -> 人审核

**前置**：T1.2

**状态**：进行中
