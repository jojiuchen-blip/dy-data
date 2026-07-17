# Security Risk Rating Policy

## Risk Levels

- `Critical`：默认 `BLOCK`
- `High`：默认 `BLOCK`；只有已有明确书面 waiver 时才允许评估为 `WAIVER`
- `Medium`：默认不直接阻断，但必须给出整改时限、责任人和影响说明
- `Low`：记录即可，不单独阻断

## Escalation Rules

出现以下任一情况时，优先按 `BLOCK` 处理：

- 发现生产级密钥、证书私钥、数据库凭证泄漏
- 发现管理后台、调试接口、敏感管理端对外暴露
- 发现明确的认证绕过、越权或未授权访问路径
- 发现与 `OWASP Top 10`、`OWASP API Security Top 10` 或 `OWASP ASVS` 高风险控制项直接冲突的问题

## Decision Mapping

- `PASS`：无阻断项，且证据足以支持放行
- `BLOCK`：存在阻断项，或关键证据不足
- `WAIVER`：存在阻断项，但已有临时豁免批准且补偿措施清晰
