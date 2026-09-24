# T1.1 费用明细导出恢复与佣金按接口订单实收计算

## 任务来源

- 主开发计划：[main-delivery-plan-dydata-97-fee-fixes.md](main-delivery-plan-dydata-97-fee-fixes.md)
- 任务看板：[task-kanban-dydata-97-fee-fixes.md](task-kanban-dydata-97-fee-fixes.md)

#### T1.1 费用明细导出恢复与佣金按接口订单实收计算

**Requirement ID**：DYDATA-97

**PRD 双链·读**：
- `docs/prd/mainprd-dy-data.md` §全局设计规则
- `docs/prd/subprd/03-subprd-order-fee-details.md` §4 费用方向与筛选、§5 一券一方向费用明细
- `docs/prd/foundation/foundation-api-dy-data/settlement-reporting.md` §3、§4
- `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md` §4.3
- `docs/prd/foundation/foundation-glossary-dy-data.md` 费用计算基数
- `docs/prd/foundation/foundation-schema-dy-data/product-rule-source.md` #8 原始券

**核心逻辑**：
- 导出恢复：`/admin/finance/invoices/export`、`/admin/finance/order-details/export`、`/order-fee-details/export` 三个端点复用与查询完全相同的筛选、权限和管理范围；导出前重新验权，忽略分页，参数为 `text/csv; charset=utf-8` 并含 UTF-8 BOM；空结果保持现有端点行为，不改动：`/admin/finance/invoices/export` 与 `/admin/finance/order-details/export` 空结果返回 200 且仅表头，仅 `/order-fee-details/export` 空结果返回 409 `EXPORT_EMPTY`。根因未确认，必须先复现故障再最小修复，不得以增加列或按钮代替复现。
- 导出按钮逐项检查（2026-09-23 追加）：对订单分佣页与财务各页全部「导出 / 下载模板 / 下载错误行」按钮做逐项全链路核对（页面路由、组件、handler、client 函数、后端端点、参数、权限、成功/空/失败呈现）；主范围 14 个按钮 + 相关页面 11 个按钮，共 25 个。确定缺陷 D1（管理费 `includeHistory` 列表/导出不一致，已修复）、D2（CORS 未 `expose_headers`，跨域时 `Content-Disposition`/`X-Export-Result` 不可读）、D3（账单异议导出反馈被详情抽屉吞掉且失败等级错误）、D4（错误行下载无 busy/异常处理）；高置信候选 C1（同步 `revokeObjectURL` 可能取消下载）、C2（100000 行上限 413）、C3（榜单导出 300s 超时）。候选需真实浏览器/大数据结论，未确认前不猜测性修改。
- 实收基数：`apps/worker/settlement.py::_direction_source_amount` 改为优先从现有 `raw_payload` 解析订单/券的明确 `receipt_amount` 及 `sub_order_amount_infos` 按券匹配值，并保留 `0` 与缺失语义；核销/券/订单 paid 字段不再冒充实收。
- 归属规则：未知、不完整或无法按券归属的实收不得猜测；不得把订单总额重复用于每张券；不得以实付冒充实收。实收缺失是否升级为数据质量阻断，保持实现侧现有处理协议。
- 字段含义：`order_paid_amount_cent`、`coupon_paid_amount_cent`、核销 `paid_amount_cent` 保留原含义，不就地改写。
- legacy 佣金链：约 2797 行 `_commission_cent(paid_amount_cent, ...)` 改为按分离后的实收基数计算，与双费用链同口径，实付字段仅作原始事实保留。
- 边界：无数据库迁移；用户已授权修复后部署（由 Codex 验收并部署）；不自动重算历史锁账与生产账单；已锁账快照只读不修改。

**核心文件**：
- `apps/worker/settlement.py`（`_direction_source_amount` 约 4040 行；调用点约 3186 行；legacy 佣金链约 2797 行）
- `apps/worker/collectors/orders.py`（原始订单/券 `raw_payload` 落库）
- `apps/api/dy_api/models.py`（`raw_douyin_orders`、`raw_douyin_order_coupons` 的 `raw_payload`）
- `scripts/settlement/build_settlement_base_from_current_data.py`（`order_receipt_amount` 第 64 行，口径对齐参照）
- `apps/api/dy_api/routes/dashboard.py`（`/admin/finance/invoices/export` 约 4198 行、`/admin/finance/order-details/export` 约 4663 行、`/order-fee-details/export` 约 5989 行、`/order-details/export` 约 6126 行）
- `apps/web/src/api/client.ts`（导出下载路由：`/order-fee-details/export`、`/order-details/export`、`/admin/finance/invoices/export`、`/admin/finance/order-details/export`、`/admin/finance/stores/export`、`/admin/finance/stores/sap-discrepancies/export`、`/admin/disputes/export`、`/admin/finance-imports/{batchId}/error-file`、`/admin/finance-imports/templates/{type}`；共享 helper `requestDownload`/`requestDownloadResult` 约 406-476 行）
- 导出按钮页面：`apps/web/src/pages/OrderDetailsPage.tsx`、`FinanceFeePage.tsx`、`FinanceOrderDetailsPage.tsx`、`FinanceStoresPage.tsx`、`FinanceImportsPage.tsx`、`FinanceDisputesPage.tsx`；`apps/web/src/components/FinanceImportActionPanel.tsx`
- `apps/api/dy_api/main.py`（CORS `expose_headers`，约 117-129 行）
- `tests/test_data_settlement.py`、`tests/test_api_dashboard.py`、`tests/test_api_account_permissions.py`、`tests/test_api_finance_contract_g5.py`、`tests/test_api_store_billing.py`、`tests/test_frontend_user_facing_contracts.py`、`tests/test_visual_smoke.py`

**完成标准**：
- 三个导出端点在真实路由下先有失败复现记录再通过；CSV 列头与内容、筛选条件和权限范围与同参数查询一致；越权返回 403；空结果保持端点现有行为（finance 两个导出返回 200 且仅表头，仅 `/order-fee-details/export` 返回 409 `EXPORT_EMPTY`）；响应为 `text/csv; charset=utf-8` 且含 UTF-8 BOM。
- 订单分佣页与财务各页 25 个导出/下载模板/错误行按钮逐项核对完成；确定缺陷 D1-D4 有红→绿证据，高置信候选 C1-C3 有真实浏览器/大数据结论或明确记录为未复现。**当前主范围 14 类入口已由修复后绿测（`tests/test_finance_export_browser.py` 30 项全部通过，119.61 秒；红测 15 通过 / 15 失败）验证，未扩大到其他 11 个旁路按钮、未对其作结论；候选 C1（`revokeObjectURL`）/C2/C3 均未修改，不在本次部署变更内，不得暗示已修。**
- 实收基数用例覆盖实收 != 实付、实收为 0、实收缺失、无效金额、多券按券归属、退款、已锁账快照、推广与管理两个费用方向；断言金额取自接口订单 `receipt_amount`，不取自 paid 字段。
- legacy 佣金链按分离后的实收基数计算，实付字段值与含义不变。
- 无数据库迁移、不自动重算历史锁账与生产账单、已锁账快照未被写入。
- `python -m pytest` 相关回归与 `npm --prefix apps/web run build` 由 Codex 执行通过（已通过：逐按钮绿测 30 项、相关回归 22 + 39 项、既有 visual_smoke 财务回归 34 项 / 228 deselected（197.81 秒）、build 23.87 秒）；用户已授权修复后部署，由 Codex 完成 CI、受控部署与部署后 smoke（CI/部署尚未执行，不声称通过）。

**Verification Method**：
- 导出：对三个端点分别运行真实路由测试，留存复现失败与修复后通过的请求/响应、权限 403、筛选一致性、空结果行为（`/admin/finance/invoices/export` 与 `/admin/finance/order-details/export` 为 200 仅表头，仅 `/order-fee-details/export` 为 409 `EXPORT_EMPTY`）、CSV BOM 与列头证据。
- 导出按钮逐项矩阵（优先复用 `tests/test_visual_smoke.py` 的 `live_fastapi_base_url` / `vite_live_admin_api_base_url` 真实本地 FastAPI 夹具，不新建框架）：按下表逐按钮真实点击 → `expect_download` → 校验文件名、`utf-8-sig` 列头、行数与页面一致；含 403 权限、空结果文案、`includeHistory` 开关、错误行下载失败提示、账单异议抽屉打开后导出反馈，以及大文件下载完成度。

| 用例 | 覆盖按钮 | 断言 |
|---|---|---|
| V1 | 财务 #3/#5 导出当前筛选结果 | 下载完成、文件名取自响应头、CSV 列头与行数一致 |
| V2 | #5 管理费 `includeHistory` 开/关 | 请求参数与下载内容含/不含历史行 |
| V3 | #6/#7 导出全部命中结果 | 下载行数 == 列表 total |
| V4 | #9/#10 门店基础/SAP 差异 | 列头匹配；空筛选仅表头 + EMPTY 文案 |
| V5 | #2/#4/#8/#11 四模板 | 首行 == 服务端模板表头 |
| V6 | #12/#13 下载全部错误 | 行数 == errorRows；失败有可见提示 |
| V7 | #14 导出账单异议 | 详情抽屉打开时提示仍可见且失败为 `alert` |
| V8 | #1 门店明细导出 | 授权范围成功；越权 403 文案不变 |
| V9 | 权限矩阵 | store 角色对财务导出期望 403 |
| V10 | C1 大文件下载 | 真实 Chromium 大 CSV 完整、非 0 字节、连续两次成功。仅作候选结论记录：C1 共享 `revokeObjectURL` **未修改**，不在本次部署变更内，不得写成已修 |
| V11 | C2/C3 大数据 | 仅在真实数据/人为延迟下验证 100000 行上限与 300s 行为，不进常规 CI |

- 金额：运行 `python -m pytest tests/test_data_settlement.py` 及相关 API/前端契约用例，逐项核对实收 != 实付、0、缺失、无效、多券、退款、锁账、两方向。
- 结构：运行 `node .agent/project-manager-suite/skills/05-01-delivery-planner/scripts/validate-plan-structure.mjs docs/plans/delivery-plans/main-delivery-plan-dydata-97-fee-fixes.md --json`、`node .agent/project-manager-suite/skills/05-01-delivery-planner/scripts/check-plan-consistency.mjs docs/plans/delivery-plans/main-delivery-plan-dydata-97-fee-fixes.md --json`、`node .agent/project-manager-suite/skills/06-01-coding-standards/scripts/verify-task-context.mjs docs/plans/delivery-plans/main-delivery-plan-dydata-97-fee-fixes.md T1.1 --json`。
- 构建与部署：运行 `npm --prefix apps/web run build`；由 Codex 执行 CI、受控部署与部署后 smoke，且不自动重算历史锁账、不写已锁账快照。

**Evidence**：
- 已落盘 `docs/devlog/`：`20260922_dydata-97-receipt-review-round2.md`（第二轮静态返修）与 `20260923_dydata-97-receipt-review-round3.md`（第三轮真实进展）。
- 全量回归：`python -m pytest --tb=short -q` 为 3160 通过 / 169 跳过 / 1 失败，4444.29 秒，不得写成全绿。唯一失败为 `tests/test_legacy_projection_bootstrap.py::test_r2c2_external_writer_lock_is_transient_and_retryable`，retry 阶段 0.05 秒 fence deadline 超时并继发 Windows SQLite 临时文件占用；169 跳过为专用 PostgreSQL 条件未配置（并发/恢复/发布数据库等），不计入通过。
- 写锁对照：当前分支 lock-fixed-1 失败 / lock-fixed-2 通过 15.76 秒；未修改 d36d991 基线 lock-baseline-1 通过 16.30 秒 / lock-baseline-2 失败 22.61 秒；同目录临时还原 HEAD 的 `settlement.py` 测试通过 16.62 秒，随后已 `finally` 恢复修复文件并确认字节一致。结论为基线也可复现的时序敏感失败，记录限制，不改阈值、不修无关写锁模块。
- 第二轮历史：Codex 独立测试 199 通过 / 2 失败已返修（A-B-A 幂等用例改走 coupon 级 `receipt_amount`、双券归属用例补上第二张券实收），并修复 `sub_order_amount_infos` 存在但非 list 被当作缺失回退到整单实收的漏洞（present-but-not-list 判为损坏并阻断）。
- 定向：`tests/test_receipt_commission_basis.py` + `tests/test_data_settlement_incremental.py` 99 通过（60.54 秒）；导出 API 20 通过 / 103 deselected；管理费 history 浏览器新代码通过、旧代码失败复现后已恢复新代码；既有 4 项导出浏览器用例通过。空结果行为保持端点原状：finance 两导出 200 仅表头，`/order-fee-details/export` 409 `EXPORT_EMPTY`。
- 批量查询回归（2026-09-23 新增）：`test_receipt_batch_variable_limit_resolves_all_coupons_without_n_plus_one` 覆盖 1001 券（SQLite 999 变量上限）；旧实现红测 **1 failed / 54 deselected（5.92 秒）**，`sqlite3.OperationalError: too many SQL variables`（`logs/dydata97/receipt-batch-red.txt`）。dsh 已在 `apps/worker/settlement.py::_receipt_amounts_for_details` 按 `RECEIPT_COUPON_BATCH_SIZE = 500` 分批查询，并按 `raw_order_id` 跨批次保留整单归属计数；Codex 绿测已完成，`logs/dydata97/receipt-batch-green.txt` 已完成：实收、结算、增量定向 **215 passed（135.06 秒，2026-09-24）**。
- 构建与静态：`npm --prefix apps/web run build` 通过（22.98 秒）；`git diff --check` 通过；治理锁、全局 0 errors / 0 warnings、路由 S4、计划结构一致性通过；索引 33 个已存在断链保持，未扩大无关修复。
- 修复后绿测（Codex 独立执行，2026-09-23）：`tests/test_finance_export_browser.py` 30 项**全部通过**（119.61 秒；修复前红测 15 通过 / 15 失败，224.21 秒），逐 14 类实际按钮下载（映射见该模块顶部），真实 FastAPI + SQLite + 真实 Vite + 真实 Chromium，认证沿用 test override，不是线上登录验证。`tests/test_api_finance_contract_g5.py` + `tests/test_api_store_billing.py` + `tests/test_api_dashboard.py` + `tests/test_api_finance_imports.py -k 'export or template or error_file'` 为 22 通过 / 106 deselected（46.91 秒）；`tests/test_frontend_finance_contracts.py` + `tests/test_frontend_store_finance_pages.py` + `tests/test_frontend_finance_v2_clean_operability.py` 为 39 通过（1.91 秒）；`npm --prefix apps/web run build` 通过（23.87 秒）；`git diff --check` 与计划一致性通过。既有 `tests/test_visual_smoke.py -k "finance or dydata_97"` 财务回归已通过（34 passed / 228 deselected，197.81 秒，`logs/dydata97/export-existing-browser.txt`）；CI 与部署尚未执行，不声称通过。
- 实现口径：佣金按实收，覆盖 0 / 缺失 / 损坏 / 多券 / 退款 / 锁账 / legacy 月度基数；管理费导出 `includeHistory` 修复。
- 导出按钮审计（2026-09-23）：`logs/dydata97/all-export-audit.md` 落盘 25 个按钮全链路清单、确定缺陷 D1-D4（含证据行号）、高置信候选 C1-C3、最小修复建议与 V1-V11 真实浏览器+真实本地 API 验证矩阵；不重跑全量 pytest。
- 修复后绿测已通过、尚待 CI/部署：逐按钮绿测与相关回归、Web build 均已通过（见上）；既有 `tests/test_visual_smoke.py -k "finance or dydata_97"` 财务回归已通过（34 passed / 228 deselected，197.81 秒，`logs/dydata97/export-existing-browser.txt`）；CI 与授权部署、部署后 smoke 尚未执行，不声称通过。主范围 14 类入口已验，未扩大到其他 11 个旁路按钮、未对其作结论；候选 C1/C2/C3 未修改、不在本次部署变更内。用户报告的整体导不出尚未复现，已再次请求页面与错误信息，仅管理费 `includeHistory` 有失败复现与修复证据，不得据此声称两类导出全面恢复。T1.1 与 Issue 保持进行中 / 已通过绿测、待 CI/部署与用户验收；用户已授权修复后部署，由 Codex 执行；无数据库迁移、不自动重算历史锁账。

**Failure Handling**：
- 导出根因无法复现：记录复现步骤与请求证据，阻塞并交 Codex 判断，不以新增列或按钮掩盖。
- 逐按钮矩阵中候选 C1-C3 无法定性：记录真实浏览器/数据条件与结果，明确标注「未复现」，不猜测性修改、不以候选未定性阻塞已确证缺陷的最小修复。
- 实收缺失、未知或无法按券归属：不猜测，按实现侧现有处理协议处理并记录样例，必要时升级为用户决策。
- 要求重算已锁账数据：拒绝并记录，保持快照只读。
- 部署门禁失败：停止发布并记录 CI/部署/日志证据，不宣称完成。
- 任一验证失败：停止并回写失败证据，不宣称完成。

**完成收尾：状态同步**：
- 完成实现、验证与 foundation 漂移判断后，把 Task 完成事实、验证证据、完成日期、漂移结论和建议下一 Task 提交给 `ai-project-manager`。
- 由 `ai-project-manager` 调度 `delivery-planner` 同步 `main-delivery-plan-dydata-97-fee-fixes.md`、`task-kanban-dydata-97-fee-fixes.md` 与本子计划三处状态。
- 同步后重新运行 `node .agent/project-manager-suite/tools/route-check.mjs . --target-stage S4 --json`，确认正式开发计划文件组三者一致；未通过前不得宣称 T1.1 已完成。

**Owner**：dsh执行 / Codex技术验收 / 用户业务验收

**前置**：Linear DYDATA-97 In Progress；用户已授权开发；用户已授权修复后部署（由 Codex 执行）；主计划、任务看板与本子计划已生成

**状态**：进行中
