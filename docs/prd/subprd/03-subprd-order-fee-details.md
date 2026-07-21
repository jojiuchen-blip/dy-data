# PRD 3: 费用类型、筛选与明细表

> **文档版本**: 1.0 | **最后更新**: 2026-07-20
> **关联文档**: [mainprd](../mainprd-dy-data.md) · [功能列表](../prd-feature-list-dy-data.md) · [上一份：单店分账](02-subprd-store-settlement.md) · [用户流程](../../../src/frontend/page-preview/explainer-flow-dy-data.md) · [交互语义](../../../src/frontend/page-preview/explainer-b-interaction-dy-data.md) · [术语表](../foundation/foundation-glossary-dy-data.md) · [Schema](../foundation/foundation-schema-dy-data.md) · [API](../foundation/foundation-api-dy-data.md)

---

## §1 文档范围

本文档覆盖**订单费用明细的费用方向、筛选、明细表与导出**（来源上下文恢复 + 推广/管理费用方向切换 + 月份/状态/关键词筛选 + 一券一方向费用追溯 + 同口径导出）。

本区块只定义 `#/orders` 的只读查询、核对和导出能力。页面不修改费率或规则版本，不重算、覆盖或删除费用结果与调整记录，不执行账单确认、锁账、资金划拨或在线开票。SKU 双费率和产品归属由后台规则提供，本区块不新增管理端配置页面。

### 需求清单

| # | 需求 | 需求简述 | 对应章节 |
|---|------|---------|---------|
| R1 | 来源上下文恢复 | 从单店分账进入时恢复账单/预览、门店、月份、产品、费用方向、费率和规则版本上下文，并由服务端重新授权和校验。 | §3 |
| R2 | 费用方向与筛选 | 在推广服务费、管理服务费两个互斥方向中查询，并支持销售月、核销月、数据状态和订单/券/SKU/产品关键词筛选。 | §4 |
| R3 | 一券一方向明细 | 每行展示一张券在一个费用方向下的原始基数、费率、原始费用、调整和调整后净额，并保留月份、门店和规则版本追溯。 | §5 |
| R4 | 同口径导出 | 按当前费用方向、筛选条件、权限和锁账口径导出 UTF-8 CSV；空结果不生成文件。 | §6 |
| R5 | 退款与锁账一致性 | 后续退款、取消核销以独立调整记录进入调整入账月份，原始结果和已锁账来源保持不可变。 | §5、§6 |

---

## §2 页面整体布局

Web 页面从上到下分为 6 个区域，主体纵向滚动，明细表在窄屏可横向滚动：

```
┌──────────────────────────────────────────────────────────────────┐
│ 主模块侧栏 / 门店结算顶栏 / 四页导航                            │
├──────────────────────────────────────────────────────────────────┤
│ 订单费用明细标题 · 已验证来源上下文 · 返回单店分账               │  ← 本文档 §3
├──────────────────────────────────────────────────────────────────┤
│ 推广服务费订单明细 / 管理服务费订单明细                          │  ← 本文档 §4
├──────────────────────────────────────────────────────────────────┤
│ 销售月 · 核销月 · 数据状态 · 订单/券/SKU/产品搜索 · 查询/重置    │  ← 本文档 §4
├──────────────────────────────────────────────────────────────────┤
│ 一券一方向费用明细表 · 调整记录展开 · 分页                       │  ← 本文档 §5
├──────────────────────────────────────────────────────────────────┤
│ 导出当前明细                                                     │  ← 本文档 §6
└──────────────────────────────────────────────────────────────────┘
```

---

## §3 来源上下文恢复

### 3.1 用户体验

**数据来源**：`GET /api/v1/order-fee-details` 返回服务端验证并规范化后的 `context`；来源页只负责传入 `statementId/statementLineId` 或 `storeId/month`，以及产品维度、费用方向、费率和规则版本上下文。
> 接口详情见[双费用结算与报表 API §3](../foundation/foundation-api-dy-data/settlement-reporting.md#3-get-apiv1order-fee-details--订单费用明细)。

**交互语义引用**：`order-fee-detail.restore-context.1`

**布局**：

```
[订单费用明细]
[来源：单店分账] [门店] [账期/预览月份] [产品范围 · 商品类型]
[费用方向] [费率集合] [规则版本集合]             [返回单店分账]
```

**交互规则**：

- 页面加载时尝试恢复来源上下文；`statementId` 存在时按账单冻结来源查询，`statementLineId` 必须属于该账单；无 `statementId` 时必须同时具备合法 `storeId + month`，按当前结果指针查询只读预览。
- URL 中的月份、门店、产品、费用方向、费率和规则版本只用于恢复筛选和校验，不授予权限，也不作为费用重算输入。
- 服务端返回的 `context` 是页面唯一可信回显；缺少可选参数时使用接口默认值并向用户说明，非法或过期上下文不得静默回退到全量查询。
- `focus=workbench` 只控制页面定位，不参与服务端授权、规则匹配或费用计算。
- 上下文失效时提供“返回单店分账重新选择”的可执行路径，不保留失效上下文下的旧明细。

**前端职责**：仅解析导航参数、提交查询、渲染服务端规范化 `context` 和返回路径；不从 URL 推导权限，不验证账单归属，不信任 URL 费率或规则版本，也不自行选择冻结结果或当前结果。

### 3.2 服务端处理逻辑

服务端按以下步骤恢复来源上下文：

1. 从登录态取得角色、组织和门店数据范围，先校验用户是否有权读取目标门店和账单来源。
2. 有 `statementId` 时校验 `statementLineId` 归属，并从 `settlement_statement_entry` 读取已冻结的结果或调整来源；无账单时校验 `storeId + month`，从 `settlement_fee_result_current` 解析当前不可变结果版本。
3. 校验 `feeDirection`、产品维度、费率集合和规则版本集合与真实来源一致；请求值只参与一致性验证，不进入计算。
4. 返回规范化 `context`、首屏明细和分页信息；上下文非法或过期时返回 422 和可执行的返回路径信息。

**处理输入**：

| 输入 | 来源 | 说明 |
|------|------|------|
| `statementId` / `statementLineId` | PRD 2 单店分账账单行 | 已生成账单时使用；账单行必须归属账单 |
| `storeId` / `month` | PRD 2 单店分账当前筛选 | 无账单时必填，用于只读预览 |
| `feeDirection` / 产品维度 | PRD 2 被点击费用汇总行 | 决定目标费用方向和产品范围 |
| `feeRates` / `ruleVersions` | PRD 2 汇总行中的实际集合 | 仅用于来源上下文校验 |
| 当前用户权限 | 宿主 App 登录态 | 查询与导出均需重新校验 |

### 3.3 数据链路

> 下表为端到端追踪：UI 元素 ← API 字段 ← 服务端计算 ← 数据源/配置源。**数据源和配置源均由服务端读取**，前端不直接访问。

| UI 元素 | API 字段 | 计算规则 | 数据源（服务端读取） | 配置源（服务端读取） |
|---------|----------|---------|--------|--------|
| 账单来源 | `context.statementId`、`context.statementLineId` | 校验账单行归属并锁定冻结来源 | `settlement_statement_entry.statement_id`、`settlement_statement_entry.statement_line_id` | — |
| 预览来源 | `context.storeId`、`context.month` | 无账单时按授权门店和月份读取当前指针 | `settlement_fee_result_current.coupon_id`、`settlement_fee_result_current.fee_direction`、`settlement_fee_result_current.fee_result_id` | — |
| 门店上下文 | `context` 中服务端接受的 `storeId` | 授权后回显规范化门店业务 ID；展示名称仅在接口实际返回时使用 | `dim_stores.store_id` | — |
| 产品维度 | `context.productScope`、`context.productType` | 与冻结来源或当前结果中的产品维度核对 | `settlement_fee_result.product_scope`、`settlement_fee_result.product_type` | `dim_sku_product_rules.product_scope`、`dim_sku_product_rules.product_type` |
| 费用方向 | `context.feeDirection` | 与来源行的费用方向一致 | `settlement_fee_result.fee_direction` | — |
| 费率与规则版本集合 | `context.feeRates`、`context.ruleVersions` | 从真实来源去重返回，不采用 URL 值计算 | `settlement_fee_result.fee_rate`、`settlement_fee_result.rule_version` | `sku_fee_rule.rule_version` |

### 3.4 异常与兜底

**服务端兜底**：

| 场景 | 处理 |
|------|------|
| 目标门店或账单超出当前用户数据范围 | 返回 403 `DATA_SCOPE_FORBIDDEN`，不返回规范化上下文、门店名称或明细。 |
| `statementLineId` 不属于 `statementId` | 返回 422 `VALIDATION_FAILED`，不回退到账单全量或预览查询。 |
| 无账单且缺少 `storeId` 或 `month` | 返回 422，指出缺失字段。 |
| 费率或规则版本上下文与真实来源不一致、已过期 | 返回 422，并返回“回到单店分账重新选择”的路径信息；不按请求值重算。 |
| 来源记录不存在或不可追溯 | 返回空结果或数据质量错误，不扩大月份、产品或费用方向。 |

**前端渲染兜底**：

| 场景 | 处理 |
|------|------|
| 可选上下文缺失但接口已给出默认值 | 使用 `context` 回显，并明确说明已采用默认筛选。 |
| 上下文非法或过期 | 清空旧明细，显示具体原因和“返回单店分账”入口，不静默查询全量。 |
| 权限失败 | 清空上下文和明细，不显示目标门店名称，不通过修改 URL 自动重试。 |
| 来源恢复请求失败 | 保留页面骨架和来源页返回入口，允许按原参数重试。 |

### 3.6 验收

| # | 类型 | 场景 | 触发条件 | 预期结果 |
|---|------|------|---------|---------|
| 1 | 业务规则 | 锁账账单下钻 | 使用合法 `statementId + statementLineId` 进入页面 | 服务端只返回该账单行冻结的来源记录，后续规则变化不改变结果。 |
| 2 | 业务规则 | URL 不授予权限 | 将 URL 中门店或账单改为未授权值 | 返回 403，页面不出现该门店上下文或明细。 |
| 3 | 业务规则 | 费率不作为计算输入 | 修改 URL 中 `feeRates` 或 `ruleVersions` | 服务端拒绝不一致上下文，不按修改值重算。 |
| 4 | UX 交互 | 合法预览上下文恢复 | 从未生成账单的汇总行进入 | 页面恢复门店、月份、产品和费用方向，并展示服务端规范化上下文。 |
| 5 | 异常兜底 | 上下文过期 | 来源规则版本已不再匹配当前来源 | 清空旧明细，说明原因并提供返回单店分账路径。 |

---

## §4 费用方向与筛选

### 4.1 用户体验

**数据来源**：`GET /api/v1/meta/filters` 返回 `saleMonths`、`verifyMonths`、`feeDirections`、`productScopes`、`productScopeTypeMap`、`productTypes` 和 `timezone`；`GET /api/v1/order-fee-details` 返回规范化 `context`、`list` 和分页信息。
> 接口详情见[公共 API 契约 §6](../foundation/foundation-api-dy-data/common-contract.md#6-get-apiv1metafilters--结算筛选元数据)与[双费用结算与报表 API §3](../foundation/foundation-api-dy-data/settlement-reporting.md#3-get-apiv1order-fee-details--订单费用明细)。

**交互语义引用**：`order-fee-detail.direction-tabs.2`、`order-fee-detail.filter-export.3`

**布局**：

```
[推广服务费订单明细] [管理服务费订单明细]
[销售月 ▼] [核销月 ▼] [数据状态 ▼]
[订单 ID / 券 ID / SKU ID或名称 / 产品名称____________] [查询] [重置]
```

**交互规则**：

- 推广服务费和管理服务费为互斥页签，任何时刻必须有且只有一个选中；默认使用已验证来源上下文的 `feeDirection`。
- 推广服务费按销售业务日匹配规则并归入销售月；管理服务费按核销业务日匹配规则并归入核销月。销售月与核销月可同时作为筛选条件，但不改变费用归属口径。
- `dataStatus` 只允许 `VALID/ADJUSTED/BLOCKED/LOCKED`；关键词 `q` 可搜索订单 ID、券 ID、SKU ID、SKU 名称和产品名称。
- 点击查询、切换方向或改变任一筛选后回到第 1 页；分页只改变 `page/pageSize`，不改变其他条件。
- 重置恢复服务端验证后的来源上下文，不扩大门店、月份、产品或账单范围。
- 两个费用方向分别展示空态，例如“当前筛选无推广服务费明细”或“当前筛选无管理服务费明细”，不得混用另一方向数据填充。

**前端职责**：仅维护互斥费用方向、筛选和分页状态，并调用接口；不在前端按销售/核销日期归属月份，不过滤越权数据，不从状态或金额猜测费用方向。

### 4.2 服务端处理逻辑

服务端按以下步骤处理筛选：

1. 按 §3 重新校验来源上下文和权限，解析账单冻结来源或当前结果指针。
2. 校验 `feeDirection`、月份格式、产品组合、状态枚举、关键词长度和分页范围；`pageSize` 默认 50、最大 100。
3. 在已确定的来源集合内按销售月、核销月、产品维度、数据状态和关键词过滤；推广服务费仍以销售门店/销售月为归属，管理服务费仍以核销门店/核销月为归属。
4. 返回服务端规范化 `context`、当前页 `list`、`total/page/pageSize`，并保证一张券在一个费用方向下只出现一个费用结果版本。

**处理输入**：

| 输入 | 来源 | 说明 |
|------|------|------|
| `feeDirection` | 来源上下文或用户切换 | 必填，`PROMOTION/MANAGEMENT` |
| `saleMonth` / `verifyMonth` | 用户选择；候选值来自元数据接口 | 可选，`YYYY-MM` |
| `productScope` / `productType` | 来源上下文或用户筛选 | 必须是元数据声明的合法组合 |
| `dataStatus` | 用户选择 | 可选，契约限定枚举 |
| `q` | 用户输入 | 搜索订单、券、SKU 和产品标识/名称 |
| `page` / `pageSize` | 页面分页状态 | 默认 `1/50`，`pageSize` 最大 100 |

### 4.3 数据链路

> 下表为端到端追踪：UI 元素 ← API 字段 ← 服务端计算 ← 数据源/配置源。**数据源和配置源均由服务端读取**，前端不直接访问。

| UI 元素 | API 字段 | 计算规则 | 数据源（服务端读取） | 配置源（服务端读取） |
|---------|----------|---------|--------|--------|
| 费用方向页签 | `feeDirections`、`context.feeDirection`、`list[].feeDirection` | 必填且互斥；结果只含所选方向 | `settlement_fee_result.fee_direction` | — |
| 销售月份 | `saleMonths`、`saleMonth`、`list[].saleMonth` | 按销售业务日形成的月份过滤 | `raw_douyin_orders.sale_time`、`settlement_fee_result.original_business_month` | — |
| 核销月份 | `verifyMonths`、`verifyMonth`、`list[].verifyMonth` | 按核销业务日形成的月份过滤 | `raw_douyin_verify_records.verify_time`、`settlement_fee_result.original_business_month` | — |
| 产品范围与类型 | `productScope`、`productType` | 按规则快照中的产品维度过滤 | `settlement_fee_result.product_scope`、`settlement_fee_result.product_type` | `dim_sku_product_rules.product_scope`、`dim_sku_product_rules.product_type` |
| 数据状态 | `dataStatus`、`list[].resultStatus` | 映射 `VALID/ADJUSTED/BLOCKED/LOCKED` 查询口径 | `settlement_fee_result.result_status` | — |
| 关键词搜索 | `q` | 在授权来源内匹配业务 ID 或名称 | `raw_douyin_orders.order_id`、`raw_douyin_order_coupons.coupon_id`、`dim_sku_product_rules.sku_id`、`dim_sku_product_rules.sku_name`、`dim_sku_product_rules.product_name` | — |
| 分页 | `total`、`page`、`pageSize` | 过滤后稳定分页 | `settlement_fee_result.fee_result_id` | — |

### 4.4 异常与兜底

**服务端兜底**：

| 场景 | 处理 |
|------|------|
| 非法费用方向、状态、月份或分页参数 | 返回 422 `VALIDATION_FAILED`，指出字段和合法范围。 |
| 产品范围与商品类型组合非法 | 返回 422，不自动扩大为 `all`。 |
| 合法筛选无结果 | 返回 `list=[]`、`total=0` 和规范化 `context`，不复用另一方向或上一页数据。 |
| 请求页码超过结果范围 | 返回空当前页及真实 `total`，由前端回到合法页；不改变筛选。 |
| 查询失败 | 返回结构化错误和 `requestId`，不返回其他门店或月份缓存。 |

**前端渲染兜底**：

| 场景 | 处理 |
|------|------|
| 当前方向无结果 | 保留所有有效筛选，显示带费用方向名称的说明性空态，禁用导出。 |
| 筛选参数非法 | 聚焦并标记具体控件，保留其余合法条件。 |
| 请求失败 | 保留费用方向和筛选，清除或明确标记旧列表，显示带 `requestId` 的重试入口。 |
| 快速连续切换条件 | 只渲染最后一次请求结果，加载期间阻止重复提交。 |

### 4.6 验收

| # | 类型 | 场景 | 触发条件 | 预期结果 |
|---|------|------|---------|---------|
| 1 | UX 交互 | 费用方向互斥 | 点击未选中的管理服务费页签 | 管理方向成为唯一选中项，回到第 1 页并按原筛选查询管理服务费。 |
| 2 | 业务规则 | 双月份口径 | 同时选择销售月和核销月 | 服务端按两个条件过滤，但推广仍归销售月、管理仍归核销月。 |
| 3 | UX 交互 | 多标识搜索 | 输入订单 ID、券 ID、SKU ID/名称或产品名称 | 仅在授权来源和当前费用方向内返回匹配行。 |
| 4 | 异常兜底 | 方向空态 | 当前筛选无推广服务费结果 | 显示推广方向专属空态并禁用导出，不展示管理方向数据。 |
| 5 | 异常兜底 | 非法产品组合 | 提交不属于当前产品范围的商品类型 | 返回 422，页面标记问题且不自动扩大为全部。 |

---

## §5 一券一方向费用明细

### 5.1 用户体验

**数据来源**：`GET /api/v1/order-fee-details` 返回 `list[]`；每行是一张券在一个费用方向下的不可变费用结果，并可展开其 `adjustments[]`。
> 接口详情见[双费用结算与报表 API §3](../foundation/foundation-api-dy-data/settlement-reporting.md#3-get-apiv1order-fee-details--订单费用明细)，字段来源见[结算与报表 Schema](../foundation/foundation-schema-dy-data/settlement-reporting.md)。

**交互语义引用**：`order-fee-detail.direction-tabs.2`、`order-fee-detail.filter-export.3`

**布局**：

```
┌────────┬──────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┐
│订单 ID │券 ID │SKU/产品│原始月份│规则日期│原始基数│费率    │费用净额│状态/版本│
├────────┼──────┼────────┼────────┼────────┼────────┼────────┼────────┼────────┤
│ ...    │ ...  │ ...    │ ...    │ ...    │原始+调整│ ...   │原始+调整│ ...    │
│        └─ 展开：调整入账月份 · 类型 · 调整基数 · 调整费用 · 原因 · 发生时间 ─┘
└───────────────────────────────────────────────────────────────────────────────┘
[共 N 条] [每页 50 条 ▼] [上一页] [第 X 页] [下一页]
```

**展示规则**：

- 每行固定为“一张券 + 一个费用方向 + 一个费用结果版本”，对外始终展示平台订单 ID、券 ID 和 SKU ID，不展示内部自增主键。
- 主行至少展示订单/券状态、费用方向、原始发生月份、销售月、核销月、规则匹配日、销售/核销门店、SKU/产品、销售渠道、原始基数、费率、原始费用、调整基数、调整费用、调整后净基数、调整后净费用、规则版本、结果状态和账单锁定关联。
- 推广服务费的规则匹配日取销售业务日，归属销售门店和销售月；管理服务费的规则匹配日取核销业务日，归属核销门店和核销月。
- 部分退款按退款后净额同比例减少费用基数；全额退款归零；取消核销只调整管理服务费。后续事件通过 `adjustments[]` 展示，不覆盖原费用结果。
- 调整记录同时展示原始发生月份和调整入账月份。页面净额只展示接口返回的 `adjustedNetBaseCent/adjustedNetFeeCent`，不由前端把调整项重新求和。
- 已锁账来源继续展示锁账时冻结的规则版本和金额；后续调整以独立账单来源关联原费用结果，不改写已锁账行。
- 金额由整数分格式化为人民币，费率按服务端返回值展示；负向调整保留负号，状态文本不得只依赖颜色表达。

**前端职责**：仅格式化并渲染服务端返回字段、展开调整记录和维护分页；不重算基数、费率、原始费用或净额，不合并两个费用方向，不从退款事件自行生成调整，不修改锁账状态。

### 5.2 服务端处理逻辑

服务端按以下步骤构建明细行：

1. 按 §3、§4 得到已授权、已过滤的账单冻结来源或当前费用结果版本；以 `coupon_id + fee_direction` 保证当前查询每个方向只有一个结果版本。
2. 关联订单、券、销售门店、核销记录/门店和 SKU 产品规则，补齐业务 ID、状态、时间、门店和产品展示字段。
3. 从 `settlement_fee_result` 读取原始基数、费率、原始费用、规则版本和结果状态；不得在查询时依据当前规则重算。
4. 按原费用结果读取不可变调整记录，分别汇总 `adjustmentBaseCent/adjustmentFeeCent`，返回原始值与调整后净额，并在 `adjustments[]` 保留逐项追溯。
5. 有账单上下文时关联 `settlement_statement_entry`，标识冻结来源和账单行；未锁账时只返回当前指针命中的结果版本。

**处理输入**：

| 输入 | 来源 | 说明 |
|------|------|------|
| 规范化来源集合 | §3 的服务端校验结果 | 冻结账单来源或当前结果指针 |
| 规范化筛选 | §4 的服务端校验结果 | 费用方向、月份、产品、状态、关键词与分页 |
| 原始费用结果 | `settlement_fee_result` | 不可变原始金额、费率和规则版本 |
| 费用调整 | `settlement_fee_adjustment` WHERE `original_fee_result_id` | 不可变退款、取消核销或人工更正记录 |
| 账单来源映射 | `settlement_statement_entry` | 锁账上下文中的冻结来源关系 |

### 5.3 数据链路

> 下表为端到端追踪：UI 元素 ← API 字段 ← 服务端计算 ← 数据源/配置源。**数据源和配置源均由服务端读取**，前端不直接访问。

| UI 元素 | API 字段 | 计算规则 | 数据源（服务端读取） | 配置源（服务端读取） |
|---------|----------|---------|--------|--------|
| 订单/券业务标识 | `list[].orderId`、`list[].couponId` | 直透平台字符串业务 ID，不返回内部主键 | `raw_douyin_orders.order_id`、`raw_douyin_order_coupons.coupon_id` | — |
| 订单/券状态 | `list[].orderStatus`、`list[].couponStatus` | 返回规范化状态 | `raw_douyin_orders.order_status_normalized`、`raw_douyin_order_coupons.coupon_status_normalized` | — |
| 销售与核销时间 | `list[].saleTime`、`list[].verifyTime`、`list[].ruleMatchDate` | 推广取销售业务日，管理取核销业务日 | `raw_douyin_orders.sale_time`、`raw_douyin_verify_records.verify_time` | — |
| 销售/核销门店 | `list[].saleStoreId/Name`、`list[].verifyStoreId/Name` | 分别关联销售门店和核销 POI 映射门店 | `settlement_fee_result.sale_store_id`、`settlement_fee_result.verify_store_id`、`dim_stores.store_id`、`dim_stores.store_name` | `dim_store_poi_mappings.poi_id`、`dim_store_poi_mappings.store_id` |
| SKU 与产品 | `list[].skuId`、`list[].skuName`、`list[].productName`、`list[].productScope`、`list[].productType` | 费用结果产品维度与 SKU 规则展示信息关联 | `settlement_fee_result.sku_id` | `dim_sku_product_rules.sku_id`、`dim_sku_product_rules.sku_name`、`dim_sku_product_rules.product_name`、`dim_sku_product_rules.product_scope`、`dim_sku_product_rules.product_type` |
| 销售渠道 | `list[].saleChannel` | 返回规范化渠道 | `settlement_fee_result.sale_channel_normalized` | — |
| 来源金额与退款金额 | `list[].sourceAmountCent`、`list[].refundedAmountCent` | 读取费用结果固化的计算来源金额 | `settlement_fee_result.source_amount_cent`、`settlement_fee_result.refunded_amount_cent` | — |
| 原始基数、费率与费用 | `list[].originalBaseCent`、`list[].feeRate`、`list[].originalFeeCent` | 直透不可变费用结果 | `settlement_fee_result.fee_base_cent`、`settlement_fee_result.fee_rate`、`settlement_fee_result.fee_amount_cent` | — |
| 调整基数与调整费用 | `list[].adjustmentBaseCent`、`list[].adjustmentFeeCent` | 对所选来源关联的调整记录求和 | `settlement_fee_adjustment.adjustment_base_cent`、`settlement_fee_adjustment.adjustment_fee_cent` | — |
| 调整后净额 | `list[].adjustedNetBaseCent`、`list[].adjustedNetFeeCent` | 原始值加调整值，由服务端返回 | `settlement_fee_result.fee_base_cent`、`settlement_fee_result.fee_amount_cent`、`settlement_fee_adjustment.adjustment_base_cent`、`settlement_fee_adjustment.adjustment_fee_cent` | — |
| 原始/销售/核销月份 | `list[].originalBusinessMonth`、`list[].saleMonth`、`list[].verifyMonth` | 原始月份固化；销售/核销月由各自业务日形成 | `settlement_fee_result.original_business_month`、`raw_douyin_orders.sale_time`、`raw_douyin_verify_records.verify_time` | — |
| 规则版本与结果状态 | `list[].ruleVersion`、`list[].resultStatus` | 直透费用结果版本，查询不重算 | `settlement_fee_result.rule_version`、`settlement_fee_result.result_status` | `sku_fee_rule.rule_version` |
| 调整记录 | `list[].adjustments[]` | 按原费用结果读取并按发生时间稳定排序 | `settlement_fee_adjustment.adjustment_id`、`settlement_fee_adjustment.adjustment_posting_month`、`settlement_fee_adjustment.adjustment_type`、`settlement_fee_adjustment.adjustment_reason`、`settlement_fee_adjustment.occurred_at` | — |
| 账单锁定关联 | `list[].statementId`、`list[].statementLineId`、`list[].statementEntryId` | 有账单上下文时关联不可变来源映射 | `settlement_statement_entry.statement_id`、`settlement_statement_entry.statement_line_id`、`settlement_statement_entry.statement_entry_id` | — |

### 5.4 异常与兜底

**服务端兜底**：

| 场景 | 处理 |
|------|------|
| 原始费用结果缺少订单、券或 SKU 业务标识 | 标记为数据质量阻断并返回可追踪错误，不用内部主键或空字符串替代。 |
| 核销记录或门店映射缺失 | 管理服务费结果不猜测核销时间/门店；按数据质量规则标记 `BLOCKED`。 |
| 调整记录存在但无法关联原费用结果 | 不并入任意明细净额，进入数据质量问题并返回结构化错误。 |
| 同一券同一方向命中多个当前结果 | 视为数据一致性错误，不随机选择版本。 |
| 锁账来源与费用结果版本不一致 | 以冻结映射为审计依据并阻断异常行，不切换到当前指针。 |

**前端渲染兜底**：

| 场景 | 处理 |
|------|------|
| 可选展示名称缺失但稳定业务 ID 存在 | 展示业务 ID 和“名称暂缺”，不隐藏整行。 |
| 行为 `BLOCKED` | 金额字段按接口结果展示或显示不可计算，明确列出阻断原因，不猜测为 0。 |
| 调整项为空 | 显示“无后续调整”，不伪造零金额调整记录。 |
| 明细加载失败 | 保留筛选和表头，清除或明确标记旧行，允许原条件重试。 |

### 5.6 验收

| # | 类型 | 场景 | 触发条件 | 预期结果 |
|---|------|------|---------|---------|
| 1 | 业务规则 | 一券一方向唯一 | 同一券同时产生推广服务费和管理服务费 | 两个方向各有一行；同一方向不重复出现多个当前版本。 |
| 2 | 业务规则 | 部分退款调整 | 原费用完成后发生部分退款 | 原费用结果不变，新增负向调整并显示原始月、调整入账月和调整后净额。 |
| 3 | 业务规则 | 取消核销 | 已核销券随后取消核销 | 只对管理服务费生成独立调整；推广服务费不因取消核销自动调整。 |
| 4 | 业务规则 | 锁账后规则变化 | 已锁账结果对应的当前费率发生变化 | 页面仍展示锁账时冻结的金额、费率和规则版本。 |
| 5 | UX 交互 | 展开调整记录 | 点击有调整的明细行 | 展示每项调整的入账月份、类型、基数、费用、版本、原因和发生时间。 |
| 6 | 异常兜底 | 数据质量阻断 | 管理费缺少有效核销记录或门店映射 | 行明确显示阻断状态和原因，不猜测核销时间、门店或金额。 |

---

## §6 同口径导出

### 6.1 用户体验

**数据来源**：`GET /api/v1/order-fee-details/export` 使用与当前列表完全相同的来源上下文、费用方向和筛选参数，返回带 UTF-8 BOM 的 CSV 文件。
> 接口详情见[双费用结算与报表 API §4](../foundation/foundation-api-dy-data/settlement-reporting.md#4-get-apiv1order-fee-detailsexport--导出订单费用明细)。

**交互语义引用**：`order-fee-detail.filter-export.3`

**布局**：

```
[当前方向：推广服务费/管理服务费] [当前筛选摘要] [共 N 条]
                                           [导出当前明细]
```

**交互规则**：

- 导出请求复用当前列表除 `page/pageSize` 外的全部参数；页面不得在导出前自行放宽月份、产品、状态、关键词或来源上下文。
- 点击导出后服务端重新校验登录态、数据范围、账单归属、费用方向、费率和规则版本上下文；列表可见不代表后续导出自动获权。
- 导出文件至少包含订单/券、费用方向、原始发生月、销售月、核销月、调整入账月份集合、规则匹配日、销售/核销门店、SKU/产品、原始/调整/净基数、费率、原始/调整/净费用、规则版本和账单锁定状态。
- 文件头写入筛选摘要和生成时间；文件名使用安全业务日期，不包含门店隐私信息、本地路径或凭据。
- 当前结果为零时禁用导出；服务端二次校验为空时返回 409 `EXPORT_EMPTY`，不生成空文件。
- 导出失败可按原条件重试，不改变筛选、费用结果、账单状态或任何业务数据。

**前端职责**：仅提交当前规范化参数、展示导出进度、接收文件和处理错误；不在浏览器拼装 CSV，不绕过权限导出已缓存列表，不把页面分页参数带入导出。

### 6.2 服务端处理逻辑

服务端按以下步骤生成导出文件：

1. 重新执行 §3 的权限和来源上下文校验，并执行 §4 的全部筛选校验；忽略分页参数。
2. 使用与列表一致的费用方向、结果版本、调整记录和锁账来源构建导出行；不得使用另一套查询或重算逻辑。
3. 结果为空时返回 409 `EXPORT_EMPTY`；非空时生成带 UTF-8 BOM 的 CSV，写入筛选摘要和生成时间。
4. 对文件名和文本字段执行安全处理，返回文件流；生成失败只记录审计和 `requestId`，不修改业务状态。

**处理输入**：

| 输入 | 来源 | 说明 |
|------|------|------|
| 来源上下文 | §3 当前服务端规范化上下文 | 导出时重新授权和校验 |
| 费用方向与筛选 | §4 当前有效条件 | 与列表一致，忽略分页 |
| 明细和调整 | §5 同一服务端查询口径 | 不由前端缓存列表生成 |
| 当前用户权限 | 宿主 App 登录态 | 每次导出重新校验 |

### 6.3 数据链路

> 下表为端到端追踪：UI 元素 ← API 字段 ← 服务端计算 ← 数据源/配置源。**数据源和配置源均由服务端读取**，前端不直接访问。

| UI 元素 | API 字段 | 计算规则 | 数据源（服务端读取） | 配置源（服务端读取） |
|---------|----------|---------|--------|--------|
| 导出按钮可用性 | 列表 `total` | `total > 0` 时前端可发起；服务端仍二次判空 | `settlement_fee_result.fee_result_id` | — |
| 导出筛选摘要 | 导出请求中的上下文与筛选参数 | 使用服务端规范化后的条件写入文件头 | `settlement_statement_entry.statement_id`、`settlement_fee_result.fee_direction`、`settlement_fee_result.product_scope`、`settlement_fee_result.product_type` | — |
| 明细导出行 | CSV 业务列 | 与 §5 列表同源，忽略分页 | `settlement_fee_result.fee_result_id`、`settlement_fee_result.fee_amount_cent`、`settlement_fee_adjustment.adjustment_id`、`settlement_fee_adjustment.adjustment_fee_cent`、`settlement_statement_entry.statement_entry_id` | `dim_sku_product_rules.sku_id`、`dim_sku_product_rules.product_name` |
| 调整入账月份集合 | CSV 调整入账月份列 | 同一原费用结果的调整月份去重、稳定排序 | `settlement_fee_adjustment.adjustment_posting_month` | — |
| 生成时间 | CSV 文件头 | 使用服务端业务时区生成 | — | `Asia/Shanghai` |

### 6.4 异常与兜底

**服务端兜底**：

| 场景 | 处理 |
|------|------|
| 导出时权限已失效 | 返回 403，不生成文件，不泄露文件名或筛选摘要。 |
| 导出时上下文已过期 | 返回 422 和返回单店分账路径，不按当前规则重算。 |
| 同口径结果为空 | 返回 409 `EXPORT_EMPTY`，不生成空 CSV。 |
| 文件生成或传输失败 | 返回结构化错误和 `requestId`，不改变费用、调整或账单状态。 |

**前端渲染兜底**：

| 场景 | 处理 |
|------|------|
| 当前列表为空 | 禁用导出并说明“当前筛选无可导出明细”。 |
| 服务端返回 `EXPORT_EMPTY` | 保留当前条件并刷新列表，提示数据已变化。 |
| 权限或上下文失效 | 不重试下载；清除旧下载状态并提供返回来源页路径。 |
| 导出失败 | 恢复按钮，保留筛选，显示带 `requestId` 的重试提示。 |

### 6.6 验收

| # | 类型 | 场景 | 触发条件 | 预期结果 |
|---|------|------|---------|---------|
| 1 | 业务规则 | 列表与导出同口径 | 在管理服务费方向设置月份、状态和关键词后导出 | 文件仅含相同来源、方向和筛选命中的记录，且不受当前页影响。 |
| 2 | 业务规则 | 导出重新授权 | 列表加载后撤销用户门店权限再点击导出 | 服务端返回 403，不生成或下载文件。 |
| 3 | UX 交互 | 完整追溯列 | 导出包含退款调整的明细 | 文件包含原始月、调整入账月份、原始/调整/净额及规则版本。 |
| 4 | 异常兜底 | 空结果导出 | 当前筛选为零条或导出时变为零条 | 页面禁用按钮或服务端返回 `EXPORT_EMPTY`，不产生空文件。 |
| 5 | 异常兜底 | 生成失败重试 | CSV 生成或传输失败 | 页面保留筛选并允许重试，任何费用和账单状态均不改变。 |

---

## §7 异常与兜底策略（全局）

### 7.1 接口级兜底

| 场景 | 处理 |
|------|------|
| `GET /api/v1/meta/filters` 超时 | 保留页面骨架，禁用依赖元数据的筛选，显示带 `requestId` 的重试提示。 |
| `GET /api/v1/order-fee-details` 超时 | 保留来源上下文、费用方向和筛选，清除或标记旧明细，禁止把缓存结果伪装为最新。 |
| `GET /api/v1/order-fee-details/export` 超时 | 恢复导出按钮并允许原条件重试，不改变列表或业务状态。 |
| 接口返回 `code ≠ 0` | 按权限、参数、上下文过期、空结果、数据质量或内部错误分别提示，不使用同一笼统文案。 |

### 7.2 子数据源降级

| 子数据源 | 失败影响 | 降级策略 |
|---------|---------|---------|
| `settlement_statement_entry` | 无法验证锁账来源 | 锁账上下文查询和导出失败，不切换到当前结果指针。 |
| `settlement_fee_result` / `settlement_fee_result_current` | 无法取得不可变费用结果 | 返回结构化错误，不在查询时按原始订单和当前费率临时重算。 |
| `settlement_fee_adjustment` | 无法确定调整与净额 | 不把调整视为零；相关明细进入数据质量阻断。 |
| `raw_douyin_orders` / `raw_douyin_order_coupons` / `raw_douyin_verify_records` | 无法补齐业务标识、状态或业务时间 | 不猜测字段；按影响范围标记阻断并保留可审计 `requestId`。 |
| `dim_sku_product_rules` / `dim_stores` | 无法补齐产品或门店展示 | 稳定业务 ID 可用时显示 ID 与“名称暂缺”；影响规则校验时阻断查询。 |

---

## §8 接口契约

完整字段、包络、错误和权限契约以 Foundation API 为准；本节只列本区块实际使用的接口、请求来源和前端边界，不复制一套可分叉的接口定义。

### 8.1 接口：`GET /api/v1/meta/filters`

为费用明细页提供销售月、核销月、费用方向、产品维度和业务时区元数据。

> 完整接口契约见[公共 API 契约 §6](../foundation/foundation-api-dy-data/common-contract.md#6-get-apiv1metafilters--结算筛选元数据)。

**本区域业务说明**：

- **本区域使用的全部响应字段**：`saleMonths`、`verifyMonths`、`feeDirections`、`productScopes`、`productScopeTypeMap`、`productTypes`、`timezone`（§4）。
- **前端不做业务判断**：月份可用性、产品合法组合和门店数据范围均以接口返回为准；前端不加载全量选项后自行过滤。

### 8.2 接口：`GET /api/v1/order-fee-details`

按已授权来源上下文、费用方向和筛选条件返回一券一方向费用明细。

> 完整接口契约见[双费用结算与报表 API §3](../foundation/foundation-api-dy-data/settlement-reporting.md#3-get-apiv1order-fee-details--订单费用明细)。

**请求参数来源**：

- `statementId/statementLineId` 或 `storeId/month`：来自 PRD 2 的账单行或预览汇总行；两种口径不得混用为权限依据。
- `feeDirection/productScope/productType/feeRates/ruleVersions`：来自 PRD 2 被点击汇总行和本页服务端规范化上下文；费率与版本只用于校验。
- `saleMonth/verifyMonth/dataStatus/q/page/pageSize`：来自本页筛选和分页状态。
- 登录身份与权限：来自宿主 App 登录态，不通过查询参数授予。

**本区域业务说明**：

- **本区域使用的全部响应字段**：`context`、`list`、`total`、`page`、`pageSize`（§3-§5）；`list[]` 使用 `feeResultId`、`statementEntryId`、`orderId`、`couponId`、`orderStatus`、`couponStatus`、`feeDirection`、`originalBusinessMonth`、`saleMonth`、`verifyMonth`、`ruleMatchDate`、`saleTime`、`verifyTime`、`saleStoreId`、`saleStoreName`、`verifyStoreId`、`verifyStoreName`、`skuId`、`skuName`、`productName`、`productScope`、`productType`、`saleChannel`、`sourceAmountCent`、`refundedAmountCent`、`originalBaseCent`、`feeRate`、`originalFeeCent`、`adjustmentBaseCent`、`adjustmentFeeCent`、`adjustedNetBaseCent`、`adjustedNetFeeCent`、`ruleVersion`、`resultStatus`、`statementId`、`statementLineId`、`adjustments[]`（§5）。
- **调整项字段**：`adjustmentId`、`adjustmentPostingMonth`、`adjustmentType`、`adjustmentBaseCent`、`adjustmentFeeCent`、`ruleVersion`、`adjustmentReason`、`occurredAt`（§5）。
- **前端不做业务判断**：权限、来源版本、费用方向、月份归属、费率匹配、退款调整、净额与锁账状态全部由服务端判定；前端只渲染返回结果。

### 8.3 接口：`GET /api/v1/order-fee-details/export`

按与列表相同的授权、来源、费用方向和筛选口径导出订单费用明细 CSV。

> 完整接口契约见[双费用结算与报表 API §4](../foundation/foundation-api-dy-data/settlement-reporting.md#4-get-apiv1order-fee-detailsexport--导出订单费用明细)。

**本区域业务说明**：

- 请求参数与 §8.2 相同，但忽略 `page/pageSize`；服务端必须重新授权和判空。
- 响应为带 UTF-8 BOM 的 CSV；空结果返回 409 `EXPORT_EMPTY`。
- 导出字段、筛选摘要、生成时间和安全文件名遵循 Foundation 契约；前端不得用当前页缓存自行拼接文件。
