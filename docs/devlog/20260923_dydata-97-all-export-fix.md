# DYDATA-97 全部导出按钮缺陷最小修复（D2/D3/D4，2026-09-23）

范围：`logs/dydata97/all-export-audit.md` §3.2 三项确定缺陷的最小修复；不含候选 C1/C2/C3，不含上限、鉴权、冻结/金额口径与其他页面改造。
角色：dsh 执行实现与红测核对；Codex 已独立完成绿测（30 项全部通过）、Web build 与计划一致性核对，CI、授权部署与部署后 smoke 尚未执行；用户业务验收。

## 1. 红测证据（真实本地环境，非生产复现）

- 证据文件：`logs/dydata97/all-export-red.txt`。
- 结果：30 项 = **15 passed / 15 failed**（`15 failed, 15 passed, 2 warnings in 224.21s`），没有 fixture 失败。
- 运行环境：真实本地 FastAPI + SQLite + 真实 Vite dev server + 真实 Chromium（Playwright），沿用既有认证 override 与 `DY_API_CORS_ORIGINS` 跨域配置。
- **性质声明**：这是本地隔离环境的真实链路红测，**不是生产复现**；生产 nginx 为同源，D2 的响应头不可读在生产同源下不显现。不得据此宣称生产已复现或已恢复。
- 15 项失败全部为审计已定性的 D2/D3/D4：
  - D2（11 项）：6 项文件名回退断言失败（推广/管理服务费、订单明细、门店、`/details`、错误行、账单异议），5 项空结果 `EMPTY` 提示不可见。
  - D3（2 项）：打开异议详情抽屉后导出，按钮被 fixed 抽屉遮挡导致点击超时；失败分支无 `alert`。
  - D4（2 项）：`/finance/imports` 批次详情与导入面板的错误行下载在请求中断时无任何可见失败反馈。
- 15 项通过 = 14 类按钮的**成功内容**已验：模板表头、CSV 行数与列表 total 一致、`utf-8-sig` 可解码、门店角色越权 403、权限矩阵 403，以及 D1 管理费 `includeHistory` 开/关行集一致。通过项证明服务端响应体与共享下载链路本身可用。

## 2. 本次修改（4 个生产文件，未改任何测试断言）

1. `apps/api/dy_api/main.py`：`CORSMiddleware` 增加 `expose_headers=["Content-Disposition", "X-Export-Result", "X-Export-Generated-At", "X-Request-ID"]`。仅暴露下载元数据头；`allow_origins` / `allow_credentials` / `allow_methods` / `allow_headers` 与鉴权完全未放宽。服务端各端点本已正确写入这些头（`dashboard.py:1682/2022/4780-4783/6047-6050/11339-1141`），此前仅因跨域不可读而全部退化。
2. `apps/web/src/pages/FinanceDisputesPage.tsx`：导出改用独立 `exportMessage` / `exportIsError`；反馈渲染在页面标题操作区并置于 fixed 抽屉之上（`position: relative; zIndex: 50`），成功后 `role="status"`、失败后 `role="alert"` 且文案含「失败」。`actionMessage`、检测轮询与审批转移逻辑保持原样。
3. `apps/web/src/pages/FinanceImportsPage.tsx`：批次详情「下载全部错误」改为 async `downloadErrorFile`，`errorDownloadState` busy 阻止重复点击，`try/catch`（成功转 `success`、失败转 `error`，无 `finally`），成功/失败均有可见文案，失败 `role="alert"` 且以「下载失败：」复用 `userFacingError`。不清空批次详情、错误行分页或撤销状态；权限路径未改。
4. `apps/web/src/components/FinanceImportActionPanel.tsx`：面板内「下载全部错误」同样改为 async handler + busy + `try/catch/finally` + 成功/失败可见反馈（失败 `role="alert"`，含「下载失败」，复用 `userFacingError`）。上传预览、批次状态与提交流程保持原样；新上传开始时仅重置下载反馈。

未改动：共享 `requestDownload` / `requestDownloadResult` 的 `revokeObjectURL` 行为（C1 无失败证据，且 15 项成功内容下载已通过），导出上限、鉴权、冻结/金额口径及其他页面。`downloadFinanceInvoices` 的 `includeHistory` 类型未改动：`FinanceFeePage` 以变量传参，结构类型已可编译，无需类型改造。

## 3. 验收状态（2026-09-23 更新：绿测已通过，CI/部署未执行）

- 红测（修复前）：`tests/test_finance_export_browser.py` 30 项 = **15 passed / 15 failed**（224.21 秒）。
- 绿测（修复后，Codex 独立执行）：同一模块 30 项**全部通过**（119.61 秒），逐 14 类按钮的真实下载均已验。运行环境为真实 FastAPI + SQLite + 真实 Vite + 真实 Chromium，认证沿用既有 test override，**不是线上登录验证**。
- 相关回归（Codex）：`tests/test_api_finance_contract_g5.py` + `tests/test_api_store_billing.py` + `tests/test_api_dashboard.py` + `tests/test_api_finance_imports.py -k 'export or template or error_file'` 为 22 通过 / 106 deselected（46.91 秒）；`tests/test_frontend_finance_contracts.py` + `tests/test_frontend_store_finance_pages.py` + `tests/test_frontend_finance_v2_clean_operability.py` 为 39 通过（1.91 秒）。
- 构建与静态：`npm --prefix apps/web run build` 通过（23.87 秒）；`git diff --check` 与计划一致性检查通过。
- 前一轮全量 3160 通过 / 169 跳过 / 1 失败保留：唯一失败为基线可复现的 0.05 秒写锁时序敏感项，不改阈值、不修无关写锁模块；实收 99 项定向已通过。
- 批量查询回归（2026-09-23 新增）：`tests/test_receipt_commission_basis.py -k receipt_batch_variable_limit` 覆盖 1001 张券（触及 SQLite 999 变量上限）；旧实现红测 **1 failed / 54 deselected（5.92 秒）**，失败为 `sqlite3.OperationalError: too many SQL variables`，证据 `logs/dydata97/receipt-batch-red.txt`。dsh 已在 `apps/worker/settlement.py::_receipt_amounts_for_details` 按 `RECEIPT_COUPON_BATCH_SIZE = 500` 分批查询，并按 `raw_order_id` 跨批次保留整单归属计数。Codex 绿测已完成，`logs/dydata97/receipt-batch-green.txt` 已完成：实收、结算、增量定向 **215 passed（135.06 秒，2026-09-24）**。
- 主范围 14 类入口见 `tests/test_finance_export_browser.py` 顶部映射；本次未扩大到其他 11 个旁路按钮，不对其作结论。
- 既有 `tests/test_visual_smoke.py -k "finance or dydata_97"` 财务回归**已通过**：34 passed / 228 deselected（197.81 秒），证据 `logs/dydata97/export-existing-browser.txt`。
- **尚未执行 / 不声称通过**：CI、授权部署与部署后 smoke 均未执行。§5 发布闸门中与 CI/部署相关的勾选保持未勾选。
- 部署变更不含候选 C1：共享 `requestDownload` / `requestDownloadResult` 的 `revokeObjectURL` **未修改**，不在本次部署变更内，不得把 C1 写成已修；C2/C3 同样未修改。
- 用户已授权修复后部署；部署由 Codex 执行，部署后 smoke 只读核验。无数据库迁移，不自动重算历史锁账，不修改已锁账快照。

## 4. 复跑方式（供 Codex）

```powershell
python -m pytest tests/test_finance_export_browser.py -q --tb=short
```

预期：30 项全部通过；修复后实测 30 passed（119.61 秒）。随后按既有流程执行 `npm --prefix apps/web run build`、CI 与授权部署。

## 5. 证据索引

- 红测：`logs/dydata97/all-export-red.txt`
- 审计：`logs/dydata97/all-export-audit.md`
- 生产前状态快照：`logs/dydata97/production-before.json`
- 既有 visual_smoke 财务回归：`logs/dydata97/export-existing-browser.txt`
- 批量查询回归：`logs/dydata97/receipt-batch-red.txt`、`logs/dydata97/receipt-batch-green.txt`（待 Codex 出最终 summary）
- 相关既有：`logs/dydata97/export-history-red.txt`、`export-history-green.txt`、`full-pytest.txt`
