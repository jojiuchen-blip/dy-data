# DYDATA-19 G2 — 管理费单店更正、SAP 建议确认与导入撤销

Status: Ready after G1 shared-model slices
Owner: G2 implementer; controller reviews and integrates

## Goal

在现有四类原子导入和不可变更正版本基础上，补齐 Linear DYDATA-19 §3/§5/§6 的三项发布阻断能力：管理服务费单店直接更正、门店 SAP 建议及管理员确认、已提交导入的更正撤销。所有行为保留版本和审计，不物理删除历史。

## Current reusable behavior

- `InvoiceRecord` 已支持一店一账期一方向的当前有效版本及历史版本。
- `StoreFinanceProfile` 已支持基础信息和 SAP 确认导入的不可变版本。
- `FinanceImportBatch`/row 已支持四类模板、整批校验、幂等、首次提交、差异更正、错误分页和审计。
- 新实现必须复用这些口径，不另建并行事实源。

## Slice G2a — management direct correction

- 管理员可在 `/finance/management` 对单个 `storeId + statementMonth` 当前有效管理服务费记录直接填写更正。
- 必填：发票号码、发票日期、发票金额、厂家扣款日期、厂家扣款金额、更正原因、`readVersion`；金额以分存储且不得为负。
- 新值生成 `InvoiceRecord` 新版本，旧版本 `is_current=false`，历史永久保留；`source_type=3` 标识更正，`import_batch_id=null` 表示页面直接更正。
- 更正提交后立即生效，不设置系统内审核节点。
- 第一笔并发事务成功；旧 `readVersion` 返回 409 和当前版本，不静默覆盖。
- `Idempotency-Key` 重放返回原版本；相同键不同载荷返回 409。
- 管理员和最高管理员权限一致；不按区域或门店拆分管理员权限。门店账号只读，不得直接更正。
- 写入 `FinanceOperationAudit`，保存前后快照、原因、操作者、请求 ID 和幂等摘要。

## Slice G2b — SAP suggestion and confirmation

- 门店账号可为自己的门店提交 SAP 建议；门店 ID 是唯一匹配键，SAP 不是匹配键。
- 建议至少包含建议 SAP、说明、`readVersion`；新增建议版本，不覆盖历史。
- 使用独立不可变 `SapSuggestion` 版本流，保存门店、建议 SAP、说明、建议版本、处理状态、提交人/时间和幂等摘要；不得把待处理建议塞入仅表示基础信息/有效确认值的 `StoreFinanceProfile`。
- SAP 缺失、冲突或未确认只展示提示，不阻断任一费用方向的确认、开票或财务处理。
- 管理员在 `/finance/stores` 查看建议，并确认、修正或驳回；确认/修正生成新的当前有效 `StoreFinanceProfile` SAP 确认版本，旧版本保留。
- 管理员可直接确认页面值，也可继续通过 `SAP_CONFIRMATION` 导入覆盖；两种路径共用同一版本序列和乐观锁。
- 门店端 API/UI 只允许本店提交和查看建议；管理员 `/finance/stores` 端提供全局查看、确认、修正和驳回。确认请求分别携带 `suggestionVersion` 与 `expectedConfirmedVersion`，避免把建议并发和有效值并发混成一个版本。
- 页面直接确认生成 `StoreFinanceProfile` 当前有效版本时允许 `importBatchId=null`，并以显式来源类型区分页面确认与导入确认；不得伪造导入批次。
- 最高管理员与管理员权限一致；门店不能确认自己的建议。
- 建议、确认、驳回和冲突都写入审计。
- `/admin/finance/stores` 返回当前有效 SAP、建议状态/版本、确认版本和更新时间；搜索需覆盖门店 ID、名称及 SAP。

## Slice G2c — correction reversal

- 已提交的四类导入均允许撤销，但撤销必须表现为一个新的“更正覆盖版本”，不得删除原批次或历史业务记录。
- `POST /api/v1/admin/finance-imports/{batchId}/reversals`，必填 `readVersion` 和 `changeReason`，并要求 `Idempotency-Key`。
- 仅可撤销已提交/已更正批次；是否仍可撤销必须逐行业务唯一键检查，而不是只比较 `importType + statementMonth` 的最大批次版本。过期、验证失败、未提交，或任一目标业务版本已被后续导入/页面修改覆盖时整批返回 409。
- 撤销批次关联 `reversesBatchId`，获得同一 `importType + statementMonth` 的下一版本，并成为当前有效版本。
- `FinanceImportBatch` 保存 `reversesBatchId`；每个反向 `FinanceImportRow` 保存被撤销目标、撤销前一有效目标、新反向目标及覆盖关系，并使用 `VALUE`/`TOMBSTONE` 效果类型明确“恢复上一值”或“撤销后无当前值”。
- 对 BASIC_INFO/SAP_CONFIRMATION：恢复目标批次提交前的上一有效 profile 版本；若不存在上一版本，则以反向版本表示“无当前值”，不得物理删除。
- 对 `PROMOTION_FACTORY_RESULT`：恢复目标批次提交前的上一有效厂家审核/结算版本；若不存在，则以反向版本让该结果退出当前统计。
- 对 `MANAGEMENT_FACTORY_RESULT`：发票与厂家扣款按同一模板、同一完成口径恢复目标批次提交前的上一有效版本；若不存在，则以反向版本让该业务槽位退出当前统计。不得拆成第五类扣款模板。
- 被撤销批次和所有原业务版本永久保留；列表/详情展示覆盖链、原批次、撤销批次、当前有效性和操作者。
- 撤销只能新增业务版本和反向行，禁止把旧历史业务行重新标记为当前；逐行业务键均验证通过后才在一个事务内提交。
- 并发及幂等规则与现有 commit/correction 完全一致；整批事务原子提交，任一行失败不得部分写入。
- 写入 `FinanceOperationAudit`，操作类型 `FINANCE_IMPORT_REVERSAL`。

## Slice G2d — management negative carry-forward

- 管理服务费退款/取消核销负数按同一门店、同一费用方向优先抵扣账期最早的未开票正数账期；较早正数账期仍未开票时，后出现的负数也优先抵扣它，未抵扣完再向未来结转。
- 负数账期不创建管理服务费发票；累计净额 `<= 0` 时待开票显示 0。
- 管理服务费仍严格保持“一门店 + 一账期 = 一张当前有效发票”，不得为了抵扣改成跨账期发票。
- 后续正数账期的可开票金额为该账期有效确认金额加尚未消耗的负数结转；仅当结果 `> 0` 时允许导入或页面更正。
- 增加不可变结转应用审计，关联负数来源账单、被抵扣的正数账单、最终承载净额的当前有效管理费发票版本（可空）和实际抵扣金额；不得回改原账单或历史发票。
- 管理费导入、单店更正、列表和单月/累计指标必须调用同一后端结转投影；不得由前端计算。
- 发票或导入版本被更正/撤销后，旧结转应用退出当前投影但永久保留，重新按当前有效事实确定性计算并落审计。
- 本切片依赖 G0 先把已开票/锁定月后的退款或取消核销保存并顺延到后续账单；不得只扫描现有账单而漏掉 worker 已跳过的事件。

## Schema and migration rules

- 增加最小不可变实体/字段以表达 `SapSuggestion`、页面确认来源、反向批次/逐行覆盖链及管理费结转应用，并创建按依赖顺序排列、可逆、单头 Alembic migration。
- 不允许 destructive migration、数据删除、历史行原地覆盖或生产迁移。
- 金额始终使用整数分；时间使用带时区 UTC 存储并按现有 API 规范输出。

## Frontend contract

- `/finance/management` 提供单店更正表单、当前版本提示、冲突恢复和历史版本入口。
- `/finance/stores` 展示 SAP 建议/确认状态，支持门店建议入口和管理员确认/修正/驳回动作。
- `/finance/imports` 展示当前有效、覆盖/撤销关系；仅对可撤销批次显示撤销动作，要求原因和确认。
- 所有动作具备 loading、成功、失败、冲突和幂等重试反馈。

## TDD gates

1. 分 G2a/G2b/G2c/G2d 依次写 RED；每片先后端、再前端。
2. 覆盖权限、建议版本与确认版本、页面修改/导入竞争、逐业务键撤销冲突、版本、并发、幂等、历史保留、整批原子、当前指标退出/恢复及审计。
3. G2d 额外覆盖连续负数、跨多个正数、单期净额为零、已锁定月经 G0 顺延、导入/直接修改竞争、撤销后重新投影，并执行结转实体 migration 往返验证。
4. focused API GREEN 后运行 migration test、frontend contracts、build、visual/browser checks 和 `git diff --check`。

## Non-goals

- 不为管理服务费设计红冲、作废、替换或推广费厂家审核状态。
- 不允许 SAP 缺失阻断业务。
- 不进行生产迁移、部署、commit、push、reset、checkout 或全仓格式化。
- 不覆盖或回退并发改动。

## Required report

Return `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT` or `BLOCKED`, followed by changed files, exact red and green commands/results, self-review findings and remaining risks.
