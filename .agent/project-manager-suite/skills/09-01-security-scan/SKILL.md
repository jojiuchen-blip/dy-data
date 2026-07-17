---
name: security-scan
description: Use when the user is preparing to finalize a project, asking whether the project is safe to wrap up, requesting a completion-time security gate, or needing a fixed PASS/BLOCK/WAIVER decision before declaring the project done. Use this whenever the request mentions 完工、落地放行、安全闸门、go-live (if applicable)、release blocking, or final security checks, even if the user only explicitly mentions dependencies, secrets, or code-level risks. Default scope focuses on code security + secrets + dependencies + input validation (internal-tool oriented).
---

# Security Scan

## Overview

把"完成前安全扫描"变成固定结构的闸门，而不是开放式安全顾问。这个 skill 的核心价值是稳定触发、稳定输出、稳定判定，避免在真正交付前出现"没扫就放行"或"每次回答口径都不一样"的情况。本套包默认场景为内部 / 本机工具，scan 范围聚焦应用代码 + 依赖 + 敏感信息 + 输入校验四维；不预设公开部署 / 多用户 / 云配置维度。

## Gate Rule

命中以下任一条件时，默认进入本 skill：

- 用户要求完成、落地、go-live（如适用）、放行交付
- 用户要求判断"能不能完工"
- 用户要求做完工前 security gate
- 用户要求做最终安全检查、最终安全放行、release blocking check

命中后先读取 [references/gate-contract.md](references/gate-contract.md)。

如果请求只是开发期的一般性安全讨论、代码风格、功能设计、任务拆解，不要抢占其他 skill。

## Fixed Inputs

优先读取以下输入材料：

- 当前执行计划与完成标准
- 本轮代码、配置、依赖、文档变更
- 测试报告与验收材料
- 部署配置、环境变量清单、镜像或制品信息
- （如适用）对外暴露的域名、端口、入口地址 —— 默认为内部 / 本机工具，无此输入则跳过对应维度

如果部分材料缺失，可以继续扫描，但必须在最终报告里写明“输入证据缺口”，不得假装已完成全量扫描。

## Workflow

1. 判断当前是否为完工 / 交付前场景。
2. 读取 [references/scan-scope.md](references/scan-scope.md) 作为默认扫描范围。
3. 读取 [references/risk-rating-policy.md](references/risk-rating-policy.md) 作为分级与放行规则。
4. 需要给出权威依据时，读取 [references/standards-map.md](references/standards-map.md)。
5. 按 [references/report-template.md](references/report-template.md) 输出固定报告。
6. 若存在豁免，按 [references/waiver-template.md](references/waiver-template.md) 记录。

## Non-Negotiables

- 未完成扫描前，不得直接给出"可完工"结论。
- 不得把单维度扫描当作全部安全扫描；如果只扫描部分域，必须明确标注为局部扫描。
- 不得用模糊措辞替代放行结论；最终结论只能是 `PASS`、`BLOCK` 或 `WAIVER`。
- 不得口头 waiver；只要放行依赖豁免，就必须写出责任人、理由、失效日期和临时缓解措施。
- 遇到 `Critical` 风险、已知在野利用、或密钥泄漏时，默认判定为 `BLOCK`，除非已有书面 waiver 且你已在报告中明确引用。

## Report Structure

始终使用 [references/report-template.md](references/report-template.md) 的固定结构，不增删核心章节。

扫描报告必须落盘到 `<host>/docs/security/`（宿主项目文档目录下的安全报告目录，不存在则先创建），不得只停留在对话里。

如果本轮仅为局部扫描，也要保留完整章节，并在 `扫描范围` 和 `输入证据` 里写清楚缩减原因。

## Decision Logic

- `PASS`：未发现阻断项，且输入证据足以支持本轮放行判断。
- `BLOCK`：存在阻断级风险、证据严重不足、或关键检查项无法确认。
- `WAIVER`：存在本应阻断的风险，但已有明确批准的临时豁免记录。

当你输出 `WAIVER` 时，必须同时说明：

- 哪些风险本应阻断
- 由谁承担豁免责任
- 豁免何时失效
- 完工后需要补做什么

## References

- Gate contract: [references/gate-contract.md](references/gate-contract.md)
- Scan scope: [references/scan-scope.md](references/scan-scope.md)
- Standards map: [references/standards-map.md](references/standards-map.md)
- Risk rating: [references/risk-rating-policy.md](references/risk-rating-policy.md)
- Report template: [references/report-template.md](references/report-template.md)
- Waiver template: [references/waiver-template.md](references/waiver-template.md)
