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
| 状态 | 实现与验证中；冻结 foundation 回捞待评审，未宣称生产生效 |

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
| 状态 | 待评审 |

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
| 状态 | 已按需求原文澄清并实现，foundation 回捞待评审 |

用户追问“需求是怎么写的”后重新核对 Linear 原文：“首先按附件规则在系统配置中补充分佣商品列表”，配置完成后重跑8、9月，并“使用第一步已核验的有效商品规则”。原文未规定当前下架便排除历史订单；此前提问把“有效商品规则”简化为“有效商品”不准确。本次据既有需求解释并修正实现，不记作用户另行批准了新的业务规则。

当前在售状态与历史计费资格分开：保留原有效标记路径，仅额外允许已有档案且平台状态为 INACTIVE、同步为 SUCCESS 的商品继续进入原有校验。仍须满足正式付款与有效核销、稳定归属账号、唯一销售门店、渠道与范围规则、核销日生效费率、可证明实收及退款等条件；缺档案、未知/封禁/删除状态或失败同步不获新资格。不重写商品平台状态，不按本次SKU或月份硬编码，已确认/开票/锁账保护保持。34项专项及邻近结算回归共245 passed/2 PG skipped；平台档案无DML有SQL监听与全字段快照证明。

foundation-glossary 的“至少要求平台状态有效”及 T2.3 沿用的“有效商品”待按以上解释回捞；本轮 S4 不直接改写冻结的 foundation 文件。

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
| 状态 | 按已批准修复范围实施及验证；foundation 回捞待评审 |

导入限定原始内部/业务订单、券、原始账号、有效核销ID/时间/上海业务月及目标门店，记录来源摘要、审批证据、执行者和批次；默认只读预演，应用需精确文件SHA256，共享写入锁与同事务审计。裁决不可修改或删除，不创建当前账号绑定，不赋予查询权限，不自动创建重算任务。

运行时仅匹配批准的稳定交易身份。原始payload指纹保存作审批审计，合法退款、状态更新不因整份payload变化被当作身份变化；明确原核销撤销只对已经引用同裁决、同核销事实的费用进入原有撤销处理。不同订单、账号、门店、核销、月份及重核销不借旧裁决自动扩范围。旧费用结果的新增字段为NULL，原金额/指纹不回填；已确认、开票与锁账继续保护。没有裁决的月份保持旧水位算法。
