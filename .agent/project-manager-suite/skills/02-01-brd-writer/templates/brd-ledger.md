# BRD 决策台账 展示层结构示例

> **本文件是结构示例，不是可手工填写的模板。**
> 台账的权威数据源是 `ledger-state-<slug>.json`；`brd-ledger-<slug>.md` 由 `init` 自动生成，并在每次脚本写操作（lock / rollback / set-phase / update-gates 等）后按 `renderMarkdown` 重新渲染。不要手工创建或编辑它——下面的结构用于理解和核对渲染输出。

<!--
头部 "Phase"（当前阶段）取值与更新时机：
  B     — 台账刚创建，Phase B 诊断进行中
  C     — 进入 Phase C 收敛（含 Phase D.5 回退后重新收敛，及 DONE 后 reopen）
  D.5   — P0 确认率 100%，前提挑战进行中
  E     — 前提挑战通过，充分性判定进行中
  E.5   — 充分性通过，终稿前确认进行中
  F     — 终稿输出中
  DONE  — 终稿已落盘（此后脚本拒绝 lock / rollback，需 set-phase --phase C 显式重开）

每次 Phase 切换通过 set-phase 完成，脚本同步回写头部。跨会话恢复时直接读取头部的
Phase / Round（即 JSON 的 current_phase / current_round），不需要从字段状态反推。
-->

以下为渲染输出的实际结构（以一个集成型项目为例，字段行数随项目类型变化）：

```markdown
<!-- 此文件由 ledger-state-<slug>.json 自动生成，请勿手动编辑。修改请通过 brd-writer 脚本操作 JSON 源文件。 -->

# BRD Ledger — <项目名称>

- **Slug**: <slug>
- **Skill**: brd-writer
- **Phase**: C
- **Round**: 3
- **Created**: YYYY-MM-DD HH:MM
- **Last Updated**: YYYY-MM-DD HH:MM

## §1 P0 字段总览

| # | 字段名 | 值 | 状态 | 锁定轮次 | 方法论 |
|---|--------|----|------|----------|--------|
| 1 | 项目类型 | integration | locked | 0 | Phase A 定性 |
| 2 | 项目背景 | 订单数据需人工导表同步到 BI | locked | 1 | 来源: project-profile |
| 3 | 利益相关角色 | 运营/数据分析师/IT | locked | 1 | 来源: 需求方确认 |
| 4 | 核心痛点 | 每日手工导表 2 小时且易漏 | locked | 1 | 来源: 需求方确认 |
| 5 | 核心价值模型 | 省人力 + 数据时效提升 | locked | 2 | 第一性原理 → 消除手工环节 |
| 6 | 范围定义 | — | open | — | — |
| … | （类型追加字段、页面定位字段依次排在下方，行数随项目类型变化） | — | open | — | — |
```

§1 是**一张扁平总表**：通用 P0、类型追加 P0、页面定位字段（若项目含页面）按序排在同一张表里，不分小节。`展开状态`、`只看缺口`、`生成终稿前摘要` 均从本表读取。

**"方法论"列填写规则**（在 `lock` 的 `--fields` 载荷 `methodology` 键中给出）：`[决策]` 型字段必须填方法论名称及关键推导（如 `JTBD → 场景匹配`）；`[事实]` 型字段填信息来源（如 `来源: project-profile` / `需求方确认` / `数据佐证`）。字段分类见 `references/p0-fields.md`。

```markdown
## §2 冲突记录

（无冲突）
```

有冲突时渲染为表格（来源：`lock` 触发的静态规则冲突自动写入，或 AI 通过 `add-conflict` 写入语义冲突；`resolve-conflict` 后状态变为 resolved）：

```markdown
| 冲突 ID | 描述 |
|---------|------|
| 1 | [no_pages_page_field] 无页面项目不能锁定页面定位字段 |
```

```markdown
## §3 变更日志

### Round 1 — batch_lock（Phase B 批量锁定）
- **时间**: YYYY-MM-DD HH:MM
- **方法论**: 来源: project-profile
- **需求原话**: （一句话，用于追溯）
- **变更内容**:
  - `project_background`: null → "订单数据需人工导表同步到 BI"
  - `stakeholder_roles`: null → "运营/数据分析师/IT"
  - `core_pain_points`: null → "每日手工导表 2 小时且易漏"

### Round 2 — lock
- **时间**: YYYY-MM-DD HH:MM
- **方法论**: 第一性原理 → 消除手工环节
- **需求原话**: （一句话，用于追溯）
- **变更内容**:
  - `core_value_model`: null → "省人力 + 数据时效提升"

### Round 2 — rollback（回滚）
- **时间**: YYYY-MM-DD HH:MM
- **变更内容**:
  - `core_value_model`: "省人力 + 数据时效提升" → null
```

§3 按动作类型渲染：`lock`（单字段锁定）、`batch_lock`（Phase B 批量锁定）、`rollback`（回滚，变更内容为反向恢复）、`reopen`（DONE 后重开，无字段变更）。回滚记录的 Round 号取被回滚那一轮的编号。

```markdown
## §4 质量门

| 质量门 | 适用 | 状态 | 备注 |
|--------|------|------|------|
| field_completeness | 是 | pass | P0 确认率 100% |
| consistency | 是 | pass | 冲突数 0 |
| scope | 是 | — | — |
| methodology | 是 | — | — |
| role | 是 | — | — |
| measurement | 是 | — | — |
| page | 否 | — | — |
```

§4 的"质量门"列显示英文门槛 id（与 `update-gates` 的 `gate` 键取值一致，中英对照见 SKILL.md Phase E）；"适用"列由项目类型派生（如无页面项目 `page` 门不适用）；"状态"由 Phase E 的 `update-gates` 写入，字段值变化后会被脚本自动清空重判。
