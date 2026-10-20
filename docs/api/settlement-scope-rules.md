# 结算范围持续生效规则

DYDATA-104，用户于 2026-10-20 确认。范围规则决定商品归属账号和销售渠道是否参与结算，费率、核销时间、金额计算及门店归属继续沿用各自规则。

## 生效与历史保护

- 每个 `ownerAccountId + saleChannel` 有独立时间线。从业务月向前寻找最新的生效月，先选版本再判断是否启用。
- 例如八月启用直播、十一月停用直播：八至十月沿用八月版本，十一月起停用。十二月新建启用版本后恢复。不能跳过停用记录退回八月启用，也不将八月规则逐月复制。
- 新规则只改变明确提交的渠道。未提交的账号、渠道保持其原时间线；未来生效的版本不提前使用。
- 同一生效月、账号、渠道只能有一个版本，不原地改写已有版本。历史已确认、锁定或关联确认及开票事实的账单，继续由原有账单和费用保护机制阻止追溯替换。
- 无规则、最新规则停用和没有费用结果是三种不同事实。费用阻断证据记录 `scope_state=unconfigured/disabled`；零条费用结果不能单凭范围规则推断为合法零金额账单。

## 管理接口

`POST /api/v1/admin/settlement-scope-rules` 要求超级管理员、既有请求鉴权和 `Idempotency-Key`。在已有字段上增加可选的 `isActive`，默认 `true`：

```json
{
  "effectiveMonth": "2026-11",
  "ownerAccountId": "example-product-owner",
  "allowedSaleChannels": ["LIVE"],
  "isActive": false,
  "changeReason": "从十一月起停止该账号的直播渠道结算"
}
```

`allowedSaleChannels` 保持原字段名，表示本次变更涉及的渠道；停用请求只影响所列渠道。响应继续包含 `scopeRuleVersions`、`effectiveMonth`、`ownerAccountId`、`allowedSaleChannels`，并返回 `isActive`。

缺省 `isActive` 和显式 `true` 保持相同语义，兼容已存旧请求的幂等指纹。`false` 是不同请求；复用同一幂等键切换启停返回冲突，不覆盖原记录。配置写入继续沿用既有可审计重建队列与保护机制，不确认账单、不自动付款。

`GET /api/v1/admin/settlement-scope-rules` 是规则版本列表。其 `effectiveMonth` 仍精确筛选记录的生效月，不能将该列表筛选解释成“该业务月全部生效规则”。业务计算使用持续生效解析器。

## 发布与验证边界

此次无需表结构迁移或逐月回填规则；匹配语义随代码发布生效。回滚读取代码可恢复旧的精确月匹配，但不得为回滚删除规则、费用或账单版本。开发验证与生产上线状态分别记录在 [DYDATA-104 开发日志](../devlog/20261020_dydata-104-followthrough.md)。

自然月自动结算仅生成上一月的待确认账单。来源未完整、费用结果缺失或资源不满足时保持明确的阻断状态；确认、开票和付款由人操作。
