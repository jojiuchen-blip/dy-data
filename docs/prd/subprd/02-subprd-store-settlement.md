# PRD 2: 费用汇总与订单下钻

> **文档版本**: 1.0 | **最后更新**: 2026-07-20
> **关联文档**: [mainprd](../mainprd-dy-data.md) · [功能列表](../prd-feature-list-dy-data.md) · [上一份：全国门店榜单](01-subprd-store-ranking.md) · [用户流程](../../../src/frontend/page-preview/explainer-flow-dy-data.md) · [交互语义](../../../src/frontend/page-preview/explainer-b-interaction-dy-data.md) · [术语表](../foundation/foundation-glossary-dy-data.md) · [Schema](../foundation/foundation-schema-dy-data.md) · [API](../foundation/foundation-api-dy-data.md)

---

## §1 文档范围

本文档覆盖**单店分账的费用汇总与订单下钻**（授权门店与月度筛选 + 五项经营及费用摘要 + 推广服务费汇总行 + 管理服务费汇总行 + 订单费用依据下钻）。

本区块只定义 `#/store` 的查看和核对能力。页面不执行账单确认、锁账、解锁、资金划拨或在线开票，也不定义订单费用明细页内部的筛选、列表和导出行为。SKU 双费率和结算范围由后台规则提供，本区块不新增管理端页面。

### 需求清单

| # | 需求 | 需求简述 | 对应章节 |
|---|------|---------|---------|
| R1 | 授权门店与月度筛选 | 当前门店由服务端权限确定，用户按月份和合法产品维度查看本店数据。 | §3 |
| R2 | 经营与双费用摘要 | 同口径展示销售、核销、推广服务费和管理服务费的关键指标。 | §4 |
| R3 | 双费用产品汇总 | 分方向展示原始基数、调整、调整后净额、实际费率和规则版本。 | §5 |
| R4 | 订单费用下钻 | 从费用汇总行携带账单或预览上下文进入订单费用明细。 | §6 |
| R5 | 退款与锁账口径 | 原结果不被覆盖，调整计入调整入账月份，已锁账来源保持不可变。 | §4、§5、§6 |

---

## §2 页面整体布局

Web 页面从上到下分为 6 个区域，主体纵向滚动，两张费用表在窄屏可横向滚动：

```
┌──────────────────────────────────────────────────────────────┐
│ 主模块侧栏 / 门店结算顶栏 / 四页导航                         │
├──────────────────────────────────────────────────────────────┤
│ 单店分账标题与账单状态                                       │
├──────────────────────────────────────────────────────────────┤
│ 月份 · 当前门店（只读）· 产品范围 · 商品类型                 │  ← 本文档 §3
├──────────────────────────────────────────────────────────────┤
│ 销售金额 · 推广基数 · 推广净额 · 核销金额 · 管理净额         │  ← 本文档 §4
├──────────────────────────────────────────────────────────────┤
│ 推广服务费汇总行                                             │  ← 本文档 §5-§6
├──────────────────────────────────────────────────────────────┤
│ 管理服务费汇总行                                             │  ← 本文档 §5-§6
└──────────────────────────────────────────────────────────────┘
```

---

## §3 账期、门店与产品筛选

### 3.1 用户体验

**数据来源**：`GET /api/v1/meta/filters` 返回的 `stores`、`productScopes`、`productScopeTypeMap`、`productTypes`、`statementMonths`、`formalPeriodStartMonth` 和 `timezone`；筛选提交后，`GET /api/v1/stores/{storeId}/monthly-settlement` 返回服务端接受并规范化的 `store`、`month`、`productScope`、`productType` 和 `isFormalPeriod`。
> 接口详情见 [公共 API 契约 §6](../foundation/foundation-api-dy-data/common-contract.md#6-get-apiv1metafilters--结算筛选元数据)与[双费用结算与报表 API §2](../foundation/foundation-api-dy-data/settlement-reporting.md#2-get-apiv1storesstoreidmonthly-settlement--单店月度分账)。

**交互语义引用**：`store-settlement.filter.1`

**布局**：

```
[月份 ▼] [当前门店（只读）] [产品范围 ▼] [商品类型 ▼]
[正式账期/测试账期说明] [账单状态]
```

**交互规则**：

- 月份默认选择 `statementMonths` 中最新可用值；`2026-07` 可以作为测试账期查看，但页面必须标记为测试数据，不得暗示其已进入正式累计或开票准备。
- 门店账号只有一个授权门店时，门店控件只读展示；拥有多个授权门店的经营或财务人员仅能在 `stores` 返回的范围内切换，URL 中的 `storeId` 不能扩大范围。
- 产品范围改变时，商品类型立即按 `productScopeTypeMap` 收敛；原商品类型失效时重置为 `all` 后再查询。
- 任一有效筛选变化后，五项摘要和两张费用表使用同一个月度分账请求刷新；加载期间保留当前条件并阻止重复请求。
- 页面展示 `statement.statementStatus`；`statement=null` 表示未生成月度账单，当前结果仅为只读预览，不伪装成已确认或已锁账。

**前端职责**：仅维护合法筛选状态、调用接口和渲染服务端返回口径；前端不根据 URL 授权门店，不推导正式账期，不自行拼接账单状态，也不读取未授权门店后再过滤。

### 3.2 服务端处理逻辑

服务端按以下步骤构建单店筛选结果：

1. 从登录态取得角色、组织和门店数据范围，验证路径参数 `storeId` 属于当前用户授权范围。
2. 校验 `month` 为可用 `YYYY-MM`，并校验 `productScope/productType` 是元数据声明的合法组合。
3. 优先读取对应门店、月份和产品维度的月度投影；账单存在时同时读取账单头和账单汇总行。
4. 返回服务端规范化后的门店、筛选口径、正式账期标志、账单状态、摘要和双费用汇总行。
5. 已锁账时只返回冻结结果；未锁账时可返回当前投影形成的只读预览，但不得在查询过程中改变账单状态。

**处理输入**：

| 输入 | 来源 | 说明 |
|------|------|------|
| `storeId` | 当前用户授权门店或授权门店选择 | 路径参数，必须由服务端重验 |
| `month` | `statementMonths` 中的用户选择 | 必填，`YYYY-MM` |
| `productScope` / `productType` | 元数据允许的用户选择 | 默认均为 `all` |
| 当前用户权限 | 宿主 App 登录态 | 全国榜单前 20 例外不适用于单店分账 |

### 3.3 数据链路

> 下表为端到端追踪：UI 元素 ← API 字段 ← 服务端计算 ← 数据源/配置源。**数据源和配置源均由服务端读取**，前端不直接访问。

| UI 元素 | API 字段 | 计算规则 | 数据源（服务端读取） | 配置源（服务端读取） |
|---------|----------|---------|--------|--------|
| 授权门店选项 | `stores[].storeId`、`stores[].storeName` | 按当前用户数据范围过滤 | `dim_stores.store_id`、`dim_stores.store_name` | —（宿主权限关系） |
| 结算月份选项 | `statementMonths` | 可用月度投影月份去重、降序 | `agg_store_monthly_settlement.month` | — |
| 产品范围选项 | `productScopes` | 有效产品范围去重并包含 `all` | `dim_sku_product_rules.product_scope` | — |
| 商品类型选项 | `productTypes`、`productScopeTypeMap` | 按产品范围返回合法类型并包含 `all` | `dim_sku_product_rules.product_scope`、`dim_sku_product_rules.product_type` | — |
| 当前门店 | `store.storeId`、`store.storeName` | 权限校验后回显 | `dim_stores.store_id`、`dim_stores.store_name` | —（宿主权限关系） |
| 当前筛选口径 | `month`、`productScope`、`productType` | 服务端校验后回显 | `agg_store_monthly_settlement.month`、`agg_store_monthly_settlement.product_scope`、`agg_store_monthly_settlement.product_type` | — |
| 正式账期标记 | `isFormalPeriod`、`formalPeriodStartMonth` | 月份不早于 `2026-08` 时为正式账期 | `agg_store_monthly_settlement.month` | —（已确认业务规则） |
| 账单状态 | `statement.statementStatus`、`statement.lockVersion` | 账单存在时直透；未生成时为 `null` | `settlement_statement.statement_status`、`settlement_statement.lock_version` | — |

### 3.4 异常与兜底

**服务端兜底**：

| 场景 | 处理 |
|------|------|
| `storeId` 不在当前用户数据范围 | 返回 403 `DATA_SCOPE_FORBIDDEN`，不返回门店名称、摘要或费用行。 |
| 门店或账期不存在 | 返回 404 `RESOURCE_NOT_FOUND`，不得回退到其他门店或最近月份。 |
| 产品范围与商品类型组合非法 | 返回 422 `VALIDATION_FAILED`，指出非法字段和合法范围。 |
| 合法筛选无有效订单或无费用结果 | 返回零值摘要、`lines=[]` 和可区分的空结果原因。 |
| 月度分账查询失败 | 返回结构化错误和 `requestId`，不返回上一门店或上一账期缓存。 |

**前端渲染兜底**：

| 场景 | 处理 |
|------|------|
| 元数据加载失败 | 保留页面骨架，禁用筛选器，显示带 `requestId` 的重试提示。 |
| 门店权限失败 | 清空摘要和费用表，显示无权访问提示，不展示旧门店数据。 |
| 商品类型因产品范围改变而失效 | 清除旧值并按新合法选项显示，不继续提交非法组合。 |
| 当前账期无数据 | 保留当前筛选和账期说明，显示“无有效订单”或“尚未生成费用结果”的说明性空态。 |

### 3.6 验收

| # | 类型 | 场景 | 触发条件 | 预期结果 |
|---|------|------|---------|---------|
| 1 | 业务规则 | 未授权门店访问 | 修改 URL 或请求路径中的 `storeId` 为未授权门店 | 服务端返回 403，页面不出现该门店任何经营或费用数据。 |
| 2 | UX 交互 | 产品两级联动 | 改变产品范围 | 商品类型只保留合法选项，旧非法值在查询前被清除。 |
| 3 | UX 交互 | 同口径刷新 | 改变月份或产品维度 | 五项摘要和两张费用表在同一请求完成后同步更新。 |
| 4 | 业务规则 | 测试账期 | 选择 `2026-07` | 页面明确标记测试账期，不显示其已进入正式累计或开票准备。 |
| 5 | 异常兜底 | 合法空结果 | 当前筛选没有有效订单或费用结果 | 页面显示原因明确的空态，不残留上一筛选结果。 |

---

## §4 门店经营与双费用摘要

### 4.1 用户体验

**数据来源**：`GET /api/v1/stores/{storeId}/monthly-settlement` 返回的 `metrics`，本区域使用 `salesOrderCount`、`salesAmountCent`、`promotionBaseCent`、`promotionOriginalFeeCent`、`promotionAdjustmentFeeCent`、`promotionNetFeeCent`、`verifiedOrderCount`、`verifiedAmountCent`、`managementOriginalFeeCent`、`managementAdjustmentFeeCent` 和 `managementNetFeeCent`。
> 接口详情见 [双费用结算与报表 API §2](../foundation/foundation-api-dy-data/settlement-reporting.md#2-get-apiv1storesstoreidmonthly-settlement--单店月度分账)。

**交互语义引用**：`store-settlement.filter.1`

**布局**：

```
[销售总金额 / 销售订单数] [推广服务费净额基数]
[应收推广服务费调整后净额（原始金额 + 调整金额）]
[核销总金额 / 核销订单数]
[应扣管理服务费调整后净额（原始金额 + 调整金额）]
```

**展示规则**：

- 保持已确认的五卡布局；订单数作为销售和核销金额卡的辅助信息，不额外拆成独立卡。
- 推广服务费和管理服务费卡均以调整后净额为主值，同时展示原始金额与调整金额；调整金额为零也明确显示，不能用覆盖后的单值隐藏退款影响。
- 推广服务费基数表示当前筛选下的方向性净额基数；部分退款按退款后净额同比例减少基数，全额退款归零，未支付关闭订单不纳入。
- 推广服务费是销售门店应收，管理服务费是核销门店应扣；二者独立展示，不合并为单一“分佣”。
- 金额由整数分格式化为人民币；负向调整保留负号，不使用颜色代替正负语义。

**前端职责**：仅格式化并渲染 `metrics`；不从费用行求和，不重算退款比例、费用基数、原始费用或调整后净额。

### 4.2 服务端处理逻辑

服务端按以下步骤构建五项摘要：

1. 按 §3 的权限和规范化筛选读取 `agg_store_monthly_settlement`。
2. 已生成账单时校验月度投影与账单头双费用汇总一致；已锁账结果以冻结账单为准。
3. 分别返回销售、核销、推广服务费和管理服务费指标；费用调整按调整入账月份进入所选月度结果，不覆盖原始发生月份结果。
4. 对合法空结果返回必返整数零值；数据质量阻断时不得猜测金额。

**处理输入**：

| 输入 | 来源 | 说明 |
|------|------|------|
| 规范化门店、月份和产品口径 | §3 的服务端校验结果 | 五项摘要与费用行共用 |
| 月度双费用投影 | `agg_store_monthly_settlement` WHERE 规范化筛选 | 未锁账预览和查询投影 |
| 账单头 | `settlement_statement` WHERE `store_id + statement_month` | 账单存在时提供状态和冻结汇总 |

### 4.3 数据链路

> 下表为端到端追踪：UI 元素 ← API 字段 ← 服务端计算 ← 数据源/配置源。**数据源和配置源均由服务端读取**，前端不直接访问。

| UI 元素 | API 字段 | 计算规则 | 数据源（服务端读取） | 配置源（服务端读取） |
|---------|----------|---------|--------|--------|
| 销售总金额与订单数 | `metrics.salesAmountCent`、`metrics.salesOrderCount` | 当前筛选投影直透 | `agg_store_monthly_settlement.sales_amount_cent`、`agg_store_monthly_settlement.sales_order_count` | — |
| 推广服务费净额基数 | `metrics.promotionBaseCent` | 方向性净额基数直透 | `agg_store_monthly_settlement.promotion_base_cent` | — |
| 推广服务费原始/调整/净额 | `metrics.promotionOriginalFeeCent`、`metrics.promotionAdjustmentFeeCent`、`metrics.promotionNetFeeCent` | 原始费用 + 调整费用 = 调整后净额 | `agg_store_monthly_settlement.promotion_original_fee_cent`、`agg_store_monthly_settlement.promotion_adjustment_fee_cent`、`agg_store_monthly_settlement.promotion_net_fee_cent` | — |
| 核销总金额与订单数 | `metrics.verifiedAmountCent`、`metrics.verifiedOrderCount` | 当前筛选投影直透 | `agg_store_monthly_settlement.verified_amount_cent`、`agg_store_monthly_settlement.verified_order_count` | — |
| 管理服务费原始/调整/净额 | `metrics.managementOriginalFeeCent`、`metrics.managementAdjustmentFeeCent`、`metrics.managementNetFeeCent` | 原始费用 + 调整费用 = 调整后净额 | `agg_store_monthly_settlement.management_original_fee_cent`、`agg_store_monthly_settlement.management_adjustment_fee_cent`、`agg_store_monthly_settlement.management_net_fee_cent` | — |
| 已生成账单双费用汇总 | `statement` 与对应 `metrics` | 账单头与全部汇总行金额一致 | `settlement_statement.promotion_original_fee_cent`、`settlement_statement.promotion_adjustment_fee_cent`、`settlement_statement.promotion_net_fee_cent`、`settlement_statement.management_original_fee_cent`、`settlement_statement.management_adjustment_fee_cent`、`settlement_statement.management_net_fee_cent` | — |

### 4.4 异常与兜底

**服务端兜底**：

| 场景 | 处理 |
|------|------|
| 合法筛选无匹配数据 | 返回所有摘要字段的整数零值，不返回 `null`。 |
| 调整后净额与“原始 + 调整”不一致 | 视为服务端数据一致性错误，阻断成功响应并记录质量问题。 |
| 已锁账账单与月度投影不一致 | 返回冻结账单口径并记录投影异常，不用未锁账投影覆盖账单。 |
| 必需费用字段缺失 | 不猜测金额；返回结构化错误和 `requestId`。 |

**前端渲染兜底**：

| 场景 | 处理 |
|------|------|
| 合法零值 | 显示 `0`、`¥0.00`，不能误显示为加载失败。 |
| 单个指标为 `null` 或缺失 | 对该卡显示“—”并标记数据异常，不能前端自行补算。 |
| 摘要请求失败 | 清除旧摘要或明确标记旧数据，不把上一筛选金额当作当前结果。 |
| 调整金额为负数 | 保留负号并显示“调整金额”，不只通过颜色表达。 |

### 4.6 验收

| # | 类型 | 场景 | 触发条件 | 预期结果 |
|---|------|------|---------|---------|
| 1 | 业务规则 | 双费用独立 | 同一月份同时存在推广服务费和管理服务费 | 页面分别展示应收与应扣结果，不合并为一个分佣金额。 |
| 2 | 业务规则 | 部分退款调整 | 当月存在部分退款形成的负向调整 | 对应费用卡同时展示原始金额、负向调整和调整后净额，原结果未被覆盖。 |
| 3 | 业务规则 | 五卡布局 | 正常返回销售、核销和双费用指标 | 页面保持五项主卡，销售/核销订单数作为对应金额卡辅助信息。 |
| 4 | 业务规则 | 锁账口径 | 所选账单状态为已锁账 | 页面展示冻结金额和锁账版本，不使用后续费率重新计算。 |
| 5 | 异常兜底 | 合法零金额 | 当前筛选无费用结果 | 五项摘要显示零值并配合空态，不残留旧金额。 |

---

## §5 双费用产品汇总行

### 5.1 用户体验

**数据来源**：`GET /api/v1/stores/{storeId}/monthly-settlement` 返回的 `lines[]`；按 `feeDirection` 分成推广服务费和管理服务费两张表，使用产品维度、来源项数量、原始/调整/净基数、原始/调整/净费用、费率集合与规则版本集合。
> 接口详情见 [双费用结算与报表 API §2](../foundation/foundation-api-dy-data/settlement-reporting.md#2-get-apiv1storesstoreidmonthly-settlement--单店月度分账)。

**交互语义引用**：`store-settlement.filter.1`、`store-settlement.order-drilldown.2`

**布局**：

```
推广服务费（销售门店应收）
┌────────┬────────┬──────┬──────┬──────┬──────┬──────┬────────┐
│产品范围│商品类型│来源项│净基数│实际费率│原始费│调整费│调整后净额│
└────────┴────────┴──────┴──────┴──────┴──────┴──────┴────────┘

管理服务费（核销门店应扣）
┌────────┬────────┬──────┬──────┬──────┬──────┬──────┬────────┐
│产品范围│商品类型│来源项│净基数│实际费率│原始费│调整费│调整后净额│
└────────┴────────┴──────┴──────┴──────┴──────┴──────┴────────┘
```

**展示规则**：

- `PROMOTION` 行只进入推广服务费表，`MANAGEMENT` 行只进入管理服务费表；两张表不混排。
- 每行同时展示 `originalEntryCount` 和 `adjustmentEntryCount`，避免把调整记录误称为新增订单。
- 每行必须展示原始基数、基数调整、调整后基数，以及原始费用、费用调整、调整后净额；默认主列可以突出净额，但其他金额不能隐藏。
- `minFeeRate=maxFeeRate` 且只有一个规则版本时可以显示单一费率；否则显示费率区间或 `feeRates` 集合，并标明规则版本数量，不能继续沿用原型中的单一“配置比例”。
- 账单已生成时，汇总行是按“费用方向 + 产品范围 + 商品类型”冻结的账单汇总；未生成账单时，页面明确标记为当前结果预览。

**前端职责**：仅按 `feeDirection` 分组并格式化服务端行；不从 URL 或本地配置补费率，不把多费率折算成平均费率，不自行合计调整记录。

### 5.2 服务端处理逻辑

服务端按以下步骤返回双费用汇总行：

1. 账单已生成时，读取 `settlement_statement_line`；未生成时，使用月度投影和当前不可变费用结果生成同结构只读预览。
2. 按费用方向、产品范围和商品类型汇总原始来源项与调整来源项。
3. 校验 `netBaseCent = originalBaseCent + adjustmentBaseCent`、`netFeeCent = originalFeeCent + adjustmentFeeCent`。
4. 从汇总行关联的原费用结果去重得到 `feeRates/ruleVersions`，并计算费率区间和版本数量。
5. 已锁账时只返回冻结来源形成的汇总行，不受后续费率修改影响。

**处理输入**：

| 输入 | 来源 | 说明 |
|------|------|------|
| 规范化门店和筛选 | §3 的服务端校验结果 | 决定本次账单或预览范围 |
| 账单汇总行 | `settlement_statement_line` WHERE 当前 `statement_id` | 已生成账单的冻结结果 |
| 原始费用结果 | 汇总行关联 `settlement_fee_result` | 提供实际费率和规则版本 |
| 月度双费用投影 | `agg_store_monthly_settlement` WHERE 当前筛选 | 未生成账单时构建只读预览 |

### 5.3 数据链路

> 下表为端到端追踪：UI 元素 ← API 字段 ← 服务端计算 ← 数据源/配置源。**数据源和配置源均由服务端读取**，前端不直接访问。

| UI 元素 | API 字段 | 计算规则 | 数据源（服务端读取） | 配置源（服务端读取） |
|---------|----------|---------|--------|--------|
| 账单行标识 | `lines[].statementLineId` | 已生成账单时直透，预览时为 `null` | `settlement_statement_line.statement_line_id` | — |
| 费用方向 | `lines[].feeDirection` | `1/2` 映射为 `PROMOTION/MANAGEMENT` | `settlement_statement_line.fee_direction` | — |
| 产品范围与商品类型 | `lines[].productScope`、`lines[].productType` | 冻结产品维度直透 | `settlement_statement_line.product_scope`、`settlement_statement_line.product_type` | — |
| 原始项与调整项数量 | `lines[].originalEntryCount`、`lines[].adjustmentEntryCount` | 对两类账单来源项分别计数 | `settlement_statement_line.original_entry_count`、`settlement_statement_line.adjustment_entry_count` | — |
| 原始/调整/净基数 | `lines[].originalBaseCent`、`lines[].adjustmentBaseCent`、`lines[].netBaseCent` | 原始基数 + 基数调整 = 调整后基数 | `settlement_statement_line.original_base_cent`、`settlement_statement_line.adjustment_base_cent`、`settlement_statement_line.net_base_cent` | — |
| 原始/调整/净费用 | `lines[].originalFeeCent`、`lines[].adjustmentFeeCent`、`lines[].netFeeCent` | 原始费用 + 费用调整 = 调整后净额 | `settlement_statement_line.original_fee_cent`、`settlement_statement_line.adjustment_fee_cent`、`settlement_statement_line.net_fee_cent` | — |
| 实际费率区间/集合 | `lines[].minFeeRate`、`lines[].maxFeeRate`、`lines[].feeRates` | 关联原费用结果的实际费率去重、取最小和最大值 | `settlement_fee_result.fee_rate` | — |
| 规则版本数量/集合 | `lines[].ruleVersionCount`、`lines[].ruleVersions` | 关联原费用结果的规则版本去重 | `settlement_fee_result.rule_version` | — |

### 5.4 异常与兜底

**服务端兜底**：

| 场景 | 处理 |
|------|------|
| 汇总行净额公式不成立 | 阻断该账单成功响应，记录一致性问题，不返回错误净额。 |
| 汇总行缺少可追溯原费用结果 | 标记数据质量阻断，不伪造费率或规则版本。 |
| 所选方向没有汇总行 | 返回对应方向空集合，另一方向仍可正常返回。 |
| 已锁账来源被请求按新费率重算 | 忽略重算意图并返回冻结结果；任何修改请求应返回 409 `STATEMENT_LOCKED`。 |

**前端渲染兜底**：

| 场景 | 处理 |
|------|------|
| 某一费用方向为空 | 只在对应表显示方向性空态，不隐藏另一张有效表。 |
| `feeRates=[]` 或规则版本缺失 | 显示“费率/版本不可用”，禁用该行下钻并提示复核，不猜测比例。 |
| 多费率、多版本 | 显示区间、集合或数量提示，绝不显示单一配置比例。 |
| 表格列超出窄屏 | 仅表格容器横向滚动，页面本身不产生 document 级横向溢出。 |

### 5.6 验收

| # | 类型 | 场景 | 触发条件 | 预期结果 |
|---|------|------|---------|---------|
| 1 | 业务规则 | 双方向分表 | 同一筛选同时返回两种 `feeDirection` | 推广服务费和管理服务费分别进入对应表，不混排。 |
| 2 | 业务规则 | 退款调整可见 | 汇总行包含负向调整来源项 | 行内同时展示原始、调整和调整后基数/费用，来源项数量可区分。 |
| 3 | 业务规则 | 日级多费率 | 同一产品汇总行关联多个实际费率或版本 | 页面展示区间/集合和版本数量，不伪装为单一比例。 |
| 4 | 业务规则 | 锁账不可变 | 锁账后修改对应 SKU 费率 | 已锁账汇总行金额、费率集合和规则版本保持冻结结果。 |
| 5 | UX 交互 | 响应式表格 | 在 390px、768px 和 1440px 宽度查看 | 页面无 document 级横向溢出；两张表可在自身容器横向滚动。 |
| 6 | 异常兜底 | 单方向无数据 | 管理服务费方向为空但推广服务费有数据 | 管理表显示方向性空态，推广表和摘要仍可正常核对。 |

---

## §6 订单费用依据下钻

### 6.1 用户体验

**数据来源**：下钻入口使用月度分账响应中的 `statement.statementId`、`lines[].statementLineId`、`store.storeId`、`month`、`lines[].feeDirection`、`lines[].productScope`、`lines[].productType`、`lines[].feeRates` 和 `lines[].ruleVersions` 构建来源上下文；订单页再调用 `GET /api/v1/order-fee-details` 由服务端核验上下文。
> 下钻请求契约见 [双费用结算与报表 API §3](../foundation/foundation-api-dy-data/settlement-reporting.md#3-get-apiv1order-fee-details--订单费用明细)。

**交互语义引用**：`store-settlement.order-drilldown.2`

**布局**：

```
推广服务费汇总行  [查看订单]
管理服务费汇总行  [查看订单]
                         ↓
                   #/orders?来源上下文
```

**交互规则**：

- 已生成账单时，优先携带 `statementId + statementLineId + feeDirection + feeRates + ruleVersions`；订单页只读取该冻结账单行的来源项。
- 未生成账单时，携带 `storeId + month + feeDirection + productScope + productType + feeRates + ruleVersions`，订单页读取当前未锁账结果。
- 页面路由上下文使用与接口请求一致的 camelCase 业务键，并保留 `focus=workbench` 用于定位核对区域；数组使用可逆编码，不能把多个费率拼成一个假比例。
- 费率和规则版本只用于恢复和校验来源口径，不能由前端或订单页据此重新计算费用。
- 当前行没有来源项、费率/版本不可追溯或上下文构建失败时，不执行跳转，并给出可复核原因。

**前端职责**：只从服务端返回行构建可逆来源上下文并导航；不将 URL 参数当作授权或计算依据，不自行补费率、版本、账单行或门店范围。

### 6.2 服务端处理逻辑

订单明细服务端按以下步骤接受下钻上下文：

1. 重新校验当前登录用户是否有权查看 `storeId` 或 `statementId` 所属门店。
2. 有 `statementId` 时验证 `statementLineId` 属于该账单，并只读取冻结 `settlement_statement_entry`。
3. 无 `statementId` 时验证门店、月份、费用方向和产品维度，读取当前不可变费用结果及其调整。
4. 对 `feeRates/ruleVersions` 与真实汇总来源进行上下文校验；不一致或过期时返回 422，不按 URL 值重算。
5. 返回规范化 `context`，供订单费用明细页恢复来源筛选；该页内部列表和导出由下一份 subprd 定义。

**处理输入**：

| 输入 | 来源 | 说明 |
|------|------|------|
| `statementId` / `statementLineId` | 月度分账的账单头和汇总行 | 锁账口径优先 |
| `storeId` / `month` | 当前规范化门店与账期 | 无账单时条件必填 |
| `feeDirection` / 产品维度 | 被点击汇总行 | 决定订单费用方向和范围 |
| `feeRates` / `ruleVersions` | 被点击汇总行的实际集合 | 只作上下文校验 |
| 当前用户权限 | 宿主 App 登录态 | URL 不授予权限 |

### 6.3 数据链路

> 下表为端到端追踪：UI 元素 ← API 字段 ← 服务端计算 ← 数据源/配置源。**数据源和配置源均由服务端读取**，前端不直接访问。

| UI 元素 | API 字段 | 计算规则 | 数据源（服务端读取） | 配置源（服务端读取） |
|---------|----------|---------|--------|--------|
| 锁账账单上下文 | `statementId`、`statementLineId` | 验证账单行归属后读取冻结来源 | `settlement_statement.statement_id`、`settlement_statement_line.statement_line_id` | — |
| 预览上下文 | `storeId`、`month`、`productScope`、`productType` | 校验门店、月份和产品维度 | `agg_store_monthly_settlement.store_id`、`agg_store_monthly_settlement.month`、`agg_store_monthly_settlement.product_scope`、`agg_store_monthly_settlement.product_type` | — |
| 费用方向 | `feeDirection` | 汇总行方向直透并在明细接口重验 | `settlement_statement_line.fee_direction` | — |
| 费率与版本上下文 | `feeRates`、`ruleVersions` | 与真实来源费率和版本集合比对 | `settlement_fee_result.fee_rate`、`settlement_fee_result.rule_version` | — |
| 冻结订单来源 | `GET /api/v1/order-fee-details` 的规范化 `context` | 账单行下所有不可变来源项 | `settlement_statement_entry.statement_id`、`settlement_statement_entry.statement_line_id`、`settlement_statement_entry.order_id`、`settlement_statement_entry.coupon_id` | — |

### 6.4 异常与兜底

**服务端兜底**：

| 场景 | 处理 |
|------|------|
| 用户无权查看来源门店 | 返回 403 `DATA_SCOPE_FORBIDDEN`，不返回规范化上下文或订单。 |
| `statementLineId` 不属于 `statementId` | 返回 422 `VALIDATION_FAILED`，不回退到全账单查询。 |
| 费率或规则版本上下文过期 | 返回 422，并提供“返回单店分账重新选择”的可执行信息。 |
| 汇总行无来源项或来源不可追溯 | 返回空结果或数据质量错误，不扩大到其他产品、方向或账期。 |

**前端渲染兜底**：

| 场景 | 处理 |
|------|------|
| 当前行没有可下钻来源 | 禁用“查看订单”，显示“暂无订单费用依据”。 |
| 上下文过期 | 订单页显示口径已变化，并提供返回单店分账的路径；不静默使用默认全量筛选。 |
| 权限失败 | 清除来源上下文和订单结果，提示无权访问，不尝试修改 URL 重试。 |
| 导航失败 | 保留单店页当前筛选和滚动位置，允许用户重试，不改变账单状态。 |

### 6.6 验收

| # | 类型 | 场景 | 触发条件 | 预期结果 |
|---|------|------|---------|---------|
| 1 | UX 交互 | 锁账行下钻 | 点击已生成账单行的“查看订单” | 跳转携带账单头、账单行、费用方向、费率和版本上下文，订单页定位核对区域。 |
| 2 | UX 交互 | 预览行下钻 | 点击未生成账单预览行的“查看订单” | 跳转携带门店、月份、产品、费用方向、费率和版本上下文。 |
| 3 | 业务规则 | URL 不授权 | 将下钻 URL 中的门店或账单改为未授权值 | 服务端返回 403，不能查看该门店订单。 |
| 4 | 业务规则 | 上下文只作校验 | 修改 URL 中费率或规则版本 | 服务端拒绝过期/不一致上下文，不按修改值重算费用。 |
| 5 | 异常兜底 | 汇总行无来源 | 当前行来源项数量为零或不可追溯 | 下钻入口不可用并显示具体原因，页面仍保留当前筛选。 |

---

## §7 异常与兜底策略（全局）

### 7.1 接口级兜底

| 场景 | 处理 |
|------|------|
| `GET /api/v1/meta/filters` 超时 | 保留页面骨架和不可操作筛选器，显示带 `requestId` 的重试提示。 |
| `GET /api/v1/stores/{storeId}/monthly-settlement` 超时 | 保留当前筛选，清除或明确标记旧摘要和旧费用表，不跨门店回退。 |
| 接口返回 `code ≠ 0` | 按权限、参数、空结果、数据质量或内部错误分别提示，不使用同一笼统文案。 |

### 7.2 子数据源降级

| 子数据源 | 失败影响 | 降级策略 |
|---------|---------|---------|
| `agg_store_monthly_settlement` | 无法展示未锁账摘要和预览行 | 有冻结账单时只读展示冻结账单；否则返回结构化错误，不用前端计算。 |
| `settlement_statement` / `settlement_statement_line` | 无法展示账单状态或冻结汇总 | 不把当前投影伪装成已确认/已锁账；明确显示账单数据不可用。 |
| `settlement_fee_result` | 无法聚合实际费率和规则版本 | 费用金额不重算；标记该行不可下钻并进入数据质量复核。 |

---

## §8 接口契约

完整字段、包络、错误和权限契约以 Foundation API 为准；本节只列本区块实际使用的接口和字段，不复制完整契约。

### 8.1 接口：`GET /api/v1/meta/filters`

为单店分账提供授权门店、结算月份、产品两级选项和正式账期边界。

> 完整接口契约见 [公共 API 契约 §6](../foundation/foundation-api-dy-data/common-contract.md#6-get-apiv1metafilters--结算筛选元数据)。

**本区域业务说明**：

- **本区域使用的全部响应字段**：`stores[].storeId`、`stores[].storeName`、`productScopes`、`productScopeTypeMap`、`productTypes`、`statementMonths`、`formalPeriodStartMonth`、`timezone`（§3）。
- **前端不做业务判断**：门店范围、产品合法组合、月份可用性和正式账期边界全部以接口结果为准；前端不加载全量门店再过滤。

### 8.2 接口：`GET /api/v1/stores/{storeId}/monthly-settlement`

按当前用户权限、月份和产品维度返回单店经营摘要、双费用结果、账单状态和产品汇总行。

> 完整接口契约见 [双费用结算与报表 API §2](../foundation/foundation-api-dy-data/settlement-reporting.md#2-get-apiv1storesstoreidmonthly-settlement--单店月度分账)，账单与投影字段见 [结算与报表 Schema §4-§7](../foundation/foundation-schema-dy-data/settlement-reporting.md#4-settlement_statement--门店月度账单与锁账)。

**请求参数来源**：

- 路径 `storeId`：§3 当前授权门店。
- `month`、`productScope`、`productType`：§3 的用户选择和元数据约束。
- 登录身份与权限：宿主 App 登录态，不通过查询参数授予。

**本区域业务说明**：

- **本区域使用的全部响应字段**：`store.storeId`、`store.storeName`、`month`、`productScope`、`productType`、`isFormalPeriod`、`statement.statementId`、`statement.statementStatus`、`statement.confirmedAt`、`statement.lockedAt`、`statement.lockVersion`（§3）；`metrics.salesOrderCount`、`metrics.salesAmountCent`、`metrics.verifiedOrderCount`、`metrics.verifiedAmountCent`、`metrics.promotionBaseCent`、`metrics.promotionOriginalFeeCent`、`metrics.promotionAdjustmentFeeCent`、`metrics.promotionNetFeeCent`、`metrics.managementOriginalFeeCent`、`metrics.managementAdjustmentFeeCent`、`metrics.managementNetFeeCent`（§4）；`lines[].statementLineId`、`lines[].feeDirection`、`lines[].productScope`、`lines[].productType`、`lines[].originalEntryCount`、`lines[].adjustmentEntryCount`、`lines[].originalBaseCent`、`lines[].adjustmentBaseCent`、`lines[].netBaseCent`、`lines[].originalFeeCent`、`lines[].adjustmentFeeCent`、`lines[].netFeeCent`、`lines[].minFeeRate`、`lines[].maxFeeRate`、`lines[].ruleVersionCount`、`lines[].feeRates`、`lines[].ruleVersions`（§5-§6）。
- **前端不做业务判断**：权限、账单状态、退款调整、净额公式、锁账口径、费率集合和规则版本集合全部由服务端产生；前端只维护筛选、格式化和渲染。

### 8.3 下钻目标：`GET /api/v1/order-fee-details`

本区块只负责构建来源上下文并导航；订单页实际查询仍由服务端重新授权和规范化。

> 完整接口契约见 [双费用结算与报表 API §3](../foundation/foundation-api-dy-data/settlement-reporting.md#3-get-apiv1order-fee-details--订单费用明细)。

**本区域传递的上下文**：

- 锁账口径：`statementId`、`statementLineId`、`feeDirection`、`feeRates`、`ruleVersions`。
- 未锁账口径：`storeId`、`month`、`feeDirection`、`productScope`、`productType`、`feeRates`、`ruleVersions`。
- 页面定位：`focus=workbench`；只控制目标页面定位，不影响服务端查询或权限。
- **前端不做业务判断**：上下文只用于恢复筛选；真实门店权限、账单行归属、实际费率和规则版本均由订单明细接口重新校验。
