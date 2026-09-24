# DYDATA-97 费用明细导出恢复与佣金按接口订单实收计算

> **版本**：v2
> **发布日期**：2026-09-22（v2 修订 2026-09-23）
> **适用范围**：DYDATA-97（费用明细导出恢复 + 全部导出按钮逐项检查 + 佣金按接口订单实收计算 + 用户授权部署）
> **开发模式**：隔离工作区单任务（S4），主任务集成
> **上游发现结论**：按实际文档核对，必需产物齐备——`docs/prd/mainprd-dy-data.md`、`docs/prd/subprd/`（9 份）、`docs/prd/foundation/foundation-schema-dy-data.md` 及同名子目录、`docs/prd/foundation/foundation-api-dy-data.md` 及同名子目录均存在，无 `required` 缺失，结论为 `canProceed=true`，未进入失败分支；Codex 实际运行报告为最终依据。
> **轮次状态**：进行中（更新至 2026-09-23）；owner：dsh执行 / Codex技术验收 / 用户业务验收。第二轮 Codex 独立测试 199 通过 / 2 失败已返修（A-B-A 改走实收字段、双券第二券补实收），并修复 `sub_order_amount_infos` 存在但非 list 被当作缺失回退的口径漏洞。第三轮最终全量 `python -m pytest --tb=short -q` 为 3160 通过 / 169 跳过 / 1 失败（4444.29 秒），唯一失败为 `tests/test_legacy_projection_bootstrap.py::test_r2c2_external_writer_lock_is_transient_and_retryable` 的时序敏感写锁超时；不得写成全绿。用户新增明确要求：检查订单分佣页面和财务页面各个导出按钮，修复后部署；已完成只读逐按钮全链路审计（25 个按钮，证据 `logs/dydata97/all-export-audit.md`），本轮范围扩充为「逐按钮检查 + 最小修复 + 用户授权部署」，部署由 Codex 执行。修复后绿测已通过：`tests/test_finance_export_browser.py` 30 项全部通过（119.61 秒，修复前 15 通过 / 15 失败 224.21 秒），逐 14 类按钮真实下载、真实 FastAPI+SQLite+Vite+Chromium、认证 test override（非线上登录验证）；相关 API 子集 22 通过 / 106 deselected、前端契约 39 通过、`npm --prefix apps/web run build` 23.87 秒、`git diff --check` 与计划一致性通过；既有 `tests/test_visual_smoke.py -k "finance or dydata_97"` 财务回归已通过：34 passed / 228 deselected（197.81 秒，`logs/dydata97/export-existing-browser.txt`）；CI 与部署尚未执行，不声称通过。T1.1 保持进行中，已通过绿测、待 CI/部署与用户验收。

## 0. 本计划使用指南

1. 先读本主计划，确认本组只有单一 Task `T1.1`、发布闸门、设计决策与风险。
2. 打开任务看板，定位 `T1.1` 对应子开发计划。
3. 执行前只加载该子开发计划与 `PRD 双链·读` 指向的真实章节，禁止重复全量调查。

### 0.1 PRD 加载约束

- 先读 `docs/prd/mainprd-dy-data.md` §全局设计规则，建立导出一致性、金额单位与权限边界地图。
- 费用明细与导出：读 `docs/prd/subprd/03-subprd-order-fee-details.md` §4 费用方向与筛选、§5 一券一方向费用明细。
- 接口契约：读 `docs/prd/foundation/foundation-api-dy-data/settlement-reporting.md` §3、§4。
- 管理端导出：读 `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md` §4.3。
- 基数与字段口径：读 `docs/prd/foundation/foundation-glossary-dy-data.md`（费用计算基数）与 `docs/prd/foundation/foundation-schema-dy-data/product-rule-source.md`（#8 原始券）。
- 拆分产物与大文件按章节定位读取，不整包拉入。

### 0.2 读前门禁 / AI 自检清单

- `T1.1` 必须能从任务看板定位到唯一子开发计划，且三处状态同为进行中。
- 导出根因未确认前，必须先复现故障；不得以增加列或按钮代替故障复现。
- 未读到原始订单/券字段、导出端点与相关测试的真实落点前，不得声称金额口径或导出口径已定义。

### 0.3 完成前验证门禁

- 完成前必须执行 `T1.1` 的 `Verification Method`，证据写入 `Evidence` 指定位置。
- 三类导出必须复现真实路由、权限与筛选证据；金额断言必须来自接口订单实收字段的可核查样例，不得用与实现同源的期望值自证。

## 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Python | >= 3.12 | `python --version` |
| pytest | >= 8 | `python -m pytest --version` |
| Node.js | >= 22 | `node --version` |
| npm | >= 10 | `npm --version` |

## 1. 差距基线

| 差距 | 影响 | 对应任务 | 状态 |
|---|---|---|---|
| 费用明细导出故障根因未确认：`/admin/finance/invoices/export`、`/admin/finance/order-details/export`、`/order-fee-details/export` | 财务与门店无法导出明细，查询与导出口径无法核对 | T1.1 | 部分复现：管理费 `includeHistory` 列表/导出不一致；用户报告的整体导不出尚未复现 |
| 订单分佣页与财务各页导出/模板/错误行按钮从未逐项全链路核对，缺按钮清单与证据 | 无法判断「点了没反应」是单按钮缺陷还是共享下载链路缺陷，修复面无法收敛 | T1.1 | 只读审计完成：25 个按钮清单、4 项确定缺陷（D1-D4）、3 项高置信候选（C1-C3），证据 `logs/dydata97/all-export-audit.md`；D2/D3/D4 最小修复已完成（4 个生产文件，`docs/devlog/20260923_dydata-97-all-export-fix.md`），逐按钮红测 15 通过/15 失败（本地隔离链路、非生产复现）→ 修复后绿测 30 项全部通过（119.61 秒）；主范围 14 类按钮已验，未扩大到其他 11 个旁路按钮；CI/部署待 Codex |
| 佣金与费用基数使用核销/券/订单 paid 字段：`apps/worker/settlement.py::_direction_source_amount`（约 4040 行）与 legacy 佣金链 `_commission_cent(paid_amount_cent, ...)`（约 2797 行） | 实收与实付不等时佣金与费用基数错误；多券订单可能重复使用整单金额 | T1.1 | 实现完成；最终全量已跑（3160 通过 / 169 跳过 / 1 失败，唯一失败为基线可复现的写锁时序敏感项，不得写全绿），未经用户验收 |
| 结算基线脚本 `scripts/settlement/build_settlement_base_from_current_data.py:64` 已按 `sub_order_amount_infos[].receipt_amount` 处理，主链未复用同口径 | 同一接口订单在脚本与主链金额不一致 | T1.1 | 实现完成；最终全量已跑（3160 通过 / 169 跳过 / 1 失败，唯一失败为基线可复现的写锁时序敏感项，不得写全绿），未经用户验收 |

## 2. 分工与边界

| 角色 | 职责 |
|---|---|
| dsh 执行 | 复现导出故障、实现最小修复、执行子计划声明的验证方法、回写任务状态 |
| Codex 技术验收 | 校验计划结构、计划一致性与 task-context；独立运行 `python pytest`、`node`/`npm` 验证；执行用户授权后的 CI、受控部署与部署后 smoke |
| 用户业务验收 | 验收导出可用性（含 25 个导出/模板/错误行按钮）、部署结果与佣金按接口订单实收计算的业务口径 |

边界：无数据库迁移；用户已授权修复后部署（由 Codex 验收并部署）；不自动重算历史锁账与生产账单；已锁账快照只读不修改；保留实付字段原含义；不以新增导出列或按钮代替故障复现。

## 3. 执行阶段

### Phase 1：导出恢复与实收基数统一

**Entry Criteria**：Linear DYDATA-97 In Progress；主计划、任务看板与 T1.1 子计划三者状态一致为进行中；三类导出端点的复现证据通道已确定；导出按钮逐项审计清单已落盘。

**Exit Criteria**：T1.1 的 `Verification Method`（含逐按钮真实浏览器+真实本地 API 矩阵）全部通过并落盘 `Evidence`；主计划、任务看板与子计划状态完成同步。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T1.1 | [T1.1 导出恢复与实收基数](sub-delivery-plan-dydata-97-fee-fixes-T1.1-receipt-amount.md) | 进行中 |

## 4. 任务看板

- 看板入口：[task-kanban-dydata-97-fee-fixes.md](task-kanban-dydata-97-fee-fixes.md)

## 5. 发布闸门

- [x] 三类导出端点先有失败复现记录，再在真实路由下通过（含权限 403、筛选一致性；空结果保持端点现有行为——`/admin/finance/invoices/export` 与 `/admin/finance/order-details/export` 返回 200 且仅表头，仅 `/order-fee-details/export` 返回 409 `EXPORT_EMPTY`）
- [ ] 订单分佣页与财务各页 25 个导出/下载模板/错误行按钮逐项核对完成（清单与证据 `logs/dydata97/all-export-audit.md`）；确定缺陷 D1-D4 有红→绿证据，候选 C1-C3 有真实浏览器/大数据结论或明确记录为未复现。**当前仅主范围 14 类入口经修复后绿测验证（`tests/test_finance_export_browser.py` 30 项通过），未扩大到其他 11 个旁路按钮，未对其作结论；候选 C1/C2/C3 均未修改，不在本次部署变更内，不得暗示已修。**
- [x] 逐按钮验证矩阵优先复用 `tests/test_visual_smoke.py` 的真实本地 FastAPI 夹具（`live_fastapi_base_url` / `vite_live_admin_api_base_url`），不以 mock 路由通过代替生产结论
- [x] 实收基数修复覆盖：实收 != 实付、实收为 0、实收缺失、无效金额、多券按券归属、退款、已锁账、推广/管理两个费用方向
- [x] legacy 佣金链与双费用链分离基数，实付字段原含义不变
- [x] `python -m pytest` 相关回归与 `npm --prefix apps/web run build` 由 Codex 执行通过
- [ ] 用户已授权修复后部署；由 Codex 完成 CI 与受控部署及部署后 smoke，不自动重算历史锁账、不修改已锁账快照（**CI/部署尚未执行**）
- [x] 主计划、任务看板、T1.1 子计划状态一致，`validate-plan-structure` 与 `check-plan-consistency` 通过

**当前验证状态（2026-09-23 更新：绿测已通过，CI/部署未执行）**：最终全量 `python -m pytest --tb=short -q` 为 3160 通过 / 169 跳过 / 1 失败（4444.29 秒），不得写成全绿；169 跳过为专用 PostgreSQL 条件未配置（并发/恢复/发布数据库等），不计入通过；唯一失败为 `tests/test_legacy_projection_bootstrap.py::test_r2c2_external_writer_lock_is_transient_and_retryable`，retry 阶段 0.05 秒 fence deadline 超时并继发 Windows SQLite 临时文件占用，属基线也可复现的时序敏感失败（当前分支 lock-fixed-1 失败 / lock-fixed-2 通过 15.76 秒；未修改 d36d991 基线 lock-baseline-1 通过 16.30 秒 / lock-baseline-2 失败 22.61 秒；同目录临时还原 HEAD 的 `settlement.py` 通过 16.62 秒并已 `finally` 恢复且字节一致），不改阈值、不修无关写锁模块。定向 `tests/test_receipt_commission_basis.py` + `tests/test_data_settlement_incremental.py` 99 通过（60.54 秒）；导出 API 20 通过 / 103 deselected；管理费 history 浏览器新代码通过、旧代码失败复现后已恢复新代码；既有 4 项导出浏览器用例通过；`npm --prefix apps/web run build` 通过（22.98 秒）；`git diff --check`、治理锁、全局 0 errors / 0 warnings、路由 S4、计划结构一致性通过；索引 33 个已存在断链保持，未扩大无关修复。新增批量查询回归（2026-09-23）：1001 券触及 SQLite 999 变量上限，旧实现红测 **1 failed / 54 deselected（5.92 秒）**，`sqlite3.OperationalError: too many SQL variables`（`logs/dydata97/receipt-batch-red.txt`）；dsh 已在 `apps/worker/settlement.py::_receipt_amounts_for_details` 按 `RECEIPT_COUPON_BATCH_SIZE = 500` 分批查询并按 `raw_order_id` 跨批次保留整单归属计数；Codex 绿测 `logs/dydata97/receipt-batch-green.txt` 已完成：实收、结算、增量定向 **215 passed（135.06 秒，2026-09-24）**。佣金按实收（0/缺失/损坏/多券/退款/锁账/legacy 月度基数）与管理费导出 `includeHistory` 修复已实现；用户报告的整体导不出尚未复现，已再次请求页面与错误信息，不得声称两类导出全面恢复。2026-09-23 追加只读逐按钮审计（`logs/dydata97/all-export-audit.md`）：主范围 14 个按钮 + 相关页面 11 个按钮，共 25 个；确定缺陷 D1（管理费 includeHistory，已修复）、D2（CORS 未 `expose_headers`）、D3（账单异议导出反馈被详情抽屉吞掉）、D4（错误行下载无异常处理），高置信候选 C1（同步 revokeObjectURL）、C2（100000 行上限 413）、C3（榜单导出 300s 超时）。T1.1 与 Issue 保持进行中；用户已授权修复后部署，由 Codex 执行验收与部署；无数据库迁移、不自动重算历史锁账、未获业务验收前不关闭。**修复后绿测（Codex 独立执行）**：`tests/test_finance_export_browser.py` 30 项全部通过（119.61 秒；修复前 15 通过 / 15 失败 224.21 秒），逐 14 类按钮实际下载，真实 FastAPI+SQLite+Vite+Chromium，认证 test override（非线上登录验证）；`tests/test_api_finance_contract_g5.py` + `tests/test_api_store_billing.py` + `tests/test_api_dashboard.py` + `tests/test_api_finance_imports.py -k 'export or template or error_file'` 22 通过 / 106 deselected（46.91 秒）；`tests/test_frontend_finance_contracts.py` + `tests/test_frontend_store_finance_pages.py` + `tests/test_frontend_finance_v2_clean_operability.py` 39 通过（1.91 秒）；`npm --prefix apps/web run build` 通过（23.87 秒）；`git diff --check` 与计划一致性通过。主范围 14 类入口映射见 `tests/test_finance_export_browser.py` 顶部；未扩大到其他 11 个旁路按钮。既有 `tests/test_visual_smoke.py -k "finance or dydata_97"` 财务回归已通过（34 passed / 228 deselected，197.81 秒，`logs/dydata97/export-existing-browser.txt`）、CI 与部署尚未执行，不声称通过。候选 C1（`revokeObjectURL`）/C2/C3 均未修改，不在本次部署变更内，不得写成已修。

**逐按钮红测与最小修复证据（2026-09-23，绿测已通过、待 CI/部署）**：`logs/dydata97/all-export-red.txt` 为真实本地 FastAPI + SQLite + 真实 Vite + 真实 Chromium（沿用认证 override 与跨域配置）的逐按钮链路红测，30 项 = **15 通过 / 15 失败**，无 fixture 失败；**属本地隔离环境真实链路红测，不是生产复现**（生产 nginx 同源，D2 响应头不可读不显现），不得据此宣称生产已复现或已恢复。15 项失败全部为审计已定性的缺陷：D2 11 项（6 项文件名回退 + 5 项 `X-Export-Result: EMPTY` 提示不可见）、D3 2 项（详情抽屉遮挡导出按钮、失败无 `alert`）、D4 2 项（错误行下载无失败反馈）。15 项通过对应 14 类按钮成功内容已验：模板表头、CSV 行数与列表 total 一致、`utf-8-sig` 可解码、门店越权与权限矩阵 403、D1 管理费 `includeHistory` 行集一致。已完成最小修复，仅改 4 个生产文件、未改/放宽任何测试断言：`apps/api/dy_api/main.py`（CORS `expose_headers` 仅 `Content-Disposition`/`X-Export-Result`/`X-Export-Generated-At`/`X-Request-ID`，origin/credentials/权限未放宽）、`apps/web/src/pages/FinanceDisputesPage.tsx`（独立 `exportMessage/exportIsError`，置于 fixed 抽屉之上，成功 `status`/失败 `alert`）、`apps/web/src/pages/FinanceImportsPage.tsx`（错误行下载 async handler + busy 防重 + `try/catch` 分别转 `success`/`error`、无 `finally`，成功/失败可见文案，失败 `alert` 含「下载失败」，复用 `userFacingError`，不清空批次详情/错误行分页/撤销状态）与 `apps/web/src/components/FinanceImportActionPanel.tsx`（错误行下载 async handler + busy 防重 + `try/catch/finally` + 成功/失败可见文案，失败 `alert` 含「下载失败」，复用 `userFacingError`；上传预览、批次状态与提交流程保持原样）。未改共享 Blob `revokeObjectURL`（C1 无失败证据，15 项成功内容下载已通过）、未改导出上限/鉴权/冻结金额/其他页面。**修复后绿测：`tests/test_finance_export_browser.py` 30 项全部通过（119.61 秒），上述 D2/D3/D4 失败项转绿；相关回归 22 + 39 通过，Web build 23.87 秒通过，`git diff --check` 与计划一致性通过**；既有 `tests/test_visual_smoke.py -k "finance or dydata_97"` 财务回归已通过（34 passed / 228 deselected，197.81 秒，`logs/dydata97/export-existing-browser.txt`）；CI、授权部署与部署后 smoke 尚未执行，不编造通过；发布闸门中 CI/部署相关勾选保持未勾选。候选 C1/C2/C3 均未修改，不在本次部署变更内，不得暗示已修。证据见 `docs/devlog/20260923_dydata-97-all-export-fix.md`。

## 6. 设计决策与边界（已确认）

- 金额单位统一为分；优先从现有 `raw_payload` 解析订单/券的明确 `receipt_amount` 及 `sub_order_amount_infos` 按券匹配值，并保留 `0` 与缺失语义。
- 未知、不完整或无法按券归属的实收不得猜测；不得把订单总额重复用于每张券；不得以实付冒充实收。
- 实收缺失是否升级为数据质量阻断，保持实现侧现有处理协议，不在本任务改变状态机或错误码。
- 保留实付字段原含义：`order_paid_amount_cent`、`coupon_paid_amount_cent`、核销 `paid_amount_cent` 不就地改写。
- legacy 佣金链与双费用链分离基数：佣金按分离后的实收基数计算，实付字段仅作原始事实保留。
- 无数据库迁移；不自动重算历史锁账与生产账单；已锁账快照只读不修改。
- 导出按钮逐项审计已完成（25 个按钮，`logs/dydata97/all-export-audit.md`）；确定缺陷按最小修复处理，候选 C1-C3 需真实浏览器/大数据结论后再决定是否修改，不以新增列或按钮代替故障复现。本次**未修改 C1（共享 `revokeObjectURL`）/C2/C3**，它们不在本次部署变更内，不得写成已修。
- 用户已授权修复后部署；部署由 Codex 执行并留存 CI/部署/smoke 证据，未获业务验收前不得宣称完成。

## 7. 风险与应对

| 风险 | 影响 | 应对 | Owner | 状态 |
|---|---|---|---|---|
| `raw_payload` 缺失或字段不完整 | 无法确定券级实收，金额口径无法闭合 | 按设计决策记录为未知/缺失，不猜测；回归覆盖缺失样例 | dsh执行 -> Codex技术验收 | 待观察 |
| 导出根因跨路由/筛选/权限/序列化多处 | 修复面扩散 | 先红测复现再最小修复，逐端点与逐权限验证 | dsh执行 -> Codex技术验收 | 已部分复现：管理费 `includeHistory` 列表/导出不一致；其余路由未复现 |
| 多券订单按整单金额摊分 | 金额重复计费 | 禁止整单金额重复使用，按券匹配 `receipt_amount` | dsh执行 -> Codex技术验收 | 待观察 |
| 触及已锁账数据 | 破坏不可变快照 | 锁账快照只读，不重算、不写账单 | dsh执行 -> Codex技术验收 | 待观察 |
| 导出问题被以新增列或按钮掩盖 | 故障未真正修复 | 发布闸门要求失败复现证据 | dsh执行 -> Codex技术验收 | 待观察 |
| 25 个导出按钮中仅部分有证据，候选 C1-C3 未定性即部署 | 生产仍可能「点了没反应」或大数据超时 | 部署前按 `logs/dydata97/all-export-audit.md` §6 矩阵完成真实浏览器+真实本地 API 验证，候选项有结论或明确记录未复现；当前主范围 14 类入口已绿测通过，其余 11 个旁路按钮与 C1/C2/C3 未验证、未修改，部署说明中如实标注 | dsh执行 -> Codex技术验收 | 主范围 14 类绿测通过；11 旁路与 C1-C3 未定性 |
| 授权部署触及生产账单或历史锁账 | 破坏不可变事实 | 仅部署代码；不自动重算历史锁账、不写已锁账快照；部署后 smoke 只读核验 | Codex技术验收 | 待观察 |

## 8. AI 执行示例

1. 从任务看板选择 T1.1，打开子开发计划。
2. 先按 `Verification Method` 在真实路由复现三类导出故障并留存请求与响应证据。
3. 按设计决策实现 `receipt_amount` 优先解析与基数分离，运行相关 pytest 与 Web 构建。
4. 由 Codex 独立复跑结构、一致性、task-context 与测试；回写 T1.1 状态与证据。

## 9. PRD → 任务反向索引

| PRD | Task |
|---|---|
| `docs/prd/subprd/03-subprd-order-fee-details.md` §4、§5 | T1.1 |
| `docs/prd/foundation/foundation-api-dy-data/settlement-reporting.md` §3、§4 | T1.1 |
| `docs/prd/foundation/foundation-api-dy-data/billing-invoice.md` §4.3 | T1.1 |
| `docs/prd/foundation/foundation-glossary-dy-data.md` 费用计算基数 | T1.1 |
| `docs/prd/foundation/foundation-schema-dy-data/product-rule-source.md` #8 | T1.1 |
| `docs/prd/mainprd-dy-data.md` §全局设计规则 | T1.1 |
