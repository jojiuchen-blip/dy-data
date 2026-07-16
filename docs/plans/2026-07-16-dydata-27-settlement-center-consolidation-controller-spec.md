# DYDATA-27 Settlement Center Branch Consolidation Controller Spec

Status: Complete
Date: 2026-07-16
Controller: Codex main agent
Repo / workspace: `C:\Users\86138\Documents\抖音来客看板-settlement-center`
Branch / target: `codex/settlement-center` -> `origin/codex/settlement-center`

## 1. User Goal

Consolidate the previously separated settlement-center commits and relevant uncommitted settlement documentation into one long-lived remote branch, verify it, and push it without including unrelated personal assets or rewriting existing remote history.

## 2. Current Evidence

| Area | Evidence | Source | Confidence | Notes |
|------|----------|--------|------------|-------|
| Latest base | `origin/main` is `1d29178` and already contains PR #1 / `5d05ffd` store settlement visual spec | `git log origin/main` | High | Use as consolidation base |
| Old feature line | `origin/codex/commission-page-collab-20260707` contains `origin/feat/dy-dashboard-work-20260706` | `git merge-base`, `git rev-list` | High | Histories are connected |
| Current unique work | Current HEAD has five commits not in `origin/main`; only `5449f55`, `e085885`, and `6e4716e` carry unique changes | `git log origin/main...HEAD`, commit diffs | High | Two merge commits are integration-only |
| Uncommitted docs | Three new settlement documents are absent from `origin/main` | file hashes and `git rev-parse origin/main:<path>` | High | Include after content review |
| Superseded mock | Untracked navigation mock differs substantially from the newer tracked DYDATA-23 mock already in `origin/main` | `git diff --no-index` | High | Preserve original workspace file, do not overwrite newer remote version |
| Unrelated assets | Original workspace contains Word, PNG, and PSD files outside the scoped repo documentation | `git status --short` | High | Exclude from branch |

## 3. Scope

Included:
- Base the unified branch on latest `origin/main`.
- Integrate unique settlement/SKU commits `5449f55`, `e085885`, and `6e4716e` with conflicts resolved against latest main.
- Add `docs/commission-settlement-rework-decisions.md`.
- Add `docs/single-store-monthly-settlement-mock.html`.
- Add `docs/store-ranking-mock.html`.
- Add this controller spec and update collaboration guidance required by DYDATA-27.
- Run repository verification, commit any new consolidation documentation, push, and verify remote sync.

Excluded:
- Merge commits `570533b` and `d22ed85` as standalone cherry-picks; their mainline content is already in the base.
- The older untracked `docs/commission-dashboard-navigation-mock.html`; `origin/main` already contains the newer DYDATA-23 version.
- Word, PNG, PSD, and temporary files in the original workspace.
- Force-push, history rewriting, deployment, or deletion of old branches.

Scope control rule:
- Any additional commit or untracked file requires explicit evidence that it belongs to the settlement center and a controller spec update before inclusion.

## 4. Assumptions and Open Questions

| ID | Item | Type | Owner | Resolution |
|----|------|------|-------|------------|
| A1 | The three untracked settlement docs are intended content | Assumption | Controller | Supported by user request and document titles; include after review |
| A2 | The older combined navigation mock is superseded | Assumption | Controller | Keep the newer tracked DYDATA-23 file from `origin/main`; preserve old file only in original workspace |
| A3 | The migration merge commits remain valid on latest main | Question | Controller | Resolve through cherry-pick and Alembic/test verification |

## 5. Work Breakdown

| Task ID | Role | Owner | Responsibility | Write Set | Required Output | Acceptance Gate |
|---------|------|-------|----------------|-----------|-----------------|-----------------|
| T1 | Explorer | Controller | Audit branch topology, commits, and untracked files | Read-only | Inclusion/exclusion list | Every included item has evidence |
| T2 | Implementer | Controller | Create target branch and integrate scoped commits/docs | Target worktree only | Scoped branch diff | No unrelated assets or redundant merge commits |
| T3 | Spec Reviewer | Controller, separate phase | Compare result to this spec | Read-only | Pass/fail findings | All included items present; all exclusions absent |
| T4 | Code Quality Reviewer | Controller, separate phase | Review migrations, conflicts, docs, and integration risk | Read-only | Findings by severity | No blocking findings |
| T5 | Verifier | Controller | Run diff, tests, build, and remote checks | Read-only except build outputs | Command results and remote SHA | Required gates pass or exact blocker recorded |

## 6. Task Packets

### T2: Consolidate Settlement Branch

Role: Implementer

Ownership:
- Target worktree and `codex/settlement-center` only.

Non-goals:
- Do not edit the original dirty worktree.
- Do not include personal assets, force-push, deploy, or delete old branches.

Required output:
- Exact commits applied and conflicts resolved.
- Files added or changed.
- Self-review of staged and branch diffs.

Acceptance gate:
- Target history descends from latest `origin/main`, contains scoped unique changes, and has no unrelated files.

## 7. Review Plan

1. Implementer self-review of each cherry-pick conflict and final diff.
2. Spec review against included/excluded lists.
3. Code quality review of migrations, application changes, tests, and documentation.
4. Minimal fixes only for confirmed findings, followed by targeted re-review.

## 8. Verification Plan

| Gate | Command / Method | Owner | Required For Done | Notes |
|------|------------------|-------|-------------------|-------|
| Diff review | `git diff --check` and scoped branch diff | Controller | Yes | Run before final commit/push |
| Tests | `python -m pytest` | Controller | Yes | Full repo gate |
| Build | `npm --prefix apps/web run build` | Controller | Yes | Full web build |
| Migration graph | Alembic head check / migration tests | Controller | Yes | Confirm one valid head |
| Remote sync | push plus `git ls-remote` SHA comparison | Controller | Yes | No force-push |

## 9. Final Acceptance Checklist

- [x] User goal satisfied locally on the target branch.
- [x] Scope and non-goals respected.
- [x] Spec review passed.
- [x] Code quality review passed with no blocking findings.
- [x] Required tests and build passed.
- [x] Diff reviewed for unrelated changes.
- [x] Original dirty worktree remains preserved.
- [x] Local commit hashes recorded.
- [x] Push succeeds and remote SHA matches local target branch.
- [x] DYDATA-27 receives verification and remote sync evidence.

Verification results before push:

- `git diff --check origin/main..HEAD`: passed.
- `python -m alembic heads`: `20260715_0018 (head)`.
- Targeted integration suite: 181 collected; 99 non-visual tests passed, then 86 visual smoke tests passed after installing locked web dependencies.
- `python -m pytest`: 477 passed, 40 warnings.
- `npm --prefix apps/web run build`: passed; TypeScript and Vite production build completed.
- Spec review: exactly three unique code commits and one DYDATA-27 documentation commit are present above `origin/main` before this verification record.
- Quality review: no blocking migration, API, frontend, documentation, or secret-handling findings; real billing identity values in the source mock were replaced with repository-safe examples.
- Original worktree: remains on `codex/commission-page-collab-20260707` with its existing untracked files preserved.
- Initial remote sync: local HEAD, tracking ref, and `git ls-remote` all matched `46dda6289b25cb5ba79784452c4d09b9789c5b95`; ahead/behind was `0/0`.

## 10. Decision Log

| Time | Decision | Reason | Evidence |
|------|----------|--------|----------|
| 2026-07-16 | Use latest `origin/main` as base | Includes already merged settlement visual PR and avoids replaying unrelated history | Branch audit |
| 2026-07-16 | Apply three unique commits, not two merge commits | Merge commits only import mainline history already present in base | `origin/main...HEAD` audit |
| 2026-07-16 | Preserve newer navigation mock from main | Original untracked mock is an older, substantially different artifact | No-index diff |
| 2026-07-16 | Sanitize billing identity examples | Repository rules prohibit committing real sensitive business details | Scoped content review |

## 11. Change Log

| Time | Change | Owner | Evidence |
|------|--------|-------|----------|
| 2026-07-16 | Initial active spec created | Controller | DYDATA-27 and Git audit |
| 2026-07-16 | Recorded passing tests, build, spec review, and quality review | Controller | Verification commands above |
| 2026-07-16 | Created the remote integration branch and verified initial SHA equality | Controller | `git push -u`, `git fetch`, `git ls-remote` |
