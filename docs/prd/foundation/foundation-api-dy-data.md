# API 接口设计 - dy-data（抖音经营引擎）

> 生成时间: 2026-07-20 11:20
> 来源: foundation-builder Phase 4
> 关联: [术语表](foundation-glossary-dy-data.md) · [Schema](foundation-schema-dy-data.md)
> 范围: DYDATA-1/21/30/31/33/38 的商品、双费率、批量导入、商品同步、双费用结算与四页生产查询
> 状态: **Phase 4 已于 2026-07-20 获用户确认**；本文描述目标契约，不表示对应运行接口已经实现

---

## §0 契约基线

- 宿主项目统一前缀为 `/api/v1`；后台管理接口使用 `/api/v1/admin`。
- 成功响应沿用宿主项目 `{ data, definitions?, meta }` 包络，不采用套件示例中的 `{ code, msg, data }`。
- 目标业务 JSON 字段使用 `camelCase`；当前运行接口中的 `snake_case` 属于旧契约，实施时必须同步更新 FastAPI schema、前端类型和测试，不在最终响应中长期维护两套同义字段。
- 失败响应使用 HTTP 状态码和结构化 `detail`；批量导入错误必须返回原文件行号、字段和可操作原因。
- 金额使用整数分，费率使用六位小数字符串，月份使用 `YYYY-MM`，自然日使用 `YYYY-MM-DD`，时间使用带时区 ISO 8601。
- 对外只使用 `orderId`、`couponId`、`skuId`、`statementId` 等业务 ID；数据库自增 `id` 不进入 URL、对账或导出。
- 所有业务接口默认需要登录；门店数据范围由服务端重验，URL 和查询参数只表达筛选，不能授予权限。
- 列表目标结构统一为 `{ list, total, page, pageSize }`；空列表返回 `[]`，可空对象字段必须保留并返回 `null`。
- 本轮未取得抖音商品在线 API 的脱敏响应样例和正式文档，外部接口只记录待映射字段，不虚构 URL、鉴权或枚举。

详细公共约定、分页、错误码、幂等和权限见 [common-contract.md](foundation-api-dy-data/common-contract.md)。

## §1 全接口总览

| # | 方法 | 路径 | 来源 | 用途 | 数据源表 | 变更 | 详见 |
|---|------|------|------|------|----------|------|------|
| 1 | GET | `/api/v1/meta/filters` | 现有·需改动 | 获取门店、产品、账期和费用方向筛选元数据 | `dim_sku_product_rules`、两张聚合表 | **变更** | [公共契约 §6](foundation-api-dy-data/common-contract.md#6-get-apiv1metafilters--结算筛选元数据) |
| 2 | GET | `/api/v1/admin/sku-products` | 新建 | 分页查询 SKU 当前平台快照与人工分类 | `dim_sku_product_rules` | **新增** | [SKU 与费率 §1](foundation-api-dy-data/sku-fee-admin.md#1-get-apiv1adminsku-products--sku-商品列表) |
| 3 | PUT | `/api/v1/admin/sku-products/{skuId}` | 新建 | 更新 SKU 人工维护字段 | `dim_sku_product_rules` | **新增** | [SKU 与费率 §2](foundation-api-dy-data/sku-fee-admin.md#2-put-apiv1adminsku-productsskuid--更新-sku-人工分类) |
| 4 | GET | `/api/v1/admin/sku-fee-rules` | 新建 | 分页查询双费率版本 | `sku_fee_rule` | **新增** | [SKU 与费率 §3](foundation-api-dy-data/sku-fee-admin.md#3-get-apiv1adminsku-fee-rules--双费率版本列表) |
| 5 | GET | `/api/v1/admin/sku-fee-rules/{ruleVersion}` | 新建 | 查询不可变费率版本详情 | `sku_fee_rule` | **新增** | [SKU 与费率 §4](foundation-api-dy-data/sku-fee-admin.md#4-get-apiv1adminsku-fee-rulesruleversion--费率版本详情) |
| 6 | POST | `/api/v1/admin/sku-fee-rules` | 新建 | 发布单个 SKU 的新费率版本 | `sku_fee_rule`、`dim_sku_product_rules` | **新增** | [SKU 与费率 §5](foundation-api-dy-data/sku-fee-admin.md#5-post-apiv1adminsku-fee-rules--发布单条费率版本) |
| 7 | GET | `/api/v1/admin/sku-fee-rule-imports` | 新建 | 查询费率导入批次 | `sku_fee_rule_import_batch` | **新增** | [SKU 与费率 §6](foundation-api-dy-data/sku-fee-admin.md#6-get-apiv1adminsku-fee-rule-imports--导入批次列表) |
| 8 | POST | `/api/v1/admin/sku-fee-rule-imports` | 新建 | 上传模板并执行全量预校验 | 两张费率导入表 | **新增** | [SKU 与费率 §7](foundation-api-dy-data/sku-fee-admin.md#7-post-apiv1adminsku-fee-rule-imports--上传并预校验) |
| 9 | GET | `/api/v1/admin/sku-fee-rule-imports/{batchId}` | 新建 | 查询批次及逐行结果 | 两张费率导入表 | **新增** | [SKU 与费率 §8](foundation-api-dy-data/sku-fee-admin.md#8-get-apiv1adminsku-fee-rule-importsbatchid--导入批次详情) |
| 10 | POST | `/api/v1/admin/sku-fee-rule-imports/{batchId}/commit` | 新建 | 原子发布预校验通过的整批规则 | 两张费率导入表、`sku_fee_rule` | **新增** | [SKU 与费率 §9](foundation-api-dy-data/sku-fee-admin.md#9-post-apiv1adminsku-fee-rule-importsbatchidcommit--原子发布整批规则) |
| 11 | GET | `/api/v1/admin/sku-fee-rule-imports/{batchId}/result-file` | 新建 | 下载逐行校验/写入结果 | 两张费率导入表 | **新增** | [SKU 与费率 §10](foundation-api-dy-data/sku-fee-admin.md#10-get-apiv1adminsku-fee-rule-importsbatchidresult-file--下载结果文件) |
| 12 | GET | `/api/v1/admin/sku-fee-rule-imports/template` | 新建 | 下载四字段官方导入模板 | 无持久化表 | **新增** | [SKU 与费率 §11](foundation-api-dy-data/sku-fee-admin.md#11-get-apiv1adminsku-fee-rule-importstemplate--下载导入模板) |
| 13 | GET | `/api/v1/admin/settlement-scope-rules` | 新建 | 查询结算归属账号与渠道版本 | `settlement_scope_rule` | **新增** | [SKU 与费率 §12](foundation-api-dy-data/sku-fee-admin.md#12-get-apiv1adminsettlement-scope-rules--结算范围版本列表) |
| 14 | POST | `/api/v1/admin/settlement-scope-rules` | 新建 | 发布结算范围新版本 | `settlement_scope_rule` | **新增** | [SKU 与费率 §13](foundation-api-dy-data/sku-fee-admin.md#13-post-apiv1adminsettlement-scope-rules--发布结算范围版本) |
| 15 | GET | `/api/v1/admin/product-sync-runs` | 新建 | 查询商品同步运行记录 | `sku_product_sync_history`、既有任务表 | **新增** | [商品同步 §1](foundation-api-dy-data/product-sync.md#1-get-apiv1adminproduct-sync-runs--商品同步运行列表) |
| 16 | POST | `/api/v1/admin/product-sync-runs` | 新建 | 触发商品同步任务 | `sku_product_sync_history`、`dim_sku_product_rules` | **新增** | [商品同步 §2](foundation-api-dy-data/product-sync.md#2-post-apiv1adminproduct-sync-runs--触发商品同步) |
| 17 | GET | `/api/v1/admin/product-sync-runs/{syncRunId}` | 新建 | 查询商品同步运行详情 | `sku_product_sync_history`、既有任务表 | **新增** | [商品同步 §3](foundation-api-dy-data/product-sync.md#3-get-apiv1adminproduct-sync-runssyncrunid--商品同步运行详情) |
| 18 | GET | `/api/v1/admin/sku-products/{skuId}/sync-history` | 新建 | 查询单个 SKU 的平台属性历史 | `sku_product_sync_history` | **新增** | [商品同步 §4](foundation-api-dy-data/product-sync.md#4-get-apiv1adminsku-productsskuidsync-history--sku-同步历史) |
| 19 | GET | `/api/v1/dashboard/store-ranking` | 现有·需改动 | 查询月度或正式累计门店榜单 | `agg_store_ranking` | **变更** | [结算报表 §1](foundation-api-dy-data/settlement-reporting.md#1-get-apiv1dashboardstore-ranking--全国门店榜单) |
| 20 | GET | `/api/v1/stores/{storeId}/monthly-settlement` | 现有·需改动 | 查询单店月度双费用及账单行 | 月度投影、账单头、账单行 | **变更** | [结算报表 §2](foundation-api-dy-data/settlement-reporting.md#2-get-apiv1storesstoreidmonthly-settlement--单店月度分账) |
| 21 | GET | `/api/v1/order-fee-details` | 新建 | 分页查询一券一行的双费用依据 | 费用结果、当前指针、调整、账单来源项及原始数据 | **新增** | [结算报表 §3](foundation-api-dy-data/settlement-reporting.md#3-get-apiv1order-fee-details--订单费用明细) |
| 22 | GET | `/api/v1/order-fee-details/export` | 新建 | 导出与当前明细筛选一致的 CSV | 同订单费用明细 | **新增** | [结算报表 §4](foundation-api-dy-data/settlement-reporting.md#4-get-apiv1order-fee-detailsexport--导出订单费用明细) |

## §2 拆分子文件

| 子文件 | 内容 | 行数要求 |
|--------|------|:---:|
| [common-contract.md](foundation-api-dy-data/common-contract.md) | 包络、命名、分页、错误、权限、幂等、筛选元数据 | < 400 |
| [sku-fee-admin.md](foundation-api-dy-data/sku-fee-admin.md) | SKU 人工分类、双费率、原子导入、结算范围规则 | < 400 |
| [product-sync.md](foundation-api-dy-data/product-sync.md) | 商品同步运行、SKU 历史与外部接口待映射边界 | < 400 |
| [settlement-reporting.md](foundation-api-dy-data/settlement-reporting.md) | 门店榜单、单店分账、订单费用明细与导出 | < 400 |

## §3 17 张表 → 接口覆盖

| 表 | 读取接口 | 写入接口 / 写入主体 |
|----|----------|--------------------|
| `dim_sku_product_rules` | #1、#2、#3、#6、#16、#20、#21 | #3 只写人工字段；#16 的 worker 只写平台字段 |
| `sku_product_sync_history` | #15、#17、#18 | #16 触发的 worker 写入 |
| `settlement_scope_rule` | #13 | #14 发布不可变版本 |
| `sku_fee_rule` | #4、#5、#20、#21 | #6 或 #10 新增版本；无原地 PUT/DELETE |
| `sku_fee_rule_import_batch` | #7、#8、#9、#10、#11 | #8 创建校验批次；#10 原子提交 |
| `sku_fee_rule_import_row` | #8、#9、#10、#11 | 随批次校验和提交写入 |
| `raw_douyin_orders` | #21、#22 间接读取业务 ID 和订单状态 | 商品/订单采集 worker；无公开写接口 |
| `raw_douyin_order_coupons` | #21、#22 间接读取业务 ID、金额和券状态 | 订单采集 worker；无公开写接口 |
| `douyin_refund_event` | #21、#22 通过调整数组间接追溯 | 退款采集 worker；无公开写接口 |
| `settlement_fee_result` | #20、#21、#22 | 结算计算 worker；无公开写接口 |
| `settlement_fee_result_current` | #21、#22 | 未锁账重算事务内切换；无公开写接口 |
| `settlement_fee_adjustment` | #20、#21、#22 | 退款/取消核销处理器新增；无公开修改接口 |
| `settlement_statement` | #20、#21、#22 | 内部账单生成/锁账流程；本轮无 Web 写接口 |
| `settlement_statement_line` | #20、#21、#22 | 内部锁账事务生成；锁账后不可改 |
| `settlement_statement_entry` | #21、#22 | 内部锁账事务生成；锁账后不可改 |
| `agg_store_monthly_settlement` | #1、#20 | 投影任务重建；无公开写接口 |
| `agg_store_ranking` | #1、#19 | 投影任务重建；无公开写接口 |

## §4 旧接口兼容边界

| 当前运行接口 | 目标处理 |
|-------------|---------|
| `GET/PUT /api/v1/admin/sku-rules` | 旧单一 `commissionRate` 入口；由 #2～#6 和 #8～#10 替代。新正式费率不得从旧 `commission_rate` 自动复制。 |
| `POST /api/v1/admin/sku-rules/lookup` | 由 #2 列表检索和 #5 版本详情替代。 |
| `GET /api/v1/commission-rules/summary` | 仅作旧模型只读兼容；双费用页面改用 #4、#20、#21。 |
| `GET /api/v1/order-details` 与 `/export` | 保留通用订单查询语义；双费用核对使用新的 #21、#22，避免同一路径混合旧分佣和新双费用。 |
| `GET/PUT/POST /api/v1/admin/sync*` | 保留通用同步管理；商品在线 API 同步使用 #15～#18，并可在后台页面聚合展示。 |

兼容接口的删除时间不在 Foundation 阶段决定；实施前必须由 Linear issue 明确切换步骤、调用方、测试和回退路径。

## §5 明确不设计的接口

- 不设计在线开票、发票提交或财务审核接口；`#/invoice` 继续作为静态只读准备指引。
- 不设计已锁账账单的 PUT/DELETE；后续退款只新增 `settlement_fee_adjustment` 并进入事件发生月份。
- 不设计原始订单、券、退款事件和费用结果的 Web 写接口；它们只能由受控 worker/内部服务写入。
- 不把数据库自增 `id` 暴露为公开资源标识。
- 不在拿到脱敏响应样例前冻结抖音商品在线 API 的 URL、鉴权、游标和真实枚举。

## §6 Phase 4 确认记录

1. **已确认**：批量导入首版同时接受 `.xlsx` 与 UTF-8 `.csv`，单文件不超过 10 MiB、数据行不超过 5000；任一行错误仍整批不写入。
2. **已确认**：SKU 费率版本采用“只新增版本”的 POST 模型，不提供原地 PUT/DELETE；同一 SKU + 生效日冲突返回 409。
3. **已确认**：已锁账账单及开票页本轮保持只读；账单确认/锁账由内部流程完成，不新增 Web 操作接口。
4. **已确认**：订单费用明细使用新路径 `/order-fee-details`，旧 `/order-details` 保留通用订单查询，避免双费用字段破坏旧调用方。
5. **已确认**：抖音商品在线 API 外部契约等脱敏样例后补齐；不阻塞本项目内部商品同步管理接口的确认。

Phase 5 将以上五项作为冻结边界执行全量一致性自查。

## §7 Phase 5 一致性自查

> 自查日期: 2026-07-20
> 范围: 页面可写字段、22 个目标接口、17 张目标设计表、5 张本轮外既有依赖表、9 条已锁定交互语义及其校验规则

### §7.1 C2 页面可写字段 → API → Schema

| 页面操作 | 可写字段 | 写入 API | Schema 落点 |
|----------|----------|----------|-------------|
| SKU 人工分类 | `productScope`、`productType`、`isServiceProduct` | `PUT /api/v1/admin/sku-products/{skuId}` | `dim_sku_product_rules.product_scope/product_type/is_service_product` |
| 单条双费率发布 | `skuId`、`promotionServiceFeeRate`、`managementServiceFeeRate`、`effectiveDate`、`ruleStatus`、`changeReason` | `POST /api/v1/admin/sku-fee-rules` | `sku_fee_rule` 对应业务列及审计列 |
| 批量双费率预校验 | `file`、`effectiveDate`、模板四列 | `POST /api/v1/admin/sku-fee-rule-imports` | `sku_fee_rule_import_batch` + `sku_fee_rule_import_row`；此步不写正式规则 |
| 批量双费率提交 | `changeReason` | `POST /api/v1/admin/sku-fee-rule-imports/{batchId}/commit` | 原子新增 `sku_fee_rule`，并更新批次/逐行状态 |
| 结算范围发布 | `effectiveMonth`、`ownerAccountId`、`allowedSaleChannels`、`changeReason` | `POST /api/v1/admin/settlement-scope-rules` | `settlement_scope_rule` 按渠道拆分为不可变版本 |
| 商品同步触发 | `mode`、`reason` | `POST /api/v1/admin/product-sync-runs` | `job_runs` 运行元数据；worker 写商品历史和当前平台字段 |

共 22 个可写字段槽位全部有写入契约和持久化/任务来源。全国榜单、单店分账、订单费用明细仅提供查询与导出；开票确认页是静态只读指引，因此没有页面写字段，也不应补造写接口。

### §7.2 C3 API ↔ Schema

- 22/22 个总览接口均有详细契约；详细契约的方法和路径与总览逐项一致。
- 所有请求写字段都映射到目标列、导入文件暂存列或既有任务元数据；所有业务响应字段都映射到表列、受控枚举、授权关系或明确的服务端派生值。
- 17 张目标设计表已逐表回填读取接口、写入接口或“仅内部 worker/事务写入”边界；`dim_stores`、`dim_store_poi_mappings`、`raw_douyin_verify_records`、`job_runs`、`data_quality_issues` 作为结构不变的既有依赖单列说明。
- 模板下载没有持久化表是有意设计；开票只读页没有发票 API 是已确认边界，不属于覆盖缺口。

### §7.3 C4 术语一致性

- 页面“推广费”是“推广服务费”的展示简称；历史原型“厂端激励推广费”统一映射为推广服务费净额，目标文案不再继续使用历史叫法。
- API 使用 `PROMOTION/MANAGEMENT`，Schema 使用 `fee_direction=1/2`；两者与术语表中的推广服务费/管理服务费一一对应。
- `saleMonth`、`verifyMonth`、`originalBusinessMonth`、`adjustmentMonth` 分别表示销售月、核销月、原始业务发生月和调整入账月，不再混用“订单月份”。
- 费率规则按自然日生效；月度汇总行可包含多费率、多规则版本，API 使用 `feeRates[]/ruleVersions[]`，不再把汇总行伪装成单一费率。

### §7.4 C5 孤立检测

- 17/17 张目标设计表均被公开查询、管理员写入、采集/结算 worker、锁账事务或投影任务消费；没有孤立表。
- 内部自增 `id`、载荷摘要、幂等摘要、来源指针、锁账审计列和归一化枚举等字段不直接暴露给 Web 是有意的安全/一致性边界，不是孤立字段。
- 外部抖音商品 API 的真实 URL、鉴权、游标和枚举仍等待脱敏样例；该依赖只阻断真实外部适配验收，不影响内部接口与 Schema 的一致性结论。

### §7.5 C6 已锁定交互语义 → API

| 已锁定语义 | API 支撑 | 结论 |
|------------|----------|------|
| `settlement-ranking.filter-and-rank.1` | `GET /api/v1/meta/filters` + `GET /api/v1/dashboard/store-ranking` | 覆盖日期、门店搜索、排名依据与空结果 |
| `settlement-ranking.product-filter.2` | 同上 | `productScope/productType` 同时作用于指标与排名 |
| `store-settlement.filter.1` | `GET /api/v1/meta/filters` + `GET /api/v1/stores/{storeId}/monthly-settlement` | 覆盖月份、授权门店与产品维度 |
| `store-settlement.order-drilldown.2` | 月度分账返回账单行上下文，`GET /api/v1/order-fee-details` 接收并重验 | 覆盖下钻与过期上下文处理 |
| `order-fee-detail.restore-context.1` | `GET /api/v1/order-fee-details` | 服务端返回核验后的 `context` |
| `order-fee-detail.direction-tabs.2` | `feeDirection=PROMOTION/MANAGEMENT` | 强制单一费用方向 |
| `order-fee-detail.filter-export.3` | 查询与 `/export` 复用同一筛选、鉴权和口径 | 覆盖列表/文件一致性 |
| `invoice-guide.readonly-process.1` | 无写 API | 静态只读是已锁定系统行为 |
| `invoice-guide.preparation.2` | 月度分账提供可核对账单值；无发票提交 API | 覆盖准备信息且不伪造开票能力 |

9/9 条已锁定交互语义均有接口支撑或明确的“无需接口”只读边界。

### §7.6 C7 已锁定校验 → Schema / 服务层

| 已锁定校验 | 落点 |
|------------|------|
| 正式累计从 `2026-08` 开始，排除 `2026-07` | `agg_store_ranking.period_key/period_type` + API `formalPeriodStartMonth` + 查询服务校验 |
| 商品类型受产品范围约束 | `dim_sku_product_rules.product_scope/product_type` 事实组合 + `productScopeTypeMap` |
| 门店账号不可任意切换当前门店 | 用户门店授权关系和服务端重验；不以 URL 参数授权 |
| 订单下钻重新校验门店权限 | 订单明细服务按 `statementLineId/storeId` 重验授权 |
| 来源上下文的费率和规则版本不得直接用于计算 | `settlement_fee_result` 固化实际值；API 参数只用于上下文校验 |
| 费用方向始终单选 | API `feeDirection` 单值枚举；前端保持单选状态 |
| 导出重验权限并记录规则版本与口径 | 导出复用查询鉴权；文件包含规则版本、原始月和调整月 |
| 开票页不得出现误导性在线主操作 | 静态页面约束；本轮不设计发票写接口 |
| 开票范围排除 7 月测试数据和管理服务费 | `settlement_statement.promotion_*` 独立字段 + 正式账期/开票展示规则 |

9/9 条已锁定校验均落实到 Schema 约束、不可变事实、API 枚举/上下文或必须由服务层执行的授权规则；服务层规则不伪装成数据库约束。

### §7.7 自查修正记录

本轮修正了三类实际缺口：单店五项指标补齐销售/核销订单数与金额；日级费率导致的汇总下钻改为多费率/多版本集合；结构不变的门店、POI、核销、任务和数据质量表补为显式依赖。同时补齐订单明细的销售/核销月份与时间、门店/商品展示来源，以及四类 POST 的持久化幂等追溯。

Phase 5 自查未改变 Phase 4 已确认的业务边界；需用户确认本节后才能进入 Phase 6 交付规划。
