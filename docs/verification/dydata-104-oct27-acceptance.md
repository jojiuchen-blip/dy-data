# DYDATA-104 10月27日有效旧范围隔离验收

本记录承接 [T3.1 当前有效矩阵](../plans/delivery-plans/sub-delivery-plan-dydata-104-followthrough-T3.1-release-acceptance.md)，不是新计划或生产完成声明。验收基线 `801c179b6c07cb7bf2b9262d83c79912512cf9cb`，包含 PR63 商品类型/默认账期、PR65 旧归属实现和 PR64 线索核销字段；本单元仅新增测试和本记录，未修改业务代码、现有测试、全局计划或生产。

## 环境与可重复执行

- 独立 Git worktree、合成 SQLite 数据库、本地 FastAPI、Vite 与 Chromium；真实成功响应来自本地 API。认证注入 fixture 不等于真实生产登录验收；管理员发布专项使用真实本地登录 cookie。
- 浏览器下载读取落地字节，验证 UTF-8 BOM、CSV 表头、字段、行数、文件名；下载故障测试仅在明确的 403/500/网络分支注入错误。SKU 下载忙碌测试暂挂真实请求后用 `route.fetch()` 回收真实 API，未伪造成功内容。
- `npm ci --prefix apps/web --ignore-scripts --no-audit --no-fund`：75 packages，exit 0；执行前磁盘可用约 214.8 GiB，满足 15%/10 GiB 门禁。未修改 lock 文件。
- Python 使用主线程指定的现有测试虚拟环境。以下以 `$python` 表示该解释器；不将个人绝对路径或连接串写入可提交文件。
- 本次运行资产仅保留在忽略目录 `logs/oct27-acceptance/`；数据库、原始响应、下载、截图和 JUnit 不入 Git，无真实业务数据。

套件锁 `project-manager-suite@2.0.1` 有效；全局文件校验 0 errors / 0 warnings，S4 `canEnter=true`；T3.1 `--env-check` 为 `envReady=true`，独立 `verify-task-context` 为 `canExecute=true`。主线程已完成计划三者一致性检查，本单元未另改计划。

收尾 `route-check --target-stage S4 --json` 的通用选路自动选中历史 `ranking-export/T0.1`，不能把该字段作为104/T3.1三计划一致性证据；104指定任务验证如上，自动选路差异已反馈主线程，未改全局文件。

```powershell
node .agent/project-manager-suite/tools/verify-suite-lock.mjs .
node .agent/project-manager-suite/tools/validate-global-files.mjs .
node .agent/project-manager-suite/tools/route-check.mjs .
node .agent/project-manager-suite/skills/06-01-coding-standards/scripts/verify-task-context.mjs docs/plans/delivery-plans/main-delivery-plan-dydata-104-followthrough.md T3.1 --env-check
node .agent/project-manager-suite/skills/06-01-coding-standards/scripts/verify-task-context.mjs docs/plans/delivery-plans/main-delivery-plan-dydata-104-followthrough.md T3.1
```

## 执行结果与证据台账

这些为不同子集的运行记录，不冒充一次完整 pytest 或目标部署版本的最终验收。所有命令都在本隔离树执行；`pytest` 命令前缀为 `& $python -m pytest -q -ra`，各组使用相应 `--junitxml=logs/oct27-acceptance/<组>.xml`。

| 组 | 实际测试文件 / 选择 | 结果 | 资产 |
|---|---|---|---|
| api | `test_api_account_permissions.py`、`test_account_org_scope.py`、`test_account_audit_scope.py`、`test_clue_bulk_filters.py`、`test_api_clue_scope_regression.py`、`test_api_clues.py`、`test_api_dashboard_publications.py`、`test_api_product_type_visibility.py`、`test_dashboard_publication_product_types.py`、`test_api_meta_statement_months.py`、`test_dydata105_export_routes.py`、`test_export_metadata.py` | 159 passed / 0 skipped，127.45s，exit 0 | `api.log/xml` |
| contracts | `test_admin_unification.py`、`test_api_auth.py`、`test_api_admin_accounts.py`、`test_api_fee_admin.py`、`test_api_admin_sku_rules.py`、`test_api_finance_contract_g5.py`、`test_frontend_statement_month.py`、`test_frontend_product_type_visibility.py` | 172 passed / 0 skipped，73.88s，exit 0 | `contracts.log/xml` |
| browser | `test_account_scope_browser.py`、`test_clue_bulk_filter_browser.py`、`test_dydata104_ui_browser.py`、`test_finance_export_browser.py`、`test_dydata105_finance_pagination_browser.py` | 65 passed / 0 skipped，174.43s，exit 0 | `browser.log/xml`、`browser-artifacts/` |
| extra | `test_catalog_type_conversion.py`、`test_visual_admin_rule_permissions.py`、`test_api_douyin_ranking.py`，加新只读测试的首轮 | 原有 35 passed；新只读测试首轮失败，见下文夹具修正，exit 1 | `extra.log/xml`、`extra-artifacts/` |
| panels | 新 `test_dydata104_oct27_acceptance_panels.py` 四类面板 | 4 passed / 0 skipped，21.49s，exit 0 | `panels.log/xml`、`panel-artifacts/` |
| readonly-final | 新 `test_dydata104_oct27_acceptance_readonly.py` | 1 passed / 0 skipped，4.65s，exit 0 | `readonly-final.log/xml`、`readonly-final-artifacts/` |
| new-final | 上述两份新增测试最终合跑 | 5 passed / 0 skipped，23.04s，exit 0；不与 panels/readonly 重复计数 | `new-final.log/xml`、`new-final-artifacts/` |
| new-final-isolated | 两份新增测试最终文件；浏览器fixture改为模块独占数据库并验证正常审计总数恰为4 | 5 passed / 0 skipped，28.82s，exit 0；覆盖上一轮新增测试结果 | `new-final-isolated.log/xml`、`new-final-isolated-artifacts/` |
| drill | `test_dydata105_buttons_browser.py::test_dydata105_ranking_filters_drill_and_order_fee_direction_downloads` | 1 passed / 0 skipped，28.18s，exit 0 | `drill.log/xml`、`drill-artifacts/` |
| postgres 初次 | `test_clue_bulk_filters_postgres.py`、`test_catalog_type_conversion_postgres.py`、`test_admin_unification_postgres.py` | 10 skipped，4.90s；未配置专用连接，不记通过；补跑结果见后续增量 | `postgres.log/xml` |
| postgres-final | 上述三份真实PG专项，使用主线程提供的专用本地测试库 | 10 passed / 0 skipped，125.82s，exit 0；替代初次跳过 | `postgres-final.log/xml` |

按 JUnit 的 `(classname, name)` 去重并以最新运行覆盖同一用例，本单元选择的测试共 **447 个最新结果通过，0 个遗留失败、0 个遗留跳过**。这是多个定界测试组的证据集合，不是一轮完整整树测试。原失败/跳过原始记录仍保留，不删除或改写。

真实PG最终通过包括：1000 ID解析及查询/导出同范围；精诚转换金额保护、应用/回滚、忙锁拒绝、插入/改变scope加入目标集合时的predicate栅栏及预演过期检测；两管理员并发最后保留保护、等锁后操作者权限撤回重验、真实迁移保留范围并撤销旧凭据。测试库为loopback专用 `dydata_admin_test`，每case随机schema；连接从忽略安全文件仅载入测试进程，未输出或提交凭据。

新只读测试首轮将正常 `finance_operation_audit` 计入“不可变”指纹，实际仅多一条 `FINANCE_ORDER_DETAILS_EXPORT` 审计；按本轮合同允许正常访问审计，改为对其他业务/任务表及 publication metadata 全字段指纹比较，另行验证审计类型和成功结果。第二轮测试请求缺少门店导出必需的 `feeDirection/metricScope`，真实 API 返回 422；补齐与页面相同查询后通过。两处均为新增测试夹具/断言修正，未放宽业务保护、未改生产代码。原失败日志保留。

现有告警为 Starlette/httpx、MCP AuthSettings、Python 3.12 SQLite datetime adapter 等弃用告警；本记录不将它们写成已解决。

## 权限、发布、线索、类型与月份

| 验收项 | 真实入口 / 代码 | 本次证据与结论 |
|---|---|---|
| 当前角色和范围 | `auth.py`、`access_control.py`、`account_permissions.py`、账号 API；[现行权限合同](../rules/account-access-control.md) | 角色统一、管理员固定页面不扩大范围、空范围无数据、受限账号管理需包含目标全部范围、动态组织解析、审计范围隔离、越权与未知不泄露，通过 api/contracts |
| 旧会话即时失效 | `test_admin_unification.py::test_account_changes_invalidate_web_and_cli_generation` | 角色/范围变更使 Web 与 CLI 授权代次失效；真实旧 cookie/代次请求拒绝。组织变化按当前组织版本重新解析 |
| 管理员全局发布 | `fee_admin.py`；`test_api_fee_admin.py`；`test_visual_admin_rule_permissions.py` | 全范围管理员真实登录、保存、重载、发布成功与冲突；受限管理员可读但全局写按钮禁用且 API 拒绝；提交成功而刷新失败仍保留已提交事实。未对生产执行发布 |
| 门店选择器 | `/admin/accounts`；`test_account_scope_browser.py` | 名称搜索、跨搜索多选、导入、保存、桌面/390px；合成账号回读通过 |
| 线索批量门店 | `/clues/details`；`clue_store_filters.py`；`POST /clues/filter-options/stores/resolve`、`POST /clues/assignment-rounds` 及 `/export` | 名称搜索、跨搜索合并、全角规范化、粘贴账号/POI、前导零、重复去重、1000 ID边界、未知/越权隐藏、清空与显式零选、分页/总数/完整 CSV 同范围；浏览器两视口通过。仅当前正式 account/POI 映射生效，不把系统 storeId 或历史 raw binding 当匹配别名 |
| PR64核销门店/自店 | `test_api_clues.py::test_self_filter_uses_store_fact_without_follow_success`、`test_self_verified_filter_excludes_other_store_and_export_matches` | 自店核销按实际核销门店事实判断，不依赖跟进成功；跨店核销排除，导出同筛选通过 |
| 商品类型 | `fee_admin.py`、`dashboard_publications/finance.py`、`routes/meta.py`、普通页面 | 单条/批量/文件类型输入校验，原精诚 scope 精确转换；旧 scope 查询不影响普通页面的真实类型，冻结历史类型仍可选；同类型跨旧 scope 合并而不重复金额；授权范围和已发布来源保持，通过 |
| 精诚转换保护 | `scripts/convert_jingcheng_product_types.py`；`test_catalog_type_conversion.py` 及其 postgres 专项 | 预演零写入、精确 scope 目标集合、已有类型覆盖、非目标完整保留、应用/幂等/回读、预演过期拒绝、失败事务回滚、活动写任务栅栏、费用/费率/账单/行不变。CLI拒绝SQLite正式apply；真实PG补跑验证转换、锁、predicate栅栏与回滚通过，仍不代表生产转换 |
| 上一完整账期 | `utils/statementMonth.ts`；`test_frontend_statement_month.py`、`test_api_meta_statement_months.py` | 上海自然月、UTC月界、下一月与跨年，显式URL月优先，旧数据不取代上月；浏览器真实StoreSettlement组件默认9月、8/9/10切换与合法零通过。该组件测试使用真实 API，不冒称完整生产路由登录验收 |
| 独立打榜保护 | `test_api_douyin_ranking.py`、`test_frontend_product_type_visibility.py` | 独立 `all/jingcheng/byd` scope 和打榜时间合同保持，权限全量例外不扩展到其他业务；独立API与前端保护通过。未重算或发布生产排名 |

## 全部实际下载入口矩阵

以下穷举 `/details`、结算中心相关页、财务页及本轮商品治理入口。财务 API 前缀均为 `/api/v1`；“同 API”仍按不同实际按钮分别列出。通过表示本基线的隔离样本，不表示生产权限/金额已验收。

| 编号 | 页面 / 按钮 | API / 参数 | 执行证据 |
|---|---|---|---|
| DL01 | `/details` 导出，推广/管理方向 | `/order-fee-details/export`；当前方向及完整筛选/来源上下文 | `test_finance_export_browser.py` 真实文件/权限/文件名；api权限测试验证SQL分页、冻结来源与空范围；drill专项真实全路由月榜→单店→双方向下载通过 |
| DL02 | `/finance/promotion` 推广厂家模板 | `/admin/finance-imports/templates/PROMOTION_FACTORY_RESULT` | browser真实BOM/精确表头，仅表头；新只读测试重复两次 |
| DL03 | `/finance/promotion` 当前筛选导出 | `/admin/finance/invoices/export`，`feeDirection=PROMOTION` | browser+G5：同版、金额/筛选；61行跨分页完整导出 |
| DL04 | `/finance/management` 管理厂家模板 | `/admin/finance-imports/templates/MANAGEMENT_FACTORY_RESULT` | browser真实BOM/精确表头；新只读测试重复两次 |
| DL05 | `/finance/management` 当前筛选导出 | `/admin/finance/invoices/export`，`feeDirection=MANAGEMENT` | browser+G5：历史/当前、合法空结果、累计/筛选、61行完整导出 |
| DL06 | `/finance/orders/promotion` 全部命中结果 | `/admin/finance/order-details/export`，`feeDirection=PROMOTION` | browser+G5：完整冻结字段、金额、状态/日期/搜索、61行；新测试保留长ID/前导零 |
| DL07 | `/finance/orders/management` 全部命中结果 | 同上，`feeDirection=MANAGEMENT` | browser+G5：方向/筛选、不同pageSize均完整61行；新测试长ID/前导零 |
| DL08 | `/finance/stores` 基础模板 | `/admin/finance-imports/templates/BASIC_INFO` | browser精确表头；新只读测试重复两次 |
| DL09 | `/finance/stores` 基础导出 | `/admin/finance/stores/export` | browser+G5：当前基础资料和SAP、筛选/指标、61行完整；新只读测试两次 |
| DL10 | `/finance/stores?tab=sap` SAP差异导出 | `/admin/finance/stores/sap-discrepancies/export` | browser+G5：差异和权限/分页；新只读测试两次 |
| DL11 | 同上 SAP确认模板 | `/admin/finance-imports/templates/SAP_CONFIRMATION` | browser真实 `finalSapCode` 表头；新只读测试两次 |
| DL12 | `/finance/imports` 批次详情全部错误 | `/admin/finance-imports/{batchId}/error-file` | browser实际错误批次及文件名；新只读测试两次，完整行号/键/字段/原值/原因/建议 |
| DL13a | 推广页导入面板全部错误 | 同 DL12，推广批次 | 原browser与新四面板测试：真实上传→整批失败→提交禁用→下载解析 |
| DL13b | 管理页导入面板全部错误 | 同 DL12，管理批次 | 新四面板测试实际入口、合成格式错误、全部错误字节/行数与API一致 |
| DL13c | 门店页基础面板全部错误 | 同 DL12，基础批次 | 原browser与新四面板测试，真实下载解析 |
| DL13d | SAP页确认面板全部错误 | 同 DL12，SAP批次 | 新四面板测试实际入口、最终SAP模板、真实下载解析 |
| DL14 | `/finance/disputes` 账单异议导出 | `/admin/disputes/export` | browser文件/错误反馈/抽屉打开可达；G5状态/权限；61行完整下载 |
| DL15 | 商品口径批量导入下载模板 | `/admin/sku-product-imports/template` | `test_dydata104_ui_browser.py`真实字节、文件名、忙碌防重复、403/500/网络失败后重试 |
| DL16 | SKU费率导入抽屉标准模板 | `/admin/sku-fee-rule-imports/template` | 同上真实字节/表头/文件名/失败与重试 |
| DL17 | SKU费率导入抽屉结果文件 | `/admin/sku-fee-rule-imports/{batchId}/result-file` | 同上真实错误结果、逐行校验字段与文件名 |
| DL18 | SKU治理导入批次标准模板 | 同 DL16 | 独立组件入口真实下载；不是新增业务路由 |
| DL19 | SKU治理导入批次结果文件 | 同 DL17 | 独立组件入口真实下载与错误重试 |

`StoreRankingPage`、`StoreSettlementPage`、`StoreInvoicePage`、`StoreInvoiceStatusPage` 没有独立“导出账单/发票/单店结算”下载按钮；账单/费用的实际下钻导出走 DL01，财务单据走 DL03/DL05。不可虚构这四页自己的导出已通过。`FinanceImportsPage` 提供在线导入日志列表及错误文件，不提供“导出全部导入日志”或原文件下载；原上传文件不保存。不存在“发票附件/开票导入”按钮，不把厂家结果导入称为开票导入。

`DouyinRankingPage` 及其 `DouyinRankingExportDialog` 是独立打榜范围，未修改；`test_api_douyin_ranking.py` 已执行其 API/导出保护。其生产浏览器下载待主线程统一验收，不混记为财务下载。

## 只读、分页和文件证据

新增只读测试实际执行 12类API请求各两次：四模板、双方向财务单据、双方向财务订单、门店资料、SAP差异、异议和错误文件，共 24份文件。每次请求后比较业务模型 metadata 和 publication metadata 的所有表完整行哈希，覆盖金额、方向、确认/审核/发票/分配/付款/锁账、导入批次、JobRun与发布版本。仅正常访问审计豁免指纹并单独验证，最终四条 `FINANCE_ORDER_DETAILS_EXPORT`、结果均 `SUCCESS`；没有业务表/任务/发布变化。

回执包含每次请求的端点、参数、行数、SHA-256 和正常审计数，见 `logs/oct27-acceptance/new-final-isolated-artifacts/test_every_finance_download_ke0/download-receipts.json`。此处只保存合成文件摘要，不提交原文件或业务ID。订单样本专门使用超过JavaScript安全整数的文本ID和前导零券ID，原样读回。

61行浏览器测试对推广、管理、门店、SAP差异、异议分别操作下一页/末页、20/50分页、筛选后页码重置，下载全集与服务端结果逐项核对；两方向财务订单额外验证每档pageSize均下载61行且金额一致。空结果的财务下载为BOM+仅表头并显示EMPTY提示；订单费用明细自己的空结果合同不同，按真实409/禁用验证。

截图示例（均为合成数据）：

- `logs/oct27-acceptance/browser-artifacts/test_bulk_name_merge_paginatio0/bulk-applied-1440.png`
- `logs/oct27-acceptance/browser-artifacts/test_bulk_name_merge_paginatio1/bulk-applied-390.png`
- `logs/oct27-acceptance/browser-artifacts/test_dy104_default_previous_mo0/explicit-october.png`
- `logs/oct27-acceptance/browser-artifacts/test_dydata105_finance_orders_0/orders-promotion-all-61.png`
- `logs/oct27-acceptance/browser-artifacts/test_dydata105_finance_orders_1/orders-management-all-61.png`
- `logs/oct27-acceptance/new-final-isolated-artifacts/test_all_four_panel_error_down1/SAP_CONFIRMATION-errors.png`

已人工读取SAP失败面板与390px线索截图：失败提示、错误下载入口、禁用提交可见；线索窄屏所选门店/计数可读，长列表使用整页滚动。

## 已交主线程的真实缺口：逐行预览

现有差异预览未满足10月27日合同“目标行/新旧值/允许转换”。实际上传后 `FinanceImportActionPanel.tsx:204` 仅批次统计；`FinanceImportsPage.tsx:199` 仅撤销链和错误；`dashboard.py:2131` 只返回 `diff_summary.changedRows`。`FinanceImportRow`（`models.py:2593`）只有 `normalized_payload`、目标及撤销关联，没有预览时旧字段快照；上传创建逐行记录在 `dashboard.py:1889`。`types/dashboard.ts:2527` 也没有逐行差异模型。

最小实现落点已交主线程，未编辑这些页面或API：上传时按四类业务键读取目标并冻结旧值/目标版本；详情API分页返回行号、键、目标、版本、字段旧/新值与允许转换，提交仍重新检查实时版本和保护事实；共享差异表供上传确认面板和批次详情消费。不能在查看详情时读取可变“当前值”冒充上传时旧值。主线程已分别分派前后端实现，整合后须复验正常/错误/更正/保护状态及分页。

## 边界与剩余验收

- 本单元没有把原四类财务提交/撤销旧测试当成本轮新状态合同通过；四类正式写入、management更正/依赖保护由财务执行单元负责。
- 月末资格/冻结、SKU自动完整性、阜阳8券窄更正、8/9月全量对账由各执行单元负责，本记录不替代这些证据。
- 未执行最终整树完整pytest、Web build、精确提交CI、迁移、无源码挂载镜像、生产部署/发布/浏览器/导出验收；仍由主线程完成。
- 原10项PG跳过已经专用本地库复跑全部通过，见 postgres-final；不遗留可执行跳过。线索变量为`DYDATA_CLUE_TEST_DATABASE_URL`；分类转换为`DYDATA_PUBLICATION_TEST_DATABASE_URL`；账号权限为`DYDATA105_AUTH_TEST_DATABASE_URL`。每项fixture均建立和清理自己的随机schema，不接生产。
- 工作流memory文件未更新；技能usage/audit仅写宿主要求的本机日志。
