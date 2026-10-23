# 商品规则受控补录

`scripts/settlement_rule_patch.py` 用于已授权运维的有界规则补录，不属于面向用户的只读 CLI/Agent 渠道。它只修改已知SKU的产品类型并新增缺失费率版本；不创建商品、不改变平台上下架或归属、不排重算、不确认账单或登记发票。

输入是非空JSON数组，每项仅含 `sku_id`、`product_id`、`product_type`、`promotion_rate`、`management_rate`、`effective_date`。ID必须为字符串，费率是0至1且最多六位小数，日期为上海自然日。输入及报告必须位于Git之外或被忽略且未跟踪，报告路径必须不存在。

```powershell
python scripts/settlement_rule_patch.py --input tmp/rules.json --report tmp/rules-preview.json --source-digest <附件SHA256> --actor ops:codex:DYDATA-104 --change-reason <已批准的变更理由> --idempotency-key <固定批次键>
```

默认只预演。逐项审阅产品ID、分类前后值、保留scope/service、费率与生效日。未知SKU、产品ID不符或已有同日期规则冲突会阻断整批，不自动部分执行。要缩小范围必须另建明确的子集输入及固定批次键，重新预演，不能将子集成功宣称为全量完成。

应用在相同参数下增加 `--apply --fingerprint <预演指纹>` 并指定新的报告路径。指纹覆盖请求、目标商品全列和全部现有规则；并发变化须重新审阅。PostgreSQL应用获取共享heavy锁、规则表写入互斥锁及商品行锁；运行中或等待重试的来源writer会阻止执行。保持短事务，不在数据库事务内请求外部平台。

已有同日期ACTIVE且双费率相同的规则保持NOOP，包括旧分类快照；仅catalog产品类型按输入更新。不同日期旧版本、确认、发票与锁账事实不修改。自动化身份使用显式 `ops:` 前缀；个人身份必须是真实有效全局管理员。当前临时复用 `AccountPermissionAuditLog` 结构化审计载体，action固定为 `SETTLEMENT_RULE_PATCH`，记录真实ops角色和完整前后快照，不修改账号权限。规则、分类和审计原子提交，重复同键同载荷返回历史结果，不重复写入。

应用后先读回分类、规则和审计，再按既有恢复/重建流程分别预演账期；不通过新root、新幂等身份或重置次数规避恢复预算。历史下架商品的时间口径、缺失档案及受保护账单须先有明确处理依据。对账方法见[离线结算基准解析与对账](../api/settlement-reconciliation.md)。
