# DYDATA-19 G1b — 推广费发票生命周期与替换登记

Status: Ready after G1a review
Owner: G1b implementer; controller reviews and integrates

## Goal

补齐 Linear 正文中推广费发票的红冲、作废、替换和重新登记闭环。开票及红冲/作废行为均发生在系统外；系统只登记不可变事件、释放对应账期、关联替换发票并保留历史审计。

## Binding requirements

- 仅推广费发票进入本事件流；管理服务费不得复用该流程。
- 当前有效发票可登记 `RED_FLUSHED` 或 `VOIDED` 事件；必须填写原因和 `readVersion`。由于系统登记的是已经在系统外发生的事实，待厂审、审核不通过、已结算三种当前厂家状态都允许登记两类事件；同一物理发票只能有一个当前有效生命周期终止事件。
- 事件成功后，原发票及其分配退出当前有效统计，相关完整账期重新可登记；历史发票、分配、状态事件永久保留，不删除、不原地改写业务事实。
- 重新登记使用新的 20 位发票号码，并通过 `replacesInvoiceId` 关联原发票；新旧发票号码不得相同。
- 新登记必须覆盖原发票释放的全部账期，仍遵守“一个门店 + 一个账期只有一张当前有效推广费发票”和“一张发票可包含多个完整账期、不可拆分单账期”的既有规则。若 G1c 当前确定性抵扣组同时包含其他未开票账期，则允许并要求把该完整抵扣组一并提交；不得遗漏任何原释放账期。
- `replacesInvoiceId` 必须属于当前门店，且其最后一个生命周期事件必须是 `RED_FLUSHED` 或 `VOIDED`；不得跨门店替换。
- 已使用过的发票号码不得用于新的物理发票登记；同一物理发票因管理员导入审核结果形成不可变状态版本时可以沿用原号码。
- 幂等重放返回原结果；同一幂等键配不同载荷返回 409。
- 生命周期事件、厂家结果导入和换票登记共用物理发票版本锁：第一笔事务成功，后续旧 `readVersion` 或已终止版本返回 409；覆盖红冲与作废竞争、厂家状态导入与生命周期事件竞争、生命周期事件与换票登记竞争。
- 门店只能操作自身范围；财务管理员可查询审计历史，但不能代门店创建推广费发票生命周期事件。
- 所有事件使用服务器时间并进入操作审计；不调用外部开票、验真或企业微信能力。

## API contract

- `POST /api/v1/promotion-invoices/{invoiceId}/lifecycle-events`
  - request: `eventType`, `reason`, `readVersion`
  - required header: `Idempotency-Key`
  - response includes affected invoice, lifecycle event and released statement months.
- `POST /api/v1/promotion-invoices`
  - add optional `replacesInvoiceId`.
  - when present, enforce the replacement rules above and return the linkage.
- `GET /api/v1/promotion-invoices/{invoiceId}`
  - return immutable invoice/version facts, allocations, current/effective marker, replacement chain and ordered status/lifecycle events.

## Data rules

- 新增独立 `PromotionInvoiceLifecycleEvent`，只表达 `RED_FLUSHED`/`VOIDED`，不复用强制带 `toStatus` 的厂家 `InvoiceStatusEvent`，不增加伪厂家审核状态。
- `PromotionInvoice` 增加稳定的 `physicalInvoiceId` 和显式 `versionKind`：同一物理发票的厂家状态版本共享 `physicalInvoiceId` 和号码，并通过 `supersedesInvoiceId` 形成不可变状态版本链。
- 新物理替换发票生成新的 `physicalInvoiceId`，通过独立 `replacesInvoiceId` 关联被替换发票；不得再用 `supersedesInvoiceId` 同时表达厂家状态版本和换票关系。
- 生命周期事件保存物理发票、触发时的发票版本、事件类型、原因、读取版本、操作者、时间和幂等摘要；数据库唯一约束防止同一物理发票出现两个当前终止事件。
- 既有同号码状态版本按 `storeId + invoiceNumber` 回填同一物理发票 ID；无法稳定识别的历史链进入迁移异常清单，不按名称/金额猜测。
- 使用下一单头、可逆 migration；不得 destructive migration 或删除历史。

## Frontend contract

- Current invoice list exposes lifecycle/history entry points.
- Eligible invoices can register red-flush or void with a required reason and explicit confirmation.
- Released periods return to the registration selector.
- Replacement registration clearly shows the original invoice number, reason and affected periods; successful replacement refreshes statements and invoice history.
- User-facing copy must state that actual red-flush/void/reissue happens outside the system.

## TDD gates

1. Add failing API tests for scope, lifecycle event validation, state/event eligibility matrix, optimistic-lock conflicts, idempotency, released periods, historical retention, global number non-reuse, physical status-version chain and replacement linkage.
2. Verify red failures are missing behavior.
3. Implement the smallest backend behavior and transaction boundaries.
4. Add failing frontend contract tests, then implement client/types/page behavior.
5. Run focused API tests, frontend contract tests, build and `git diff --check`.

## Non-goals

- No external invoice issuance, red-flush, void, validation or Enterprise WeChat call.
- No management-fee invoice lifecycle.
- No negative-period carry-forward, management correction, SAP, import reversal or finance-order-detail change.
- No production migration, deployment, commit, push, reset, checkout or broad formatting.
- Never revert or overwrite unrelated concurrent edits.

## Required report

Return `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT` or `BLOCKED`, followed by changed files, exact red and green commands/results, self-review findings and remaining risks.
