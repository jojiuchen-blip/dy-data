# DYDATA-19 T5.1—T5.6 Controller Spec

Status: Active for historical T5 controller evidence; release authorization superseded by the 2026-08-24 T5.7 decision below
Date: 2026-08-21
Controller: Codex
Repo / workspace: `.`
Historical branch / target: `codex/dydata-19-page-loop`; current release integration is handled by `codex/dydata-19-main-integration`

## 1. User Goal

Complete DYDATA-19 T5.1 through T5.6 and close every release blocker found by T5.7 system acceptance against the current Linear description: Foundation migrations, backend business APIs, production pages, integration, system test, UAT/release preparation and a release-review package. The original release-review confirmation boundary is retained as historical evidence; the current 2026-08-24 user instruction authorizes production migration and deployment directly after every hard gate passes, with any failed gate stopping release.

## 2. Current Evidence

| Area | Evidence | Source | Confidence | Notes |
|---|---|---|---|---|
| Requirement | Multi-period promotion invoice allocations are required; management invoices remain one store plus one month | Linear DYDATA-19 §4–§5 | High | Overrides legacy single-period promotion invoice assumptions |
| Foundation | Statement version chain has been reconciled and Phase 5 checks were recorded | `docs/prd/foundation/` | High | `S4-FCR-001` is implemented |
| T5.1/T5.2 | Schema/version migrations and store-billing APIs have committed evidence | `768ef0b`, `289ae88`, `d7ff30c` | Medium | Re-verify before final acceptance |
| T5.3 | Finance query implementation and its tests are in the active worktree | `apps/api/dy_api/routes/dashboard.py`, `tests/test_api_store_billing.py` | Medium | Do not overwrite concurrent edits |
| T5.6 gate | API 238 passed; migration/data 72 passed; frontend contracts 110 passed; DYDATA-19 browser matrix 24 passed | 2026-08-21 local verification | High | Full-suite combined commands timed out without a pytest verdict |
| Requirement gap | Linear requires additional invoice lifecycle, cutoff, SAP, reversal and order-detail behavior not represented in the frozen T5.2–T5.6 subplans | Linear DYDATA-19 §§4–8 versus current code/PRD | High | User confirmed continuing with Linear as authority |

## 3. Scope

Included:

- T5.1 through T5.6 plus T5.7-discovered release-blocker closure, including Foundation reconciliation, migrations, APIs, pages, integration and preparation evidence.
- Locked-period refund/cancellation carry-forward sources and applications, followed by promotion/management invoice projections.
- Promotion invoice buyer/tax facts, settlement-batch cutoff, immutable red-flush/void/replacement lifecycle and negative-period carry-forward.
- Management invoice direct correction, SAP suggestion/confirmation, import reversal batches and full finance-order drill-down/filter/export contract.
- Per-task updates to delivery plans, execution plan, development log and Linear verification record.
- Technical, system and business/UAT preparation gates.

Excluded:

- Unrelated T5.7 work outside DYDATA-19 release blockers.
- Unrelated production-data changes outside the migration and deployment required by DYDATA-19.
- The known 16 visual permission-fixture failures; they remain a separately tracked, non-blocking follow-up.

Scope control rule: pause for a newly discovered requirement conflict, irreversible migration risk, business rule decision or production permission. All other work proceeds autonomously.

## 4. Assumptions and Open Questions

| ID | Item | Type | Owner | Resolution |
|---|---|---|---|---|
| A1 | Promotion invoice may allocate one invoice across multiple full periods; no cross-store allocation | Confirmed rule | Linear DYDATA-19 | Implement through invoice allocation records and exact sums |
| A2 | T5.3 active edits belong to the current scoped effort | Assumption | Controller | Preserve and verify; do not revert or overwrite |
| A3 | Production migration and deployment require fresh confirmation after all hard gates pass | Historical boundary | User | Superseded on 2026-08-24 by the explicit instruction to proceed automatically after all hard gates pass; any failed gate still stops release |
| A4 | Linear current description overrides narrower SubPRD/T5 task wording | Confirmed rule | User | Implement the Linear gaps and update downstream specs/evidence |

## 5. Work Breakdown

| Task ID | Role | Owner | Responsibility | Write Set | Acceptance Gate |
|---|---|---|---|---|---|
| C1 | Controller | Codex | Reconcile FCR-002 and finish Foundation delivery | Foundation docs only | Crosscheck and Foundation route gate pass |
| T5.1/T5.2 | Verifier | Codex | Re-verify committed migrations and store-billing behavior | Tests and evidence only unless defects found | Scoped regression and migration checks pass |
| T5.3 | Implementer/Verifier | Codex | Finish finance queries and order drill-down | Existing T5.3 write set only | Sub-plan completion checks pass |
| T5.4 | Implementer/Verifier | Codex | Dispute lifecycle and version switching | T5.4 write set only | API, concurrency and audit tests pass |
| T5.5 | Implementer/Verifier | Codex | Four import types, corrections and error download | T5.5 write set only | Atomicity, idempotency and pagination tests pass |
| T5.6 | Implementer/Verifier | Codex | Production finance pages and cross-page flow | Web routes/components/tests only | Build and browser integration pass |
| R1 | Controller | Codex | Three-layer acceptance and release-review preparation | Plans, devlog, Linear verification, release checklist and rollback evidence | No blocking gate failures; release review ready for Owner decision |
| G0 | Explorer/Implementer | Worker + Codex | Persist and apply locked-period refund/cancellation carry-forward sources | Settlement worker, carry-forward models/migrations/data tests | Linear §3/§6 cross-period adjustments reach the next eligible period without history mutation |
| G1 | Explorer/Implementer | Worker + Codex | Promotion invoice buyer/tax, cutoff/batch, immutable lifecycle and carry-forward | Invoice models/migrations/dashboard routes/store invoice page/tests | Linear §4 and acceptance #4 covered by red-green tests; G1c depends on G0 |
| G2 | Explorer/Implementer | Worker + Codex | Management direct correction, SAP suggestion/confirmation and import reversal | Finance profile/import models/routes/pages/tests | Linear §§3/5/6 and acceptance #3/#5/#6 covered |
| G3 | Explorer/Implementer | Worker + Codex | Freeze historical store/SAP snapshots and complete finance order-detail data, filters, export and UI | Statement snapshot models/migration/worker, finance query route/client/types/page/tests | Linear §7/§8 and acceptance #8/#9/#10 covered |
| G4 | Reviewer/Verifier | Worker + Codex | Cross-slice spec review, quality review and system/UAT release package | Read-only review plus plans/devlog/Linear | No open blocking findings; production remains gated on fresh Owner confirmation |

## 6. Review Plan

For each T5 task: read sub-plan, add/verify red-green tests for new behavior, inspect scoped diff, run the task checks, record Foundation drift, update plan/devlog/Linear, then re-run relevant regression. The controller performs final spec and quality review across all T5.1—T5.6 changes.

## 7. Verification Plan

| Gate | Method | Required |
|---|---|---|
| Technical acceptance | Targeted pytest, Alembic upgrade/downgrade or offline PostgreSQL DDL, API contract tests, `git diff --check` | Yes |
| System acceptance | API integration tests, web build, browser route checks and cross-page flow | Yes |
| Business/UAT preparation | Given/When/Then checklist, role/data fixtures, current/history/audit evidence and release/rollback plan | Yes |
| Known visual fixtures | Record separately; 16 permission-fixture failures do not fail DYDATA-19 gates | Yes |
| Production release | Authorized after all hard gates pass; no additional confirmation is required; retain CI, migration, backup, deploy, smoke and rollback evidence | Yes |

## 8. Decision Log

| Time | Decision | Reason | Evidence |
|---|---|---|---|
| 2026-08-21 | Treat DYDATA-19 description as the requirement authority for multi-period promotion invoices | Current Linear body supersedes legacy Foundation wording | Linear DYDATA-19 §4 |
| 2026-08-24 | Do not execute production release in this task | Owner explicitly requires a fresh confirmation after T5.6/release preparation | Latest user instruction |
| 2026-08-24 | Supersede the prior release-review stop and proceed automatically after hard gates | User explicitly instructed the workflow to continue through production deployment without another confirmation; failed gates remain blocking | Latest user instruction in the active T5.7 conversation |
| 2026-08-21 | Expand T5.7 blocker closure to the full current Linear body | User replied “继续” after the controller reported the narrowed-plan conflict | User confirmation and Linear DYDATA-19 §§4–8 |
| 2026-08-21 | Add G0 and historical snapshot gates before invoice/order-detail release closure | Independent spec review proved current worker skips locked-period adjustments and current master data cannot satisfy historical acceptance | `dydata-19-task-g0-carryforward-source-brief.md`, G1c/G2/G3 review findings |
