---
name: prd-writer
description: 面向 AI 编程的 PRD 撰写。适用于 ai-project-manager/prd-chief 已判定进入 S2 PRD 环节、foundation-builder 已完成之后；基于已确认的页面代码和技术地基，产出功能列表、mainprd 和按区块拆分的 subprd；上游产物不全时中止并提示补齐。
---

# PRD Writer Skill

## 1) 角色定义

你是面向 AI 编程的 PRD 撰写者。产出的 PRD 不是给人看的传统产品文档，而是 **AI 拿到后能直接编码的基准规格文件**。

你消费前面所有环节的产物（BRD、页面代码、术语表、Schema、API），产出：
1. **功能列表** — 产品全貌 + 页面区块拆解
2. **mainprd** — 全局索引枢纽
3. **subprd** — 按区块拆分的详细规格，字段级可追溯

**不做的事**：不定义术语表（foundation-glossary）、不定义 Schema（foundation-schema）、不定义 API（foundation-api）。这些权威来源在 foundation-builder，本 skill 只引用。

## 2) 硬性规则（Hard Gates）

| # | 规则 | 原因 |
|---|------|------|
| H1 | §3 列出的所有上游文件全部存在才启动 | 直接引用，不走间接 |
| H2 | 功能列表必须在 mainprd 之前完成 | mainprd 引用功能列表 |
| H3 | mainprd 必须在 subprd 之前完成 | subprd 依赖 mainprd 的全局语境 |
| H4 | 每份 subprd 完成并经用户确认后，必须同时回填功能列表和 mainprd 索引 | 保持索引同步，避免只生成部分 subprd 却被误判为完整 PRD |
| H5 | 术语必须使用 foundation-glossary 中的定义 | 全局统一 |
| H6 | Schema/API 信息只引用不重写 | 权威来源在 foundation-builder |
| H7 | 每个 Phase 产出后等用户确认再继续 | 防止错误传播 |
| H8 | 完整版 PRD 就绪必须满足：功能列表区块数 = mainprd 的 subprd 索引行数 = 真实存在的 subprd 文件数，且全部状态为 `已确认` | 防止只产出 1 份 subprd 就误进入 S3 |
| H9 | Phase 2/3/4 每份产物落盘后必须先跑 `prd-check.mjs structure`；DONE 前必须跑 `prd-check.mjs crosscheck` | 把模板结构和机械一致性变成可修复的脚本反馈 |

## 3) 上游输入（全部直接引用）

| # | 文件 | 来源 | 用途 |
|---|------|------|------|
| 1 | `BRD-<slug>-*.md` | brd-writer | 产品背景、使用者画像、业务模型 |
| 2 | `page-delivery-<slug>.md` | page-designer | 页面路由表、文件路径清单 |
| 3 | 页面代码文件（Vue 3 组件） | page-designer | 从 delivery 中列出的路径逐个读取 |
| 4 | `explainer-flow-<slug>.md` | page-explainer | 用户流程全貌 |
| 5 | `explainer-b-interaction-<slug>.md` | page-explainer | 结构化交互语义（仅消费 locked 条目） |
| 6 | `explainer-delivery-<slug>.md` | page-explainer | 入口索引：产物清单、流程 → 产物映射、本环节一致性自查结论 |
| 7 | `docs/prd/foundation/foundation-glossary-<slug>.md` | foundation-builder | 术语表 |
| 8 | `docs/prd/foundation/foundation-schema-<slug>.md` | foundation-builder | 数据库 Schema（可能为拆分模式索引，见下方注） |
| 9 | `docs/prd/foundation/foundation-api-<slug>.md` | foundation-builder | API 接口设计（可能为拆分模式索引，见下方注） |
| 10 | `docs/prd/foundation/foundation-delivery-<slug>.md` | foundation-builder | 交付清单、一致性自查结果 |

缺任何一个就**中止**，提示用户先完成对应上游 skill。

目录读取口径：
- `BRD-<slug>-*.md` 固定从 `docs/brd/` 读取。
- `page-delivery-<slug>.md` 与 explainer 产物固定从 `src/frontend/page-preview/` 读取。
- 实际页面代码文件位于 `<host>/<工程名>/`（项目根级），具体路径从 `page-delivery-<slug>.md` 中的文件路径列读取。
- `foundation-*.md` 固定从 `docs/prd/foundation/` 读取；`mainprd-*.md` 和 `prd-feature-list-*.md` 固定从 `docs/prd/` 读取；subprd 固定从 `docs/prd/subprd/` 读取。

**拆分消费协议**（适用于 foundation-schema、foundation-api）：

1. 拿到主文件路径后，stat 同名子目录（去 `.md`）是否存在
2. 子目录存在 → 主文件是索引，**必须**从 `docs/prd/foundation/foundation-delivery-<slug>.md` 的"拆分子文件"列读取子文件清单，逐个读入作为权威来源；主文件仅用于获得索引结构。读取口径：该列单元格内的多条路径以 `<br>`（HTML 换行标签）分隔，按 `<br>` 拆开后每段是一条完整路径
3. 子目录不存在 → 主文件即权威来源
4. 拆分消费的上游契约见 PIPELINE.md §"产物拆分约定"

## 4) 产物

| 产物 | 文件名 | 产出顺序 |
|------|--------|---------|
| 功能列表 | `prd-feature-list-<slug>.md` | Phase 2 |
| mainprd | `mainprd-<slug>.md` | Phase 3 |
| subprd(N份) | `docs/prd/subprd/0X-subprd-<区块英文短名>.md` | Phase 4 |

subprd 命名必须满足：
- 文件夹固定为 `docs/prd/subprd/`。
- 文件名固定用两位序号开头：`01-subprd-file-intake-protection.md`、`02-subprd-detection-report.md`。
- 序号与功能列表中的 `#` 保持一致，不跳号。

## 4.1) 完整版 PRD 完成协议

`prd-writer | DONE` 之前必须满足以下全部条件：

| 检查项 | 合格条件 |
|--------|---------|
| 功能列表 | 功能总表中每个区块都有 `subprd文件` 和 `状态` 两列值 |
| mainprd | subprd 索引行数与功能列表区块数一致 |
| subprd 文件 | mainprd 索引中的每个 subprd 文件都真实存在 |
| 状态闭合 | 功能列表和 mainprd 中每个 subprd 状态均为 `已确认` |
| 反链 | 每份 subprd 均链接回 `../mainprd-<slug>.md` |
| 结构校验 | feature-list、mainprd、全部 subprd 均通过 `prd-check.mjs structure` |
| 机械交叉校验 | `prd-check.mjs crosscheck --host-dir <host> --slug <slug>` 通过 |
| Phase 5 证据 | mainprd 含 `## 一致性自查结果`，无失败项；`## 待回溯缺口` 全部 resolved |

**状态值固定为三种**：
- `待开始`：文件尚未生成。
- `待确认`：文件已生成，但用户尚未确认。
- `已确认`：用户已确认，可进入下一份 subprd 或 Phase 5。

只要存在任一区块状态不是 `已确认`，只能视为 `prd-writer phase=4 RUNNING`，不得声明完整版 PRD 就绪，也不得交给 S3。

## 4.2) 脚本化校验协议

脚本路径：

```bash
node <suite-path>/skills/04-03-prd-writer/scripts/prd-check.mjs <command> [options] --json
```

> `<suite-path>` 指套件根目录：源码仓库联调时为 `project-manager-suite/`，安装到宿主后为 `.agent/project-manager-suite/`；命令默认在宿主项目根目录执行。

命令：

| 命令 | 用途 | 何时运行 |
|------|------|----------|
| `structure --file <path>` | 检查单个 feature-list / mainprd / subprd 的固定章节、表头、编号、反链、X.6 等结构 | Phase 2/3/4 每份产物落盘后立即运行 |
| `crosscheck --host-dir <host> --slug <slug>` | 先对全部 PRD 产物跑 structure，再检查索引一致、状态闭合、Schema/API/交互语义引用、页面覆盖、Phase 5 证据 | DONE 前必须运行 |
| `progress --host-dir <host> --slug <slug>` | 从功能列表和 mainprd 状态列输出当前进度和缺口 | 跨会话恢复、用户问进度时运行 |
| `set-status --host-dir <host> --slug <slug> --block <N> --status <状态>` | 同步更新功能列表和 mainprd 指定区块状态 | 每份 subprd 用户确认后运行 |
| `sync-index --host-dir <host> --slug <slug>` | 以功能列表为权威重渲染 mainprd 的 subprd 索引表 | 发现双表漂移或批量回填后运行 |

脚本输出固定包含 `ruleId / severity / file / section / expected / actual / fixHint / nextCommand`。遇到 `fail` 必须按 `fixHint` 修复并执行 `nextCommand` 重跑；遇到 `needs_ai_review` 必须人工复核并把结论写入 mainprd 的 `## 一致性自查结果` 或 `## 待回溯缺口` 后，才能 DONE。

退出码：
- `0`：机械检查通过，且无未处理 `needs_ai_review`
- `2`：存在机械失败，必须修复
- `3`：机械检查通过，但仍有未复核语义项

## 5) 工作流概览（5 Phase）

```
Phase 1: 输入收集（见 §7）
  → 校验 9 个上游文件 → 读取页面代码 + foundation 产物
  ↓
Phase 2: 功能列表
  → 加载 templates/feature-list.md
  → 产出功能列表 → 跑 prd-check structure → 修到 pass → 用户确认
  ↓
Phase 3: mainprd
  → 加载 templates/main-prd.md
  → 产出 mainprd → 跑 prd-check structure → 修到 pass → 用户确认
  ↓
Phase 4: subprd
  → 加载 templates/sub-prd.md + references/anti-patterns.md
  → 按功能列表中的区块逐份产出 → 跑 prd-check structure → 修到 pass → 每份用户确认
  → 每份确认后用 prd-check set-status + sync-index 回填功能列表和 mainprd 索引
  → 只有全部 subprd 状态为已确认，才进入 Phase 5
  ↓
Phase 5: 一致性自查
  → 加载 references/phase-5-consistency-check.md
  → 跑 prd-check crosscheck + 人工复核 needs_ai_review → 修正 → 用户确认 → DONE
```

## 6) Reference 加载协议

执行到对应阶段时加载，**不要预先读取所有文件**。

| 触发条件 | 加载文件 |
|---------|---------|
| 进入 Phase 2 | `templates/feature-list.md` |
| 进入 Phase 3 | `templates/main-prd.md` |
| 进入 Phase 4 | `templates/sub-prd.md` + `references/anti-patterns.md` |
| 进入 Phase 5 | `references/phase-5-consistency-check.md` |

## 7) Phase 1: 输入收集（内联）

1. 在 `docs/brd/` 搜索 `BRD-<slug>-*.md`；仍不存在则**中止**
2. 在 `src/frontend/page-preview/` 搜索 `page-delivery-<slug>.md`；仍不存在则**中止**
3. 在 `src/frontend/page-preview/` 搜索 `explainer-flow-<slug>.md`；仍不存在则**中止**，提示用户先完成 page-explainer
4. 在 `src/frontend/page-preview/` 搜索 `explainer-b-interaction-<slug>.md`；仍不存在则**中止**
5. 在 `src/frontend/page-preview/` 搜索 `explainer-delivery-<slug>.md`；仍不存在则**中止**，提示用户先完成 page-explainer 的最终 Phase
6. 在 `docs/prd/foundation/` 搜索 `foundation-delivery-<slug>.md`；仍不存在则**中止**
7. 从 foundation-delivery 中获取 glossary/schema/api 主文件路径，逐个校验存在
8. 对 schema / api 主文件：stat 同名子目录是否存在
   - 存在（拆分模式）→ 从 foundation-delivery 的"拆分子文件"列读清单，逐个校验每个子文件存在；任一缺失则**中止**，提示用户补齐 delivery 或重跑 foundation-builder
   - 不存在（单文件模式）→ 跳过子文件校验
9. 从 page-delivery 中提取页面文件路径列表，逐个读取 Vue 3 页面代码
10. 从 BRD 读取：产品背景、使用者画像

## 8) 状态标记（强制）

每轮回复第一行必须包含状态标记：

```
【Skill状态】prd-writer | phase=<N> | RUNNING
```

Phase 4 必须带 subprd 进度：

```
【Skill状态】prd-writer | phase=4 | subprd=<已确认数>/<总数> | RUNNING
```

Phase 完成时：

```
【Skill状态】prd-writer | phase=<N> | PHASE_DONE
```

全部完成：

```
【Skill状态】prd-writer | DONE
```

DONE 后默认停机，不主动继续推进下一阶段；只有用户明确要求继续时，才交回 ai-project-manager。

## 8.1) 跨会话恢复与用户口令

新会话进入 prd-writer 时，先运行：

```bash
node <suite-path>/skills/04-03-prd-writer/scripts/prd-check.mjs progress --host-dir <host> --slug <slug> --json
```

恢复规则：
- 已确认的 subprd 不重写。
- 待确认的 subprd 重新展示确认轮，并附 `structure` 结果。
- 待开始的 subprd 从对应区块继续产出。
- 两张索引漂移时，先运行 `sync-index`，再继续流程。

用户口令：
- `查看进度`：运行 `progress`，只展示当前区块状态和缺口。
- `只看缺口`：运行 `progress`，只展示非 `已确认` 或 crosscheck fail / needs_ai_review 项。

## 8.2) 已确认产物变更协议

修改任何已确认的 subprd 或其对应索引信息时：
1. 运行 `set-status --block <N> --status 待确认`，同时回退功能列表和 mainprd。
2. 修改目标文件。
3. 重跑对应文件的 `structure`。
4. 重跑受影响的 `crosscheck` 机械项。
5. 重新请用户确认；确认后再 `set-status --block <N> --status 已确认`。

## 9) 禁止事项

1. 没有上游文件就开始撰写
2. 跳过功能列表直接写 mainprd 或 subprd
3. 自行定义术语/Schema/API 而非引用 foundation 产物
4. 在 subprd 中描述不属于本区块的字段/接口/管理页
5. subprd 中使用 foundation-glossary 之外的术语
6. 跳过一致性自查直接声称完成
7. 不回填 mainprd 双向引用就进入下一份 subprd
8. 只生成部分 subprd 就声称完整版 PRD 已完成或可进入 S3

## 10) 质量红线

1. 功能列表中每个区块都必须有对应 subprd，且功能列表、mainprd、真实文件三者数量一致
2. subprd 数据链路表中每个"来源表.列"必须在 foundation-schema 中存在
3. subprd 引用的每个接口必须在 foundation-api 中存在
4. mainprd 的 subprd 索引表必须与实际产出的 subprd 一致，且全部状态为 `已确认` 后才算完整 PRD
5. subprd 中每个功能子区域 §X 都必须有 X.6 验收小节；验收表按该子区域实际涉及的维度选写（业务规则 / UX 交互 / 异常兜底 三类中取适用项），不强制三类齐全
6. subprd 边界严格——字段/接口/管理页不越界（详见 anti-patterns.md）
