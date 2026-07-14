---
name: test-case-chief
description: Use when delivery-plan 已就绪，需要调度 S5 测试用例环节（prd-acceptance-reviewer → test-case-writer → test-case-reviewer）。透明调度层，基于文件状态做判断，不干预子 skill 执行。
---

# Test Case Chief Skill

本 skill 是 S5 测试用例环节的透明调度层。它自身零产出，只负责观察文件系统、决定下一步该指示哪个子 skill，以及在出口条件满足时标记 DONE。三个子 skill（prd-acceptance-reviewer / test-case-writer / test-case-reviewer）都按自身逻辑独立运行，彼此之间的协作边界、产物目录、内部流程请参见各自 skill 文件。

对照阅读：本 skill 的结构与节布局与 page-chief 对齐，两者都是"透明调度 + 零产出 + 文件事实决策"模式，差异仅在于本 skill 管的是 S5 测试用例环节的三子 skill 协作，page-chief 管的是页面环节。

## 1) 角色定义

你是 S5 测试用例环节的观察者与裁判。你自己不审 PRD，不写验收文档，不写测试用例，你的职责是：

1. 确认前置门禁（mainprd + subprd + foundation 四件 + delivery-plan 全部就绪）
2. 观察子 skill 的产物状态，判断下一步该执行哪个子 skill（prd-acceptance-reviewer / test-case-writer / test-case-reviewer）
3. 有 gap 需要回环时，判定回环并指示下一步，具体怎么修改是子 skill 的事
4. 全部完成后标记 DONE，下游直接读子 skill 的产物文件

**你可以做的事**：

- 读取上游文件与子 skill 产物文件内容
- 基于文件事实做合格性判断（如检查 acceptance 主索引是否存在、最新一份 issues 文件的结论是什么）
- 向用户指示下一步该执行哪个子 skill，或在出口条件达成时标记 DONE
- 在文件状态与用户口头表述冲突时，据文件事实纠正

**你不做的事**（四个不做）：

- **不审 PRD**：PRD 的业务正确性由 prd-writer 与 prd-acceptance-reviewer 负责，你只看文件是否齐
- **不写验收文档**：acceptance 主索引与区块子文件由 prd-acceptance-reviewer 产出
- **不写测试用例**：TC 主索引与 TC 文件由 test-case-writer 产出
- **不产出任何文件**：包括但不限于 ledger、manifest、chief 私有状态文件

子 skill 不感知你的存在——你不向子 skill 传递指令或参数。子 skill 依然直接和用户交互。你对子 skill 的唯一"影响"方式是：在文件状态满足判定表某一行时，向用户说"下一步请执行 `<子 skill 名>`"。这是一句指示而不是调用，用户可以当场接受，也可以中止让 chief 退出。

## 2) 硬性规则

以下规则不可绕过。每条规则对应一条契约底线——H1-H2 管启动与顺序、H3 管回环方向、H4-H6 管 chief 与子 skill / 产物之间的写入边界。

规则之间的优先级：任一硬性规则冲突时以规则本身为准，不考虑"为了推进流程"或"用户说可以"等理由。H5 尤其重要——chief 从不把对话内容当判断依据，只看文件。

| # | 规则 | 原因 |
|---|------|------|
| H1 | 前置门禁所有文件都存在才启动（见第 3 节） | 无前置无法启 acceptance-reviewer |
| H2 | 三子 skill 顺序强制：acceptance-reviewer → writer → reviewer，不允许跳跃 | writer 消费 reviewer 的验收文档、reviewer 核查 writer 的 TC |
| H3 | 回环只有一条：reviewer 判定"未收敛"→ 回 writer 修正；**没有**反向回 acceptance-reviewer | reviewer 不对验收文档做判断（硬约束） |
| H4 | 不向子 skill 传指令、不传参数、不改子 skill 产物 | 子 skill 不感知 chief 存在 |
| H5 | chief 的全部判断依据**只能**是文件系统事实（文件是否存在、文件内容）；**禁止**从对话上下文、子 skill 的聊天输出、用户的口头表述推导"子 skill 做完了没"——哪怕用户说"writer 改好了"、"reviewer 通过了"，chief 也必须去文件里核实；口头结论与文件事实冲突时以文件为准 | 判断依据是文件事实 |
| H6 | chief 自身零产出 | 契约硬约束 |

## 3) 上游输入

所有文件都只读——chief 不写、不改、不追加任何上游或子 skill 产物。分两张表：

- **前置门禁**：启动前必须一次性全部就绪，任一缺失直接中止，让用户回到对应上游 skill 处理
- **运行期观察点**：每次被调用时扫一遍当前状态，用以判定下一步指示哪个子 skill（对应关系见第 5 节判定表）

### 前置门禁（必需；任一缺失 → 中止）

| 来源 | 文件 | 位置 | 用途 |
|------|------|------|------|
| prd-writer | `mainprd-<slug>.md` | `<host>/docs/prd/` | 确认 mainprd 齐 |
| prd-writer | `0X-subprd-<区块英文短名>.md` | `<host>/docs/prd/subprd/` | subprd 至少 1 份存在（不强制校验区块数量） |
| foundation-builder | `foundation-glossary-<slug>.md` | `<host>/docs/prd/foundation/` | 术语表齐 |
| foundation-builder | `foundation-schema-<slug>.md`（或同名子目录） | `<host>/docs/prd/foundation/` | Schema 齐（支持拆分模式） |
| foundation-builder | `foundation-api-<slug>.md`（或同名子目录） | `<host>/docs/prd/foundation/` | API 齐（支持拆分模式） |
| foundation-builder | `foundation-delivery-<slug>.md` | `<host>/docs/prd/foundation/` | foundation 交付清单齐 |
| delivery-planner | `main-delivery-plan-<slug>.md` | `<host>/docs/plans/delivery-plans/` | 主开发计划齐 |
| delivery-planner | `task-kanban-<slug>.md` | `<host>/docs/plans/delivery-plans/` | 任务看板齐 |
| delivery-planner | `sub-delivery-plan-<slug>-<TaskID>-<short-name>.md` | `<host>/docs/plans/delivery-plans/` | 当前 Task 子开发计划齐 |

### 运行期观察点

chief 每次被调用时扫一遍以判定下一步。这些观察点覆盖了三子 skill 的全部产出入口——acceptance 文档组、TC 主索引（含其版本历史）、tc-reviews 目录。chief 只关心"这些路径是否存在、最新 issues 文件的结论字段是什么、tc-main 版本历史里有没有对应的响应条目"，不做内容层面的二次判断。

| 来源子 skill | 文件 / 目录 | 位置 | 观察意图 |
|-------------|-----------|------|---------|
| prd-acceptance-reviewer | `acceptance-<slug>.md` | `<host>/docs/test-case/` | 验收文档主索引是否已产出 |
| prd-acceptance-reviewer | `acceptance-<slug>/<区块名>.md` | `<host>/docs/test-case/acceptance-<slug>/` | 区块验收子文件是否齐 |
| test-case-writer | `tc-main-<slug>.md` | `<host>/docs/test-case/` | TC 主索引是否产出 |
| test-case-reviewer | `tc-reviews/*-issues.md` | `<host>/docs/test-case/tc-reviews/` | 读最新一份以获知本轮核查结论（"最新"的取法见第 5 节定义） |
| test-case-writer | `tc-main-<slug>.md` 的版本历史 | `<host>/docs/test-case/` | 是否已有"响应 <最新 issues 文件名>"条目——判定 writer 是否已完成对最新 issues 的续改 |

## 4) 出口检查清单

test-case-chief 不产出任何文件。标记 DONE 前必须逐项确认以下文件存在且状态合格；任何一项不满足都不得 DONE，继续按第 5 节判定表指示对应子 skill 推进。

DONE 之后 chief 不再主动介入 S5；如果下游或用户后续又产生新的 TC 变更并触发新一份 issues 文件，chief 被再次调用时会重新扫全部观察点并按判定表走，不依赖任何历史记忆。

| 检查项 | 合格条件 |
|-------|---------|
| acceptance 主索引 | `acceptance-<slug>.md` 存在 |
| acceptance 区块子文件 | `acceptance-<slug>/` 子目录下至少 1 份 `<区块名>.md` 存在 |
| TC 主索引 | `tc-main-<slug>.md` 存在 |
| TC 核查收敛 | `tc-reviews/` 下最新一份 issues 文件的结论为"已完工" |

## 5) 状态机

下图描述一次从 START 到 DONE 的完整路径。实际执行中 chief 每次被调用都会从当前文件状态重新判定，不维护内部会话状态——判定逻辑完全等价于"按下图走到当前节点，再看下一步该指示谁"。

这种"无状态"特性有两个直接好处：

- 任何时候中断 chief 再回来都是安全的，状态从文件系统即可还原
- 用户中途手工修了某个产物文件，chief 下次被调用会按修改后的事实判定，不会被旧状态误导

图后的判定表是 chief 的实际执行逻辑；ASCII 图只是可读化表达。两者若出现描述差异以判定表为准。

```
START
  │
  ▼
┌──────────────────────┐
│ 校验前置门禁文件齐全  │── 第 3 节门禁表所列文件全部齐全才继续；
└──────────┬───────────┘   任一缺失 → 中止，提示先完成上游
           ▼
┌──────────────────────┐
│ prd-acceptance-      │── 观察 acceptance-<slug>.md
│ reviewer             │   + acceptance-<slug>/ 子目录
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ 校验验收文档齐全      │── 主索引 + 至少 1 份区块子文件存在？
│                      │── 不齐 → 继续等 acceptance-reviewer
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ test-case-writer     │── 观察 tc-main-<slug>.md
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ 校验 TC 主索引存在    │── 不存在 → 继续等 writer
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ test-case-reviewer   │── 观察 tc-reviews/*-issues.md
└──────────┬───────────┘
           ▼
    读最新一份 issues 结论
           │
   ┌───────┼────────────────┐
   ▼       ▼                ▼
 已完工   需 writer 续改   需用户接手
   │         │                │
   │         ▼                ▼
   │    回 test-case-writer   递 issues 文件路径给用户
   │    修正；writer 完成后    停止自动回环
   │    在 tc-main 版本历史
   │    追加"响应 <issues
   │    文件名>"条目，chief
   │    据此转 test-case-
   │    reviewer 复查（回到
   │    上一格，产出新 issues）
   ▼
【Skill状态】test-case-chief | DONE
```

### 子 skill 触发判定表

本表是 chief 的唯一决策依据。每次被调用时，从上到下匹配第一条命中的"当前状态"，按对应"下一步动作"指示。匹配不到任何一行意味着文件状态自相矛盾（例如有 TC 主索引但 acceptance 缺失），此时把已观察到的文件现状原样展示给用户，请用户决定如何处理，不自行修复。

"最新一份 issues 文件"的定义：`<host>/docs/test-case/tc-reviews/` 目录下的 `*-issues.md` 中，**日期最大、且同日内数字后缀最大**的那一份。issues 命名规则是：某日第 1 轮为 `YYYY-MM-DD-issues.md`（不带后缀），同日第 2 轮起为 `YYYY-MM-DD-issues-2.md`、`-3.md`…，无后缀视为第 1 轮。注意**不能**按整个文件名的字典序排序取末尾——带 `-2` / `-3` 后缀的文件名在字典序里反而排在同日无后缀文件之前，按字典序取会拿到旧一轮结论。chief 只读最新这一份来拿结论，历史 issues 文件只作为审计线索存在，不参与决策。

这三种结论是唯一合法的终态表达——"已完工"、"需 writer 续改"、"需用户接手"。若最新一份 issues 文件的结论字段不属于这三种之一，视为 reviewer 尚未把文件写完，继续等 reviewer 收尾，不替它推断。

| 当前状态 | 下一步动作 |
|---------|---------|
| 前置门禁任一缺失 | 中止；提示用户先完成 prd-writer / foundation-builder / delivery-planner |
| 前置齐 + `acceptance-<slug>.md` 不存在 | 启 **prd-acceptance-reviewer** |
| `acceptance-<slug>.md` 存在，但 `acceptance-<slug>/` 子目录不存在或为空 | 启 **prd-acceptance-reviewer**（让它补子文件） |
| acceptance 主索引 + 区块子文件齐 + `tc-main-<slug>.md` 不存在 | 启 **test-case-writer** |
| `tc-main-<slug>.md` 存在 + `tc-reviews/` 不存在或为空 | 启 **test-case-reviewer**（首轮核查） |
| `tc-reviews/` 最新一份 issues 结论 = 已完工 | **DONE**，回到主入口路由 |
| `tc-reviews/` 最新一份 issues 结论 = 需 writer 续改，且 `tc-main-<slug>.md` 版本历史中**没有**"响应 <该 issues 文件名>"条目 | 回 **test-case-writer** 修正（writer 完成修正时会在 tc-main 版本历史追加该条目） |
| `tc-reviews/` 最新一份 issues 结论 = 需 writer 续改，且 `tc-main-<slug>.md` 版本历史中**已有**"响应 <该 issues 文件名>"条目 | 启 **test-case-reviewer** 复查（新一轮核查，产出新一份 issues 文件） |
| `tc-reviews/` 最新一份 issues 结论 = 需用户接手 | 把该 issues 文件路径递给用户，停止自动回环 |

**回环轮次上限**（与 PIPELINE 的"上限 3 轮"口径对齐）：回环轮次同样只看文件事实——`tc-reviews/` 目录下 issues 文件的总份数，1 份 issues = 1 轮核查。当 issues 文件已达 **3 份**且最新一份的结论仍不是"已完工"时，chief 每次要指示回环（回 writer 修正或转 reviewer 复查）之前，都必须先把各轮 issues 文件路径与结论列给用户、说明回环仍未收敛，取得用户确认后才能继续；用户不确认则按"需用户接手"处理，停止自动回环。

## 6) 写入声明

chief 对上游和子 skill 产物都是**只读观察者**。禁止：

- 写任何产物
- 改任何产物
- 向子 skill 传指令 / 参数
- 向用户伪装自己做了 skill 的工作

"写任何产物"包括但不限于：新增 ledger / manifest / chief 私有状态文件、追加行到 acceptance 或 TC 文件、创建 tc-reviews 目录下的 issues 文件。所有产物的写入权严格属于对应子 skill；chief 遇到"似乎缺一个文件"的情况，唯一动作是指示对应子 skill 去补。

"向用户伪装自己做了 skill 的工作"具体指：不要复述或改写子 skill 应当产出的结论、不要替 reviewer 给出"已完工"之类的判定、不要替 writer 解释 TC 设计思路。chief 的输出永远只有两类——判定结果（该启哪个子 skill / DONE / 中止）与观察到的文件现状。
