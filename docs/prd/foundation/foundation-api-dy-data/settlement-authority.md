# 结算来源权威与仅发布合同（内部，不新增公开写 API）

> 所属索引：[API](../foundation-api-dy-data.md) · [资格 Schema](../foundation-schema-dy-data/account-qualification.md) · [历史归属 Schema](../foundation-schema-dy-data/historical-sale-attribution.md)
> 2026-10-27 已确认增量；依据 `account_qualification.py`、`historical_sale_attribution.py`、`protected_billing_authority.py`、`settlement_publication_only.py`、`billing_source_capture.py`、`month_close.py`。本文件定义技术边界，不将代码存在表述为生产整月闭环已验收。

## 1 资格版本与身份消费

核销业务月 `>=2026-10` 的结算读取对应月唯一冻结资格版本，输入指纹、重建 metadata、月结预检和 watermark 固定该版本/摘要。月底未完成、最后尝试失败/不完整/运行中或缺版本时暂停，不拿当前 raw/job 成功代替冻结证明。8/9 历史链、独立打榜范围不改。

来源优先级严格跟随 collector：账号依次取 `owner_account_id`、`sale_info.transfer_uid`、`sale_info.account_id`、`order_sale_info.transfer_uid`；抖音字段依次取 `owner_douyin_uid`、`sale_info.transfer_douyin_uid`、`order_sale_info.transfer_douyin_uid`。选中的首个非空原值必须与规范字段相等，不能越过高优先来源挑一个能匹配的低优先值。

官方 [订单查询字段合同](https://partner.open-douyin.com/docs/resource/zh-CN/local-life/develop/OpenAPI/general-capabilities/order.query/query) 将 `transfer_douyin_uid` 定义为订单归属人抖音号，将 `transfer_uid` 定义为加密归属 UID、非抖音 UID。只有选中的原来源是上述 transfer_douyin_uid 路径时，才可与冻结 workbook 的“抖音id”匹配；通用 owner_douyin_uid 不能统一重解释成短号，craftsman_uid 也不能当加密 transfer_uid。原来源为 transfer_uid 时不能直接连后台 account_id。

账号/UID/短抖音号命名空间分开。两个可证明身份来源匹配到不同账号、或多个合格账号时阻断；同昵称个人号不参与昵称桥。明确个人记录不得污染可证明合格账号关系，但未知类型、真实多门店冲突不能删去冒充唯一归属。

| 内部错误 | 含义 |
|---|---|
| qualification_identity_source_conflict | 选中原字段与规范字段矛盾 |
| qualification_identity_ambiguous | 两来源冲突或多个合格账号 |
| qualification_identity_unresolved | 无正式身份桥，尚不能证明资格，不等于已证明不合格 |
| account_not_qualified_in_frozen_month | 可证身份匹配到的记录均不满足月末资格 |
| qualification_version_conflict | 指定原版本与该月冻结版冲突 |

账号资格与销售时门店归属独立。区域号合格不等于当前 POI 是销售门店；仅有月末 POI、无精确销售时有效关系时不得猜店。迟到、跨月、退款沿原冻结版本/费用锚点处理，不能用当前认证或绑定反改旧月。

## 2 受保护整账权威来源

保护条件复用实际生成器：当前账单 status=3/4、confirmed_at/locked_at 非空、存在任一方向确认、同店同月状态1..4或已有 result_statement_id 的异议、推广费分配或管理费发票依赖。方向独立确认/异议操作合同不变；**来源发布保护的是整张当前账单**，不是只保护一个方向或某个修复名单。

不可变 `settlement_statement_entry` 引用的精确原 `SettlementFeeResult` 是来源依据，即使它不再是 current。校验原订单/券/方向/核销血缘、基数/费率/金额、汇总行和头闭合后才能发布；缺失或不闭合保守阻断。相同券/方向的新 primary 即使移店移月也不能替换冻结基础，不通过修复 current 指针达到发布。

经济来源金额 `source_amount_cent`、基数取精确原结果；展示快照 received_amount_cent、名称/时间等为 NULL 仍保持 NULL。不能以展示 NULL 当经济 0，也不能借当前 raw/result 猜补旧展示。

后续调整按精确事件 ID 与原费用锚点去重、校验和追加；同锚点合法退款/取消/结转仍保留。不以“相同券”粗暴吞掉全部后续事件或另一方向，不给无锚点事件找替代费用。

## 3 受控 CLI：只发布既有权威来源

入口 `scripts/ops/publish_settlement_authority.py`，默认 dry-run；`--month YYYY-MM` 必填且可重复，只接受正式月份。要求已有 active settlement 发布基代际。预演扩展实际影响月份闭包，锁/校验完整来源、当前账单、依赖和 active base；闭包内存在任何 status=4 账单时拒绝，本入口不获得锁账修复权。

预演 JSON 使用 CLI 自身 snake_case：`status=dry_run`、`protocol/base_generation_id/requested_months/closure_months/source_count/expected_headers/will_version_unprotected/preview_hash`。header 包含店/月、当前 ID/版本、protected、两方向 original/adjustment/net 和 action=protected/unchanged/version/create、expected_version。CLI 不是 Web API，不强套 Web camelCase 包络。

apply 必须 `--apply --preview-hash <64位SHA>` 匹配预演；经过真实 resource admission、持久重型任务 claim/租约、锁后首尾重验，在最终事务发布投影与未受保护待确认新版本。无变化幂等，受保护账单和 current 费用指针不变；该入口不执行费用计算或扩大金额修复范围。恢复/重启保留同 publication-only mode，不能退回普通重建。来源或依赖漂移须新预演，不可绕过 hash。

`--admission-wait-seconds` 默认90、范围0..600；失败仅输出受控 error_type，不输出数据库凭据或私有来源行。运维应用仍须按现有发布授权流程，本文不新增 HTTP 发布路由，也不将资料回捞视为生产发布完成。
