# DYDATA-104 10月23日契约回捞

## S4-FCR-004 普通商品类型、精诚养车转换与上一完整月

| 字段 | 内容 |
|---|---|
| 来源 Task | dydata-104-followthrough T3.1；用户2026-10-26明确授权三个功能，数据核查由协作者负责 |
| 分类 | DRIFT |
| 改动项 | 普通页面取消 scope 配置/筛选及类型配对；精确 scope 目标统一为精诚养车类型；订单分佣默认上海上一完整月 |
| 原因 | 最新104正文覆盖旧范围/类型双字段、三列导入模板和元数据首月默认；独立打榜被明确排除 |
| 指向代码块 | routes/fee_admin.py、routes/_data.py、dashboard_publications/、product_classification.py、convert_jingcheng_product_types.py、订单分佣页面 |
| 目标 foundation 文件:章节 | foundation-api-dy-data/sku-fee-admin.md 分类与导入；foundation-schema-dy-data/product-rule-source.md 类型/范围；订单分佣默认筛选合同 |
| 严重度 | 必须保持权限、不可变财务事实及独立打榜语义 |
| 状态 | 已改（foundation 9ba40d1；仅合同回捞，不代表生产完成） |

现行增量合同见[商品类型与默认账期](../../api/product-type-classification.md)。新分类仅需有效类型；旧 scope 输入忽略并保留内部字段。精诚养车当前目录按精确存储值归一，转换先预演再锁定摘要应用，持续同步/编辑一致；历史费用、账单行键、确认及发票不改。分析类型在发布时冻结，财务仍使用历史类型；不引入 GET 重算。独立打榜保持全部/精诚养车/比亚迪本品。默认账期按上海上一完整月，显式月份和固定账单上下文优先，不以累计或更早月份代替。

## S4-FCR-001 发票登记简化与可信金额摘要

| 字段 | 内容 |
|---|---|
| 来源 Task | dydata-104-followthrough T3.1 发布与验收 |
| 分类 | DRIFT |
| 改动项 | 账单列表增加 promotionInvoiceSummary；登记移除人工购买方、税率及三项金额，分配金额由服务端确认事实派生 |
| 原因 | 用户已批准10月23日新增范围；旧合同仍要求客户端金额，会与已验证的登记请求不符 |
| 指向代码块 | apps/api/dy_api/routes/dashboard.py:757；apps/api/dy_api/routes/dashboard.py:3830；tests/test_api_store_billing.py |
| 目标 foundation 文件:章节 | docs/prd/foundation/foundation-api-dy-data/billing-invoice.md §2.1、§4.2；foundation-schema-dy-data/billing-invoice.md 发票金额与审计 |
| 严重度 | 建议 |
| 状态 | 已改（foundation 9ba40d1；仅合同回捞，不代表生产完成） |

当前实现合同：`storeId/invoiceNumber/invoiceDate/fillerPhone/allocations[]`，分配项为 `statementId/statementMonth/readVersion/promotionInvoiceGroupId`，保留可选 `replacesInvoiceId`。旧五项人工字段及分配金额接受但忽略，不进入新幂等摘要。当前有效完整组必须全部覆盖，组内负抵扣保留；无合格组摘要为 null。总额由锁定后的确认金额合计，净额按整数分 `floor((总额×100+53)/106)`，税额为差额，整张合票只舍入一次。20位 ASCII 数字保留前导零，不调用外部验真。权限、日期、状态、版本、号码唯一性、事务和历史保护保持；旧幂等请求从持久化历史事实重建校验，不重写旧金额。

## S4-FCR-002 历史商品状态时间语义

| 字段 | 内容 |
|---|---|
| 来源 Task | dydata-104-followthrough T3.1 发布与验收 |
| 分类 | GAP |
| 改动项 | 明确历史账期有效商品的判定时间及证据来源 |
| 原因 | 当前代码用重算时平台状态；附件六笔历史轮胎订单的商品当前已下架，不能通过修改上线状态绕过 |
| 指向代码块 | apps/worker/settlement.py:3063；apps/worker/product_sync.py:785 |
| 目标 foundation 文件:章节 | docs/prd/foundation/foundation-glossary-dy-data.md 有效商品；foundation-schema-dy-data/product-rule-source.md 历史快照 |
| 严重度 | 建议；需回捞术语，避免历史资格再次受当前在售状态误阻断 |
| 状态 | 已改（foundation 9ba40d1；仅合同回捞，不代表生产完成） |

用户追问“需求是怎么写的”后重新核对 Linear 原文：“首先按附件规则在系统配置中补充分佣商品列表”，配置完成后重跑8、9月，并“使用第一步已核验的有效商品规则”。原文未规定当前下架便排除历史订单；此前提问把“有效商品规则”简化为“有效商品”不准确。本次据既有需求解释并修正实现，不记作用户另行批准了新的业务规则。

当前在售状态与历史计费资格分开：保留原有效标记路径，仅额外允许已有档案且平台状态为 INACTIVE、同步为 SUCCESS 的商品继续进入原有校验。仍须满足正式付款与有效核销、稳定归属账号、唯一销售门店、渠道与范围规则、核销日生效费率、可证明实收及退款等条件；缺档案、未知/封禁/删除状态或失败同步不获新资格。不重写商品平台状态，不按本次SKU或月份硬编码，已确认/开票/锁账保护保持。34项专项及邻近结算回归共245 passed/2 PG skipped；平台档案无DML有SQL监听与全字段快照证明。

该项旧术语冲突已由后续 foundation-builder 增量提交 9ba40d1 回捞；原 S4 实装保持不直接修改冻结文件的边界。

## S4-FCR-003 精确历史销售归属证据

| 字段 | 内容 |
|---|---|
| 来源 Task | dydata-104-followthrough T3.1，用户认可21行归属并要求修复数据 |
| 分类 | GAP |
| 改动项 | 追加独立历史销售归属裁决表；费用结果可追踪裁决ID；仅结算/财务源版本及相应月结水位纳入裁决摘要 |
| 原因 | 当前解析器同时看到认证、解绑、审核等记录，106笔历史订单不能唯一解析；改当前绑定或伪造生效区间会扩大用户批准范围 |
| 指向代码块 | apps/worker/historical_sale_attribution.py；apps/worker/settlement.py；alembic/versions/20261023_0065_historical_sale_attribution.py |
| 目标 foundation 文件:章节 | foundation-schema-dy-data 历史归属证据、费用结果来源；foundation-api-dy-data 运维导入边界 |
| 严重度 | 必须保留原始身份、审批及财务保护边界 |
| 状态 | 已改（foundation 9ba40d1；仅合同回捞，不代表生产完成） |

导入限定原始内部/业务订单、券、原始账号、有效核销ID/时间/上海业务月及目标门店，记录来源摘要、审批证据、执行者和批次；默认只读预演，应用需精确文件SHA256，共享写入锁与同事务审计。裁决不可修改或删除，不创建当前账号绑定，不赋予查询权限，不自动创建重算任务。

运行时仅匹配批准的稳定交易身份。原始payload指纹保存作审批审计，合法退款、状态更新不因整份payload变化被当作身份变化；明确原核销撤销只对已经引用同裁决、同核销事实的费用进入原有撤销处理。不同订单、账号、门店、核销、月份及重核销不借旧裁决自动扩范围。旧费用结果的新增字段为NULL，原金额/指纹不回填；已确认、开票与锁账继续保护。没有裁决的月份保持旧水位算法。

## S4-FCR-005 财务冻结预览、依赖保护与统一票号所有权

| 字段 | 内容 |
|---|---|
| 来源 Task | dydata-104-followthrough T3.1，10月27日四类财务导入导出状态验收 |
| 分类 | GAP |
| 改动项 | 新增批次逐行冻结预览接口；明确 SAP finalSapCode、跨方向票号唯一性、已结算和已被后续事实使用资料的撤销限制 |
| 原因 | 原合同缺少预览新旧字段及转换依据；仅用历史文件摘要判断无变化会掩盖当前目标已经变化，旧预览或撤销可能覆盖后续事实 |
| 指向代码块 | apps/api/dy_api/routes/dashboard.py:2181、8251、8237；tests/test_dydata104_finance_state_matrix.py；apps/web/src/components/FinanceImportPreviewTable.tsx |
| 目标 foundation 文件:章节 | docs/prd/foundation/foundation-api-dy-data/billing-invoice.md 财务导入、SAP及撤销；foundation-schema-dy-data/billing-invoice.md 导入行和票号所有权 |
| 严重度 | 阻断错误财务写入；接口与实现合同须回捞 |
| 状态 | 已改（foundation 9ba40d1；仅合同回捞，不代表生产完成） |

`GET /api/v1/admin/finance-imports/{batchId}/rows` 按真实分页返回上传时保存的原值、新值、状态转换、允许变化与阻断原因；整批权限和阻断摘要不局限当前页。只读请求不从当前业务值拼造原预览。未保存冻结预览的旧待提交批次明确要求重新上传；已经提交的幂等回放保留。上传仍仅写导入批次与校验记录，确认提交重新检查当前档案/票据版本与范围。

四种导入模板的 `finalSapCode` 与实际 API 同步。已结算推广票据、已有扣款管理票据，以及已经被账单/SAP事实使用的资料，不能通过撤销破坏依赖。所有新票、换票、管理更正及导入先按同一 20 位 ASCII 数字票号串行检查跨方向所有权，保留前导零和历史登记事实。具体状态矩阵、并发与浏览器证据见 `docs/verification/dydata-104-oct27-finance.md` 和 `dydata-104-oct27-finance-preview.md`；本条不表示生产验收完成。

## S4-FCR-006 限定历史附件更正及后续生命周期

| 字段 | 内容 |
|---|---|
| 来源 Task | dydata-104-followthrough T3.1，用户批准阜阳指定8券的历史金额更正 |
| 分类 | GAP |
| 改动项 | 复用 MANUAL_CORRECTION 调整账本与财务审计，为精确来源创建可追溯的新账单版本；固定原费用依据并正确处理后续退款/取消 |
| 原因 | 原始费用指针被重算替换会丢掉手工差额；普通退款累计不包含手工差额，可能在全额退款后留下余额 |
| 指向代码块 | apps/worker/historical_fee_correction.py:418；apps/worker/settlement.py:4430；tests/test_historical_fee_correction_lifecycle.py |
| 目标 foundation 文件:章节 | docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md 调整、来源与历史保护；foundation-api-dy-data/billing-invoice.md 历史更正与票据事实 |
| 严重度 | 阻断错误历史更正及重复冲减 |
| 状态 | 已改（foundation 9ba40d1；仅合同回捞，不代表生产完成） |

本次服务限定2026年9月、8券16方向，逐条验证附件文件/行摘要、订单/券、门店、原费用与当前账单版本；预演无写入，应用必须提供预演摘要并在锁后重验，全批原子提交。仅非零差额增加调整，零差额仍留精确审计；原费用、原账单及目标外条目保留。已确认/开票/争议/复杂结转拒绝进入本次窄更正，不擅选其他入账月，也不登记缺证票据。

成功审计只固定对应原费用依据，不锁整个门店账期。人工更正不伪造退款时间；全额退款、取消核销包含手工差额精确归零，保护月份沿既有顺延流程处理，新核销不继承旧定额。历史手工定额后的部分退款没有已批准的比例规则时保留原金额并明确转人工核查，不猜算比例。验证及限制见 `docs/verification/dydata-104-oct27-correction.md` 与生命周期测试；本条不将候选、只读预演写成生产已应用。

零差额审计仅固定来源，不构成金额定额覆盖：其原费率部分退款继续生效；只有实际非零人工金额变化才触发上述待核查。16方向均保留审计，不能删除零差额证据来恢复退款。

## S4-FCR-007 月末资格冻结与来源身份合同

| 字段 | 内容 |
|---|---|
| 来源 Task | dydata-104-followthrough T3.1，用户确认月底完整采集并冻结 |
| 分类 | GAP |
| 改动项 | 新增不可变账号资格内容、采集观察与按月版本；费用引用资格版本；分析源依赖纳入版本插入 |
| 原因 | 当前绑定不能证明历史月末状态；普通成功任务不能替代完整来源证明，订单加密UID也不能直接当后台账户ID |
| 指向代码块 | apps/worker/account_qualification.py；apps/worker/browser_exports/backend_aweme_proof.py；apps/worker/month_close.py；alembic/versions/20261027_0066_account_qualification.py |
| 目标 foundation 文件:章节 | docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md 费用来源及资格快照；foundation-api-dy-data/billing-invoice.md 月结预检 |
| 严重度 | 阻断资格漂移及未知身份误计费 |
| 状态 | 已改（foundation 9ba40d1及1eca0ab）；仅合同回捞，不代表真实月末或生产验收完成 |

自2026-10起，同一来源行类型为子机构门店号/区域号且绑定状态认证成功才合格，认证信息自由文本不限制。上海月末最后2小时内启动且截止前完成的最后完整采集可冻结；最新失败、不完整、跨截止或仍运行均暂停月结。保留真实时间，不声称精确午夜状态，不把10月27日资料回填为月末。冻结后只引用该版本，销售门店关联、核销账期及费率日期保持各自合同。

自动永久采集最多8次/月及1条预算失败标记，内容按hash去重，单快照上限8MiB；平时导出继续但不永久增加资格快照。正式空筛选导出任务、同任务完成元数据和实际文件字节/hash共同构成来源证明，禁止mtime拾取旧文件或以另一scope列表总数代替。失败和主事务回滚不留下假成功。迁移0066为加法；已使用的不可变资格来源不允许降级删除。

官方订单查询中transfer_douyin_uid为短抖音号，transfer_uid为加密且非抖音UID的归属人编号。仅collector实际选中的原始短号字段与归一列一致时，才匹配冻结workbook同命名空间。未取得关联、明确不合格、冲突分别记录；昵称和跨命名空间数值相等均不能补桥。其他历史候选关联尚未批准为自动资格证据。验证及当前来源限制见 `docs/verification/dydata-104-oct27-monthend.md`。

自动计算启动与正式出账条件分别记录：完整来源和冻结资格允许派发正常全月计算，不能要求先存在已引用新资格的费用。正式提交及实际月份闭包仍检查所有current费用的资格版本；未知或不合格旧费用不得过滤删除，整批失败回滚。稳定计算摘要不引用费用输出版本，以免重复创建任务或重置失败预算。实现4369a41、合同1eca0ab已集成，根线程67项集成测试零跳过通过；真实月底仍待发生。

## S4-FCR-008 受保护账单来源与只发布恢复

| 字段 | 内容 |
|---|---|
| 来源 Task | dydata-104-followthrough T3.1，八月旧确认来源及发布差异修复 |
| 分类 | GAP |
| 改动项 | 受保护 current bill 全部不可变条目作为读取与聚合依据；增加不重算费用的预演、摘要校验和只发布恢复入口 |
| 原因 | 费用 current pointer 被后续重算替换，不能用新金额覆盖原确认账单，也不能因原费用已非 current 而拒绝合法的原确认来源 |
| 指向代码块 | apps/worker/protected_billing_authority.py；apps/worker/billing_source_capture.py；apps/worker/settlement_publication_only.py；scripts/ops/publish_settlement_authority.py；tests/test_protected_billing_authority_postgres.py |
| 目标 foundation 文件:章节 | docs/prd/foundation/foundation-schema-dy-data/settlement-reporting.md 不可变来源及投影；foundation-api-dy-data/billing-invoice.md 保护状态与发布恢复 |
| 严重度 | 阻断错误确认金额及页面、导出不一致 |
| 状态 | 已改（foundation 9ba40d1；仅合同回捞，不代表生产完成） |

已确认/锁账、任一方向确认、争议或票据依赖均保护整份 current bill；来源采用全部 immutable entries 及精确原 FeeResult，逐项核验身份、金额、行和头部闭合。展示快照的 NULL 保留，经济实收基数不能用展示快照或当前费用替代。同券同方向的新 primary 在跨店、跨月后也不能覆盖冻结依据；调整只按精确事件 ID 与原 anchor 判断，保留可证明的合法原依据退款/撤销/结转，不按券批量吞掉其他方向或其他 anchor。

恢复工具默认预演，摘要绑定完整来源、现行账单/依赖状态、active base 和请求及闭包月份。正式应用必须正常通过 heavy claim、资源准入和 lease，首末持锁重验摘要，再原子发布和生成未保护账单版本；不会调用费用重算或替换费用指针。恢复任务重启仍分派到只发布流程，不能退回普通重算。当前入口明确拒绝闭包触及 status4 的月份，不扩展锁账修复权限。金额更正及开票另走相应授权流程；本条不批准19方向3.59元等剩余差额。证据见 `docs/verification/dydata-104-oct27-protected-authority.md` 及 `dydata-104-oct27-publication-only.md`，生产是否应用须以独立收据为准。
