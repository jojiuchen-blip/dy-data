# DYDATA-23 门店结算看板视觉规范 Controller Spec

Status: Ready for finalization
Date: 2026-07-15
Controller: Codex main agent
Repo / workspace: repository root
Branch / target: `codex/dydata-23-store-dashboard` -> `origin/main`

## 1. User Goal

将用户已逐条确认的门店结算看板视觉规范迁入正式仓库；基于 `b61f456` 最新主线完成验证、提交、推送并合并，不使用 `reset --hard` 或强制推送。

## 2. Current Evidence

| Area | Evidence | Source | Confidence | Notes |
|------|----------|--------|------------|-------|
| Requirement | DYDATA-23 为 High / In Progress，范围与验收标准已确认 | Linear `DYDATA-23` | High | 用户已明确“确认，请提交” |
| Main baseline | `origin/main` 为 `b61f456` | `git fetch origin`; `git show b61f456` | High | 与用户给定基线一致 |
| Integration | 本地 `main` 已执行 `git merge origin/main` 并 fast-forward 到 `b61f456` | Git 命令输出 / reflog | High | 合并前工作树干净，无需 commit/stash |
| Branch | 已从最新主线创建 `codex/dydata-23-store-dashboard` | `git status --short --branch` | High | 不直接在 main 开发 |
| Reviewed source | 临时原型已通过浏览器批注与 Design QA | 当前任务的隔离评审原型 | High | 原型继续作为视觉真相 |
| Production limits | 当前正式 API 不具备所有累计和五项门店指标口径 | 现有前端类型、页面与 DYDATA-23 不做项 | High | 本 issue 不扩展生产 API/数据库 |

## 3. Scope

Included:

- 在仓库文档区域落地可审阅、可交互的四页门店结算视觉规范。
- 四个同级页面：全国门店榜单、单店分账、订单费用明细、开票确认。
- 日期范围、产品范围、商品类型、门店搜索、排名依据等已确认筛选与文案。
- 当月/累计占位、厂端激励推广费术语、两类费用订单明细、开票五节点流程。
- 添加结构性自动化测试，防止关键导航、术语、累计起点和开票范围回退。
- 记录验证证据，提交、推送并远端同步。

Excluded:

- 生产 API、数据库、累计计算、历史回填和真实财务操作。
- 发票字段、税额校验、红冲/重开、财务角色看板。
- 与 DYDATA-23 无关的前端重构或设计系统改造。

Scope control rule:

- 任何需要新增后端字段、改数据库或改变现有生产路由语义的工作，必须拆分到后续 issue，不在本分支顺带实现。

## 4. Assumptions and Open Questions

| ID | Item | Type | Owner | Resolution |
|----|------|------|-------|------------|
| A1 | 本次“提交”指已确认视觉规范，不代表立即接入生产数据 | Assumption | Controller | 由 DYDATA-23 的不做项和此前讨论确认 |
| A2 | 仓库说明中的示例路径与当前 clone 不一致 | Assumption | Controller | 以 `git rev-parse --show-toplevel` 返回的仓库根目录为准 |
| A3 | 推送后是否直接合并 main 取决于远端分支保护与可用工具 | Question | Controller | 先推送并核对；可直接安全合并则完成，否则创建合并请求并报告 |

## 5. Work Breakdown

| Task ID | Role | Owner | Responsibility | Write Set | Required Output | Acceptance Gate |
|---------|------|-------|----------------|-----------|-----------------|-----------------|
| T1 | Explorer | repo_state_audit | 仓库、分支、并发与远端状态审计 | Read-only | 命令、状态、风险 | 唯一工作树且无未提交改动 |
| T2 | Explorer / Spec Reviewer | integration_map | 比对临时原型、正式代码与现有规范 | Read-only | 最小迁移清单 | 不扩展生产 API/数据库 |
| T3 | Implementer | Controller | 落地视觉规范与结构性测试 | 仅本 spec 列出的 docs/tests 文件 | 变更与自审 | 关键需求均有静态证据与测试 |
| T4 | Spec Reviewer | integration_map | 复核 diff 是否满足 DYDATA-23 | Read-only | 通过/缺项 | 无缺失、无额外范围 |
| T5 | Code Quality Reviewer / Verifier | repo_state_audit | 测试、可维护性与远端就绪度 | Read-only | findings / gate 结果 | 无阻断发现 |

## 6. Subagent Task Packets

### T1: 仓库状态审计

Role: Explorer

- 只读检查分支、worktree、未提交改动、远端差异、锁与并发风险。
- 不切换分支、不拉取、不提交、不推送。
- 输出检查命令、证据、风险和安全 finalization 建议。

### T2 / T4: 迁移映射与规格复核

Role: Explorer / Spec Reviewer

- 对比已确认原型与最新主线的结算页面、路由、样式和测试。
- 确认本 issue 应落入文档视觉规范，不扩展生产数据契约。
- 实现后复核每条验收标准与 diff，报告缺项或越界。

### T5: 独立质量与验证

Role: Code Quality Reviewer / Verifier

- 只读审查 scoped diff。
- 运行结构测试、完整 pytest、Web 构建及必要的静态/浏览器检查。
- 将产品失败与环境失败分开报告。

## 7. Review Plan

1. Controller 完成最小实现和自审。
2. Spec reviewer 逐条对照 DYDATA-23。
3. Code reviewer 检查回归、维护性、测试和集成风险。
4. 仅修复已确认问题，并重新执行对应复核。
5. 无开放 P0/P1/P2 或规格缺项后进入 finalization。

## 8. Verification Plan

| Gate | Command / Method | Owner | Required For Done | Notes |
|------|------------------|-------|-------------------|-------|
| Diff review | `git diff --check` + scoped diff | Controller | Yes | 不混入无关改动 |
| Focused tests | `python -m pytest tests/test_commission_dashboard_navigation_mock.py` | Controller | Yes | 关键导航、术语、状态 |
| Full tests | `python -m pytest` | Controller / Verifier | Yes | 项目常规门槛 |
| Web build | `npm --prefix apps/web run build` | Controller / Verifier | Yes | 最新 main 前端可构建 |
| Visual/static check | 浏览器打开文档 mock；检查四路由、筛选、下钻和控制台 | Controller | Yes | 使用已确认原型作视觉真相 |
| Remote sync | fetch、push、remote ref/commit comparison | Controller | Yes | 禁止 force push |

## 9. Final Acceptance Checklist

- [x] 用户目标满足。
- [x] 范围和不做项保持。
- [x] 所有只读审计和 reviewer 输出已复核。
- [x] Spec review 通过。
- [x] Code quality review 通过或剩余风险已接受。
- [x] `git diff --check`、focused tests、完整 pytest、Web build 通过。
- [x] 浏览器静态/交互检查通过。
- [x] diff 无无关文件、无秘密或本机路径泄露。
- [ ] commit hash 已记录。
- [ ] push 和远端同步已确认。
- [ ] Linear 已回填验证与链接。

## 10. Decision Log

| Time | Decision | Reason | Evidence |
|------|----------|--------|----------|
| 2026-07-15 17:12 +08:00 | 合并前无需 commit/stash | 工作树干净 | `git status --short --branch` |
| 2026-07-15 17:12 +08:00 | 先 fast-forward 本地 main，再创建 issue 分支 | 远端 main 已到用户指定 `b61f456` | `git fetch origin`; `git merge origin/main` |
| 2026-07-15 17:16 +08:00 | 本 issue 落地视觉规范与测试，不直接补生产数据契约 | DYDATA-23 明确不做生产 API/数据库 | Linear issue + 当前代码检查 |
| 2026-07-15 17:37 +08:00 | 畸形月份参数按选项值枚举匹配，不拼接 CSS selector | 保持深链健壮性并避免初始化中断 | 回归测试覆盖 `%22%5D` 输入 |

## 11. Change Log

| Time | Change | Owner | Evidence |
|------|--------|-------|----------|
| 2026-07-15 17:16 +08:00 | 创建 controller spec，进入实现前受控状态 | Controller | 本文件 |
| 2026-07-15 17:38 +08:00 | 四页视觉规范、V0.2 导航、结构与交互回归完成 | Controller | focused `35 passed`；完整套件 `473 passed`，末次暂态失败项复跑 `2 passed`；Web build 通过 |
