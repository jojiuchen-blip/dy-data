# AGENTS.md

This file defines project-level instructions for Codex and other agentic coding
tools working in this repository.

## 1. Turn Gate

At the start of every turn, load `myskills-router` and follow its routing
instructions before answering, asking clarifying questions, inspecting files, or
editing code.

When a skill is loaded, append the required skill usage log under
`~/my-skills/.logs/skill-usage.jsonl`, and write one audit record with:

- timestamp
- user_goal
- candidate_skills
- selected_skills
- reason

If the router cannot be read after an actual read attempt, state the read error
briefly, then fall back to matching the user intent against available skill
descriptions.

## 2. Repository Context

The active application repository is this directory, not the parent workspace:

```text
C:\Own Docm\Coding\抖音结算中心\dy-data
```

The product is the Douyin business/settlement engine. It covers Douyin order
settlement dashboards, store ranking, store monthly settlement, order details,
clue follow-up, admin operations, data collection workers, and production
deployment reliability.

Do not commit secrets, cookies, browser profiles, real exported data, database
URLs, local personal paths, or credentials.

## 3. Linear-First Requirement Lifecycle

For this project, Linear is the unified requirement pool and execution view.
The Linear team is:

```text
抖音经营引擎
```

The Linear team key is:

```text
DYDATA
```

Whenever the user, a collaborator, or any Codex window mentions a new idea,
optimization, feature, bug, UX problem, data issue, technical debt, or product
request, do not jump straight into implementation. Start with requirement
intake.

The default flow is:

1. Understand the request.
2. Classify it.
3. Judge whether it should enter the requirement pool.
4. Deepen the definition through brief discussion if needed.
5. Create or update a Linear issue.
6. Report the Linear issue ID/link.
7. Ask whether the user wants to enter development.

Do not write code, edit files, create branches, run migrations, or change
production configuration before the user explicitly confirms that the Linear
issue should enter development.

Exceptions:

- If the user explicitly says "先别建票", "只是想法", "只分析", or equivalent,
  do not create a Linear issue. Provide analysis or a Backlog draft only.
- If the request is a trivial direct answer that clearly is not a project
  requirement, answer directly.
- If Linear tools are unavailable, provide a ready-to-create Linear issue draft
  and ask the user to reconnect Linear before issue creation.

## 4. Requirement Intake Steps

During intake, Codex should produce or confirm:

- type: Feature, Bug, Improvement, Tech Debt, Docs, or Data Quality
- source: Codex Intake, GitHub Issues, Manual Intake, or Production Signal
- project: one of the Linear projects under `抖音经营引擎`
- affected area: Settlement, Store Ranking, Store Settlement, Order Details,
  Clue Center, Admin Console, API, Worker, Frontend, Database, Deploy / CI, or
  Docs
- priority: Urgent, High, Medium, or Low
- risk labels: Data Correctness, Schema Migration, Production Deploy,
  Security / Secret, External API, where applicable
- current state: Backlog, Todo, In Progress, In Review, Done, Canceled, or
  Duplicate

If information is missing, prefer `Needs Definition`, `Needs Data`, or
`Needs Decision` over guessing.

## 5. Linear Issue Definition

Every Linear issue created from Codex should include:

```markdown
## 背景

## 当前问题

## 目标结果

## 范围

## 不做

## 涉及模块 / 文件 / 页面

## 验收标准

## 风险 / 依赖

## 验证记录
```

Use Chinese for issue content unless the user explicitly asks otherwise.

For GitHub Issues used as a source:

- keep the original GitHub issue URL in the Linear issue
- add the `GitHub Issues` source label
- summarize the GitHub issue instead of copying long comment threads
- use Linear for planning, status, acceptance, and closure
- keep GitHub for PRs, commits, CI, and external discussion context

## 6. Development Gate

Only enter development after all of these are true:

- a Linear issue exists or the user explicitly says no issue is needed
- the user confirms development should start
- the scope and non-goals are clear
- acceptance criteria are checkable
- relevant files/modules/pages are identified
- high-risk areas have been labeled
- one active Codex window or assignee owns the issue

When starting implementation on an existing Linear issue:

1. Read the Linear issue first.
2. Check its project, labels, state, and acceptance criteria.
3. Move or ask to move it to In Progress.
4. Read the relevant repository files.
5. Implement the smallest scoped change that satisfies the issue.
6. Update Linear with verification records and remaining risks.

If another collaborator or Codex window is already working on the issue, stop
and ask how to coordinate before editing files.

## 7. Settlement Center Branch Continuity

Settlement center work uses one long-lived remote integration branch by
default:

```text
codex/settlement-center
```

Apply these rules to Settlement, Store Ranking, Store Settlement, Order
Details, and closely related settlement administration work:

- Reuse `codex/settlement-center`; do not create a date-named or issue-named
  remote branch for each Linear issue by default.
- Keep Linear issues separate and include the relevant `DYDATA-xx` identifier
  in checkpoint commit messages so each change remains traceable.
- Local temporary branches are allowed for isolated work, but do not push them
  by default. Review and merge them locally into `codex/settlement-center`.
- Only one active Codex window or collaborator owns push access to the shared
  branch at a time. Record the owner and current HEAD in the Linear issue.
- Before every push, fetch the remote and report the tracking branch,
  ahead/behind counts, staged diff, unstaged changes, untracked files, recent
  commits, verification results, and intended push target.
- Never rebase or force-push the shared branch. If a non-fast-forward update is
  detected, stop and audit both histories before merging.
- An exception remote branch requires explicit user approval and a Linear
  record explaining the isolation reason and cleanup plan.
- At handoff, record the branch, HEAD, committed-but-unpushed count,
  staged/unstaged/untracked state, completed verification, and next action.

## 8. Verification Gate

For code changes, start with:

```powershell
git diff --check
```

Use the relevant tests for the touched area. The usual full local gate before
push is:

```powershell
python -m pytest
npm --prefix apps/web run build
```

For frontend work, add screenshots or route checks when appropriate.

For data correctness work, include row counts, sample comparisons, SQL or export
evidence, and explain any excluded or anomalous records.

For production or deployment work, include CI/deploy status, logs, smoke tests,
and rollback considerations.

## 9. Done Gate

Do not close or call an issue done until:

- implementation is complete, or the issue is explicitly resolved without code
- verification commands and results are recorded
- PR/commit/CI/deploy links are added when applicable
- user-facing or collaborator-facing docs are updated when behavior changes
- any remaining risk is recorded or split into a follow-up issue
- the user or responsible collaborator accepts the result

## 10. Team Documentation

The Linear team documentation is part of the working system. Use and maintain:

- `团队首页资源索引`
- `Codex + Linear 协作手册`
- `Issue 模板与验收规范`

When the collaboration process changes, update Linear team documentation and, if
the rule affects all Codex windows for this repository, update this `AGENTS.md`
too.

## 11. Suggested User Phrases

Backlog only:

```text
这是一个想法，先不要开发。请理解需求、判断是否进入 Linear，并整理成 Backlog。
```

Define for development:

```text
请把这个需求深化成可开发的 Linear issue，补齐范围、不做、验收标准和验证计划。
```

Start development:

```text
请处理 Linear issue DYDATA-xx。先读 issue 和相关代码，确认方案后进入开发。
```

GitHub issue intake:

```text
请把这个 GitHub issue 聚合进 Linear，保留原链接，先不要开发。
```

Completion:

```text
完成后请把测试、PR/commit、CI/部署结果和剩余风险回填到 Linear。
```
