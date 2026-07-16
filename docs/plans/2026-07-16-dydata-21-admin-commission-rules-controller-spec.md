# DYDATA-21 管理后台分佣规则文档分支 Controller Spec

Status: Complete

Date: 2026-07-16

Controller: Codex main agent

Repo / workspace: `dy-data` isolated worktree

Branch / target: `codex/dydata-21-admin-commission-rules` -> `origin/codex/dydata-21-admin-commission-rules`

## 1. User Goal

创建一个不同于订单分佣页面开发线的独立管理后台规则分支，将当前对话确认的业务规则、非目标、验收标准和协作者启动提示提交并推送到 GitHub；不实现生产功能、不合并主线、不部署。

## 2. Current Evidence

| Area | Evidence | Source | Confidence | Notes |
|------|----------|--------|------------|-------|
| Main baseline | `origin/main` 为 `1d29178` | Git fetch / log | High | 新分支从最新远端主线创建 |
| Branch isolation | 原工作区有用户未跟踪文件 | Git status / worktree list | High | 使用独立干净 worktree，保留原工作区 |
| Existing behavior | 当前生产模型仍使用单一 `commission_rate` | models / schemas / tests | High | 双比例尚未实现 |
| Requirement source | 用户已确认术语、规则维度、销售总金额口径和迁移边界 | 当前对话 | High | 精诚养车初始比例暂不设置 |
| Linear mapping | DYDATA-21 为核心双比例上下文；批量导入需独立 issue | 本地协作记录 | Medium | 推送后仍需在线核验 Linear 当前正文 |

## 3. Scope

Included:

- 创建独立管理后台规则分支和隔离工作树。
- 提交管理后台双比例业务规格。
- 提交协作者拉取、实现、验证、PR 和 Linear 回填提示。
- 添加静态规格测试。
- 验证、提交、推送并核对远端 SHA。

Excluded:

- 生产 API、数据库、Worker、前端实现。
- 订单分佣页面视觉改动。
- 角色、账号和权限配置。
- 精诚养车初始双比例写入。
- 合并 `main`、部署或生产数据变更。

Scope control rule:

- 任何生产代码或业务数据变更必须在协作者读取 Linear、确认工单为 `In Progress` 后另行实施。

## 4. Assumptions and Open Questions

| ID | Item | Type | Owner | Resolution |
|----|------|------|-------|------------|
| A1 | 核心双比例规格归属 DYDATA-21 | Assumption | Controller | 由此前多次 DYDATA-21 讨论支持，协作者开发前在线核验 |
| Q1 | 批量导入独立 issue ID | Question | Linear owner | 推送后创建或关联独立 issue |
| Q2 | 批量模板是否包含 SKU_ID | Question | Product owner | 保持 `Needs Decision` |
| Q3 | 现有产品初始双比例和切换月份 | Question | Product owner | 不预设、不实施 |

## 5. Work Breakdown

| Task ID | Role | Owner | Responsibility | Write Set | Required Output | Acceptance Gate |
|---------|------|-------|----------------|-----------|-----------------|-----------------|
| T1 | Explorer | Controller | 审计仓库、分支和并发状态 | Read-only | 基线与风险 | 独立干净 worktree |
| T2 | Implementer | Controller | 写入控制规格、业务规格和静态测试 | docs / one test | 受控 diff | 无生产代码改动 |
| T3 | Spec Reviewer | Controller, separate phase | 对照用户确认内容检查范围 | Read-only | pass/fail | 无遗漏和越界 |
| T4 | Code Quality Reviewer | Controller, separate phase | 检查可执行性、歧义、秘密和路径 | Read-only | findings | 无阻断问题 |
| T5 | Verifier | Controller | 运行测试、构建和远端同步核验 | Read-only/build outputs | 结果与 SHA | 必需门槛通过 |

## 6. Review Plan

1. 完成文档与测试后进行规格复核。
2. 规格通过后进行质量与安全复核。
3. 只修复确认问题并重新复核。
4. Controller 运行最终验证并审查 staged diff。
5. 提交、推送并用远端 ref 核对 SHA。

## 7. Verification Plan

| Gate | Command / Method | Required For Done | Notes |
|------|------------------|-------------------|-------|
| Diff review | `git diff --check` + scoped diff | Yes | 不混入无关文件 |
| Focused test | `python -m pytest tests/test_admin_commission_rules_spec.py` | Yes | 保护关键决策 |
| Full tests | `python -m pytest` | Yes | 仓库标准门槛 |
| Web build | `npm --prefix apps/web run build` | Yes | 确认主线仍可构建 |
| Remote sync | push + fetch + `ls-remote` | Yes | 本地与远端 SHA 一致 |

验证结果：

- `git diff --check`：通过。
- `python -m pytest tests/test_admin_commission_rules_spec.py -q`：`2 passed`。
- `python -m pytest`：`479 passed, 40 warnings`。
- `npm --prefix apps/web run build`：安装锁定依赖后通过。
- `npm ci` 报告 1 个 low severity 依赖告警，未由本分支引入，不阻断文档分支交付。

## 8. Final Acceptance Checklist

- [x] 用户确认规则已落入规格。
- [x] 订单分佣、角色权限和生产代码未混入。
- [x] Spec review 通过。
- [x] Code quality review 通过。
- [x] Focused tests、完整测试和 Web build 通过。
- [x] staged diff 已审查且无秘密、本机路径或真实业务数据。
- [x] commit hash 已记录：`7ec7d876fc2cfb78b2dcd578e4131a1cc4c51052`。
- [x] 首次推送后远端分支与本地 SHA 一致。
- [x] 协作者提示词可直接粘贴到 Linear。

## 9. Decision Log

| Time | Decision | Reason | Evidence |
|------|----------|--------|----------|
| 2026-07-16 | 使用独立管理后台规则分支 | 避免与订单分佣页面开发线混杂 | 用户明确要求 |
| 2026-07-16 | 只提交规格，不提交生产实现 | 当前交付是对话规则和协作者交接 | 用户明确要求 |
| 2026-07-16 | 精诚养车初始双比例不预设 | 整体规则尚需确认 | 用户批注 |
| 2026-07-16 | 角色配置全部排除 | 角色权限在独立对话讨论 | 用户批注 |

## 10. Change Log

| Time | Change | Owner | Evidence |
|------|--------|-------|----------|
| 2026-07-16 | 创建控制规格 | Controller | 本文件 |
| 2026-07-16 | 完成规格、质量、完整测试和 Web 构建验证 | Controller | `479 passed`；Web build passed |
| 2026-07-16 | 提交并首次推送规则交接 | Controller | `7ec7d876fc2cfb78b2dcd578e4131a1cc4c51052`；本地、remote-tracking ref 与 `ls-remote` 一致 |
