# DYDATA-104：2026-10-27 财务导入导出与状态不变量

范围来自 DYDATA-104 2026-10-27 的四类财务验收增量，承接 S4/T3.1。基线 `d206a654`。本记录使用隔离合成门店、账单及票据，未导入生产文件、改生产账务、登记真实票据或部署。

## 实际入口

四类实现均在 `apps/api/dy_api/routes/dashboard.py`，没有独立 `finance_import` 模块。前端通过 `FinanceImportActionPanel.tsx` 上传/预览/提交/更正，`FinanceImportsPage.tsx` 提供批次日志、错误、覆盖关系与撤销。

| 页面 | 类型/操作 | 权限 |
| --- | --- | --- |
| `/finance/stores` | BASIC_INFO 模板、导入、资料 CSV 导出 | FIN04 + 管理员 + 门店范围 |
| `/finance/stores?tab=sap` | SAP_CONFIRMATION 模板、导入、SAP 差异 CSV 导出 | FIN04 + 管理员 + 门店范围 |
| `/finance/promotion` | PROMOTION_FACTORY_RESULT 模板、导入、发票 CSV 导出 | FIN01 + 管理员 + 门店范围 |
| `/finance/management` | MANAGEMENT_FACTORY_RESULT 模板、导入、发票 CSV 导出 | FIN02 + 管理员 + 门店范围 |
| `/finance/orders/promotion`、`/finance/orders/management` | 财务订单列表与 CSV 导出 | FIN03 + 管理员 + 门店范围 |
| `/finance/imports` | 日志、详情、错误 CSV、满足条件时撤销 | FIN06；详情/撤销再检查对应类型页面与整批门店范围 |
| `/finance/disputes` | 异议列表、CSV 导出 | FIN05 + 管理员 + 门店范围；本轮不改变异议工作流 |

| HTTP 入口（前缀 `/api/v1`） | 作用/业务写入 |
| --- | --- |
| GET `/admin/finance-imports/templates/{importType}` | 四类 UTF-8 BOM CSV，仅正式表头，无示例数据；业务只读 |
| POST `/admin/finance-imports` | CSV/XLSX 上传预校验；仅保存批次、标准化摘要与行/错误；不改变正式费用、账单或票据 |
| GET `/admin/finance-imports`、`/{batchId}` | 批次分页与详情；业务只读 |
| GET `/admin/finance-imports/{batchId}/rows` | 冻结逐行新旧值、目标版本与状态迁移，真实分页；类型页权与全批门店范围检查；业务只读 |
| GET `/admin/finance-imports/{batchId}/error-file` | 全量逐字段错误 CSV；业务只读 |
| POST `/admin/finance-imports/{batchId}/commits`、`/corrections` | 显式原因、幂等键和读取版本；整批事务，新业务版本与操作审计 |
| POST `/admin/finance-imports/{batchId}/reversals` | 仅允许未结算且无后续依赖的当前目标；追加恢复/墓碑版本，不删除历史 |
| GET `/admin/finance/invoices/export` | 两方向费用/发票导出，读取固定分析发布 |
| GET `/admin/finance/order-details/export` | 两方向订单明细导出；允许单独访问/导出审计，业务只读 |
| GET `/admin/finance/stores/export`、`/admin/finance/stores/sap-discrepancies/export` | 资料与 SAP 差异导出；业务只读 |
| POST `/admin/finance/management-invoices/{storeId}/{month}/corrections` | 管理费正式票据更正；沿用原金额/分配合同，本轮补统一票号归属校验与锁 |

没有通用发票导入入口。普通推广票登记是 POST `/promotion-invoices`，与推广厂家结果导入分开。既有真实路由用例 `test_store_to_finance_both_directions_complete_api_flow` 验证普通登记状态为 `SUBMITTED_PENDING_FACTORY_REVIEW`，之后只有独立厂家结果才能成为 `APPROVED_SETTLED`。

## 类型与允许变化

所有导入、导出、撤销均不得重算费用、生成账单、自动确认账单、修改费率/实收、改动另一费用方向或启动采集/重算/发布任务。已确认/锁账的账单是厂家结果的有效来源，合法厂家结果不解除或重写其确认、金额或锁账。

| 类型 | 正式字段与精确键 | 提交允许变化 | 禁止变化/保护 |
| --- | --- | --- | --- |
| BASIC_INFO | `storeId,storeName,sapCode,importedAt`；键 `storeId` | 当前 type=1 财务资料链追加版本，仅名称快照/SAP 等基础字段 | 不修改门店主数据、POI 映射、费用、确认、发票、结算、锁账；错误 ID/名称拒绝；不接受 POI 作为替代匹配键 |
| SAP_CONFIRMATION | `storeId,storeName,financeInitialSap,serviceStoreCode,finalSapCode,factoryConfirmationResult,confirmedAt`；键 `storeId` | 同一 type=1 资料链追加最终 SAP 与 CONFIRMED/REJECTED 事实 | 不联动任何费用方向和历史账单快照；与 BASIC_INFO 共享同一并发控制链，不能跨模板/月用旧预览覆盖 |
| PROMOTION_FACTORY_RESULT | `invoiceNumber,reviewResult,rejectionReason,settlementDate,settlementAmountCent`；键精确 20 位 ASCII 票号 + 批次月定位当前分配 | 未结算当前票据追加版本；APPROVED_SETTLED 需全额与日期，生成 status=3 和厂家事件；REJECTED_REUPLOAD 需原因，生成 status=4 | 不增加应计费用或票额；复制原分配，不改变店/月；已结算不得退回拒绝，也不能撤销结算；生命周期/换票依赖禁止撤销 |
| MANAGEMENT_FACTORY_RESULT | `storeId,statementMonth,storeName,invoiceNumber,invoiceDate,deductionDate,deductionAmountCent`；键 `storeId+month` | 有效管理确认、无现有有效票据且可开票全额为正时，登记发票及同额厂家扣款，status=3 | 不允许部分扣款、零/负金额、跨月、名称错配、重复票据；已有有效票据的不同载荷须走独立正式更正入口；已生成扣款不得撤销 |

管理负数结转继续使用既有 invoiceable projection，不把原始确认额直接当作结转后全额。负数/退款不是导入“付款”事实的替代品。不存在独立的付款表或自动银行付款指令，本系统的“已结算/厂家扣款”由上述明确厂家结果事实驱动。

## 版本、撤销与失败不变量

- 同上传幂等键/同文件参数重放同批次；同键不同载荷冲突。提交重放不再生成费用、票据、版本或分配。
- `NO_CHANGE` 必须同时满足标准化内容相同且原批次的全部业务目标仍当前、非墓碑；仅“历史曾导入”不算当前无变化。
- 同模板/月的正式版本由 PG 事务锁与现有唯一约束共同保护；BASIC/SAP 还保存内部预览 profile ID，并锁门店/当前资料，防止跨模板、跨月的旧预览覆盖。
- 提交时重新验证门店名称、精确目标、有效确认、全额、已有票据和当前目标范围；预览不是业务预留。第二行失效/意外异常时，第一行的业务版本与扣款一起回滚。
- 管理票号由导入与独立更正共享事务锁；多个号码按固定顺序取锁。全部历史版本保留原店/月/方向的票号所有权；同店同月的历史号码可以追加正式更正，不能跨店/月重复计费。
- 推广新票/换票登记与管理导入/更正共用 `finance-invoice-number:{number}` PG 事务锁，先取号码锁，再取账单/物理票据锁；管理多号码批次按号码排序。推广锁后重查成功幂等与全部管理历史票号，管理也反查推广票号注册，防止跨方向重复票据。普通推广成功登记仍为待厂端审核，不生成管理扣款或已结算事实。
- 已结算推广或已产生管理扣款的批次返回 `409 IMPORT_SETTLEMENT_PROTECTED`；资料已被账单快照/SAP 确认引用、票据有后续生命周期/换票依赖时返回 `409 IMPORT_DEPENDENCY_PROTECTED`。详情/日志 `canReverse` 与 POST 使用同一保护判断。
- 未结算 REJECTED_REUPLOAD 可追加恢复版本回到原待审；账单、费用、确认与原分配额不变。旧版本被其他操作覆盖则整批撤销冲突，不部分恢复。
- 模板空表返回 `422 IMPORT_EMPTY_FILE`，不创建空的可提交版本。全角/阿拉伯数字字符不是有效 ASCII 发票号码。
- 上传时将模板白名单字段及状态迁移冻结在行内 `__preview`，不纳入内容 hash；before/after、目标 ID/版本、允许变化与阻断原因均来自上传时事实。GET rows 不重查即时业务目标，默认/最多50行，返回全批 `previewSummary.frozenAvailable/blockedRowCount/totalRows`。旧批次没有冻结依据返回明确不可用，未提交旧批次必须重新上传；既有成功幂等重放保持。

## 缺陷与回归证据

| 原缺陷（真实 HTTP + DB 复现） | 修正 |
| --- | --- |
| 管理费预览后新增其他当前票据/改门店名，旧预览仍 200 并覆盖 | 提交锁定账单及管理确认后重校验，返回 IMPORT_PREVIEW_STALE；失败整批回滚 |
| 资料 A→B 后重传历史 A 被误报 NO_CHANGE | 内容匹配还须验证全部目标仍当前 |
| BASIC 与 SAP/跨月旧预览均可覆盖共享资料链 | 保存预览 profile ID、串行化当前资料目标，过期预览 409 |
| 只有表头仍 FIRST_IMPORT_READY，可生成空正式版本 | 空数据文件 422，回滚临时批次 |
| 20 位全角数字管理票号通过校验 | 两类厂家结果统一要求 ASCII 数字 |
| 同文件或其他门店可重复使用同管理票号 | 批内去重、历史归属检查、导入/更正共享 PG 票号锁 |
| 已结算推广撤销 status 3→2、管理已扣款撤销成墓碑，旧测试还期待成功 | 按 104 最新保护拒绝；更新旧测试，保留未结算拒绝结果恢复路径 |

新增 `tests/test_dydata104_finance_state_matrix.py`：真实应用路由/鉴权/提交回读，对完整金融事实行、费用结果、账单/确认/异议、发票/分配/事件、资料、任务和固定发布表做前后指纹比较。允许导入批次/校验日志及访问/冲突审计独立增长，不将审计写入误算为费用变化。

样本为可重建的源码常量 `CONTENTS`：推广 1200 分、管理 2500 分；前导零长文本 SAP、跨店、跨月、错方向、零/负数/部分金额、无权限/权限变更、全部错误、空模板、失败回滚、幂等、已确认/锁账、已开票/已结算以及资料消费依赖。CSV UTF-8 BOM 与 XLSX 浏览器预览用例均使用合成样本，不持久保存真实原文件。

单个成功用例的正式事实对照：基准为3张账单（两店、两月）、6笔方向确认、1张推广待审票、1笔有效分配、1个票号注册；账单推广合计3600分、管理合计7500分。BASIC/SAP 分别只新增1笔当前财务资料；推广只追加1个票据版本/1笔对应分配/1个厂家事件，仍仅1张有效物理票及1笔有效1200分分配；管理只新增1笔2500分发票与等额扣款。各类型及重复请求均不改3张账单的金额、6笔确认或另一费用方向；前后逐行指纹由测试断言。

以下为 `CONTENTS` 原始 UTF-8 上传 CSV 的字节数/SHA-256（下载模板/错误 CSV 另带 BOM）：

| 类型 | 字节数 | SHA-256 |
| --- | --- | --- |
| BASIC_INFO | 106 | `739c1cc7bfe52aca56e291dabb46b5cd065bfc2c989d1e8616df0acf7bd49270` |
| SAP_CONFIRMATION | 184 | `f06496d49fffc4fa907171eb2d5ecc1bc141a3c79ec3a6285392d7e0b1ca27c6` |
| PROMOTION_FACTORY_RESULT | 134 | `d8db1ef822bb740b2ce3545995063e6b2fada96e8393110ca4dead98a46fb871` |
| MANAGEMENT_FACTORY_RESULT | 167 | `b8a448d35a8f4b0fe96ae80cf6ef1436c8c3d20a2fc323c43005388707edb070` |

## 验证记录与剩余限制

已执行：

| 验证 | 结果 |
| --- | --- |
| SQLite 财务回归：矩阵、`test_api_finance_contract_g5.py`、`test_api_finance_g2.py`、`test_api_finance_imports.py`、`test_dydata105_import_replay.py`、`test_api_store_billing.py` | 存储边界与跨方向管理校验后 226 passed / 9 PG-only skipped，110.54秒 |
| 推广新登记/换票全局票号锁增量后：`test_api_store_billing.py test_api_finance_g2.py test_dydata104_finance_state_matrix.py` | 189 passed / 13 PG-only skipped，103.50秒；含普通登记、生命周期、换票、既有管理更正、全部新增矩阵；PG-only另列已执行 |
| 实际 PG：`test_dydata104_finance_state_matrix.py` | 扩展61项全部通过，837.21秒；四类状态、已结算/已消费保护及9组真实HTTP资料/票号竞争；该轮先于冻结预览与后续存储边界增量，增量另列 |
| 浏览器：`test_dydata105_buttons_browser.py -k 'four_import or xlsx_preview'` | 12 passed / 9 deselected，43.54秒；真实 Vite + FastAPI + Chromium，合成 SQLite；截图保存在 pytest 临时输出，不含生产数据 |
| 冻结预览后端专项 | 首轮矩阵/import/replay 68 passed / 9 PG-only skipped，37.04秒；包含四类型冻结before、分页/全批scope/白名单、旧批次不可用与提交保护；5项真实PG通过，101.99秒 |
| 冻结预览合入后重新执行真实 PG 并发：`test_dydata104_finance_state_matrix.py -k test_postgres_` | 9 passed / 57 deselected，157.27秒；3组资料链 + 6组管理票号跨店/月 import/import、correction/correction、mixed；每组仅一个成功/一个冲突/一个有效目标所有权 |
| 跨方向票号新增覆盖 | SQLite真实路由3项通过：已登记推广→管理拒绝，已有管理票→推广新票/换票拒绝；真实PG 4 passed / 74 deselected，53.65秒，强制推广/管理分别先持有号码锁 × 新票/换票，均1成功+1明确409，跨方向总所有权1，无deadlock/500 |
| `git diff --check`、相关Python `compileall -q` | 最终提交前通过，exit 0；测试无失败，第三方弃用/并发 schema warning 保留 |

- 代码/SQLite 回归与真实 PG 并发独立记录；CI、合并、生产版本、生产浏览器与实际导出验收由集成负责人承接。
- PG测试仅连接本机专用 `_test` 数据库，各用例创建并清理 UUID 专属 schema，使用现行 SQLAlchemy metadata；本轮无新迁移，不把它表述为整套生产 Alembic/镜像发布门禁。
- 新增冻结预览 API 后，前端逐行新旧值展示由独立前端工作树集成验收；本工作树不改产品前端。既有12项浏览器通过不替代该新增UI验收。
- 其他模块的榜单/订单费用/异议导出沿用各自契约；本轮新增指纹矩阵覆盖财务四类导出、模板、错误文件和日志，既有财务契约回归包含异议与普通票据登记。
- 本轮发现 API 契约文档的 SAP 模板字段缺少现行 `finalSapCode`，以及旧“撤销覆盖”描述未反映最新已结算保护；属于 foundation 漂移，交主线程追加待改请求，未改旧基础文档。
- 无模型或迁移变更。应用回滚保留已写新版本、票据与审计；不得通过删除历史或恢复旧数据库消除期间的正式事实。回滚旧应用会重新暴露本记录修复的写入漏洞，应优先前滚修复并保持保护入口。

## 交叉审查补充：直接管理票据更正的 ASCII 校验

`correct_management_invoice` 原先只有长度和 `isdigit()`，因此20位全角数字及 Arabic-Indic 数字可通过真实更正路由并生成V2。该窄区现与两类导入保持相同的“20位 + ASCII + 数字”判断，错误明确标识 `invoiceNumber`。

新增 `test_direct_management_correction_rejects_unicode_digits_without_business_or_audit_writes` 覆盖两种Unicode数字：返回422/VALIDATION_FAILED，完整业务事实和全部 `finance_operation_audit` 行逐行不变；同一用例紧接着使用合法ASCII票号，仍正常生成2500分管理票V2。本次不调整票号归属锁、金额或其他业务合同。

- SQLite相关号码/归属校验6项通过，5.73秒；既有直接管理票更正版本/幂等/冲突/审计契约1项通过，3.65秒。
- 隔离PostgreSQL真实路由2项通过，23.36秒；`git diff --check` 通过，exit 0。未操作生产或修改迁移。
