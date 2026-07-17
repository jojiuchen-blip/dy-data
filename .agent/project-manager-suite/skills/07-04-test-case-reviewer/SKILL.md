---
name: test-case-reviewer
description: Use when test-case-writer 已产出 `tc-main-<slug>.md` 和业务域 TC 文件、需要做独立核查；核查范围限于 TC 自身质量（与验收文档对齐、结构 / 数据准备 / 预期可判定性）。只改 TC，不改 PRD、不改验收文档；每轮产出一份待裁定问题清单，文件头部带本轮核查终态结论。
---

# test-case-reviewer

独立核查型 skill。test-case-writer 产出 TC 之后，本 skill 从 TC 核查者视角重新读 TC 与验收文档；不复用 writer 生成期的记忆。核查范围限于 TC 自身质量——断言是否对齐验收文档条目、结构是否符合产物规格、数据准备和预期是否可判定。

每轮核查结果以一份 `tc-reviews/<日期>-issues.md` 呈现，文件头部写明本轮终态结论；reviewer 可自决的 TC 错误原地修复，超出能力或需用户裁决的问题写清楚事实和选项后收尾，不自动回环、不代替用户裁决。

## 1. 角色定义

**验收文档是唯一 Oracle**：`acceptance-<slug>/<区块名>.md` 的验收条目是对错判定的唯一基准。PRD / foundation / API 契约 / 宿主代码只做上下文或辅助，不参与对错判定。

**硬约束（默认上游正确）**：默认验收文档 / PRD / foundation 都是对的。核查过程中即使觉得某条验收条目可疑，也不记录、不反馈、不触发跨 skill 打补丁流程；reviewer 的定位是"找 TC 自己的问题"，不是"代替用户审验收文档"。

**问题类型只有两类**：
- `TC 错误`：TC 断言引用不存在的字段、自创逻辑、曲解验收条目、引用条目 ID 错位
- `TC 遗漏`：验收文档条目未被 TC 覆盖

**"被动察觉"三条约束**：当核查某条 TC 时，TC 引用的 PRD 正文段落与验收文档对同一规则的描述不一致——
- 被动触发：仅在核查单条 TC 时顺带触发，不主动扫 PRD 全文 vs 验收文档找脱节
- 只记录事实：贴 TC 原文 + PRD 段落 + 对应验收条目三份文字，不做对错裁决
- 不改上游：不改 PRD、不改验收文档、不改 foundation / BRD / delivery-plan

**四个不做**：不改 PRD、不改验收文档、不改 foundation / BRD / delivery-plan、不改 PRD 元信息或版本文件。

## 2. 输入

### Pipeline 依赖文件（严格对齐 PIPELINE §10）

| 文件 | 来源 | 位置 | 用途 |
|---|---|---|---|
| `acceptance-<slug>.md` | prd-acceptance-reviewer | `<host>/docs/test-case/` | 验收文档主索引；核查覆盖完整性的唯一基准 |
| `acceptance-<slug>/<区块名>.md` | prd-acceptance-reviewer | `<host>/docs/test-case/acceptance-<slug>/` | 唯一 Oracle；TC 断言必须可回链到条目 |
| `tc-main-<slug>.md` | test-case-writer | `<host>/docs/test-case/` | TC 主索引（含业务域 TC 文件路径 / 编号前缀 / 覆盖率 / `[待确认]` 汇总） |
| `<业务域>/tc-<业务域>.md` | test-case-writer | `<host>/docs/test-case/<业务域>/` | 域 TC 文件（索引层 / 详情层） |
| `<业务域>/sql/<PREFIX>-<NN>.sql`（场景数据）与 `<PREFIX>-SEED.sql`（种子数据） | test-case-writer | `<host>/docs/test-case/<业务域>/sql/` | 核查 SQL 与用例是否匹配；`<PREFIX>` 为该域编号前缀（形如 `TC-<域简称>`） |

### 可选运行时辅助输入（不属于 PIPELINE §10 依赖）

| 文件 / 目录 | 用途 |
|---|---|
| foundation-glossary / foundation-schema / foundation-api | 核查字段、枚举、API 契约是否存在 |
| subprd（docs/prd/subprd/0X-subprd-<区块英文短名>.md） | "被动察觉"（见第 1 节）时读 TC 引用的 PRD 正文段落——**只读 TC 引用到的位置**，不主动扫全文 |
| 宿主代码实现 | 核查 SQL 数据链路时按需抽读 |

和 PIPELINE §10 的"不查 PRD 或验收文档"对齐说明：这里的"不查"指不审查上游正确性；读取验收文档作为唯一 Oracle、读取 TC 已引用的 PRD 局部段落做被动事实记录，不算越界。

### 内部共享知识包（相对 SKILL.md）

| 文件 | 位置 | 用途 |
|---|---|---|
| `methodology.md` | `../07-01-test-case-chief/knowledge/methodology.md` | 覆盖维度框架（BCDE）——核查 TC 覆盖是否完整时对照 |
| `templates-shared.md` | `../07-01-test-case-chief/knowledge/templates-shared.md` | TC 产物规格模板——核查文件头 / 验收矩阵 / 版本历史结构 |

共享知识包里**没有** reviewer 的核查清单——reviewer 的核查自检一律使用本 skill 的 `references/verification-check.md`，不要去 `../07-01-test-case-chief/knowledge/` 下找。

## 3. 产出

| 产物 | 文件名 | 存放位置 | 说明 |
|---|---|---|---|
| 待裁定 TC 问题清单 | `tc-reviews/<日期>-issues.md` | `<host>/docs/test-case/tc-reviews/` | 每轮核查产出一份；`<日期>` 格式 `YYYY-MM-DD` |
| TC 原地修正 | `<业务域>/tc-<业务域>.md` 等 | `<host>/docs/test-case/<业务域>/` | reviewer 可自决的 TC 内部问题，直接改对应文件 |

### 3.1 issues 文件的结论字段

每份 issues 文件头部必须带一行**结论**，说清楚本轮核查的终态——让任何读者（用户 / 下游调度层 / 未来的自己）一眼看清这轮核查发现了什么、reviewer 自己修了什么、还剩什么待处理。

reviewer 必须使用 `test-case-chief/SKILL.md` 已登记的三种结论字段值，不自造同义词：

| 结论字段值 | 什么情况写这个 |
|---|---|
| `已完工` | 本轮没发现问题，或发现的 TC 错误 / 遗漏都已 reviewer 自行原地修完 |
| `需 writer 续改` | 问题超出 reviewer 原地修正能力（SQL 需重构、验收矩阵重算、跨域用例重组等） |
| `需用户接手` | 被动察觉到 PRD 正文 vs 验收文档不一致的事实、或其它 reviewer 无法自决的疑问 |

同日多轮 issues 的命名规则：第 1 轮 `YYYY-MM-DD-issues.md`（不带后缀），同日第 2 轮起加数字后缀 `YYYY-MM-DD-issues-2.md` → `YYYY-MM-DD-issues-3.md`…。"最新一份"= 日期最大的那天中数字后缀最大的一份（无后缀视为第 1 轮）；**不要**按整个文件名的字典序排序取末尾——带 `-2` / `-3` 后缀的文件名在字典序里反而排在无后缀文件之前。历史 issues 保留作审计。

reviewer 的职责到"用固定结论值写清楚本轮终态"为止。下游（用户或调度层）如何基于这行结论决定动作——不是 reviewer 的事。

## 4. 工作流

工作流分五个 Phase：建立清单 → 逐域比对 → 覆盖完整性 → 分类处理 → 产出 issues。任一 Phase 出现需要等用户裁决的疑问就先标记到 issues 草稿里，继续往下走，不中断流程——所有裁决都在 Phase 5 产出 issues 时一次性提交。

**Phase 1：建立核查清单**
读 `acceptance-<slug>.md` + 区块子文件，建立验收条目清单（区块 / §X / 条目 ID / 类型 / 预期 / `[待确认]` 标记）；读 `tc-main-<slug>.md` 列出所有业务域 TC 文件路径和编号前缀；建立 (验收条目 ID ↔ TC 编号) 映射表。

**Phase 2：逐域比对（每次只处理一个业务域）**
按 `references/phase-verification.md` §3 的流程重读该域验收子文件 + TC 文件 + sql/，逐条比对 TC 断言的字段存在性、值 / 条件支撑、逻辑一致性、条目引用正确；对照 `references/verification-check.md` §1 做逐项自检。若某条 TC 引用了 PRD 正文段落、且该段落与验收文档同一规则描述不一致——仅记录事实到 issues，不裁决。

**Phase 3：检查覆盖完整性**
(验收条目 ID ↔ TC 编号) 映射表里无对应 TC 的条目标记为 `TC-GAP-`；统计覆盖率；列出明确标注 `[待确认]` 的条目。

**Phase 4：分类处理**
- 可自决的 TC 错误（断言改写、条目回链修正、SQL 小调整）：reviewer 直接改 TC；issues 只记"已修"作审计
- 需 writer 续改的问题（SQL 需重构、验收矩阵重算、跨域用例重组）：issues 记完整问题 + 修正建议；本轮终态写 `需 writer 续改`
- 需用户接手的问题（被动察觉冲突、无法给唯一修正方案）：issues 记事实 + 待裁选项；本轮终态写 `需用户接手`
- 没问题：issues 简要写"本轮无发现"；本轮终态写 `已完工`

**Phase 5：产出 issues + 自检**
按 `references/phase-verification.md` §4 的规范写 `tc-reviews/<日期>-issues.md`；对照 `references/verification-check.md` §2 / §3 做问题记录 / 结论字段 / 命名规范自检；写入明确的本轮终态结论；向用户展示 issues 文件路径——后续由用户或调度层决定下一步动作，不在本 skill 职责范围。

## 5. 写入边界

| 能做 | 不能做 |
|---|---|
| 原地修正 `<业务域>/tc-<业务域>.md` 里可自决的 TC 错误 | 改 PRD 文件 |
| 原地修正 `<业务域>/sql/*.sql` 里 SQL 细节 | 改验收文档 `acceptance-<slug>.md` / `acceptance-<slug>/<区块名>.md` |
| 更新 `tc-main-<slug>.md` 的覆盖率 / `[待确认]` 汇总（如 reviewer 原地改 TC 导致统计变化） | 改 foundation / BRD / delivery-plan |
| 新建 `tc-reviews/<日期>-issues.md` | 改 PRD 元信息或版本文件 |
| 读 TC 引用的 PRD 正文段落做被动察觉 | 主动扫 PRD 全文 vs 验收文档找脱节 |
| 在 issues 里记"PRD 正文 vs 验收文档不一致"的**事实** | 在 issues 里裁决 PRD 正文或验收文档哪个对 |

**最硬规则**：默认上游是对的。reviewer 发现的所有问题都归在 `TC 错误` / `TC 遗漏` 两类里；唯一例外是被动察觉事实记录——仍不做对错裁决。

"更新 `tc-main-<slug>.md`"仅限 reviewer 因原地修 TC 而引起的统计变化同步，不对 TC 主索引做结构性改动；如主索引结构需要调整，转给 test-case-writer 续改。

## 6. 参考文件

| 文件 | 内容 | 何时读取 |
|---|---|---|
| `../07-01-test-case-chief/knowledge/methodology.md` | 覆盖维度框架（BCDE） | Phase 2 核查 TC 覆盖维度时 |
| `../07-01-test-case-chief/knowledge/templates-shared.md` | TC 产物规格模板 | Phase 2 核查 TC 结构时 |
| `references/phase-verification.md` | 核查方法论（逐域比对流程 / 问题分类 / 记录规范 / 修复流程） | Phase 2-5 全程 |
| `references/verification-check.md` | 核查自检清单、常见核查期陷阱 | Phase 2 / Phase 5 自检时 |

核查自检相关内容全部在 `references/verification-check.md`；`../07-01-test-case-chief/knowledge/` 共享包中只有方法论与产物模板，没有 reviewer 的核查清单。

writer 侧的 `../07-03-test-case-writer/references/self-check.md` 是 writer 自检清单，不在 reviewer 读取范围；reviewer 的自检完全走本 skill 的 `references/verification-check.md`。
