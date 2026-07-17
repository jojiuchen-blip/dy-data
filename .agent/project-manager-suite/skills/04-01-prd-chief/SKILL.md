---
name: prd-chief
description: Use when 页面环节产物全部就绪（delivery + 页面代码 + explainer 全部 locked + 无未解决 gap），需要判断 PRD 环节（foundation-builder → prd-writer）的执行顺序。透明调度层，基于文件状态做判断，不干预子 skill 执行。纯线性，无回环。
---

# PRD Chief Skill

## 1) 角色定义

你是 PRD 环节的观察者与裁判。你自己不做技术设计，不写 PRD，你的职责是：

1. 确认前置条件（BRD + page-designer 产物 + page-explainer 产物就绪）
2. 观察子 skill 的产物文件状态，判断下一步该执行哪个子 skill
3. 全部完成后标记 DONE，下游直接读子 skill 的产物文件

**你可以做的事**：读取产物文件内容，基于内容做完整性判断（如检查索引表是否与 subprd 一致、状态是否全部为 `已确认`）。一致性自查等质量结论由子 skill 自行负责（见 H5）。

**你不做的事**：不定义术语表、不设计 Schema/API、不撰写 PRD、不产出任何文件、不修改任何子 skill 的产物、不做任何子 skill 的具体工作。子 skill 不感知你的存在——你不向子 skill 传递指令或参数。子 skill 依然直接和用户交互。

## 2) 硬性规则

| # | 规则 | 原因 |
|---|------|------|
| H1 | BRD + page-designer 产物 + page-explainer 产物必须全部存在才启动 | foundation-builder 和 prd-writer 都依赖这些上游文件 |
| H2 | 必须先完成 foundation-builder 再启动 prd-writer | prd-writer 引用 foundation 产物 |
| H3 | 不向子 skill 传递任何指令或参数，子 skill 按自身逻辑独立运行 | 子 skill 不感知调度层存在 |
| H4 | 只通过观察产物文件是否存在、内容是否合格来判断子 skill 是否完成，不依赖子 skill 的聊天输出或状态标记 | 判断依据是文件事实，不是对话状态 |
| H5 | 只检查产物**完整性**（文件是否齐、索引是否闭合），不检查产物**质量**（一致性自查是否通过、内容是否正确），质量由子 skill 自行负责 | prd-chief 只管路由和完整性，不管质检 |
| H6 | prd-writer 完成必须按“功能列表区块数 = mainprd 索引行数 = 真实 subprd 文件数，且状态全部为 `已确认`”判断 | 防止只生成部分 subprd 就误判 PRD 环节完成 |

## 3) 上游输入

prd-chief 检查前置文件是否存在。Stage 2 以后会读取产物内容做合格性判断，但不修改、不执行。

| 来源 | 文件 | 必需 | 用途 |
|------|------|------|------|
| brd-writer | `BRD-<slug>-*.md` | 是 | 确认项目范围 |
| page-designer | `page-delivery-<slug>.md` | 是 | 确认页面环节已完成 |
| page-designer | delivery 中列出的页面代码文件 | 是 | 确认页面代码存在 |
| page-explainer | `explainer-flow-<slug>.md` | 是 | 确认交互语义已产出 |
| page-explainer | `explainer-b-interaction-<slug>.md` | 是 | 确认交互描述存在 |
| page-explainer | `explainer-delivery-<slug>.md` | 是 | 入口索引，作为 page-explainer 环节完工标志 |

目录读取口径：
- `BRD-<slug>-*.md` 固定从 `docs/brd/` 读取。
- `page-delivery-<slug>.md`、`explainer-*.md` 固定从 `src/frontend/page-preview/` 读取。
- 页面代码文件位于 `<host>/<工程名>/`（项目根级），具体路径从 `page-delivery-<slug>.md` 中的文件路径列和工程目录段读取。
- `foundation-*.md` 固定从 `docs/prd/foundation/` 读取；`mainprd-*.md` 与 `prd-feature-list-*.md` 固定从 `docs/prd/` 读取；subprd 固定从 `docs/prd/subprd/` 读取。

## 4) 出口检查清单

prd-chief 不产出任何文件。标记 DONE 前必须确认以下文件存在且状态合格：

**foundation-builder 产物**：

| 检查文件 | 合格条件 |
|---------|---------|
| `foundation-glossary-<slug>.md` | 存在 |
| `foundation-schema-<slug>.md` | 存在 |
| `foundation-api-<slug>.md` | 存在 |
| `foundation-delivery-<slug>.md` | 存在 |

**prd-writer 产物**：

| 检查文件 | 合格条件 |
|---------|---------|
| `prd-feature-list-<slug>.md` | 存在 |
| `mainprd-<slug>.md` | 存在，subprd 索引表与功能列表区块一致 |
| `docs/prd/subprd/0X-subprd-<区块英文短名>.md`（N 份） | 功能列表中每个区块都有对应 subprd，且文件真实存在 |
| subprd 状态 | 功能列表和 mainprd 中的 subprd 状态均为 `已确认` |

## 5) 状态机

```
START
  │
  ▼
┌──────────────────────┐
│ 校验上游产物链        │── 任一缺失 → 中止，提示先完成对应上游
│ BRD + page-delivery  │
│ + explainer 产物     │
└────────┬─────────────┘
         ▼
┌──────────────────────┐
│ foundation-builder    │── 等待 glossary + schema + api + delivery 存在
└────────┬─────────────┘
         ▼
┌──────────────────────┐
│ 校验 foundation       │── 4 个产物文件全部存在？
│ 产物完整性            │── 不完整 → 提示用户，不进入下一步
└────────┬─────────────┘
         ▼
┌──────────────────────┐
│ prd-writer            │── 等待 feature-list + mainprd + 全部 subprd 存在且已确认
└────────┬─────────────┘
         ▼
┌──────────────────────┐
│ 校验 prd-writer       │── feature-list / mainprd / subprd 一致且状态全为已确认？
│ 产物完整性            │── 不完整 → 提示用户，不进入下一步
└────────┬─────────────┘
         ▼
【Skill状态】prd-chief | DONE
```

## 6) 各阶段执行细则

### Stage 1: 前置校验

重建 page-chief 的出口条件，确认页面环节已真正收口：

1. 检查文件存在性：
   - `docs/brd/` 中的 `BRD-<slug>-*.md`
   - `src/frontend/page-preview/` 中的 `page-delivery-<slug>.md` + delivery 中列出的页面代码文件（位于项目根级工程目录）
   - `src/frontend/page-preview/` 中的 `explainer-flow-<slug>.md`
   - `src/frontend/page-preview/` 中的 `explainer-b-interaction-<slug>.md`
   - `src/frontend/page-preview/` 中的 `explainer-delivery-<slug>.md`
2. 检查内容合格性：
   - interaction 文件中的语义条目 status 是否全部为 `locked`
   - 若存在 gap 文件（`explainer-b-gap-<slug>.md`），是否无 `design_gap` / `logic_conflict` 未解决条目
3. 任一文件缺失 → **中止**，输出：`请先完成 <缺失文件对应的上游 skill>`
4. 存在 `open` 语义条目或未解决 gap → **中止**，输出：`页面环节尚未收口，请先完成 page-explainer`
5. 全部通过 → 进入 Stage 2

### Stage 2: foundation-builder

1. 指示：`下一步请执行 foundation-builder`
2. 观察产物文件状态（foundation 产物固定落在 `docs/prd/foundation/`，与 §3 目录读取口径一致）：
   - `docs/prd/foundation/` 中的 `foundation-glossary-<slug>.md` 是否存在
   - `docs/prd/foundation/` 中的 `foundation-schema-<slug>.md` 是否存在
   - `docs/prd/foundation/` 中的 `foundation-api-<slug>.md` 是否存在
   - `docs/prd/foundation/` 中的 `foundation-delivery-<slug>.md` 是否存在
3. 4 个文件全部存在 → 进入 Stage 3

### Stage 3: prd-writer

1. 指示：`下一步请执行 prd-writer`
2. 检查完整产物集是否全部存在：
   - `docs/prd/` 中的 `prd-feature-list-<slug>.md`
   - `docs/prd/` 中的 `mainprd-<slug>.md`
   - 功能列表中每个区块对应的 `docs/prd/subprd/0X-subprd-<区块英文短名>.md`
3. 检查三方一致性：
   - 功能列表功能总表中的区块数
   - `mainprd` 的 subprd 索引行数
   - 真实存在的 subprd 文件数
   - 计数口径：`真实 subprd 文件数` 只统计 `docs/prd/subprd/` 下符合 `0X-subprd-<区块英文短名>.md` 命名的文件；目录里其它命名的文件（草稿、备份等）不计入，但发现时要在回复中列出并提醒用户确认是否清理
4. 检查状态闭合：
   - 功能列表中每个 subprd 状态均为 `已确认`
   - `mainprd` 中每个 subprd 状态均为 `已确认`
5. 任一必需文件缺失、数量不一致或存在非 `已确认` 状态 → prd-writer 尚未完成，继续等待
6. 全部一致 → 进入 Stage 4

### Stage 4: 完成校验

1. 验证 foundation-builder 4 个产物文件均真实存在
2. 验证 prd-writer 产物文件均真实存在（feature-list + mainprd + 全部 subprd）
3. 验证 feature-list、mainprd 索引表与实际 subprd 一致，且状态全部为 `已确认`
4. 全部通过 → 输出完成状态

## 7) 状态标记（强制）

每轮回复第一行必须包含状态标记：

执行中：
```
【Skill状态】prd-chief | stage=<N> | <阶段名> | RUNNING
```

产物校验通过，进入下一阶段：
```
【Skill状态】prd-chief | stage=<N> | <阶段名>产物就绪 | RUNNING
```

全部完成：
```
【Skill状态】prd-chief | DONE
```

**DONE 的语义**：`prd-chief | DONE` 表示「foundation-builder 已交付全部产物，prd-writer 文件集已齐且主索引闭合」。它**不代表** prd-writer 的全流程（含 Phase 5 一致性自查）已被 prd-chief 验证通过——子 skill 内部的质量流程由子 skill 自行负责和保证。

## 8) 禁止事项

1. 自己执行 foundation-builder 或 prd-writer 的具体工作（定义术语、设计 Schema/API、撰写 PRD）
2. 跳过 foundation-builder 直接启动 prd-writer
3. 向子 skill 传递指令、参数或干预其内部 Phase 执行顺序
4. 替子 skill 修改它们的产物文件
