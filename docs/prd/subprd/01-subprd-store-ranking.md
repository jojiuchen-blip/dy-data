# PRD 1: 排名筛选与结果

> **文档版本**: 1.0 | **最后更新**: 2026-07-20
> **关联文档**: [mainprd](../mainprd-dy-data.md) · [功能列表](../prd-feature-list-dy-data.md) · [用户流程](../../../src/frontend/page-preview/explainer-flow-dy-data.md) · [交互语义](../../../src/frontend/page-preview/explainer-b-interaction-dy-data.md) · [术语表](../foundation/foundation-glossary-dy-data.md) · [Schema](../foundation/foundation-schema-dy-data.md) · [API](../foundation/foundation-api-dy-data.md)

---

## §1 文档范围

本文档覆盖**全国门店榜单的排名筛选与结果**（月度/正式累计口径 + 两级产品筛选 + 门店搜索与排序 + 摘要指标 + 门店排名表）。

本区块只定义 `#/ranking` 的查看与比较能力，不定义单店账单、订单费用下钻、SKU 规则管理、商品同步或在线开票。页面使用的经营与结算结果均为可复核依据，不代表系统执行真实资金划拨。

### 需求清单

| # | 需求 | 需求简述 | 对应章节 |
|---|------|---------|---------|
| R1 | 账期与产品筛选 | 提供月度/正式累计、月份、产品范围和受约束商品类型选项。 | §3 |
| R2 | 门店搜索与排名依据 | 支持按门店关键词过滤，并在受控指标中选择排序依据。 | §3、§5 |
| R3 | 全国摘要指标 | 在同一筛选口径下展示销售、核销、双费用净额和结算参考净额。 | §4 |
| R4 | 全国门店排名 | 展示按所选指标排序后的门店名次和经营结算指标。 | §5 |
| R5 | 权限例外与空态 | 全国前 20 横向对标不扩展明细权限，正式累计尚无数据时明确说明。 | §3、§5 |

---

## §2 页面整体布局

Web 页面从上到下分为 5 个区域，主体纵向滚动，排名表在窄屏可横向滚动：

```
┌──────────────────────────────────────────────────────────────┐
│ 主模块侧栏 / 门店结算顶栏 / 四页导航                         │
├──────────────────────────────────────────────────────────────┤
│ 全国门店榜单标题与当前数据口径                               │
├──────────────────────────────────────────────────────────────┤
│ 月度/累计 · 月份 · 产品范围 · 商品类型 · 搜索 · 排名依据     │  ← 本文档 §3
├──────────────────────────────────────────────────────────────┤
│ 销售 · 核销 · 推广服务费 · 管理服务费 · 结算参考摘要         │  ← 本文档 §4
├──────────────────────────────────────────────────────────────┤
│ 全国门店排名表                                                │  ← 本文档 §5
└──────────────────────────────────────────────────────────────┘
```

---

## §3 筛选与口径

### 3.1 用户体验

**数据来源**：`GET /api/v1/meta/filters` 返回的 `periodTypes`、`saleMonths`、`productScopes`、`productScopeTypeMap`、`productTypes`、`formalPeriodStartMonth` 和 `timezone`；用户提交筛选后，由 `GET /api/v1/dashboard/store-ranking` 返回服务端接受并规范化的 `periodType`、`periodKey`、`productScope` 和 `productType`。
> 接口详情见 [公共 API 契约 §6](../foundation/foundation-api-dy-data/common-contract.md#6-get-apiv1metafilters--结算筛选元数据)与[双费用结算与报表 API §1](../foundation/foundation-api-dy-data/settlement-reporting.md#1-get-apiv1dashboardstore-ranking--全国门店榜单)。

**交互语义引用**：`settlement-ranking.filter-and-rank.1`、`settlement-ranking.product-filter.2`

**布局**：

```
[口径：月度 / 正式累计] [月份 ▼] [产品范围 ▼] [商品类型 ▼]
[门店名称关键词________________] [排名依据 ▼] [升序/降序]
```

**交互规则**：

- 首次进入默认选择 `MONTHLY`；月份默认使用 `saleMonths` 中最新可用值，排序默认 `NET_SETTLEMENT_REFERENCE + DESC`。
- 口径切换为 `CUMULATIVE` 后，月份表示累计截止月；页面同时展示“正式累计从 2026-08 开始”的说明。
- 产品范围改变时，商品类型选项立即按 `productScopeTypeMap` 收敛；原商品类型不再合法时重置为 `all`，不得带旧值查询。
- 门店搜索使用门店名称关键词；输入、账期、产品或排序变化后，摘要指标与排名表使用同一组筛选条件刷新。
- 排名依据只允许 `SALES_AMOUNT`、`VERIFIED_AMOUNT`、`PROMOTION_FEE`、`MANAGEMENT_FEE`、`NET_SETTLEMENT_REFERENCE`；排序方向只允许 `ASC`、`DESC`。

**前端职责**：仅维护筛选状态、调用目标接口并渲染服务端规范化结果；前端不自行累计月份、不重算金额、不推导商品类型合法组合，也不依据本地数据决定权限范围。

### 3.2 服务端处理逻辑

服务端按以下步骤处理榜单筛选：

1. 从当前登录态取得角色、组织和数据范围，判断普通授权范围或全国前 20 横向对标例外。
2. 校验 `periodType`、`periodKey`、产品范围与商品类型组合、排序枚举和分页参数。
3. `MONTHLY` 查询所选月份；`CUMULATIVE` 读取从正式账期开始到所选截止月形成的正式累计投影，绝不把 `2026-07` 测试账期并入累计。
4. 按产品维度和门店关键词过滤，再按受控 `sortBy + sortOrder` 排序；所有摘要与列表使用同一过滤条件。
5. 返回规范化筛选、权限模式、摘要、排名结果和标准分页信息。

**处理输入**：

| 输入 | 来源 | 说明 |
|------|------|------|
| `periodType` | 用户选择；合法值来自 `GET /api/v1/meta/filters` | `MONTHLY/CUMULATIVE` |
| `periodKey` | 用户选择；候选月份来自 `saleMonths` | `YYYY-MM`，累计时表示截止月 |
| `productScope` / `productType` | 用户选择；合法组合来自 `productScopeTypeMap` | 默认均为 `all` |
| `q` | 用户输入 | 门店名称关键词；空值表示不过滤 |
| `sortBy` / `sortOrder` | 用户选择或接口默认 | 仅允许契约枚举 |
| `page` / `pageSize` | 页面分页状态 | 默认 `1/20`；例外访问固定为第 1 页、最多 20 行 |
| 当前用户权限 | 宿主 App 登录态 | URL 和筛选参数不能授予数据权限 |

### 3.3 数据链路

> 下表为端到端追踪：UI 元素 ← API 字段 ← 服务端计算 ← 数据源/配置源。**数据源和配置源均由服务端读取**，前端不直接访问。

| UI 元素 | API 字段 | 计算规则 | 数据源（服务端读取） | 配置源（服务端读取） |
|---------|----------|---------|--------|--------|
| 月度/正式累计选项 | `periodTypes` | 返回 `MONTHLY/CUMULATIVE` | `agg_store_ranking.period_type` | — |
| 月份选项 | `saleMonths` | 可用月份去重、降序 | `agg_store_ranking.period_key`、`raw_douyin_orders.sale_time` | — |
| 正式累计起点说明 | `formalPeriodStartMonth` | 固定为 `2026-08` | `agg_store_ranking.period_key` | —（已确认业务规则） |
| 产品范围选项 | `productScopes` | 有效产品范围去重并包含 `all` | `dim_sku_product_rules.product_scope` | — |
| 商品类型选项 | `productTypes`、`productScopeTypeMap` | 按产品范围返回合法商品类型并包含 `all` | `dim_sku_product_rules.product_scope`、`dim_sku_product_rules.product_type` | — |
| 当前账期与产品口径 | `periodType`、`periodKey`、`productScope`、`productType` | 服务端校验后回显 | `agg_store_ranking.period_type`、`agg_store_ranking.period_key`、`agg_store_ranking.product_scope`、`agg_store_ranking.product_type` | — |
| 门店搜索 | 请求参数 `q` | 对门店名称执行关键词过滤 | `agg_store_ranking.store_name` | —（用户输入） |
| 排名依据与方向 | 请求参数 `sortBy`、`sortOrder` | 映射到允许排序的金额或费用指标 | `agg_store_ranking.sales_amount_cent`、`agg_store_ranking.verified_amount_cent`、`agg_store_ranking.promotion_net_fee_cent`、`agg_store_ranking.management_net_fee_cent`、`agg_store_ranking.net_settlement_reference_cent` | —（用户输入/接口默认） |

### 3.4 异常与兜底

**服务端兜底**：

| 场景 | 处理 |
|------|------|
| 商品类型不属于所选产品范围 | 返回 422 `VALIDATION_FAILED`，不按非法组合查询。 |
| `periodType`、月份格式或排序枚举非法 | 返回 422，并指出具体参数及合法取值。 |
| 请求正式累计但截止月早于 `2026-08` | 返回空 `list`、零值 `totals` 和正式账期边界，不混入测试数据。 |
| 当前用户无榜单访问权限 | 返回 403 `DATA_SCOPE_FORBIDDEN`，不返回任何榜单行。 |
| 元数据或榜单查询失败 | 返回结构化错误及 `requestId`，不得返回上一次用户的缓存结果。 |

**前端渲染兜底**：

| 场景 | 处理 |
|------|------|
| 元数据加载失败 | 保留页面骨架，筛选器不可操作，显示带 `requestId` 的重试提示。 |
| 当前产品范围没有商品类型 | 商品类型重置为 `all` 或空选项，并按服务端结果显示明确空态。 |
| 筛选校验失败 | 保留用户当前输入，标记错误字段，不覆盖已成功加载的筛选选项。 |
| 正式累计尚无数据 | 指标显示 `0` 或“—”并展示“累计从 2026-08 开始”，排名表显示说明性空态。 |

### 3.6 验收

| # | 类型 | 场景 | 触发条件 | 预期结果 |
|---|------|------|---------|---------|
| 1 | 业务规则 | 正式累计边界 | 选择 `CUMULATIVE` 且截止月不晚于 `2026-07` | 页面不出现 7 月累计数值，并明确累计从 `2026-08` 开始。 |
| 2 | UX 交互 | 产品两级联动 | 改变产品范围 | 商品类型只保留该范围下合法选项；旧非法值被清除后再发起查询。 |
| 3 | UX 交互 | 筛选同步刷新 | 改变账期、产品、关键词或排序 | 摘要与排名表使用同一请求口径刷新，页面口径说明同步更新。 |
| 4 | 业务规则 | 排名依据白名单 | 尝试提交非契约排序字段 | 服务端拒绝请求，不能将任意字段拼入排序。 |
| 5 | 异常兜底 | 元数据失败 | `GET /api/v1/meta/filters` 失败 | 页面不使用硬编码筛选项，显示可重试错误并保留布局骨架。 |

---

## §4 全国摘要指标

### 4.1 用户体验

**数据来源**：`GET /api/v1/dashboard/store-ranking` 返回的 `totals`，包含 `salesOrderCount`、`salesAmountCent`、`verifiedOrderCount`、`verifiedAmountCent`、`promotionNetFeeCent`、`managementNetFeeCent` 和 `netSettlementReferenceCent`。
> 接口详情见 [双费用结算与报表 API §1](../foundation/foundation-api-dy-data/settlement-reporting.md#1-get-apiv1dashboardstore-ranking--全国门店榜单)。

**交互语义引用**：`settlement-ranking.filter-and-rank.1`、`settlement-ranking.product-filter.2`

**布局**：

```
[销售订单数] [销售金额] [核销订单数] [核销金额]
[推广服务费净额] [管理服务费净额] [结算参考净额]
```

**展示规则**：

- 金额按整数分转换为统一人民币格式；计数使用整数和千分位。
- “推广服务费净额”和“管理服务费净额”均为调整后净额；不能继续显示历史文案“厂端激励推广费”。
- “结算参考净额”表示推广服务费净额减管理服务费净额，仅为经营与结算依据，不代表资金到账或划拨。
- 摘要只反映当前完整筛选范围，不受当前列表分页影响。

**前端职责**：仅格式化并渲染 `totals`；不得从当前页 `list` 求和，不得在浏览器重算退款调整、双费用或结算参考净额。

### 4.2 服务端处理逻辑

服务端在分页前，对当前权限、账期、产品和门店关键词过滤后的完整集合汇总 `totals`：

1. 读取与排名表相同口径的 `agg_store_ranking` 行。
2. 对销售、核销、推广服务费净额和管理服务费净额分别求和。
3. 汇总并返回结算参考净额；任何一项均不读取前端传入金额。

**处理输入**：

| 输入 | 来源 | 说明 |
|------|------|------|
| 规范化筛选 | §3 的服务端校验结果 | 与排名表完全相同 |
| 门店排名投影 | `agg_store_ranking` WHERE 当前规范化筛选与权限范围 | 金额字段已经是目标口径的整数分 |

### 4.3 数据链路

> 下表为端到端追踪：UI 元素 ← API 字段 ← 服务端计算 ← 数据源/配置源。**数据源和配置源均由服务端读取**，前端不直接访问。

| UI 元素 | API 字段 | 计算规则 | 数据源（服务端读取） | 配置源（服务端读取） |
|---------|----------|---------|--------|--------|
| 销售订单数 | `totals.salesOrderCount` | 过滤后完整集合求和 | `agg_store_ranking.sales_order_count` | — |
| 销售金额 | `totals.salesAmountCent` | 过滤后完整集合求和 | `agg_store_ranking.sales_amount_cent` | — |
| 核销订单数 | `totals.verifiedOrderCount` | 过滤后完整集合求和 | `agg_store_ranking.verified_order_count` | — |
| 核销金额 | `totals.verifiedAmountCent` | 过滤后完整集合求和 | `agg_store_ranking.verified_amount_cent` | — |
| 推广服务费净额 | `totals.promotionNetFeeCent` | 过滤后完整集合求和 | `agg_store_ranking.promotion_net_fee_cent` | — |
| 管理服务费净额 | `totals.managementNetFeeCent` | 过滤后完整集合求和 | `agg_store_ranking.management_net_fee_cent` | — |
| 结算参考净额 | `totals.netSettlementReferenceCent` | 推广服务费净额减管理服务费净额后汇总 | `agg_store_ranking.net_settlement_reference_cent` | — |

### 4.4 异常与兜底

**服务端兜底**：

| 场景 | 处理 |
|------|------|
| 合法筛选无匹配数据 | 返回七个必返整数零值，不返回 `null`，同时返回空 `list`。 |
| 投影中的必需指标缺失或数据质量阻断 | 不猜测金额；返回结构化错误或排除受阻断行并通过受控质量状态说明影响范围。 |
| 汇总与同筛选全集不一致 | 视为服务端一致性错误，不返回看似成功的摘要。 |

**前端渲染兜底**：

| 场景 | 处理 |
|------|------|
| 合法零值 | 显示 `0` 或 `¥0.00`，不能显示为加载失败。 |
| 指标字段意外为 `null` 或缺失 | 对该卡显示“—”，整组标记数据异常并提供重试，不自行补零。 |
| 请求失败 | 保留筛选状态，清除旧摘要或明确标记旧数据，不把旧数值当作当前结果。 |

### 4.6 验收

| # | 类型 | 场景 | 触发条件 | 预期结果 |
|---|------|------|---------|---------|
| 1 | 业务规则 | 摘要与分页无关 | 同一筛选依次查看第 1 页和后续页 | 七项摘要保持一致，均基于过滤后的完整集合。 |
| 2 | 业务规则 | 双费用独立 | 返回推广服务费净额与管理服务费净额 | 页面分别展示两项，不合并为单一“分佣”金额。 |
| 3 | 业务规则 | 结算参考净额 | 推广服务费净额与管理服务费净额均存在 | 页面展示服务端返回的差额，并附非资金动作语义。 |
| 4 | UX 交互 | 筛选一致性 | 改变任一有效筛选 | 七项摘要与排名表在同一请求完成后同步更新。 |
| 5 | 异常兜底 | 合法空结果 | 当前筛选无匹配门店 | 七项显示零值，页面同时展示排名空态，不残留旧摘要。 |

---

## §5 门店排名结果

### 5.1 用户体验

**数据来源**：`GET /api/v1/dashboard/store-ranking` 返回的 `scopeMode`、`list`、`total`、`page` 和 `pageSize`；`list[]` 使用 `rank`、`storeId`、`storeName` 及与 `totals` 同名的七项门店指标。
> 接口详情见 [双费用结算与报表 API §1](../foundation/foundation-api-dy-data/settlement-reporting.md#1-get-apiv1dashboardstore-ranking--全国门店榜单)。

**交互语义引用**：`settlement-ranking.filter-and-rank.1`、`settlement-ranking.product-filter.2`

**布局**：

```
全国门店排名 · [月度/累计口径说明] · [匹配门店总数]
┌────┬────────────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┐
│名次│门店名称 / ID│销售单│销售额│核销单│核销额│推广费│管理费│参考净额│
└────┴────────────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┘
[分页]
```

**展示与权限规则**：

- 默认按 `NET_SETTLEMENT_REFERENCE DESC` 排名；用户选择其他受控指标或方向后，名次和表格顺序同步变化。
- `rank` 是完整过滤集合排序后的名次，不在每页重新从 1 计算。
- `scopeMode=GLOBAL_TOP_20_EXCEPTION` 时，页面明确标记“全国前 20 横向对标”，固定展示第 1 页且最多 20 行；榜单行不提供其他门店账单或订单明细下钻。
- `scopeMode=AUTHORIZED` 时仍只展示服务端授权范围；本 PRD 不新增从榜单行进入单店账单的跨门店授权能力。
- 宽度不足时表格区域横向滚动，门店名称和名次保持可识别；不得通过隐藏管理服务费或规则口径来适配窄屏。

**前端职责**：按 `list` 顺序渲染，不重新排序、不重排名次、不扩大分页、不依据门店 ID 决定是否允许下钻。

### 5.2 服务端处理逻辑

服务端按以下步骤构建排名结果：

1. 使用 §3 的规范化筛选和权限范围读取 `agg_store_ranking`。
2. 对门店名称执行关键词过滤，并将 `sortBy` 映射到白名单指标列。
3. 在分页前完成稳定排序和全局名次计算；相同排序值必须使用稳定次序，避免翻页时重复或漏行。
4. 普通授权模式按请求分页；全国前 20 例外强制 `page=1`、`pageSize≤20`。
5. 返回门店业务 ID、名称快照、七项门店指标、完整集合总数及服务端权限模式。

**处理输入**：

| 输入 | 来源 | 说明 |
|------|------|------|
| 筛选与排序 | §3 的服务端校验结果 | 不接受任意列名 |
| 门店排名投影 | `agg_store_ranking` WHERE 当前规范化筛选 | 每行是一个门店、账期和产品维度的目标投影 |
| 权限模式 | 宿主 App 登录态与数据范围 | 决定授权集合或全国前 20 例外 |

### 5.3 数据链路

> 下表为端到端追踪：UI 元素 ← API 字段 ← 服务端计算 ← 数据源/配置源。**数据源和配置源均由服务端读取**，前端不直接访问。

| UI 元素 | API 字段 | 计算规则 | 数据源（服务端读取） | 配置源（服务端读取） |
|---------|----------|---------|--------|--------|
| 权限范围提示 | `scopeMode` | 登录态判定 `AUTHORIZED/GLOBAL_TOP_20_EXCEPTION` | —（宿主服务端权限上下文） | — |
| 名次 | `list[].rank` | 过滤后按受控指标稳定排序，再在分页前计算 | `agg_store_ranking.store_id` 与当前排序指标列 | — |
| 门店 | `list[].storeId`、`list[].storeName` | 直透业务 ID 与名称快照 | `agg_store_ranking.store_id`、`agg_store_ranking.store_name` | — |
| 销售订单数 | `list[].salesOrderCount` | 直透 | `agg_store_ranking.sales_order_count` | — |
| 销售金额 | `list[].salesAmountCent` | 直透 | `agg_store_ranking.sales_amount_cent` | — |
| 核销订单数 | `list[].verifiedOrderCount` | 直透 | `agg_store_ranking.verified_order_count` | — |
| 核销金额 | `list[].verifiedAmountCent` | 直透 | `agg_store_ranking.verified_amount_cent` | — |
| 推广服务费净额 | `list[].promotionNetFeeCent` | 直透调整后净额 | `agg_store_ranking.promotion_net_fee_cent` | — |
| 管理服务费净额 | `list[].managementNetFeeCent` | 直透调整后净额 | `agg_store_ranking.management_net_fee_cent` | — |
| 结算参考净额 | `list[].netSettlementReferenceCent` | 直透推广净额减管理净额 | `agg_store_ranking.net_settlement_reference_cent` | — |
| 匹配总数与分页 | `total`、`page`、`pageSize` | 过滤后计数并执行标准分页 | `agg_store_ranking.store_id` | — |

### 5.4 异常与兜底

**服务端兜底**：

| 场景 | 处理 |
|------|------|
| 合法筛选无匹配门店 | 返回 `list=[]`、`total=0` 和当前规范化口径。 |
| 例外用户请求第 2 页或超过 20 行 | 服务端强制第 1 页且最多 20 行，或拒绝越界分页；不得泄露更多全国门店。 |
| 排名投影缺少门店业务 ID 或名称 | 该行进入数据质量处理，不返回不可追溯榜单行。 |
| 查询超时或投影不可用 | 返回结构化错误和 `requestId`，不降级到未经授权的全量查询。 |

**前端渲染兜底**：

| 场景 | 处理 |
|------|------|
| `list=[]` | 在表格区域显示与当前筛选一致的空态，保留表头和筛选条件。 |
| `GLOBAL_TOP_20_EXCEPTION` | 显示横向对标说明，隐藏分页扩展入口和其他门店明细操作。 |
| 单个非关键展示字段缺失 | 对该单元格显示“—”并上报异常；不得用其他门店或上一页数据补位。 |
| 排名请求失败 | 不显示旧排名为当前结果；保留筛选并提供重试。 |

### 5.6 验收

| # | 类型 | 场景 | 触发条件 | 预期结果 |
|---|------|------|---------|---------|
| 1 | 业务规则 | 全局名次 | 同一筛选结果超过一页 | 后续页名次延续完整集合排序，不从 1 重新开始。 |
| 2 | UX 交互 | 更换排名依据 | 从结算参考净额切换到管理服务费 | 列表顺序和名次按管理服务费重新返回，摘要口径不改变。 |
| 3 | 业务规则 | 全国前 20 例外 | `scopeMode=GLOBAL_TOP_20_EXCEPTION` | 最多显示 20 行，无翻页扩展和其他门店明细下钻。 |
| 4 | 业务规则 | 门店关键词 | 输入名称关键词 | 只返回名称匹配门店，`total`、摘要和名次均基于过滤后的集合。 |
| 5 | UX 交互 | 响应式表格 | 在 390px、768px 和 1440px 宽度查看 | 页面无 document 级横向溢出；窄屏仅表格区域横向滚动，全部指标仍可访问。 |
| 6 | 异常兜底 | 空排名 | 合法筛选无匹配门店 | 表格显示说明性空态，旧排名被清除，筛选条件仍可调整。 |

---

## §6 接口契约

完整字段、包络、分页、错误和权限契约以 Foundation API 为准；本节只列本区块实际使用的接口和字段，不复制完整契约。

### 6.1 接口：`GET /api/v1/meta/filters`

为全国门店榜单提供可用账期、产品两级选项和正式账期边界。

> 完整接口契约见 [公共 API 契约 §6](../foundation/foundation-api-dy-data/common-contract.md#6-get-apiv1metafilters--结算筛选元数据)。

**本区域业务说明**：

- **本区域使用的全部响应字段**：`productScopes`、`productScopeTypeMap`、`productTypes`、`saleMonths`、`periodTypes`、`formalPeriodStartMonth`、`timezone`（§3）。
- **前端不做业务判断**：筛选合法组合、月份可用性和正式账期边界均以接口结果为准；前端不读取管理员接口，也不硬编码商品分类。

### 6.2 接口：`GET /api/v1/dashboard/store-ranking`

按服务端权限和当前筛选返回全国门店摘要及排名结果。

> 完整接口契约见 [双费用结算与报表 API §1](../foundation/foundation-api-dy-data/settlement-reporting.md#1-get-apiv1dashboardstore-ranking--全国门店榜单)，投影字段见 [结算与报表 Schema §8](../foundation/foundation-schema-dy-data/settlement-reporting.md#8-agg_store_ranking--门店排名投影现有需改动)。

**请求参数来源**：

- `periodType`、`periodKey`、`productScope`、`productType`：§3 的用户选择与元数据约束。
- `q`、`sortBy`、`sortOrder`：§3 的用户输入或接口默认。
- `page`、`pageSize`：§5 的分页状态；全国前 20 例外仍由服务端强制边界。
- 登录身份与权限：宿主 App 登录态，不由查询参数传入授权。

**本区域业务说明**：

- **本区域使用的全部响应字段**：`periodType`、`periodKey`、`productScope`、`productType`、`formalPeriodStartMonth`（§3）；`totals.salesOrderCount`、`totals.salesAmountCent`、`totals.verifiedOrderCount`、`totals.verifiedAmountCent`、`totals.promotionNetFeeCent`、`totals.managementNetFeeCent`、`totals.netSettlementReferenceCent`（§4）；`scopeMode`、`list[].rank`、`list[].storeId`、`list[].storeName`、`list[]` 七项同名指标、`total`、`page`、`pageSize`（§5）。
- **前端不做业务判断**：累计、金额汇总、费用净额、排名、权限范围和全国前 20 边界全部由服务端完成，前端只维护筛选并渲染返回值。
