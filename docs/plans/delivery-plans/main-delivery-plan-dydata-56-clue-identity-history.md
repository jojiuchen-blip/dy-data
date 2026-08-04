# DYDATA-56 线索主档多标识热修复主开发计划

> **版本**：v1
> **发布日期**：2026-08-04
> **前序版本**：无
> **适用范围**：线索主档物化、来源标识历史、数据库迁移与回归测试
> **参与角色**：AI 执行，Human Owner 审核与验收
> **开发模式**：solo-local
> **执行约束**：生产 P0 缺陷独立修复；TDD；不改分配规则、总部池、评分、跟进操作或前端
> **目标**：同一原始线索记录的 `clue_id` 或身份信息发生变化时，继续关联原 `lead_key`，保留全部历史标识并避免物化事务回滚
> **当前需求基线**：Linear `DYDATA-56` 与线索中心 Foundation 主档/来源映射契约
> **上游发现结论**：`collect-upstream-context.mjs` 返回 `canProceed=true`；本热修复只消费线索中心 Foundation 相关文件

## 0. 本计划使用指南

1. 先读取本主计划和任务看板，确认唯一进行中的 Task。
2. 再读取当前子开发计划及其 `PRD 双链·读` 指向的文件。
3. 先添加并运行失败回归测试，再做最小实现和迁移。
4. 完成前执行子计划中的全部验证，并将证据回写 Linear `DYDATA-56`。

### 0.1 PRD 加载约束

- 业务身份以 `lead_key` 和非空 `order_id` 为稳定主档键。
- `canonical_clue_id` 仅是代表值，不得作为唯一历史或主档身份。
- 原始记录稳定键优先于可变的 `clue_id`、手机号身份键等来源属性。
- 本热修复不得提前实现 DYDATA-42/43 尚未冻结的页面或分配行为。

### 0.2 读前门禁 / AI 自检清单

- Linear `DYDATA-56` 为 In Progress，包含风险说明和验收标准。
- 主计划、任务看板和子计划三处仅 T1.1 为“进行中”。
- 应用代码修改前必须观察到目标回归测试按预期失败。
- 数据迁移必须可在 SQLite 测试库升级/降级，并兼容 PostgreSQL。

### 0.3 完成前验证门禁

- 执行 T1.1 的 `Verification Method`。
- 运行 `git diff --check`、全量 `python -m pytest` 和 Web production build。
- Alembic 只能保留一个 head；迁移测试必须通过。
- 生产重建不属于本地代码完成事实，需在部署后单独执行和回查。

## 环境依赖声明

| 依赖项 | 版本要求 | 检测命令 |
|---|---|---|
| Python | >= 3.11 | `python --version` |
| Node.js | >= 18 | `node -v` |

| 工程目录 | 就绪标识 |
|---|---|
| `.` | `requirements.txt` 存在 |

## 1. 差距基线

| 差距 | 优先级 | 影响 | 对应任务 | 状态 |
|---|---|---|---|---|
| 物化器未按 `source_clue_row_key` 优先匹配，来源身份变化会尝试重复插入主档 | P0 | 最新线索采集成功但主档、轮次和页面不再更新 | T1.1 | 已完成本地修复，待生产重建 |
| 主档仅保存一个 `canonical_clue_id` 和一个 `source_identity_key` | P0 | 同一线索的历史平台 ID 和身份版本不可追溯 | T1.1 | 已完成本地修复，待生产回填验收 |

## 2. 分工与边界

| 角色 | 职责 |
|---|---|
| AI | 失败测试、模型与迁移、物化修复、回归验证、Linear 证据回写 |
| Human Owner | 审核业务身份口径，并在部署后验收生产重建结果 |

## 3. 执行阶段

### Phase 1：主档稳定关联与标识历史

**Entry Criteria**：Linear `DYDATA-56` 已建立且用户明确要求开始开发；本计划文件组通过结构、一致性和环境门禁。

**Exit Criteria**：同一原始记录变更 `clue_id`/身份后仍只有一个稳定主档，历史标识完整且幂等，迁移、回归和全量验证通过。

| Task | 子开发计划 | 状态 |
|---|---|---|
| T1.1 | [sub-delivery-plan-dydata-56-clue-identity-history-T1.1-materialization.md](sub-delivery-plan-dydata-56-clue-identity-history-T1.1-materialization.md) | 进行中（本地实现与验证已完成，待生产验收） |

## 4. 任务看板

- 看板入口：[task-kanban-dydata-56-clue-identity-history.md](task-kanban-dydata-56-clue-identity-history.md)

## 5. 发布闸门

- [x] 来源记录优先匹配和多标识历史回归测试通过
- [x] 迁移升级、降级和唯一 head 检查通过
- [x] 全量后端测试与 Web production build 通过
- [x] Linear `DYDATA-56` 已回写验证证据和剩余生产步骤
- [x] 主计划、任务看板和子计划状态一致

## 6. 风险与应对

| 风险 | 影响 | 应对 | Owner | 状态 |
|---|---|---|---|---|
| 历史身份键与其他主档冲突 | 误合并两个订单或迁移失败 | 原始记录键和订单键优先；冲突保留历史并用测试阻止跨订单合并 | AI -> Human Owner | 监控中 |
| 新表与 Foundation 目标表重复 | 后续迁移成本增加 | 使用来源映射的子级标识历史，不新造第二套主档/来源映射概念 | AI -> Human Owner | 受控 |
| 本地通过但生产未恢复 | 最新线索仍不可见 | 部署后执行受控重建并核对最新时间、主档数和失败日志 | AI -> Human Owner | 待部署 |

## 7. AI 执行示例

1. 运行 T1.1 环境与一致性门禁，添加“同一来源记录更换标识”失败测试并确认红灯。
2. 实现最小模型、迁移和物化逻辑，运行聚焦测试后再运行全量验证。

## 8. PRD → 任务反向索引

| 需求依据 | Requirement ID | Task | 子开发计划 |
|---|---|---|---|
| Linear `DYDATA-56`；`clue_master_lead` 与 `clue_source_record_link` Foundation 契约 | DYDATA-56 | T1.1 | [T1.1 物化与标识历史](sub-delivery-plan-dydata-56-clue-identity-history-T1.1-materialization.md) |
