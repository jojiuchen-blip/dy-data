# Security Scan Gate Contract

## Purpose

`security-scan` 是完工 / 交付前的固定安全闸门，不是开放式安全建议器。本套包默认场景为内部 / 本机工具。

## Mandatory Triggers

出现以下任一表达时，默认触发本 skill：

- 完成 / 完工 / 落地
- 完工放行
- go-live（如适用）
- release blocking
- 最终安全检查
- 能不能完工 / 能不能交付

## Default Scan Mode

- 默认模式：`full`
- 默认覆盖：`code + secrets + dependencies + api-input-validation`

> v2.0.0 删除原默认覆盖中的 `network + authz + config + ci/cd` 四维——本套包默认场景为内部 / 本机工具，不预设公开部署、多用户授权、云配置加固、CI/CD 公开发布面。
> 如果宿主项目实际确实对外暴露或多用户部署，由用户在执行 security-scan 时显式声明，再额外触发对应维度（按 `scan-scope.md` 原历史维度列表）。

如果用户明确要求只看某一部分，可以降级为局部扫描，但必须在报告中标记为 `partial`。

## Allowed Final Decisions

最终结论只能是以下三种之一：

- `PASS`
- `BLOCK`
- `WAIVER`

## Hard Stops

- 未完成扫描前，不得给出"可完工"结论。
- 未写明输入证据缺口时，不得假装已完成全量扫描。
- 存在 `Critical` 风险、密钥泄漏、或已知在野利用风险时，默认不得放行。
