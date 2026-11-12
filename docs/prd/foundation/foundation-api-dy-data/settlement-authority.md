# 结算来源权威与仅发布合同（内部，不新增公开写 API）

> 所属索引：[API](../foundation-api-dy-data.md) · [资格 Schema](../foundation-schema-dy-data/account-qualification.md) · [历史归属 Schema](../foundation-schema-dy-data/historical-sale-attribution.md)
> 2026-10-27 已确认增量；依据 `account_qualification.py`、`historical_sale_attribution.py`、`protected_billing_authority.py`、`settlement_publication_only.py`、`billing_source_capture.py`、`month_close.py`。本文件定义技术边界，不将代码存在表述为生产整月闭环已验收。

## 1 资格版本与身份消费

核销业务月 `>=2026-10` 的结算读取对应月唯一冻结资格版本，输入指纹、重建 metadata、月结预检和 watermark 固定该版本/摘要。月底未完成、最后尝试失败/不完整/运行中或缺版本时暂停，不拿当前 raw/job 成功代替冻结证明。8/9 历史链、独立打榜范围不改。

自动月结启动与正式出账就绪分开：冻结成功且完整月每日真实 finalize 完成，可进入原 month-scoped 计算，无须先有费用或全部 current 已 pin；正式 preflight/watermark 仍严格要求非空 current 且全部 pin 到期望版。稳定输入与 job metadata 见 [资格 Schema §6](../foundation-schema-dy-data/account-qualification.md#6-自动月结计算输入与任务血缘fcr007-增量)，提交/发布闸门见 §4；不会将启动成功报告为正式 READY。

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

`--admission-wait-seconds` 显式范围0..1800秒；省略时按 `max(900, ceil(recovery + stable + max(30, 3 * SAMPLE_SECONDS)))` 推导预算，使用正式压力策略配置及别名。推导值超1800秒时在启动监控前明确拒绝；显式短预算只允许一次有界观察，未取得真实ALLOW即拒绝。dry-run不启动监控、不读取本次压力窗口配置。失败仅输出受控 error_type，不输出数据库凭据或私有来源行。运维应用仍须按现有发布授权流程，本文不新增 HTTP 发布路由，也不将资料回捞视为生产发布完成。

2026-10-31（S4-FCR-020）修正旧90秒/600秒预算无法覆盖默认180秒恢复加600秒稳定期的问题；策略初态、阈值、采样、正式claim/lease/hash及费用保护均保持。参数合同回捞不代表候选代码已经生产部署。

## 4 自动计算与统一正式出账门禁（FCR007 增量）

依据 `month_close._calculation_preflight/_calculation_inputs_digest/ensure_month_close_job` 及 `settlement_rebuild` 的 `_verify_month_calculation_input/_require_publication_qualification`。计算启动使用不含输出的输入 SHA，不依赖正式 READY 解锁自身；正式出账继续验证冻结版，不删除或过滤旧未 pin 费用来通过闸门，不改变资格或旧费处置策略。

| 入口/阶段 | 必须执行的校验与失败结果 |
|---|---|
| 自动 month runner | 计算前重验启动协议/完整日 revisions/完整输入 SHA 与固定资格版；真实全月选择和双费计算后、费用事务提交/refresh前再次重验 SHA，并要求该月每条 current pin 期望版；零 current 仍拒绝出账 |
| 原 full legacy runner | 原费用/聚合事务提交前，对实际 current fee 或当前账单涉及的所有 `>=2026-10` 月份执行冻结版本/全部 current pin 检查；即使 active pointer 为空也不能绕过，失败整批事务回滚 |
| refresh | 以实际 `plan.affected_months` 为准，在首次和最终来源捕获前后都复核；active/slot/bill 锁等待后的复读仍检查，不只相信锁前快照，失败不切换发布指针/账单版本 |
| publication-only | 对真实月份 closure 在预演捕获前后检查，apply 首末持锁捕获继续严格检查；仅发布合同与 status4拒绝不变，不转为费用重算 |

`require_current_month_qualification` 对8/9月直接保留旧合同；8/9初始化或闭包确实不含10月经济输出时，不因10月未冻结而阻断。真实依赖闭包包含未冻结或未完整 pin 的10月时，拒绝整个批次，不截断闭包。不存在把“请求的是8/9月”当作跳过实际10月依赖的理由。

旧未知/明确不合格 current 仍未 pin 时，明确报 `current_fee_qualification_version_mismatch`，费用及指针不因通过门禁而删除或被替换；月度费用事务回滚。启动输入漂移报来源未就绪并等待新的来源版本任务，同输入正常失败沿已有有限重试预算，不假造新 JobImpact 或重置预算。自动任务依然使用正常 runner 和发布最终事务，不提供新增 HTTP/强制跳过接口。

合成/本地 PG 证据见 [自动启动验证报告](../../../verification/dydata-104-oct27-month-auto-bootstrap.md)：报告记录相关集179 passed及本地隔离PG五项5 passed，覆盖完整日/观察后实际月度计算、并发幂等、旧未 pin 回滚、full无active和闭包门禁。这是合成月底与本地测试结果；10月真实月底尚未发生，不据此宣称真实冻结收据、生产月结或生产容量验收完成。
