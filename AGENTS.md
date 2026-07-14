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

## 2. Project Governance Suite Gate

The company governance suite is vendored at:

```text
.agent/project-manager-suite/
```

Its tracked version lock is:

```text
.agent/project-manager-suite.lock.json
```

For project work, the mandatory turn order is:

1. Load `myskills-router` as required by the Turn Gate.
2. Verify the installed suite and lock:

   ```powershell
   node .agent/project-manager-suite/tools/verify-suite-lock.mjs .
   ```

3. Load `.agent/project-manager-suite/skills/00-01-ai-project-manager/SKILL.md`.
4. Run the global-file and stage checks when the task can change project state:

   ```powershell
   node .agent/project-manager-suite/tools/validate-global-files.mjs .
   node .agent/project-manager-suite/tools/route-check.mjs .
   ```

5. Follow the route selected by `ai-project-manager` and load only the rules and
   materials required for the current task.

If the suite directory, lock file, package version, or content hash is missing
or invalid, ordinary project work is blocked. Only recovery work under an
active governance issue may repair the standard suite source, reinstall it,
refresh the lock, and rerun the gates.

After installation, repository work must not depend on an external absolute
suite path. Do not hand-edit the vendored suite to create a host-only fork.
Change the standard suite source, run its tests, reinstall it, and commit the
updated lock and vendored copy together.

For an existing project, baseline adoption is always two-stage:

1. Run `collect-baseline-gaps.mjs` with `--dry-run --json --slug dy-data`.
2. Review the README source, page/API/model evidence, profile field sources,
   and document-gap conclusions before allowing a formal baseline write.

Scanner inference is evidence, not user confirmation. It must never overwrite
or masquerade as `【用户确认】` information.

Authority boundaries:

- `AGENTS.md` is the platform and repository hard-rule authority.
- Linear is the requirement pool, priority, ownership, acceptance, and issue
  state authority.
- `project-rules.md` is the thin long-lived authority index.
- `docs/rules/` is the host-specific implementation-rule authority.
- `project-profile.md` is the project identity and current-stage snapshot.
- `docs/plans/execution-plan.md` is the current execution cockpit, not the
  Linear backlog or a full development plan.
- `docs/plans/delivery-plans/` becomes authoritative only after the suite's S3
  planner generates a formal plan group.
- `docs/governance/authority-map.md` records how legacy documents map into the
  suite without creating duplicate sources of truth.

## 3. Repository Context

The active application repository is the Git repository root (`.`), not its
parent workspace. All repository instructions and commands must use relative
paths so the checkout remains portable across machines and worktrees.

```text
.
```

The product is the Douyin business/settlement engine. It covers Douyin order
settlement dashboards, store ranking, store monthly settlement, order details,
clue follow-up, admin operations, data collection workers, and production
deployment reliability.

Do not commit secrets, cookies, browser profiles, real exported data, database
URLs, local personal paths, or credentials.

## 4. Linear-First Requirement Lifecycle

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

## 5. Requirement Intake Steps

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

## 6. Linear Issue Definition

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

## 7. Development Gate

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
