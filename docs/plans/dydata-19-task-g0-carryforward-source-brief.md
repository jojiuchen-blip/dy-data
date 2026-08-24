# DYDATA-19 G0 — 锁定账期后的退款/取消核销顺延事实

Status: Required before G1c and G2d
Owner: G0 implementer; controller reviews and integrates

## Goal

修复当前 worker 在退款/取消核销发生月已经锁账、开票或结算时直接跳过调整的问题。系统必须先保存不可变差额来源，再把差额确定性归入下一个可处理结算账期；不得修改原账单、原发票或原结算。

## Binding requirements

- 退款金额缺失或券级映射缺失仍保持既有数据异常，不生成顺延事实。
- 对已能精确计算的退款/取消核销，先按原费率版本计算两个费用方向各自的基数和费用负数差额，再判断事件发生月是否可入账。
- 同一费用结果先发生退款、后发生取消核销时，取消核销的剩余差额必须基于统一有效调整集合计算：普通调整直接计一次；顺延来源无论待应用或已应用都只计来源一次，其生成的目标调整不得重复计入。最终净额不得低于零。
- 事件发生月可处理时，保持现有 `SettlementFeeAdjustment` 入账行为。
- 事件发生月已锁定/已开票/已结算时：
  - 不回改该月账单、发票或结算；
  - 创建唯一、不可变的 `SettlementCarryforwardSource`，保存原费用结果、退款/取消事件、门店、费用方向、原业务月、事件发生月、基数差额、费用差额、原规则版本、原因和创建任务；
  - 来源初始为待应用，不能因 worker 重跑重复生成。
- 后续账期生成/重算时，按事件时间、来源 ID 稳定排序，把待应用来源完整归入第一个大于事件发生月且尚可处理的账期，创建不可变 `SettlementCarryforwardApplication` 并生成对应 `SettlementFeeAdjustment`。
- 若候选账期仍锁定，继续向后顺延；不得丢弃、截断或在锁定账期部分写入。
- “不可处理账期”不仅包含 `statement_status=4`，还包含已有当前有效推广费发票分配、管理费发票/厂家扣款或结算事实的账期；统一由一个不可变账期判断处理，禁止出现账单状态可写但发票事实已冻结的旁路。
- 推广费和管理服务费分别创建来源及应用，不跨方向抵销。
- 来源一经应用后永久保留；目标账单生成新版本时沿用既有不可变调整复制/版本规则，不把来源重复应用到第二个账期。
- 异议产生账单 Vn+1 时，旧应用版本转为非当前，复制对应不可变调整并创建指向新账单/新调整的应用 Vn+1；旧应用、旧调整和旧账单永久保留，新账单分录必须引用复制后的调整 ID。
- 顺延调整按不可变 `original_fee_result_id` 投影，不得因 `SettlementFeeResultCurrent` 指针换版从账单、统计或导出中消失。
- 并发统一使用业务唯一键、数据库唯一约束和短事务锁；第一笔成功，重复任务幂等命中，竞争任务不得重复应用。
- 成功、继续等待、冲突和幂等命中均写入现有数据问题/操作审计证据。已安全保存的待顺延、等待和幂等命中使用 info/warning；只有金额、来源或应用链冲突使用 error，避免误伤发布门禁。

## Schema and migration

- 新增不可变来源表和应用表；来源唯一键至少覆盖 `refundEventId + originalFeeResultId + feeDirection`。
- 应用表保存来源、目标账单/账单版本、目标调整记录、目标入账月、应用版本和当前有效标记；只通过新应用版本纠正，不物理删除。
- 创建下一单头、可逆 Alembic migration；不回填或猜测现有被跳过事件。历史缺口进入迁移异常清单，待稳定 ID 和原始事件核对后重新计算。

## Worker integration

- 调整金额必须在锁定判断前完成计算。
- 账期生成/重算事务在最终锁账前消费可应用来源。
- `SettlementFeeAdjustment.adjustment_posting_month` 使用实际顺延账期，`original_business_month` 和 source 仍保留原始事实。
- 不改变原退款事件、原费用结果或已锁定账单。

## TDD gates

1. RED：发生月已锁定仍创建来源；两个费用方向独立；重跑幂等；下月应用；下月也锁定继续顺延；跨多月；退款后取消核销最终归零且不重复计数；应用后再重建/新增退款不重复；账单分录和头汇总包含顺延调整；已有推广/管理发票事实强制顺延；目标账单版本变化产生应用 Vn+1；费用结果当前指针换版后调整仍可投影；并发仅应用一次；缺失金额/券映射不创建。
2. GREEN：worker/data tests、模型约束、迁移 upgrade/downgrade、PostgreSQL DDL。
3. 与 G1c/G2d 集成后验证负数可以进入发票/待开票投影。

## Write set

- `apps/api/dy_api/models.py`
- `apps/worker/settlement.py`
- one new `alembic/versions/20260821_0038_*.py`
- `tests/test_data_settlement.py`
- `tests/test_alembic_migrations.py`
- a new focused worker test file only if it reduces overlap; no dashboard/web changes

## Non-goals

- 不修改原账单、原发票、原结算或原退款事件。
- 不按比例猜测券级退款。
- 不进行历史自动猜测回填、生产迁移、部署、commit、push、reset 或 checkout。
- 不覆盖或回退并发改动。

## Required report

Return `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT` or `BLOCKED`, followed by changed files, exact red and green commands/results, self-review findings and remaining risks.
