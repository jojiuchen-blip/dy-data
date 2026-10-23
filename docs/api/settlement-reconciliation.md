# 离线结算基准解析与对账

`scripts/settlement_reconcile.py` 仅读取本地 JSON，不连接数据库或业务 API，不修改账单、规则、发票或生产。输出是材料解析及同粒度比对证据，不能独立证明系统正确、账期完整或金额已被业务核准。

## 基准输入

浏览器 DOM 提取的结构为 `{tables: [[[文本单元格, ...], ...], ...]}`，单元格必须是字符串。当前支持已核对表头的 2026-08 / 2026-09 文件：table0 为门店汇总，table1 为订单券明细；九月 table4 为八月未开票明细。其他附件表不参与当期费用求和。`--rules` 单独解析带有显式 `SKU ID` 的规则表，产品线直接保留为 `product_type`，不根据商品名或商品 ID 推断 SKU。

```powershell
python scripts/settlement_reconcile.py --august tmp/august.json --september tmp/september.json --rules tmp/rules.json
```

金额以 `Decimal` 解析，每行金额按 `ROUND_HALF_UP` 换算整数分后求和，负数保持符号；空金额保持未知，不当作零。纯空行、明确合计行、重复表头和缺标识行分别计数排除，非本月核销行不进入该月明细。重复订单允许多张券；重复订单券键会被单独报告，不自动删除。汇总总额是有效表行的已知金额之和，重复 SAP 需另行解释，不能把已知值合计当成完整值。

九月推广费、管理费、八月未开票、累计应开票、已填写推广发票金额分别输出。九月 table4 始终作为独立的八月 carryover，不与八月当期明细拼接，也不混入九月当期。发票列仅代表附件中已填写金额，空值未知；不能当作应计费用或完整发票台账。附件明细的管理费列不代表八月未开票管理费。

## 门店映射

两费方向分别使用附件的推广归属门店和管理支付门店文本。核销门店 ID 不等于两费的归属 ID，工具不替代映射。没有映射时记录 `store_id=null`。

`--store-map tmp/store-map.json` 接受显式数组：

```json
[{"source_store_ref":"合成门店甲","store_id":"0001"}]
```

也兼容 `{门店文本: store_id}` 对象。ID 必须是字符串，文本采用去除首尾空白后的精确匹配；数组一名对应不同 ID 时整次拒绝。同名同 ID 重复单列计数。映射的生成方应先检查系统展示名与基准名完全相同且唯一，存在重名、改名或别名时必须有另行核准的依据。stdout 给出显式映射来源和各月各方向未映射行数，不输出门店名称。

若名称与 SAP 均不能直接桥接，可在确认“管理费应扣方为核销门店”的已批准业务契约后，以附件管理支付门店文本→同券核销 POI→系统唯一 POI 映射推导候选。每一步必须唯一，跨月同名出现多个系统 ID 必须拒绝，不可使用模糊名称。推广门店只可复用已由这条事实链证明的相同名称映射；这不是把所有推广归属直接替换为核销门店。

传入 `--store-map-source management_redemption_poi` 可在 aggregate 中记录调用方声明的这条来源；另外支持 `explicit_reference`（默认）、`sap_snapshot`。该声明不是自动验真，映射生成证据仍由调用方保存。

## 券码与内部券 ID

附件 `券码（已撤销核销加密）` 是 `source_coupon_code`，不等于系统内部 `coupon_id`。当前实际附件为 15 位券码，而系统内部券 ID 为 19 位，工具保持两者独立；即使同订单只有一张券也不能推测其对应关系。

`--coupon-map tmp/coupon-map.json` 接受从真实来源字段证明的显式桥接数组：

```json
[{"order_id":"000123456789012345678901","source_coupon_code":"00001","coupon_id":"0000000001234567890"}]
```

同订单同券码多 ID，或同订单同内部 ID 多券码时整次拒绝。缺映射时 `coupon_id=null`，保持键未知而不制造“完整键不一致”的结论；原始文本券码保留在私密输出中，默认不会打印。

## 系统标准化输入

`--system tmp/system.json` 要求系统导出方先统一度量定义，不接受订单、门店或账单聚合直接与券行相减：

```json
{
  "schema_version":1,
  "grain":"coupon_fee",
  "amount_basis":"accrued_fee",
  "receipt_basis":"order_receipt",
  "records":[{
    "month":"2026-09",
    "direction":"promotion",
    "order_id":"000123456789012345678901",
    "coupon_id":"00001",
    "store_id":"0001",
    "amount_cent":100,
    "rate":"0.1",
    "receipt_cent":1000,
    "sku_id":null
  }]
}
```

`direction` 为 `promotion` 或 `management`；唯一键固定为 `(month,direction,order_id,coupon_id,store_id)`。所有 ID 必须为字符串，金额为整数分，费率为十进制字符串。可选金额、费率、实收、SKU 为 null 或缺省时归入未知，不能补零。月份为核销归属月，与基准一致；导出方应提供同范围、同原始应计费用定义，不把调整后净额、发票额混入 `amount_cent`。

当前系统导出使用费用结果 `fee_amount_cent` 作为 `amount_cent`：按该历史结果的退款 cutoff，以 `(source_amount_cent-refunded_amount_cent)*fee_rate` 分币舍入；不包含后续另表按事件月入账的 adjustment。`receipt_cent` 应对应 `source_amount_cent`，不能用退款后 fee base 替代订单实收。`refunded_amount_cent` 可作为额外字段提供，工具仅单列非零退款基数行数和未知数，不应用调整、不同月份冲抵或声称附件与系统必然等额。输出额外按月和费用方向给出匹配覆盖，未知键或重复键时 `coverage=unresolved_keys`。

仅两边都唯一且字段完整的键才比较金额和费率，差额方向为 `系统-基准`。任何一边重复的键整体标记歧义，不合并、不相减；仅基准、仅系统、缺键、缺字段分别计数。`only_system` / `only_baseline` 只表示当前可解析完整键集合的差异，映射或其他键未知时仍需人工解释。附件没有实际 SKU 明细时，该字段保持未知。`receipt_cent` 是附件订单实收在券行上的观测值，可能同订单重复；只有显式声明 `receipt_basis=order_receipt` 才比较，绝不累计这些重复实收为销售额。

## 私密输出与验证

默认 stdout 仅输出 aggregate。只有显式 `--private-output tmp/reconciliation.json` 才写规范化记录、映射后的门店引用和逐键差异；目标必须位于 Git 仓库内、被 ignore、未被跟踪且无符号链接。工具不写原始全表、邮箱、账户或发票号码。原始附件和私密结果均不得提交 Git。不要将 stdout 的总额或匹配数量当作业务验收结论。

```powershell
python -m pytest tests/test_settlement_reconcile.py -q
git diff --check
```

测试只使用合成资料，覆盖大文本 ID 和前导零、浮点尾差、负数、汇总行排除、九月夹带八月、多券与重复键、金额费率差异、未知字段、不同粒度拒绝、门店重名冲突和私密输出路径保护。
