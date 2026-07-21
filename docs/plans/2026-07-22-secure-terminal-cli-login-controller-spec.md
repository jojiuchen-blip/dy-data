# 安全终端 CLI 登录控制器规范

## Goal

在 `feat/cli-terminal-login` 隔离分支完成 DYDATA-40 的安全终端登录增量，主 Agent 保留实现与最终验证所有权，子代理仅承担边界清晰的只读审查。

## Shared context

- Worktree：`C:\Own Docm\Coding\抖音结算中心\dy-data\.worktrees\cli-terminal-login`
- Authority：`docs/plans/delivery-plans/main-delivery-plan-dydata-40-secure-terminal-login.md`
- Design：`docs/superpowers/specs/2026-07-22-secure-terminal-cli-login-design.md`
- Baseline：目标 CLI/API 测试 156 passed。
- 禁止：真实凭据、部署、推送、合并、修改根工作树、通用 HTTP/脚本入口。

## Ownership map

| Work package | Owner | Write scope | Deliverable |
|---|---|---|---|
| T1.1-T1.3 实装 | 主 Agent | 计划列出的实现/测试/文档 | TDD commits |
| Spec review | 子代理 A | 只读 | 按设计逐条列出缺口，含文件/行号/严重度 |
| Code/security review | 子代理 B | 只读 | 泄漏、Cookie 隔离、TTY、CAS、错误映射审查 |
| Final verification | 主 Agent | devlog、计划 Evidence | 新鲜命令证据与最终结论 |

## Interface contracts

- 子代理不得修改共享文件；发现问题后只发报告，由主 Agent修复。
- 每条发现必须包含：严重度、可复现路径、违反的设计条款、建议修复方向。
- “通过”必须说明实际检查过的文件和测试，不接受泛化结论。
- 主 Agent 在两轮审查之间完成修复和目标回归，防止第二轮基于过时 diff。

## Test matrix

| Boundary | Required proof |
|---|---|
| TTY | 非 TTY 在输入和网络前失败；默认路径只接受交互 TTY |
| Secret | password/Cookie/token 不在 stdout、异常、repr、文档或 diff |
| Identity | username/role/store scope 严格验证并由用户确认 |
| Session | login 与 approve 同 Cookie；退出时清 Cookie、close |
| Credential | 已有状态 no-op；CAS 竞态不覆盖；失败令牌尽力撤销 |
| Compatibility | `--browser` 原流程、业务只读命令、全量 API/Web 无回归 |

## Completion protocol

1. 子代理 A 给出规格审查；主 Agent 修复并验证。
2. 子代理 B 给出质量/安全审查；主 Agent 修复并验证。
3. 主 Agent 完成所有新鲜验证、计划三处同步、devlog 与 Linear 评论。
4. 未经用户新授权，只交付分支与验证结果，不部署、不推送、不合并。

