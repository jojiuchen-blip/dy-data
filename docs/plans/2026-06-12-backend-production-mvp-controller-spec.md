# Backend Production MVP Controller Spec

Status: Active
Date: 2026-06-12
Controller: Codex main agent
Repo / workspace: repository root
Branch / target: codex/backend-production-mvp

## 1. User Goal

Deliver a production-ready MVP for the Douyin settlement dashboard backend, with agent-orchestrated implementation, testing, review, minimal fixes, commit, push, and remote branch confirmation.

The production MVP must run on Linux Docker Compose with PostgreSQL, FastAPI, worker jobs, the existing React frontend, and a protected noVNC Chromium browser for Douyin backend exports.

## 2. Current Evidence

| Area | Evidence | Source | Confidence | Notes |
| --- | --- | --- | --- | --- |
| Backend | No FastAPI app, ORM, migrations, Docker, or pytest suite exists yet. | `rg --files`, `requirements.txt` | High | Current repo is script and frontend mock oriented. |
| Data contract | First-round data model exists and supports one-row-per-coupon detail modeling. | `docs/data-model.md` | High | Needs v1 cleanup for no invoice/refund display. |
| API contract | Page 1/2/3 contract exists. | `docs/api-contract.md` | High | Needs v1 cleanup and metadata endpoint. |
| Frontend | React/Vite app exists but reads synchronous mock files. | `apps/web/src/data/mockData.ts` | High | Needs API client, loading/error state, and pagination. |
| Browser export | Edge export branch exists but is Windows-oriented. | `origin/codex/backend-aweme-edge-export` | High | Needs Linux Chromium/noVNC adaptation. |

## 3. Scope

Included:
- PostgreSQL schema and migrations for raw, dimension, settlement, aggregate, job, and exception data.
- FastAPI `/api/v1` query, auth, export, metadata, and job-status endpoints.
- Worker commands for 2026-onward ingest, idempotent settlement rebuilds, and daily scheduling.
- Frontend API integration replacing production mock data usage.
- Linux Docker Compose deployment with API, worker, frontend, PostgreSQL, proxy, and protected noVNC browser service.
- Tests, build checks, independent spec review, code quality review, minimal fixes, commit, push, and remote confirmation.

Excluded:
- Refund API ingestion in v1.
- Invoice, OCR, finance approval, and final financial receivable workflow in v1.
- Committing real business data, credentials, cookies, browser profiles, local paths, or account configuration.
- Changing unrelated legacy exploration scripts unless required for the production path.

Scope control rule:
- Any request to expose noVNC publicly, add refund API, add invoice workflow, or commit real data requires explicit user approval and a controller spec update.

## 4. Decisions And Assumptions

| ID | Item | Resolution |
| --- | --- | --- |
| D1 | Production runtime | Linux Docker Compose on one cloud server. |
| D2 | Auth | Single administrator login protects frontend, API, and noVNC entry. |
| D3 | Data range | Initial backfill starts at `2026-01-01 00:00:00 Asia/Shanghai`. |
| D4 | Douyin accounts | One Douyin Laike account for v1. |
| D5 | Invoice | Hidden from v1 API and frontend. Deferred to v2. |
| D6 | Refund display | Hidden from v1 API and frontend. Refund is internal exclusion/status logic only. |
| D7 | Page 2 receivable | Product label is `预计应收分佣`; API field is `estimated_receivable_commission_cent`. |
| D8 | Owner matching | ID first, nickname fallback, unmatched/conflict rows go to exceptions. |
| D9 | Sales count | `sales_order_count` is distinct order count; coupon count is a separate metric when needed. |
| D10 | noVNC | Browser login entry is routed behind the same administrator auth. |

## 5. Work Breakdown

| Task ID | Role | Responsibility | Write Set | Acceptance Gate |
| --- | --- | --- | --- | --- |
| T1 | Implementer | Contract and controller spec updates. | `docs/`, `mock/` if needed | Deferred invoice/refund display only appears in risk/deferred notes. |
| T2 | Implementer | Database schema, migrations, DB helpers, seed/import helpers. | `apps/api`, `alembic`, `tests` | Migrations run on test DB and uniqueness constraints exist. |
| T3 | Implementer | Worker ingest, settlement materialization, idempotency, job logging. | `apps/worker`, `src/dy_data`, `tests` | Repeated fixture ingest does not duplicate rows; exceptions are generated. |
| T4 | Implementer | FastAPI auth, dashboard APIs, export, metadata, recent jobs. | `apps/api`, `tests` | Unauthenticated calls 401; authenticated API responses match contract. |
| T5 | Implementer | Frontend API client, v1 field cleanup, pagination, loading/error states. | `apps/web/src` | `npm run build` passes and no invoice/refund UI fields remain. |
| T6 | Implementer | Docker Compose, proxy, browser/noVNC container, deployment docs. | `deploy`, Dockerfiles, docs | Compose config validates; noVNC path is protected by auth/proxy design. |
| T7 | Spec Reviewer | Check implementation against this spec. | Read-only | No missing required behavior or extra scope. |
| T8 | Code Reviewer | Check bugs, security, data handling, tests, maintainability. | Read-only | No blocking findings. |
| T9 | Minimal-Fix Worker | Fix confirmed review issues only. | Controller-assigned | Targeted review passes after each fix. |

## 6. Subagent Rules

- Workers are not alone in the codebase and must not revert unrelated edits.
- Workers must stay inside their write set and report collisions instead of overwriting others.
- Worker output must include files changed, commands run, test results, assumptions, and risks.
- Spec review must pass before code quality review.
- Minimal fixes must be narrow and re-reviewed.
- Final acceptance stays with the controller.

## 7. Verification Plan

| Gate | Command / Method | Required For Done |
| --- | --- | --- |
| Dirty state | `git status --short --branch` | Yes |
| Whitespace/diff | `git diff --check` | Yes |
| Python tests | `pytest` | Yes |
| Frontend build | `npm run build` in `apps/web` | Yes |
| Secret scan | `rg` for real secrets/local profiles/download paths in tracked files | Yes |
| Contract cleanup | Search for deferred invoice/refund display fields; matches must be limited to risk/deferred notes or internal exclusion fields. | Yes |
| DB gate | Migration and idempotent fixture ingest tests | Yes |
| API smoke | Login, protected endpoints, filters, export | Yes |
| Docker gate | Compose config validation/build where environment allows | Yes |
| Browser gate | noVNC protected route design and job failure logging tests/docs | Yes |

## 8. Final Acceptance Checklist

- [ ] User goal satisfied without narrowing scope.
- [ ] Scope and non-goals respected.
- [ ] All worker outputs reviewed by controller.
- [ ] Spec review passed.
- [ ] Code quality review passed or residual risks documented.
- [ ] Required tests/build/checks run or exact blockers documented.
- [ ] Diff reviewed for unrelated changes.
- [ ] Working tree status understood.
- [ ] Commit hash recorded.
- [ ] Branch pushed and remote branch confirmed.

## 9. Decision Log

| Time | Decision | Reason | Evidence |
| --- | --- | --- | --- |
| 2026-06-12 | Use `estimated_receivable_commission_cent` / `预计应收分佣`. | Invoice workflow is v2; v1 cannot present final financial receivable. | User confirmation. |
| 2026-06-12 | Hide refund fields in v1 UI/API. | Refund API is not used and refund amount display risks overclaiming. | User confirmation. |
| 2026-06-12 | Protect noVNC with administrator auth. | Browser session is equivalent to Douyin backend access. | User confirmation. |

## 10. Change Log

| Time | Change | Owner | Evidence |
| --- | --- | --- | --- |
| 2026-06-12 | Controller spec created. | Controller | This file. |
