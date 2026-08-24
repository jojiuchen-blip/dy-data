# DYDATA-19 G2 Controller Spec

Status: Completed
Date: 2026-08-24
Controller: Codex main agent
Branch: `codex/dydata-19-page-loop`

## 1. User Goal

Implement every G2a/G2b/G2c/G2d requirement in `docs/plans/dydata-19-task-g2-brief.md` with TDD in the current dirty worktree. Preserve the closed G1 implementation and do not enter G3, commit, push, deploy, reset, or checkout.

## 2. Scope

Included:

- One new reversible single-head Alembic migration after `0040`.
- `SapSuggestion`, explicit profile source with nullable import batch, reversal batch/row lineage, and immutable management carry-forward applications.
- One backend management invoiceable projection used by validation, direct correction, imports, reversals, lists, and metrics.
- G2a management direct correction API/UI.
- G2b store SAP suggestion and administrator confirm/correct/reject API/UI.
- G2c four-template per-business-key VALUE/TOMBSTONE reversal API/UI.
- G2d deterministic management negative carry-forward and immutable application history.
- Focused API, migration, frontend contract, build, diff, and browser evidence.

Excluded:

- G1 behavior or migration changes, including `0037`-`0040`.
- G3 order-detail projection, export, snapshot migration, or release gate work.
- Production data, deployment, commit, push, reset, checkout, and broad formatting.

Scope control rule: any required change to G1 semantics or G3 files stops this task and is reported instead of implemented.

## 3. Work Ledger

| Task | Role | Write set | Status | Acceptance evidence |
|---|---|---|---|---|
| G2-M | Controller implementer | `alembic/versions/0041*`, models, migration tests | completed | 0041/0042 single-head and reversible migration coverage |
| G2-P | Controller implementer | dashboard projection and focused API tests | completed | deterministic shared invoiceable projection |
| G2a | Controller implementer | dashboard, finance fee page/client/types/tests | completed | permission/version/idempotency/history/audit coverage |
| G2b | Controller implementer | dashboard, stores page/client/types/tests | completed | store scope, immutable decision versions, actions/search/audit |
| G2c | Controller implementer | dashboard, imports page/client/types/tests | completed | four templates, VALUE/TOMBSTONE, atomic conflict/replay |
| G2d | Controller implementer | dashboard/models/tests and shared UI projection | completed | continuous negatives, multi-positive, zero, locked carry, reproject |
| Review | Independent reviewer | read-only diff review | completed | no Critical/Important; Ready: Yes |
| Verify | Controller verifier | read-only commands/browser artifacts | completed | 104 related tests, build, Alembic head, diff check |

## 4. Acceptance Gates

1. Every new behavior starts with a focused failing test whose failure is caused by missing G2 behavior.
2. The migration is single-head, reversible, non-destructive, and preserves all history.
3. Every write has backend authorization, optimistic concurrency, idempotency, one transaction, immutable versions, and audit evidence.
4. Import reversal validates every target business key before writing any reversal facts.
5. Management import, direct correction, list, metrics, and reversal use the same invoiceable projection.
6. Frontend supplies loading/success/failure/conflict/retry states and never calculates financial truth.
7. Required focused API/migration/frontend/build/browser/diff checks are freshly GREEN.

## 5. Decision Log

| Decision | Reason | Evidence |
|---|---|---|
| Continue in `.worktrees/dydata-19-page-loop` | It contains the G1 implementation and the only G2 brief; main checkout is unrelated and dirty | `git worktree list`, `git status`, brief path |
| Append migration `0041`; do not edit `0037`-`0040` | Preserve closed G1 and shared migration history | user scope and database rules |
| Use independent implementation and review agents with controller verification | Agent tooling became available; independent review found and closed the PostgreSQL lock-order defect | review reports and lock-order regression test |
| Acquire finance-import version slot before business-target locks in commit and reversal | A single global lock order avoids PostgreSQL deadlocks | focused RED/GREEN test and final independent review |
