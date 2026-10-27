# DYDATA-104：精确首次漏记费用修复

本工具承接已批准 T3.1 内普通合格漏记数据的处理。暂停22券、原106券、阜阳指定范围和受保护交易必须通过独立排除清单剔除。工具不自行筛选、不接受整月替代范围、不放宽预算，也不提供自动拆批、队列、恢复或重算兜底。

## 运维合同

入口：`scripts/ops/repair_missing_fees.py`。默认只预演，报告只写入忽略/未跟踪路径或仓库之外。默认路径在 `.tmp/missing-fee-repair/`，输出文件使用排他创建；重跑时可指定另一个私有输出文件。标准输出仅包含数量、摘要和报告路径，不输出业务ID或数据库连接串。

```text
python scripts/ops/repair_missing_fees.py --manifest <private-manifest.json> --exclusions <private-exclusions.json>
python scripts/ops/repair_missing_fees.py --manifest <private-manifest.json> --exclusions <private-exclusions.json> --apply <exact-preview-sha256> --output <new-private-report.json>
```

数据库连接沿用 `DY_DATABASE_URL` / `DATABASE_URL`。应用只允许 PostgreSQL。每次调用使用全新、干净的 session，函数拥有事务边界。私有清单与排除证据不提交 Git。

CLI 将业务拒绝、输入/输出文件错误、已提交后的报告错误和提交结果未知分别输出。业务拒绝退出2；输入/输出I/O失败退出3。应用函数成功返回后若报告写入或关闭失败，返回 `applied_but_report_failed`、`applied=true`、退出4；不能称为回滚。应用阶段数据库错误或提交响应丢失时，返回 `apply_outcome_unknown`、`applied=null`、退出5，不猜测提交结果。没有进入应用的数据库失败退出6。失败消息不包含驱动异常详情，提供确定性审计ID；必须先回读审计及真实费用再决定重试，工具从不自动重试。预演和应用都先校验完整输入，再创建私有报告或连接数据库。

清单合同：

```json
{
  "schema_version": 1,
  "request_id": "synthetic-reviewed-request",
  "approval_ref": "DYDATA-104/review-reference",
  "actor": "ops:authorized-operator",
  "coupons": [{
    "coupon_id": "synthetic-coupon",
    "order_id": "synthetic-order",
    "raw_coupon_id": 1,
    "raw_order_id": 1,
    "business_month": "2026-09",
    "expected_sale_store_id": "synthetic-sale-store",
    "expected_verify_store_id": "synthetic-verify-store",
    "verify_id": "synthetic-verify",
    "verify_time": "2026-09-05T02:00:00+00:00"
  }]
}
```

排除清单为 `schema_version: 1` 与 `groups`。`groups` 必须恰有 `paused22`、`cohort106`、`fuyang`、`protected` 四组；每组含 `coupon_ids` 文本数组、`count` 和 `sha256`。组摘要使用去重后的排序数组，经 UTF-8、`ensure_ascii=False`、排序键及紧凑 JSON 编码后计算 SHA-256；重复值直接拒绝，不能默默去重。四组可以相互重叠，任一组与目标清单交集都会拒绝整批。完整原文档的所有字段均进入请求摘要，不只绑定已知字段。

## 只读报价与依赖

`NewFeeQuote` 是冻结的类型化业务快照。正常结算函数新增显式 `quote_only=False` 参数；报价与默认写入共用费用算法。报价在首次账期锁定之前返回，不创建 DQ、不自动冻结10月起账号资格，不接纳已有任意方向/月/状态的费用历史或当前指针。前正式窗口或无费用结果的提前返回也会拒绝。

PostgreSQL 预演使用驱动事务选项取得 `REPEATABLE READ`、`READ ONLY`，可见 SQL 保持 SELECT-only。依赖摘要覆盖原订单、目标券及全部同订单/内部订单引用兄弟券、所有核销、原退款记录与退款事件、SKU和费率/范围版本、绑定/账号/POI/门店、历史销售归属裁决、费用/调整/顺延/账单来源历史及目标账期保护事实。Decimal 原始精度保留，不使用看板的来源摘要代替本工具依赖摘要。

## 应用与保护

固定预算为最多500券、锁等待1秒、单SQL最多5秒、完整事务30秒；预算参与预演摘要。SQL 超时进一步限制到剩余事务时间，预算不足整笔回滚。

应用强制 `READ COMMITTED`，先领取共享重任务 advisory transaction lock，拒绝 running/retry_wait 来源写任务。对相关原始来源、配置、保护和财务关系按名称排序取得写入栅栏，防止新增匹配或保护记录的幻读；再按券及账期排序加锁，重新完整报价和核对预演摘要。栅栏可能与正常业务写入冲突；1秒内取不到时停止，不提高预算。

任一历史费用、当前指针、调整、顺延或账单来源都拒绝；任一退款、取消或多个核销也拒绝。本版只支持2026年8/9月的准确核销账期。目标账期若存在历史账单但没有唯一当前版本、已确认/锁定/有方向确认、异议或发票事实，均拒绝；不存在当前账单时也检查独立异议/发票保护。

精确调用原 `rebuild_dual_fee_results(coupon_ids=..., force_recalculate=False)`，要求恰好 `2*N` 条费用、零调整、零阻断。对每条输出的全部业务字段、核销门店快照、版本/当前指针和 `input_fingerprint` 逐项回读。意外金额、快照、数量或其他财务变化都会整笔回滚。

目标外财务、SAP、管理费顺延、账单、票据、导入、聚合、所有 dashboard sidecar 关系和任务状态使用 PostgreSQL 内置 SHA-256 逐行/整表摘要核对；正常费用及指针的来源失效计数允许变化，其余来源计数在费用写入比较期间保持。成功操作审计使用 `FinanceOperationAudit`，与费用同一事务提交；其自身正常来源计数更新属于操作审计。工具不发布报表、不生成账单、不确认、不开票、不付款，不清除既有DQ。后续发布仍由原正式流程单独承接。

相同请求重放先校验原请求/完整排除清单/预算及原预演摘要，再核对真实费用与当前指针；不能用一次新预演绕过已有历史，也不会重复创建成功审计。失败事务不留下部分成功审计。

## 验证证据

- 初版只读、清单/排除校验、拒绝条件及共享默认写入验证：33 passed。
- 最终只读/清单/历史/拒绝/CLI验证：47 passed，零跳过（7.65秒，`unit.xml`）。包括真实合成费用已提交后的写入/关闭故障及提交响应丢失验证，确保不谎称回滚、不自动再次执行。默认写入及实收/历史下架回归：332 passed，明确排除下述两项已复现的基线失败。
- 初版真实 PostgreSQL 验证：32 passed、0 skipped，包含完整 Alembic 升级、正常提交回读/幂等、任意历史、保护事实、费率/来源/兄弟券漂移、写入比较/预算回滚、共享重任务锁、正在写入的来源和原始/配置/确认新增幻读栅栏。
- 新增事务特性、剩余时间限制及373券规模收据：真实 PostgreSQL 3 passed。373券样本附带100,000条无关已发布窄事实和10,000张无关账单；初次预演30.047秒触发预算，未进入应用，新增费用/审计/任务均为0。本数据来自隔离测试库，不能证明生产373券已完成。
- 显式50券样本使用同样100,000条发布事实和10,000张账单：首次应用30.016秒触发预算，零写入。发现预算监听器重复发送已生效的5秒超时设置后，仅去掉前25秒内的重复设置；最后5秒仍逐SQL限制到剩余时间。修订后预演3.610秒、应用11.687秒，100条费用/100条当前指针/零调整/一条审计/零任务；目标外SHA-256一致。剩余事务时间取消验证同时通过。数据均来自隔离测试库，运行负载变化仍可能触发正式预算拒绝。
- 扩展普通结算回归初次运行141 passed、2 failed。两个失败为 `test_locked_reverification_appends_delta_and_preserves_history[False-True]`、`[True-True]`，异常为 `ProtectedBillingAuthorityError: adjustment uses an unapproved replacement of a frozen fee basis`。将原 HEAD 的未修改 `settlement.py` 装入单独测试进程后，两项仍失败（2 failed / 3.93秒），已交由主线程另行处理，未在本写集修改保护账务。
- 修订后完整真实PG验证：38 passed、0 failed、0 errors、0 skipped，502.776秒，包含完整迁移及4种批量规模。运行证据位于本地忽略目录 `.tmp/missing-fee-verification/postgres.log` 和 `postgres.xml`。本轮未连接生产数据库。

最终规模收据均使用100,000条无关发布窄事实和10,000张无关账单：

| 明确请求券数 | 预演秒数 | 应用秒数 | 实际结果 |
|---|---:|---:|---|
| 10 | 1.031 | 5.375 | 20费用/20指针/零调整/一条审计/零任务，目标外摘要相同 |
| 20 | 1.687 | 6.703 | 40费用/40指针/零调整/一条审计/零任务，目标外摘要相同 |
| 50 | 3.844 | 13.000 | 100费用/100指针/零调整/一条审计/零任务，目标外摘要相同 |
| 373 | 26.719 | 30.031 | 应用语句预算拒绝，零费用/指针/调整/审计/任务新增 |

50券应用的分阶段实测：重新报价/完整依赖3.719秒、1783条可见SQL；目标外摘要分别1.250/1.171秒、各61条SQL；原精确写入器6.562秒、3005条SQL。373券应用重新报价耗28.719秒、13088条SQL，随后在目标外摘要阶段停止，未进入费用写入。SQL计数由测试监听器记录成功执行的 SQLAlchemy 语句，不包含驱动在最后5秒直接设置剩余超时的语句。性能证据不承诺生产延迟，也不放宽生产的1/5/30秒限制。

## 当前边界

本工作只实施和验证工具，未连接生产执行预演或应用，未部署、推送或发布。主线程提供的373券私有清单已离线通过结构、数量和排除交集校验；这不等于完成真实来源报价或允许绕过30秒预算。任何范围变化都需要重新形成准确清单和预演摘要。

主线程已决定不增加结算算法读取缓存，不为373券单事务放宽预算。可由主线程人工形成、逐份审阅和冻结至多50券的准确分区清单，每份独立预演、摘要、审计和事务；这是单独审阅的运维请求，工具不自动拆分或排程，也不承诺373券整体原子性。真实环境任一份预算不足仍必须停止。

本工具不新增持久化结构或公开业务API；本子任务无 foundation 漂移。当前 T3.1、Linear 状态和最终验收由主线程维护。
