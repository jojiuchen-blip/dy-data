---
name: doc-governance
description: Audit rule documents, protocol documents, SKILL files, runbooks, and prompt-like governance files when the user asks where content should live, which file should be the single source of truth, whether multiple files overlap, how to split or deduplicate them, or whether a single long file should add an index, reorder sections, or fold low-frequency detail. This skill is advisory only: it gives governance recommendations and does not directly edit the governed files.
---

# Document Governance

Use this skill when the task is to govern a documentation or rule system rather than to execute the business workflow described by that system.

This skill helps Claude:

- decide which file should be the unique authority source for a rule
- identify overlap, drift, and misplaced content across multiple docs
- propose Keep / Move / Delete / Navigate refactors
- propose explicit authority-source statements and cross-file navigation
- propose when governance should stay manual vs. become a script, scan, lint, or alignment check
- propose forward and backward navigation together when a doc system needs bidirectional indexing
- evaluate whether a single long document should add an index, reorder sections, use folds, or split by role
- optionally run a lightweight keyword and heading scan before proposing changes

## When to use it

Load this skill when the user asks questions such as:

- "这几份文档是不是重复了"
- "这条规则到底该放哪一份"
- "帮我做 single source of truth"
- "这个 README / runtime / routing 太长了，怎么拆"
- "这个文件太长了，要不要加目录索引"
- "这个文档怎么提高阅读效率"
- "这些 skill 文档怎么分层"
- "帮我做文档治理 / 规则治理 / authority source 治理"

Do not use this skill as the execution source for the governed workflow itself.

This skill is advisory only:

- it audits
- it classifies
- it proposes
- it does not directly edit the governed files

Once governance decisions are accepted, route back to the actual runtime / protocol / routing / implementation file and edit there.

## Operating model

1. Inventory the files in scope and their apparent roles.
2. Classify each file using the authority model in `references/authority-model.md`.
3. Mark overlap as one of:
   - legitimate navigation
   - boundary statement
   - duplicated rule
   - misplaced content
4. If the issue is single-file overload, classify it as one or more of:
   - missing reading index
   - poor section ordering
   - low-frequency detail blocking high-frequency reading
   - mixed audiences in one file
5. Produce an action matrix:
   - Keep here
   - Move to another authority file
   - Delete duplicated copy
   - Replace with navigation
   - Add forward index
   - Add backward index
   - Add index
   - Reorder sections
   - Fold low-frequency detail
   - Split only if single-file optimization is no longer enough

This skill stops at the proposal layer. It does not execute the file edits itself.

## Default output format

When auditing, use this structure:

1. Findings
2. Proposed authority map
3. Action plan
4. Residual risks

When the main issue is single-file overload, prefer this structure:

1. Reading pain points
2. Lowest-cost improvement
3. Recommended index or section order
4. Optional next step if the file keeps growing

## Validation example

Use this example to verify that the skill stays in advisory mode and returns governance recommendations instead of editing files.

### Example input

```text
请检查 project-manager-suite/skills/00-01-ai-project-manager/references/core/runtime.md
和 project-manager-suite/skills/00-01-ai-project-manager/references/core/routing.md
是不是有重复内容。

另外 runtime.md 很长，评估一下要不要加目录索引。

不要直接改文件，只给我处理建议。
```

### Expected output shape

```text
1. Findings
- runtime.md 和 routing.md 在 S2 页面协议、骨架补齐、脚本顺序上存在重合
- runtime.md 适合保留运行顺序、阶段判断、S2 运行规则
- routing.md 适合保留能力映射、目录骨架、安装与补齐策略
- runtime.md 属于单文件过长但角色仍清晰，优先建议加“按任务阅读”索引，而不是立刻拆分

2. Proposed authority map
- runtime.md: 执行顺序 / 阶段判断 / S2 特殊约束
- routing.md: 路由目标 / 目录骨架 / docs/rules 生成 / 安装策略

3. Action plan
- Move: 将 routing.md 中重复的 S2 运行细则下沉回 runtime.md
- Navigate: 在 routing.md 文件头明确声明 S2 规则统一看 runtime.md
- Add index: 在 runtime.md 顶部增加按任务阅读索引
- Reorder: 若后续仍然过长，再把低频补充段落后移或折叠

4. Residual risks
- 如果后续阶段规则继续增长，但没有同步补双链索引，维护者仍可能不知道该改哪份文件
```

### What this example validates

- The skill identifies overlap and assigns one authority source per rule family.
- The skill can treat “single-file overload” as a navigation problem first, not a forced split.
- The skill proposes `Move / Navigate / Add index` actions together when appropriate.
- The skill does not directly execute the refactor.

## Proposal rules

- Prefer one unique authority source per rule family.
- Secondary files may keep only:
  - a short boundary note
  - a short navigation note
  - a short summary that does not recreate the full rule
- If a rule change would require editing more than one file, re-evaluate whether the authority boundary is wrong.
- If a file answers more than two distinct governance questions, split or downscope it.
- If a single file is long but still has one clear role, prefer `index + reorder + fold` before proposing a split.
- Only propose a split when single-file optimization is no longer enough to restore reading efficiency.
- Do not directly modify the governed files while using this skill; return recommendations only.

## Scriptification guidance

Treat governance automation as progressive escalation, not as the default first move.

Prefer this order:

1. Manual judgment
2. Lightweight scan
3. Structured impact map
4. Alignment checker
5. Blocking lint or CI rule

Recommend scriptification only when a governance problem is:

- repeated across turns or maintainers
- stable enough to express as explicit rules
- expensive to keep checking by hand
- high-risk when missed

Good candidates for governance scriptification:

- repeated headings or repeated keywords across multiple files
- authority-source drift between docs and structured implementations
- “changed A, forgot to inspect B/C/D” style change-impact omissions
- missing forward or backward links in a layered doc system

Do not rush to scriptify:

- one-off wording cleanup
- ambiguous ownership that still needs human judgment
- explanation quality, tone, or readability that cannot be checked reliably by rules

## Double-link indexing

When a doc system has more than one layer, prefer bidirectional navigation instead of one-way linking only.

Use:

- `Forward index`
  - entry file -> authority file
  - overview file -> detailed file
  - task-based reading path -> deep rule source
- `Backward index`
  - authority file -> entry file
  - authority file -> structured implementation / scripts
  - authority file -> change-impact neighbors

Recommend bidirectional indexing when:

- the system has entry, authority, structured, or tool layers
- readers often jump by task instead of reading top to bottom
- maintainers open deep files directly and need upstream/downstream context

If a proposal includes navigation for a layered system, check whether a forward link alone is insufficient. If yes, propose both forward and backward indexing together.

## Use the reference

Read `references/authority-model.md` before proposing a refactor when the authority boundary is ambiguous.

## Use the script

Use `scripts/scan-authority-overlap.mjs` when:

- more than 2 files are in scope
- you suspect repeated keywords or headings across files
- you want a quick pre-edit scan before proposing moves

Default usage:

```bash
node <suite-path>/skills/00-04-doc-governance/scripts/scan-authority-overlap.mjs \
  --files file-a.md,file-b.md,file-c.md \
  --patterns "docs/rules,S2 页面先行协议,project-status\\.md"
```

> `<suite-path>` 指套件根目录：源码仓库联调时为 `project-manager-suite/`，安装到宿主后为 `.agent/project-manager-suite/`；命令默认在宿主项目根目录执行。

What the script does:

- reports repeated headings across the input files
- reports matching lines for the supplied patterns
- helps confirm whether overlap is real before editing

## Authority rule

If a rule could plausibly belong to multiple files, choose the file whose primary job is closest to the change. All other files should point to it instead of re-explaining it.
