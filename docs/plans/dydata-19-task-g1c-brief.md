# DYDATA-19 G1c — 推广费负数账期结转抵扣

Status: Ready after G0/G1a/G1b
Owner: G1c implementer; controller reviews and integrates

## Goal

补齐 Linear DYDATA-19 中推广费负数账期的确定性结转：负数不单独开票，按账期顺序持续抵扣最早未开票正数账期；原账单、原发票和原结算记录不回改，列表、指标和登记校验使用同一后端投影。

## Binding algorithm

- 处理同一门店、推广费方向、当前有效且已确认、尚无当前有效推广费发票分配的账期；账单必须已经包含 G0 顺延来源形成的当前有效负数调整。
- 推广费确认保存带符号的当前账单净额：负数账单确认金额必须等于负数净额，不能在确认接口截断为 0；管理服务费确认规则不在本任务改动。
- 从 2026-08 起只在同一门店内投影；不同门店绝不合并。
- 汇总全部未开票负数确认账期形成抵扣池，并按 `statementMonth` 升序抵扣最早未开票正数账期。若较早正数账期仍未开票，后出现的负数也应优先抵扣它；已开票正数账期不回改，剩余负数才向未来结转。
- 负数不能单独登记发票。一个抵扣组由全部尚未消耗的负数完整账期和按月升序加入的最早未开票正数完整账期组成：
  - 若组内累计金额仍 `<= 0`，待开票金额为 0，整个未结清组继续等待后续正数账期。
  - 当组内累计金额首次 `> 0`，该组成为一个可登记组；发票金额等于组内所有完整账期确认金额之和。
  - 抵扣组闭合后，未参与抵扣的其余正数账期可按既有规则单独或合并登记。
- 登记时必须一次包含该组全部正/负账期；每个 allocation 金额严格等于对应账期当前有效确认金额。不得跳过中间抵扣账期、拆分单个账期或只提交净额到一个正数账期。
- 一张发票可以继续合并多个已闭合的可登记组，但每个组和每个账期必须完整包含；发票总额严格等于所有 allocation（含负数）的合计且必须大于 0。
- 若没有负数结转，保持现有“一张发票覆盖一个或多个完整正数账期”的行为。
- 已登记、已结算或历史失效发票不被回改；后续才出现的负数只影响仍未开票的最早正数账期，若无可抵扣正数则继续向未来结转。
- 指标：账单总额和已确认金额保留带符号值；待开票金额为所有未开票组可开票净额之和且不小于 0；已开票/已结算金额只统计当前有效发票净额。

## API projection

- 门店账单响应为推广费增加：`promotionInvoiceableAmountCent`、`promotionCarryforwardBalanceCent`、`promotionInvoiceGroupId`、`promotionRequiredStatementIds`。
- `promotionInvoiceGroupId` 由排序后的 `statementId + statementVersion + confirmationId/version` 规范化后确定性哈希生成，不使用随机 ID；任一账单或确认版本变化后旧组失效，提交基于旧组返回 409 并要求刷新。
- 管理员汇总和门店汇总调用同一 carry-forward helper，避免列表与指标分叉。
- `POST /promotion-invoices` 继续接收完整 allocations；校验所选账期集合等于一个或多个完整可登记组，且每个分配等于确认金额。
- 每个 allocation 必须回传列表给出的 `promotionInvoiceGroupId`；任一组 ID 缺失或与服务端当前投影不一致返回 409。无负数时单个正数账期也形成确定性单账期组，现有多正数合并即提交多个完整组。
- 当组内净额 `<= 0` 时返回明确 422，不能创建零额或负额发票。
- 同组所有成员返回同一 `promotionInvoiceGroupId` 和完整 `promotionRequiredStatementIds`；`promotionInvoiceableAmountCent` 为组闭合后的净发票金额，未闭合成员为 0；`promotionCarryforwardBalanceCent` 为该成员处理后的未结清余额。月度待开票只统计在所选月闭合（组内最后账期为所选月）的组净额，累计待开票统计截至所选月已闭合且未开票的全部组净额。

## Schema and migration

- `PromotionInvoiceAllocation.allocated_amount_cent` 必须允许负数；通过下一单头、可逆 migration 调整约束。
- 不新建可被人工改写的结转余额表。结转投影由当前有效账单确认和当前有效发票分配确定性计算；不可变 allocation 提供已消费组的审计事实。
- 不删除或重写历史 allocation；被红冲/作废/替换而失效的 allocation 不占用账期，账期重新进入投影。
- 本任务依赖 G0 的不可变顺延来源/应用事实；不得把 worker 已跳过的锁定月退款当成“没有负数”。

## Frontend contract

- 负数账期显示“结转抵扣中”及当前结转余额，不能单独选择。
- 可登记正数账期显示抵扣前确认金额、负数抵扣和可开票净额。
- 选择一个可登记组时自动选择其全部必需账期；移除时整组移除，防止形成非法部分集合。
- 登记摘要分别展示正数原费用、负数抵扣和净发票金额。

## TDD gates

1. RED：单个负数、连续负数、负数大于首个正数、跨多个后续正数、已开票/锁定月退款通过 G0 顺延、多个可登记组、跨门店隔离、已有发票排除、失效发票重新释放、非法部分组、列表/指标/登记一致。
2. 确认 RED 为缺失行为后实现单一纯函数/查询 helper。
3. GREEN 后运行 focused API、migration、frontend contracts、build、visual/browser checks 和 `git diff --check`。

## Non-goals

- 不开具零额或负数发票。
- 不按比例猜测或拆分账期金额。
- 不回改原账单、原发票或历史结算。
- 不处理管理服务费负数抵扣；该方向仅按当前已冻结规则展示。
- 不进行生产迁移、部署、commit、push、reset、checkout 或全仓格式化。
- 不覆盖或回退并发改动。

## Required report

Return `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT` or `BLOCKED`, followed by changed files, exact red and green commands/results, self-review findings and remaining risks.
