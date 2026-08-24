# DYDATA-19 G1a — 推广费登记字段与结算批次

Status: Active
Owner: G1a implementer; controller reviews and integrates

## Goal

Close the first Linear §4 release blocker with TDD: promotion-invoice registration must persist and return the fixed buyer, 6% tax rate, and the settlement batch derived from the server validation time in Beijing.

## Binding requirements

- Buyer name: `比亚迪汽车销售有限公司`.
- Buyer taxpayer ID displayed by the production page: `914403007604674476`.
- Submitted API fields: `buyerName` and `taxRatePercent`; both required. Buyer must equal the fixed name and tax rate must be integer `6`.
- Registration success time is the server `utcnow()` converted to `Asia/Shanghai`.
- Beijing day 1 through day 10 inclusive (therefore day 10 `23:59:59`) maps to the previous calendar month settlement batch; day 11 `00:00:00` onward maps to the current calendar month.
- A multi-period invoice has one registration time, therefore all of its allocation rows receive the same `settlementBatchMonth`.
- Existing immutable version/idempotency/allocation rules remain unchanged.
- API JSON remains camelCase through the existing response wrapper.

## Data changes

- Add immutable promotion-invoice facts for buyer and tax rate.
- Add `settlement_batch_month` to each promotion-invoice allocation.
- Create the next single-head reversible Alembic migration after `20260821_0036`; backfill existing rows deterministically and do not delete data.

## TDD gates

1. Add tests that fail because buyer/tax/batch behavior is missing.
2. Verify the red failure is the missing behavior, not a test error.
3. Implement minimal backend/model/migration behavior.
4. Update all existing promotion-invoice request fixtures to the new required contract.
5. Add production-page/client/type fields and user-facing fixed buyer/tax display.
6. Run focused API tests, migration tests, frontend user-facing contracts, TypeScript/Vite build, and `git diff --check`.

## Write set

- `apps/api/dy_api/models.py`
- `apps/api/dy_api/routes/dashboard.py`
- one new `alembic/versions/20260821_0037_*.py`
- `apps/web/src/api/client.ts`
- `apps/web/src/types/dashboard.ts`
- `apps/web/src/pages/StoreInvoicePage.tsx`
- `tests/test_api_store_billing.py`
- `tests/test_api_finance_imports.py` only if existing promotion fixtures require it
- `tests/test_alembic_migrations.py`
- `tests/test_frontend_user_facing_contracts.py`
- `tests/test_visual_smoke.py` only for the live production-page payload/fixture contract

## Non-goals

- No red-flush/void/replacement endpoint in this slice.
- No negative-period carry-forward in this slice.
- No management-fee, SAP, import reversal or finance-order-detail changes.
- No production migration, deployment, commit, push, reset, checkout or broad formatting.
- Never revert or overwrite unrelated concurrent edits.

## Required report

Return `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT` or `BLOCKED`, followed by changed files, the exact red and green commands/results, self-review findings and remaining risks.
