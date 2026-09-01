# DYDATA-81 Production Correction Implementation Plan

> **For agentic workers:** Execute this plan task-by-task with a review checkpoint after each gate. The plan is limited to the already accepted store-finance UAT baseline.

**Goal:** Merge the accepted `codex/dydata-81-store-finance` UAT implementation onto the current production `main` baseline, preserve all existing `/finance/*` behavior, and deploy only after every release gate passes.

**Architecture:** Start a release branch from the current `origin/main` (`95c5032`), merge the UAT branch (`eb53e10`) with explicit conflict resolution, then verify that the resulting diff adds only store-facing DYDATA-81 scope and release evidence. CI remains the source of truth for build/test/deploy; production smoke validates the exact deployed SHA.

**Tech Stack:** Git/GitHub Actions, Python/pytest, React/Vite, PostgreSQL release gates, Tencent Lighthouse deployment, Playwright visual checks.

## Global Constraints

- Do not modify, remove, or refactor `/finance/*` pages, APIs, navigation, permissions, or tests.
- Do not add UAT/demo data, dates, statuses, prompts, or fabricated financial values to production.
- Use only confirmed rules and formal APIs; missing data must remain an explicit empty/pending state.
- Keep DYDATA-81 open until the user performs final acceptance.
- Preserve the existing release rollback and pre-migration backup procedure.

---

### Task 1: Freeze evidence and prepare the release branch

**Files:**
- Modify: `docs/superpowers/plans/2026-09-01-dydata-81-production-correction.md`
- No product source changes in this task.

- [ ] Record `origin/main`, UAT branch, workflow, and current production asset evidence.
- [ ] Confirm the working UAT checkout has no uncommitted product edits; keep existing visual evidence recoverable in its original worktree.
- [ ] Create `codex/dydata-81-release` from `origin/main` and verify the base SHA.

Run:

```powershell
git ls-remote origin refs/heads/main
git status --short --branch
git show -s --format="%H%n%s" origin/main
```

Expected: base SHA is the current remote `main`; no untracked release source is silently discarded.

### Task 2: Merge the accepted UAT branch without changing protected finance scope

**Files:**
- Merge source: `codex/dydata-81-store-finance`
- Review all conflict paths before committing.

- [ ] Merge UAT into the release branch with `--no-commit`.
- [ ] Resolve only integration conflicts in shared files (`App.tsx`, `Shell.tsx`, shared API/types/styles, settlement routes and tests) by preserving current main finance behavior and adding the accepted store contract.
- [ ] Abort the merge if any resolution requires changing a protected `/finance/*` page/API/navigation/permission/test beyond the current `origin/main` content.
- [ ] Verify `git diff --name-only origin/main...HEAD` contains no protected finance path changes.

Run:

```powershell
git merge --no-commit --no-ff codex/dydata-81-store-finance
git diff --name-only origin/main...HEAD
git diff --check
```

Expected: UAT store pages, formal API wiring, status route, and evidence are present; protected finance paths have zero release diff.

### Task 3: Run local release gates on the exact merge candidate

**Files:**
- Test: `tests/`
- Build: `apps/web/`
- Governance: `.agent/project-manager-suite/`, `docs/plans/`

- [ ] Run governance lock, global-file, and route checks.
- [ ] Run the complete pytest suite, including DYDATA-81 contract, API, permission, visual, and deployment tests.
- [ ] Run the production frontend build and inspect the generated bundle for accepted invoice/status route markers and absence of demo values.
- [ ] Recheck the release diff for `/finance/*` protection and `git diff --check`.

Run:

```powershell
node .agent/project-manager-suite/tools/verify-suite-lock.mjs .
node .agent/project-manager-suite/tools/validate-global-files.mjs .
node .agent/project-manager-suite/tools/route-check.mjs .
python -m pytest
npm --prefix apps/web run build
git diff --check
```

Expected: every command exits zero; any failure blocks push and deployment.

### Task 4: Commit, push, and verify CI for one immutable SHA

**Files:**
- Commit all approved merge changes and required release evidence only.

- [ ] Commit the merge candidate with a release message.
- [ ] Push `codex/dydata-81-release` and open/update the DYDATA-81 pull request.
- [ ] Wait for the PR verification workflow; do not merge while any check is pending or failed.
- [ ] Merge the approved PR into `main`, capture the resulting SHA, and wait for the main-branch CI and Tencent deployment workflow for that exact SHA.

Expected: PR checks, main CI, and deploy workflow all report success for the same commit SHA.

### Task 5: Execute production smoke and rollback checks

**Files:**
- Evidence: `docs/devlog/20260830_dydata-81-store-finance.md` (append release evidence only)

- [ ] Verify production index and static assets correspond to the deployed SHA.
- [ ] Probe public shell routes, unauthenticated API/MCP responses, and all five store routes.
- [ ] With an authorized store session, verify bound-store access and reject a different-store query; do not fabricate or mutate business records.
- [ ] Verify the pre-migration backup path, previous verified SHA, and rollback command from `docs/runbook.md`.
- [ ] Keep DYDATA-81 open and report the deployed SHA, workflow links, smoke results, and any remaining user-acceptance item.

Expected: all smoke and rollback checks pass; any failed check blocks final delivery and triggers the runbook's rollback/hold procedure.
