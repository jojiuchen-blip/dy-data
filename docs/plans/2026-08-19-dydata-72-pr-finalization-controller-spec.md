# DYDATA-72 PR Finalization Controller Spec

Status: Active
Date: 2026-08-19
Controller: Codex main agent
Repo / workspace: dy-data / `.worktrees/dydata-72-product-types`
Branch / target: `codex/dydata-72-product-types` -> `main` (PR #9)

## 1. User Goal

修复 PR #9 已确认的审查问题，完成独立复审和全量验证，合并 PR #9；随后基于更新后的主分支复核并合并 PR #8。PR #7 只做范围决策和 Linear 回填，不在本任务中改造财务原型。

## 2. Current Evidence

| Area | Evidence | Source | Confidence | Notes |
|---|---|---|---|---|
| Requirement | SKU 更新需要并发版本校验，列表按最近修改时间倒序 | Linear DYDATA-72 | High | Issue 处于 In Progress，Owner 已确认继续开发 |
| API | 单条更新未携带/校验版本 | `apps/api/dy_api/schemas.py`, `apps/api/dy_api/routes/fee_admin.py` | High | 需要前后端契约同步 |
| Query | 当前同状态按 `sku_id` 排序 | `apps/api/dy_api/routes/fee_admin.py` | High | 与验收口径不一致 |
| Database | 商品口径导入行未关联导入批次外键 | model + `20260813_0030` migration | High | PR 尚未合并/部署，可在原迁移中修正 |
| Governance | S4/T4.1 上下文、环境和计划一致性检查通过 | suite scripts | High | 以发布核验任务承接审查修复 |

## 3. Scope

Included:
- 单条 SKU 更新增加基于 `manualModifiedAt` 的乐观并发校验，冲突返回稳定 409。
- 前端单条设置提交当前版本；刷新后继续使用服务端新版本。
- 待完善列表保持“未配置 -> 部分配置”，同状态按最近修改时间倒序；已配置列表按最近修改时间倒序。
- 商品口径导入行对批次增加 `ON DELETE CASCADE` 外键，并验证模型/迁移一致。
- 目标测试、全量 pytest、Web build、diff check、独立代码复审、提交、推送和远端同步。

Excluded:
- 不扩张为批量更新版本协议重构。
- 不修改分佣规则、结算计算、生产数据库或部署配置。
- 不清理其他工作树或用户未提交文件。
- 不在 PR #7 中修改代码。

Scope control rule:
- 若修复要求改变 DYDATA-72 已确认业务口径、历史迁移策略或生产发布范围，停止并回到用户/Linear 决策。

## 4. Assumptions and Open Questions

| ID | Item | Type | Owner | Resolution |
|---|---|---|---|---|
| A1 | `manualModifiedAt` 可作为单条人工更新的版本令牌 | Assumption | Controller | 客户端使用列表返回值原样提交；空值表示从未人工修改 |
| A2 | `20260813_0030` 尚未生产执行 | Assumption | Controller | Linear/PR 边界明确未部署、未执行生产迁移 |

## 5. Work Breakdown

| Task ID | Role | Owner | Responsibility | Write Set | Required Output | Acceptance Gate |
|---|---|---|---|---|---|---|
| T1 | Implementer | Controller | 并发校验与前端契约 | schemas/routes/types/page/tests | 红灯、最小实现、绿灯证据 | 旧版本更新 409，当前版本成功 |
| T2 | Implementer | Controller | 列表排序 | route/tests | 红灯、最小实现、绿灯证据 | 两种列表顺序符合 Linear |
| T3 | Implementer | Controller | 导入行外键 | model/migration/tests | 红灯、最小实现、绿灯证据 | 外键目标与级联策略一致 |
| T4 | Spec Reviewer | Independent agent | 验收范围检查 | Read-only | 缺失/越界项 | 无阻断范围问题 |
| T5 | Code Reviewer | Independent agent | 质量与回归检查 | Read-only | 分级 findings | 无 Critical/Important |
| T6 | Verifier | Controller | 完整门禁与远端同步 | None | 命令、退出码、提交/远端 SHA | 所有必需门禁通过 |

## 6. Subagent Task Packets

### T4/T5: PR #9 Final Review

Role: Spec Reviewer and Code Quality Reviewer

Context:
- 对 PR #9 的审查修复做只读复审，确认实现满足 DYDATA-72 且没有引入数据正确性回归。

Ownership:
- 只读检查本分支相对 `origin/main` 的 diff、相关测试和迁移。

Non-goals:
- 不编辑文件、不切换分支、不提交或合并。

Required output:
- 文件与 git range；命令和结果；按 Critical/Important/Minor 排序的 findings；明确 merge verdict。

Acceptance gate:
- Spec compliance 通过；无未处理的 Critical/Important。

## 7. Review Plan

1. 每项改动完成红灯、最小实现和目标绿灯。
2. Controller 自审 scoped diff。
3. 独立 agent 先做规格符合性，再做代码质量审查。
4. 发现有效问题时只做最小修复，并重跑目标测试和复审。

## 8. Verification Plan

| Gate | Command / Method | Owner | Required For Done | Notes |
|---|---|---|---|---|
| Diff | `git diff --check` + scoped diff | Controller | Yes | 排除无关文件 |
| Target tests | `python -m pytest tests/test_api_fee_admin.py -q` | Controller | Yes | API、排序、并发、外键 |
| Full tests | `python -m pytest -q` | Controller | Yes | 合并前新鲜运行 |
| Web build | `npm --prefix apps/web run build` | Controller | Yes | TypeScript 契约 |
| Migration | 空 SQLite `alembic upgrade head` + 结构核验 | Controller | Yes | 不接触生产库 |
| Remote sync | push 后核对远端 SHA；合并后核对 `origin/main` | Controller | Yes | 不以本地状态代替远端状态 |

## 9. Final Acceptance Checklist

- [ ] 三项审查问题均有红灯和绿灯证据。
- [ ] 前后端契约一致，旧版本冲突不会覆盖新数据。
- [ ] 列表排序满足 DYDATA-72。
- [ ] 模型与迁移的导入行外键一致。
- [ ] 独立规格与代码复审通过。
- [ ] 目标测试、全量测试、Web build、迁移和 diff check 通过。
- [ ] PR #9 提交、推送、合并及远端 main 同步已核验。
- [ ] PR #8 在新 main 上重新验证后再合并。
- [ ] Linear 回填包含命令、SHA、合并结果与剩余风险。

## 10. Decision Log

| Time | Decision | Reason | Evidence |
|---|---|---|---|
| 2026-08-19 | 以 T4.1 发布核验任务承接 PR 审查修复 | 正式计划当前唯一活动任务为 T4.1，且一致性/上下文检查通过 | suite check outputs |
| 2026-08-19 | 不在本轮重构批量更新版本协议 | 审查阻断针对单条 SKU 更新契约；控制修复范围 | DYDATA-72 + code review |

## 11. Change Log

| Time | Change | Owner | Evidence |
|---|---|---|---|
| 2026-08-19 | 建立 PR #9 -> PR #8 顺序交付控制规范 | Controller | 用户明确确认执行 |
| 2026-08-19 | 完成 PR #9 审查修复、独立复审与合并前门禁 | Controller + Independent reviewer | 61 scoped tests passed；1185 passed, 2 skipped；Web build passed；diff check passed；review verdict Yes |

## 12. Pre-Merge Verification Evidence

- 三项审核问题均先由失败测试复现，再由最小修复转绿。
- 相关后端、迁移和前端静态回归：`61 passed`。
- 完整测试：`1185 passed, 2 skipped, 155 warnings`，退出码 0。
- 前端生产构建：`npm --prefix apps/web run build`，退出码 0。
- 空 SQLite 迁移到 head 并核验外键：通过（包含在迁移测试中）。
- `git diff --check`：通过；仅有 Git 的 LF/CRLF 提示。
- 独立规格与代码复审：PASS；Critical / Important / Minor 均为 0；merge verdict 为 Yes。
