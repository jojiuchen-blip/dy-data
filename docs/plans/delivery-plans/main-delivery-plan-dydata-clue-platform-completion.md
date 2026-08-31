# 线索平台收口主开发计划

> **版本**：v1
> **发布日期**：2026-08-30
> **适用范围**：DYDATA-56、8、14、15、34、70、58
> **开发模式**：main-worktree / sequential-integration
> **目标**：按依赖顺序关闭线索主池、总部池、规则控制台、旧引擎下线和 8GB 安全同步的剩余实现与验收缺口
> **当前需求基线**：Linear issue 验收口径、线索中心 BRD/Foundation、DYDATA-58 已确认设计
> **上游发现结论**：`collect-upstream-context.mjs` 返回 `canProceed=true`；当前代码基线为已同步的 `origin/main`

## 0. 本计划使用指南

1. 从任务看板读取唯一“进行中”任务，再读取对应子计划。
2. 先关闭已经实现但缺证据的任务，再进行旧引擎和安全同步代码集成。
3. 每个任务完成后同步三份计划状态，并立即切换到下一任务。

### 0.1 PRD 加载约束

- 主池、轮次、总部池、联系方式和跟进权限以线索中心 BRD/Foundation 为准。
- 当前产品决策优先：自动分配和自动再分配保持关闭，不因 DYDATA-34/58 的技术改造被隐式开启。
- DYDATA-58 的每日窗口统一使用 `Asia/Shanghai` 左闭右开自然日。
- 生产发布、重启和写数据不由“本地完成”自动授权。

### 0.2 读前门禁 / AI 自检清单

- 当前仓库与 `origin/main` 同步，未跟踪规格和旧隔离 worktree 均受保护。
- 任务看板、主计划和当前子计划仅有一个“进行中”任务。
- 每次写代码前执行 `verify-task-context.mjs` 并加载最多两份匹配编码规范。

### 0.3 完成前验证门禁

- 执行当前子计划全部 `Verification Method`。
- 代码任务必须运行聚焦测试、相关回归、`git diff --check`；最终运行全量 pytest 和 Web production build。
- PostgreSQL 并发、迁移和 4C/8GB RSS 门禁必须使用真实环境证据，不以 SQLite 或静态检查替代。

## 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Python | >= 3.11 | `python --version` |
| Node.js | >= 18 | `node -v` |
| Git | >= 2.40 | `git --version` |

| 工程目录 | 就绪标识 |
|---|---|
| `.` | `requirements.txt` 存在 |
| `apps/web/` | `package.json` 存在 |

## 1. 差距基线

| 差距 | 影响 | 对应任务 | 状态 |
|---|---|---|---|
| DYDATA-56、8、14、15 已有实现但缺当前基线与用户视角验收闭环 | Linear 状态与实际能力不一致 | T0.1-T0.4 | 已解决（2026-08-31） |
| 旧物化器仍创建 `legacy` 轮次 | 正式/旧轮次混杂，权限与可操作性不稳定 | T1.1 | 已处理 |
| DYDATA-58 的完整实现仅存在旧脏 worktree，未审查集成到 main | 控制面、按日恢复和资源保护未成为正式代码 | T2.1、T2.3、T2.4 | T2.1/T2.3 已解决；T2.4 本地通过、发布阻断 |
| DYDATA-70 依赖控制面和影响集合，不能单独移植 | 线索物化仍可能全历史扫描和线性增内存 | T2.2 | 已解决（2026-08-31） |

## 2. 分工与边界

| 角色 | 职责 |
|---|---|
| 主代理 | 计划、实现、集成、差异审查、测试、最终验收 |
| 只读审查子代理 | 审计已实现任务、旧引擎边界、DYDATA-70 依赖和 DYDATA-58 工作树证据 |
| Human Owner | 仅处理必须由人授权的生产写操作和最终业务验收 |

## 3. 执行阶段

### Phase 0：已实现能力闭环

**Entry Criteria**：远端 main 已同步，当前功能测试基线通过。

**Exit Criteria**：四个 issue 的代码、测试、用户验收路径和剩余生产门禁均被明确，能关闭的关闭。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T0.1 | [sub-delivery-plan-dydata-clue-platform-completion-T0.1-dydata-56.md](sub-delivery-plan-dydata-clue-platform-completion-T0.1-dydata-56.md) | 已完成（2026-08-30） |
| T0.2 | [sub-delivery-plan-dydata-clue-platform-completion-T0.2-dydata-8.md](sub-delivery-plan-dydata-clue-platform-completion-T0.2-dydata-8.md) | 已完成（2026-08-31） |
| T0.3 | [sub-delivery-plan-dydata-clue-platform-completion-T0.3-dydata-14.md](sub-delivery-plan-dydata-clue-platform-completion-T0.3-dydata-14.md) | 已完成（2026-08-31） |
| T0.4 | [sub-delivery-plan-dydata-clue-platform-completion-T0.4-dydata-15.md](sub-delivery-plan-dydata-clue-platform-completion-T0.4-dydata-15.md) | 已完成（2026-08-31） |

### Phase 1：旧分配引擎下线

**Entry Criteria**：Phase 0 完成，正式轮次、总部池和规则管理能力已被当前测试确认。

**Exit Criteria**：运行时代码不再创建或依赖 legacy 轮次，现有 legacy 数据可无损转换，自动分配/再分配仍关闭。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T1.1 | [sub-delivery-plan-dydata-clue-platform-completion-T1.1-dydata-34.md](sub-delivery-plan-dydata-clue-platform-completion-T1.1-dydata-34.md) | 已完成（2026-08-31） |

### Phase 2：8GB 安全同步与线索增量物化

**Entry Criteria**：旧引擎已下线；旧 worktree 仅作为补丁来源，每一片差异均经主代理独立审查。

**Exit Criteria**：按日父子任务、租约/恢复、变化捕获、线索和结算增量、控制台、运维护栏及最终资源门禁闭合。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T2.1 | [sub-delivery-plan-dydata-clue-platform-completion-T2.1-dydata-58-foundation.md](sub-delivery-plan-dydata-clue-platform-completion-T2.1-dydata-58-foundation.md) | 已完成（2026-08-31；环境门禁归入 T2.4） |
| T2.2 | [sub-delivery-plan-dydata-clue-platform-completion-T2.2-dydata-70.md](sub-delivery-plan-dydata-clue-platform-completion-T2.2-dydata-70.md) | 已完成（2026-08-31） |
| T2.3 | [sub-delivery-plan-dydata-clue-platform-completion-T2.3-dydata-58-remaining.md](sub-delivery-plan-dydata-clue-platform-completion-T2.3-dydata-58-remaining.md) | 已完成（2026-08-31） |
| T2.4 | [sub-delivery-plan-dydata-clue-platform-completion-T2.4-final-verification.md](sub-delivery-plan-dydata-clue-platform-completion-T2.4-final-verification.md) | 进行中（本地 PG 与 4C/8GB 资源通过；大量 PG 恢复与服务栈探测阻断） |

## 4. 任务看板

- 看板入口：[task-kanban-dydata-clue-platform-completion.md](task-kanban-dydata-clue-platform-completion.md)

## 5. 发布闸门

- [x] T0.1-T2.3 的 Verification 与 Evidence 均闭合；T2.4 本地证据闭合
- [x] 运行时代码不创建 `execution_mode=legacy` 轮次
- [x] 自动分配与自动再分配默认关闭，现有正式轮次仍可跟进
- [x] Alembic 只有一个 head；本地迁移链、真实 PostgreSQL 空库与带数据升级通过
- [x] 全量 pytest、Web production build、Compose 配置和 `git diff --check` 通过
- [x] 4C/8GB Linux 三轮资源门禁及 shadow 等价性有真实本地报告
- [ ] 大量真实 PostgreSQL 恢复验收及 HTTPS/SSH/API/PG 压测同步探测通过
- [ ] Linear 状态与实际完成证据一致

## 6. 风险与应对

| 风险 | 影响 | 应对 | Owner | 状态 |
|---|---|---|---|---|
| 旧脏 worktree 含大量未审查差异 | 误合并过时或无关代码 | 分任务抽取，逐文件审查，禁止整体 merge | 主代理 | 受控 |
| 0030-0036 迁移已在 main、运行时模型缺失 | 迁移链与 ORM 不一致 | 先恢复依赖顺序，再运行空库/升级/降级测试 | 主代理 | 已解决（Alembic 全链 54 passed） |
| DYDATA-34 原范围要求自动正式分配，但当前产品决策关闭自动分配 | 误将待分配线索自动下发 | 只移除 legacy 创建；正式分配保留显式触发且默认关闭 | 主代理 -> Human Owner | 已确认 |
| 大量 PostgreSQL 恢复场景和完整服务栈探测环境未建立 | 无法签发生产可用性门禁 | 本地 PG 与 4C/8GB 资源证据已通过；补齐崩溃恢复、跨日统计及 HTTPS/SSH/API/PG 同步探测前保持发布阻断 | Human Owner | 发布阻断 |

## 7. AI 执行示例

1. 完成 T0.1 验证后同步三份状态，自动把 T0.2 切换为进行中。
2. T1.1 开始前先证明 legacy 创建路径存在，再以测试约束正式轮次迁移和默认不自动分配。

## 8. PRD → 任务反向索引

| 需求依据 | Requirement ID | Task | 子开发计划 |
|---|---|---|---|
| 主档/来源标识 Foundation | DYDATA-56 | T0.1 | [T0.1](sub-delivery-plan-dydata-clue-platform-completion-T0.1-dydata-56.md) |
| 线索主池 BRD/Foundation | DYDATA-8 | T0.2 | [T0.2](sub-delivery-plan-dydata-clue-platform-completion-T0.2-dydata-8.md) |
| 总部池 Foundation | DYDATA-14 | T0.3 | [T0.3](sub-delivery-plan-dydata-clue-platform-completion-T0.3-dydata-14.md) |
| 规则版本与管理控制台 Foundation | DYDATA-15 | T0.4 | [T0.4](sub-delivery-plan-dydata-clue-platform-completion-T0.4-dydata-15.md) |
| 轮次、物化与运行时 Foundation | DYDATA-34 | T1.1 | [T1.1](sub-delivery-plan-dydata-clue-platform-completion-T1.1-dydata-34.md) |
| DYDATA-58 设计 §5-7 | DYDATA-58 | T2.1 | [T2.1](sub-delivery-plan-dydata-clue-platform-completion-T2.1-dydata-58-foundation.md) |
| 线索增量物化与身份规则 | DYDATA-70 | T2.2 | [T2.2](sub-delivery-plan-dydata-clue-platform-completion-T2.2-dydata-70.md) |
| DYDATA-58 设计 §8-18 | DYDATA-58 | T2.3 | [T2.3](sub-delivery-plan-dydata-clue-platform-completion-T2.3-dydata-58-remaining.md) |
| DYDATA-58 设计 §19-20 | DYDATA-58 | T2.4 | [T2.4](sub-delivery-plan-dydata-clue-platform-completion-T2.4-final-verification.md) |
