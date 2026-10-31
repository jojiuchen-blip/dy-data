# 逾期账单自动确认与补偿扫描

来源：DYDATA-104 2026-10-30确认。上一完整自然月账单在次月6日结束后（Asia/Shanghai，7日00:00起）按方向确认。晚生成、失败恢复和重新发布不重新开启确认窗口。

## 首次启用

`BILLING_AUTO_CONFIRM_ENABLED` 默认 `false`。首次部署不会自动确认历史待修账单。生产负责人先完成既有补费/发布、核对逐方向预演和必要的精确暂停项，再显式启用该配置；不以部署成功代表账单已确认。

worker通过既有队列调度入口执行有界补偿：每批最多50张当前账单、一个工作预算；同小时按游标继续，扫描完后下小时重新从头检查晚生成账单。成功任务记录处理统计及阻断原因；失败留任务记录并退避5分钟。源采集/重建在途、资源保护仍优先，不在页面GET或导出时确认。

## 默认只读预演

在目标运行代码环境中，使用私有且未存在的报告路径：

```bash
python scripts/ops/confirm_overdue_statements.py --month 2026-09 --limit 50 --report /private/receipts/confirmation-preview-001.json
```

可用 `--store-id` 限定精确门店，月份/门店参数可重复。省略月份即盘点正式窗口内全部当前账单。`has_more=true` 时使用报告的 `next_after_id` 作为下一批 `--after-id`，不能把单页当全量完成。

每行包含门店、账期、账单ID/版本、方向、分金额、截止时间、已有确认来源/时间及 `candidate/already_confirmed/not_due/blocked`。`scheduler_enabled` 是本进程的实际配置状态。报告含业务ID，禁止提交Git或贴到公共日志。

`statement_amount_cent` 保留原账单净额，`amount_cent` 是与人工确认共用的正式可确认额：推广费保留负值用于结转，管理费扣除冻结异议后最低为0。不能将负管理费账单净额直接写成负确认额。

## 精确补执行

```bash
python scripts/ops/confirm_overdue_statements.py --month 2026-09 --limit 50 --apply --expected-hash REVIEWED_SHA256 --report /private/receipts/confirmation-apply-001.json
```

所有筛选、游标和批大小必须与预演一致。写入前获取共享任务认领锁、当前发布指针、门店账期锁和账单行锁，重新核对当前版本、来源及保护事实；预演变动整批拒绝。每方向确认和财务审计原子提交，不创建发票、不登记付款、不更改费用或原确认。相同批hash重放返回原批已完成标志、本次新增数0，不重复确认。

正常检查包括：完整逐日来源及10月起冻结资格；当前月度发布的原始/调整/净额与账单一致；来源项精确集合和金额一致；来源完成时间不晚于该月实际数据发布。未知旧发布、版本差异、在途重建/采集、锁账、争议和票据事实均返回明确阻断。没有费用的缺失券不能仅靠账单集合检查证明完整，既有人工核查事项必须先保留暂停并完成修复。

确认、争议、最新暂停和票据按批次预取；月来源、发布owner及完成证据按月复用。精确slot的分录和经济来源各只执行一次批次查询，流式读取且每组最多50,000行，超限整批拒绝而不截断为完整。单SQL最长5秒、锁等待最长3秒，若连接已有更小限制则保留；整批30秒墙钟预算包含比较、flush和提交前检查，后段SQL下推剩余预算。预演也使用相同只读预算（PostgreSQL会执行仅事务内的超时设置，不写业务表）。

最终flush之后，在剩余SQL预算内执行 `SET CONSTRAINTS ALL IMMEDIATE`，使延迟约束/触发器在可超时的SQL阶段执行；不能仅设置COMMIT前的 `statement_timeout`，该设置不足以约束提交阶段的延迟动作。随后核对预算和无待写ORM对象并封闭后续SQL/flush，再提交。此封闭保护提交期新写入，不声称是对最终flush中所有直接SQL写入的独立写集后验。

本店在overlay分区无汇总行并不自动等于0：仅在全部账单原始/调整/净额皆0、分录和权威来源皆空，且正式生成审计的来源摘要恰为空集时，按合法零账单处理；非零或缺证继续拒绝。

## 精确审核暂停项

`apps.worker.billing_auto_confirmation.set_confirmation_hold` 是仅供授权运维调用的正式事务服务。参数为准确 `store_id/month/direction`、`active`、理由、证据引用、操作者和幂等请求键；调用者负责授权及提交。新增和解除均追加 `FinanceOperationAudit` 的 `BILLING_CONFIRMATION_HOLD` 事件，不向来源质量问题表写伪异常，不修改历史事件；重建和自动扫描都不会解除。解除须显式调用同一服务的 `active=False` 并提供理由和证据，不能无范围给全库设置暂停。

## 开票金额读取

开票页面显式URL账期优先，否则使用上海上一完整自然月。先读取该账期响应中服务端计算的完整开票汇总，再按 `requiredStatementIds` 获取必要成员并校验同店、当前版本、确认和抵扣组。与开票组无关的历史账期读取失败不再牵连；必要成员缺失、越权或组变化则清空金额并阻止提交。含税、不含税和税额只渲染服务器分币结果，真实零、待确认、无账单和读取失败分别说明。

## 验证边界

本文件描述实现及操作合同，不证明已在生产执行。严格PG并发测试为 `tests/test_billing_auto_confirmation_postgres.py`，使用已有独立测试库/临时schema；实际开票浏览器测试为 `tests/test_dydata104_oct30_invoice_browser.py`。生产逐笔预演、补执行、配置启用及页面/导出回读由唯一生产负责人分别留证。
