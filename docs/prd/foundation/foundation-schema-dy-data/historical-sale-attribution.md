# 历史销售归属与人工纠错来源（DYDATA-104）

> 所属索引：[Schema](../foundation-schema-dy-data.md) · [内部消费合同](../foundation-api-dy-data/settlement-authority.md)
> 依据：`apps/api/dy_api/models.py`、`alembic/versions/20261023_0065_historical_sale_attribution.py`、`apps/worker/historical_sale_attribution.py`、`apps/worker/settlement.py`；仅反映已批准范围，不把精确审批扩展为通用绑定。

## 1 `historical_sale_attribution_decisions`

| 字段 | PostgreSQL 类型 | 可空 | 约束/来源 |
|---|---|---|---|
| decision_id | varchar(128) | NO | PK，决定 ID |
| batch_id | varchar(128) | NO | 审批批次 |
| raw_order_id | bigint | NO | FK raw_douyin_orders.id，RESTRICT |
| order_id | text | NO | 平台订单 ID 快照 |
| raw_coupon_id | bigint | NO | FK raw_douyin_order_coupons.id，RESTRICT |
| coupon_id | text | NO | 唯一约束 `uq_historical_sale_attribution_coupon` |
| verify_id | text | NO | FK raw_douyin_verify_records.verify_id，RESTRICT |
| verify_time | timestamptz | NO | 被批准的精确核销时间 |
| business_month | varchar(7) | NO | 被批准上海核销业务月 |
| source_account_id | text | NO | 原始账号身份 |
| store_id | text | NO | FK dim_stores.store_id，RESTRICT |
| source_identity_sha256 | varchar(64) | NO | 稳定身份摘要 |
| source_identity_json | jsonb | NO | 内部/平台订单券 ID、账号、核销等精确来源 |
| evidence_sha256 | varchar(64) | NO | 审批证据摘要 |
| approval_evidence_json | jsonb | NO | 已批准证据，不新增授权 |
| actor | varchar(128) | NO | 审批应用操作者 |
| created_at | timestamptz | NO | 应用 UTC 时间，无通用 gmt_modified |

索引 `ix_historical_sale_attribution_month(business_month, decision_id)`、`ix_historical_sale_attribution_batch(batch_id)`；两个 digest 长度 CHECK=64。决定不可 UPDATE/DELETE/TRUNCATE。

`settlement_fee_result.sale_attribution_decision_id varchar(128) NULL`，FK → decision_id、RESTRICT。旧结果不追写。来源计数名 `historical_sale_attribution_decisions` 仅影响 settlement/finance；月结 watermark 只合入受影响月的决定 digest，无该月决定时保持旧格式，不使独立打榜失效。

## 2 应用与消费约束

受控脚本默认 preview；apply 必须匹配精确 manifest 文件 SHA，验证每个内部/平台订单券 ID、账号、核销 ID/时间、月份、目标店和审批摘要，并在共享来源写锁下原子写入决定及财务审计。不得昵称猜桥、创建当前关系、延展到别的券/核销/月，也不自动触发费用重建或发布。

匹配稳定来源身份，不要求整个 raw JSON 永远不变，合法退款更新不使精确决定丢失。取消只作用于同决定/原核销费用；重核销不继承该次批准归属。缺证据或真实冲突继续单列阻断。

## 3 已批准历史人工纠错

不新造费用结果或专用替代账本，使用已有 `settlement_fee_adjustment.adjustment_type=MANUAL_CORRECTION` 与 `finance_operation_audit`。预演固化源文件/逐行摘要、订单券/门店、精确原费用结果、当前账单版本及预览 hash；apply 锁后重验，整批原子提交。

仅非零差额追加调整，零差额仍保存审计/来源锚点。原费用、current 指针、原账单及非目标条目保持；确认、发票、异议或复杂结转保护导致拒绝，不自动选择其他入账月，不补造缺证据发票。保护锚点是精确原费用结果，不是把整店账期所有后续退款锁死。

合法全额退款/取消核销按原锚点消除原费用及人工差额，受保护期仍走既有结转；重核销不继承旧固定金额。非零固定人工金额遇部分退款且无批准比例，保留金额并进入人工复核；零差额审计不形成固定金额覆盖，仍可按原费率处理部分退款。公开接口不新增任意历史修复入口。
