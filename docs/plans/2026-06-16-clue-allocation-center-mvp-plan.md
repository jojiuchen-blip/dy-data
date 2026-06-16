# Clue Allocation Center MVP Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the MVP "线索跟进分配中心" from `raw_douyin_clues`, including order-level clue center data, assignment-round details, admin reallocation-rule configuration, API contracts, and a read-only dashboard UI.

**Architecture:** Keep `raw_douyin_clues` as the immutable raw source. Add a derived order-level clue table for dashboard reads and a round-level assignment table for follow-up/reassignment history; rebuild them idempotently from raw clues, SKU rules, settlement details, and admin SLA configuration. Expose read-only clue dashboard APIs plus authenticated admin rule APIs; frontend adds a clue center page and a clue reallocation-rule admin page.

**Tech Stack:** Python, FastAPI, SQLAlchemy ORM, Alembic, PostgreSQL/SQLite tests, pytest, React, TypeScript, Vite.

---

## Confirmed MVP Scope

- Data source is `raw_douyin_clues`.
- A clue is an order that is still `order_status = '履约中'` and has a valid `order_id`.
- Exclude blank `order_id` and `order_id = '0'`.
- MVP order grain is one row per `order_id`; keep `source_clue_ids` and `source_clue_count` because existing data has a small number of duplicate `order_id` clue rows.
- First assignment store comes from `follow_life_account_id` and `follow_life_account_name`.
- MVP `assigned_at` equals clue generation time: `raw_douyin_clues.create_time_detail`.
- Product type comes from `raw_douyin_clues.product_id = dim_sku_product_rules.sku_id`.
- Follow result enum:
  - `pending`: 未跟进
  - `success`: 成功跟进
  - `failed`: 跟进失败，进入待再分配
  - `unreachable`: 未接通，算已跟进，不算成功
  - `continue_following`: 继续跟进中，算已跟进，不算成功
- MVP does not allow frontend/manual editing of follow result.
- SLA duration is not hardcoded. Add an admin configuration page for reallocation rules.
- If no SLA is configured:
  - `expires_at = null`
  - `remaining_reassign_seconds = null`
  - "距离再分配剩余时间" is blank
  - no automatic `expired_pending_reassign`
- Verification matching:
  - `clue_center.order_id = settlement_order_details.order_id`
  - self-store verification is `assigned_store_id = settlement_order_details.verify_store_id`
- Self-store verification ratio:
  - denominator: total clues assigned to the store
  - numerator: clues assigned to the store where follow result is `success` and the order is verified at the same store
- Phone display is masked plaintext with the middle four digits hidden, for example `138****5678`.
- The dashboard is read-only in MVP.

## Non-Goals

- No actual multi-round reallocation algorithm yet.
- No distance/latitude/longitude based reallocation yet.
- No manual follow-result editing in the UI.
- No full plaintext phone number in API responses or frontend state.
- No Railway config changes.
- No GitHub Actions changes unless a later deployment task explicitly requires them.
- No direct mutation of `raw_douyin_clues` payloads.

## Technical Risk To Handle First

`raw_douyin_clues` already exists in the deployed Railway database because the local export was uploaded manually, but the repo currently has no model or Alembic migration for it. The implementation must codify `raw_douyin_clues` in `apps/api/dy_api/models.py` and add an idempotent migration that does not fail when the table already exists online.

Use SQLAlchemy inspection in the migration before creating this table. Do not write a plain `op.create_table("raw_douyin_clues", ...)` that would fail on Railway.

---

## Data Model

### `raw_douyin_clues`

Codify the existing raw table. Keep it raw-source oriented; do not make it the frontend read model.

Required fields for MVP:

- `clue_row_key text primary key`
- `clue_id text`
- `source_window_start timestamptz`
- `source_window_end timestamptz`
- `fetched_at timestamptz`
- `create_time_detail timestamptz`
- `modify_time timestamptz`
- `telephone text`
- `enc_telephone text`
- `product_id text`
- `product_name text`
- `order_id text`
- `order_status text`
- `follow_life_account_id text`
- `follow_life_account_name text`
- `auto_city_name text`
- `auto_province_name text`
- `author_nickname text`
- `raw_payload jsonb`

### `clue_center_orders`

Order-level direct source for the clue dashboard.

Recommended fields:

- `order_id text primary key`
- `source_clue_ids jsonb not null default []`
- `source_clue_count integer not null default 0`
- `canonical_clue_id text`
- `lead_status text not null`
- `current_assignment_round_id text`
- `current_round_no integer not null default 1`
- `current_round_status text not null`
- `assigned_at timestamptz`
- `assigned_at_source text not null default 'clue_create_time_detail'`
- `assigned_store_id text`
- `assigned_store_name text`
- `assigned_city text`
- `assigned_province text`
- `phone_masked text`
- `phone_source text`
- `product_id text`
- `product_name text`
- `product_type text`
- `author_nickname text`
- `follow_result text not null default 'pending'`
- `is_followed boolean not null default false`
- `is_follow_success boolean not null default false`
- `verified_store_id text`
- `verified_store_name text`
- `verified_at timestamptz`
- `is_self_store_verified boolean not null default false`
- `expires_at timestamptz`
- `reassign_reason text`
- `updated_at timestamptz not null`

Indexes:

- `assigned_store_id`
- `assigned_at`
- `lead_status`
- `current_round_status`
- `product_type`
- `assigned_city`
- `is_self_store_verified`

### `clue_assignment_rounds`

Round-level detail table. This is the source for assignment history.

Recommended fields:

- `assignment_round_id text primary key`
- `order_id text not null`
- `round_no integer not null`
- `assigned_at timestamptz`
- `assigned_at_source text not null default 'clue_create_time_detail'`
- `assigned_store_id text`
- `assigned_store_name text`
- `followed_at timestamptz`
- `follow_result text not null default 'pending'`
- `is_followed boolean not null default false`
- `is_follow_success boolean not null default false`
- `round_status text not null`
- `expires_at timestamptz`
- `reassign_reason text`
- `reassigned_at timestamptz`
- `verified_store_id text`
- `verified_store_name text`
- `verified_at timestamptz`
- `is_self_store_verified boolean not null default false`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`

Constraints and indexes:

- unique `(order_id, round_no)`
- index `order_id`
- index `assigned_store_id`
- index `assigned_at`
- index `round_status`
- index `follow_result`

### `clue_reassign_rule_settings`

Global MVP admin configuration for reallocation timing.

Recommended fields:

- `setting_key text primary key` with singleton value `global`
- `reassign_sla_hours integer null`
- `updated_by text`
- `updated_at timestamptz not null`

Rules:

- `reassign_sla_hours = null` means SLA is not configured.
- When SLA is null, do not compute expiration or remaining time.
- Later versions can add city/store-specific rules without changing this MVP dashboard contract.

---

## Status Definitions

### `lead_status`

- `active`: order is still `履约中` and current round is active.
- `pending_reassign`: current round is failed or expired and no next round exists.
- `converted`: order has successful follow and self-store or other-store verification.
- `closed`: order is no longer eligible as a clue.

MVP dashboard mainly reads `active` and `pending_reassign`.

### `round_status`

- `active_unfollowed`: no follow action, still within SLA window or SLA is not configured.
- `active_followed`: followed with `success`, `unreachable`, or `continue_following`, and not reassigned.
- `failed_pending_reassign`: follow result is `failed`.
- `expired_pending_reassign`: SLA exists, now is after `expires_at`, and there is no follow action.
- `reassigned`: a later round exists.

### Follow Calculations

```text
is_followed =
follow_result in ('success', 'failed', 'unreachable', 'continue_following')

is_follow_success =
follow_result = 'success'
```

### SLA Calculations

```text
if reassign_sla_hours is null:
    expires_at = null
    remaining_reassign_seconds = null
    no automatic timeout

if reassign_sla_hours is not null:
    expires_at = assigned_at + reassign_sla_hours
    remaining_reassign_seconds = max(0, expires_at - now)
```

### Phone Masking

```text
13812345678 -> 138****5678
```

Rules:

- Return only `phone_masked` to the frontend.
- Do not return `telephone` or full decrypted phone in dashboard APIs.
- If phone is blank or malformed, return an empty string.

---

## API Contract

### Public dashboard endpoints

Add a clue route module:

```text
apps/api/dy_api/routes/clues.py
```

Include it in:

```text
apps/api/dy_api/main.py
```

Endpoints:

```http
GET /api/v1/clues/filters
GET /api/v1/clues/overview
GET /api/v1/clues/assignment-rounds
```

`GET /api/v1/clues/filters` returns:

- assigned stores
- assigned cities
- product types
- lead statuses
- round statuses

`GET /api/v1/clues/overview` query params:

- `assigned_store_id`
- `assigned_date_start`
- `assigned_date_end`
- `lead_status`
- `round_status`
- `product_type`
- `city`

Returns:

- `total_clues`
- `active_clues`
- `follow_rate`
- `follow_success_rate`
- `self_store_verify_rate`
- `pending_reassign_count`

`GET /api/v1/clues/assignment-rounds` query params:

- all overview filters
- `page`
- `page_size`

Returns rows:

- `assignment_round_id`
- `order_id`
- `round_no`
- `lead_status`
- `round_status`
- `assigned_at`
- `expires_at`
- `remaining_reassign_seconds`
- `assigned_store_id`
- `assigned_store_name`
- `phone_masked`
- `product_type`
- `author_nickname`
- `followed_at`
- `follow_result`
- `reassign_reason`
- `reassigned_at`
- `verified_store_id`
- `verified_store_name`
- `verified_at`
- `is_self_store_verified`

### Admin endpoints

Extend:

```text
apps/api/dy_api/routes/admin.py
```

Endpoints:

```http
GET /api/v1/admin/clue-reassign-rule
PUT /api/v1/admin/clue-reassign-rule
POST /api/v1/admin/clues/rebuild
```

`GET /api/v1/admin/clue-reassign-rule` returns:

- `reassign_sla_hours`
- `updated_at`
- `updated_by`

`PUT /api/v1/admin/clue-reassign-rule` body:

```json
{
  "reassign_sla_hours": null
}
```

Validation:

- `null` is allowed and means not configured.
- integer values must be between `1` and `168`.

`POST /api/v1/admin/clues/rebuild` queues or runs a rebuild of clue center tables.

---

## Frontend Scope

### Home page

Modify:

```text
apps/web/src/pages/HomePage.tsx
```

Change the "线索跟进分配中心" card from planned to active and link it to:

```text
/clues
```

### Dashboard page

Create:

```text
apps/web/src/pages/ClueCenterPage.tsx
```

Route in:

```text
apps/web/src/App.tsx
```

UI sections:

- filter bar:
  - assigned store
  - assigned date range
  - lead status
  - product type
  - city
- metrics:
  - 线索总数
  - 有效线索总数
  - 跟进比例
  - 跟进成功率
  - 自店核销比例
- detail table:
  - assignment round ID
  - lead status
  - round status
  - assigned at
  - remaining reassign time
  - assigned store
  - store ID
  - masked phone
  - product type
  - author nickname
  - followed at
  - follow result
  - reassigned at
  - self-store verified

### Admin rule page

Create:

```text
apps/web/src/pages/AdminClueRulePage.tsx
```

Route:

```text
/admin/clues/rules
```

Modify:

```text
apps/web/src/pages/AdminHomePage.tsx
apps/web/src/App.tsx
apps/web/src/api/client.ts
apps/web/src/types/dashboard.ts
```

UI behavior:

- Auth required through existing admin session flow.
- Show current SLA value.
- Allow blank/null SLA.
- Save via `PUT /api/v1/admin/clue-reassign-rule`.
- Show helper text: "未配置时不会自动进入超时待再分配，距离再分配剩余时间为空。"

---

## Implementation Tasks

### Task 0: Start Gate

**Files:**
- Read only: repository state

**Step 1: Sync main**

Run:

```powershell
git checkout main
git pull --ff-only
git status --short --branch
```

Expected: clean `main`. If not clean, stop and report changed files. Do not overwrite or revert unrelated work.

**Step 2: Confirm raw clue data exists locally or in DB**

Run a non-sensitive count check against the target DB or test fixture. Do not print phone numbers, full raw payloads, database URLs, tokens, or secrets.

Expected: `raw_douyin_clues` is available before dashboard rebuild work starts.

### Task 1: Add Schema Models And Idempotent Migration

**Files:**
- Modify: `apps/api/dy_api/models.py`
- Create: `alembic/versions/20260616_0003_clue_center_mvp.py`
- Modify: `tests/test_data_schema.py`

**Step 1: Write failing schema tests**

Add expected tables:

```python
expected_tables = {
    "raw_douyin_clues",
    "clue_center_orders",
    "clue_assignment_rounds",
    "clue_reassign_rule_settings",
}
```

Add primary key assertions:

```python
assert [column.name for column in tables["raw_douyin_clues"].primary_key] == ["clue_row_key"]
assert [column.name for column in tables["clue_center_orders"].primary_key] == ["order_id"]
assert [column.name for column in tables["clue_assignment_rounds"].primary_key] == ["assignment_round_id"]
assert [column.name for column in tables["clue_reassign_rule_settings"].primary_key] == ["setting_key"]
```

Run:

```powershell
python -m pytest tests/test_data_schema.py -v
```

Expected: fails because tables are missing.

**Step 2: Implement models**

Add ORM classes:

- `RawDouyinClue`
- `ClueCenterOrder`
- `ClueAssignmentRound`
- `ClueReassignRuleSetting`

Use existing `JSON_TYPE` and `utcnow()`.

**Step 3: Add idempotent Alembic migration**

Use SQLAlchemy inspection:

```python
from sqlalchemy import inspect

bind = op.get_bind()
inspector = inspect(bind)
if not inspector.has_table("raw_douyin_clues"):
    op.create_table(...)
```

Apply the same pattern to the new derived tables. For indexes, check existing index names before creating them, or use dialect-safe `CREATE INDEX IF NOT EXISTS` only when the dialect supports it.

**Step 4: Verify**

Run:

```powershell
python -m pytest tests/test_data_schema.py -v
```

Expected: pass.

**Step 5: Commit**

```powershell
git add apps/api/dy_api/models.py alembic/versions/20260616_0003_clue_center_mvp.py tests/test_data_schema.py
git commit -m "feat: add clue center schema"
```

### Task 2: Add Clue Center Rebuild Service

**Files:**
- Create: `apps/worker/clue_center.py`
- Modify: `tests/test_worker_clue_center.py`

**Step 1: Write failing tests**

Cover:

- eligible clue rows are filtered by `order_status = "履约中"` and valid `order_id`
- duplicate `order_id` raw clues produce one `clue_center_orders` row
- first assignment uses the earliest `create_time_detail`
- product type joins through `dim_sku_product_rules`
- first assignment round ID is `order_id + "-1"`
- no SLA means `expires_at` is `None`
- SLA config generates `expires_at`
- `failed` follow result produces `failed_pending_reassign`
- `unreachable` counts as followed but not success
- masked phone never returns full phone

Run:

```powershell
python -m pytest tests/test_worker_clue_center.py -v
```

Expected: fails because service does not exist.

**Step 2: Implement rebuild function**

Create:

```python
def rebuild_clue_center(session, *, now: datetime | None = None) -> dict[str, int]:
    ...
```

Behavior:

- query eligible `RawDouyinClue`
- group by `order_id`
- choose canonical clue row by earliest `create_time_detail`, then `clue_id`
- store all `source_clue_ids`
- create or update `ClueCenterOrder`
- create initial `ClueAssignmentRound` for `round_no = 1` if absent
- do not overwrite non-pending follow state if future code later allows edits
- join settlement details to compute `verified_store_id`, `verified_store_name`, `verified_at`, `is_self_store_verified`

**Step 3: Add helper functions**

Add helpers in the same module:

```python
def mask_phone(value: str | None) -> str:
    ...

def current_round_status(...):
    ...

def load_reassign_sla_hours(session) -> int | None:
    ...
```

**Step 4: Verify**

Run:

```powershell
python -m pytest tests/test_worker_clue_center.py -v
```

Expected: pass.

**Step 5: Commit**

```powershell
git add apps/worker/clue_center.py tests/test_worker_clue_center.py
git commit -m "feat: rebuild clue center tables"
```

### Task 3: Add Dashboard API Schemas And Store Methods

**Files:**
- Modify: `apps/api/dy_api/schemas.py`
- Modify: `apps/api/dy_api/routes/_data.py`
- Create: `tests/test_api_clues.py`

**Step 1: Write failing API data-store tests**

Test:

- filter metadata lists assigned stores and statuses
- overview returns total, active, follow rate, follow success rate, self-store verify rate
- detail endpoint paginates assignment rounds
- `remaining_reassign_seconds` is `null` when no SLA/expires_at exists
- response includes `phone_masked` but not full `telephone`

Run:

```powershell
python -m pytest tests/test_api_clues.py -v
```

Expected: fails because schemas and methods are missing.

**Step 2: Add schemas**

Add Pydantic models:

- `ClueFilterMetadata`
- `ClueOverviewMetrics`
- `ClueAssignmentRoundRow`
- `ClueAssignmentRoundData`
- `ClueReassignRuleData`
- `ClueReassignRuleUpdate`
- `ClueRebuildResult`

**Step 3: Add store methods**

In `DashboardDataStore`, add:

- `clue_filters()`
- `clue_overview(filters)`
- `clue_assignment_rounds(filters, page, page_size)`
- `get_clue_reassign_rule()`
- `save_clue_reassign_rule(payload)`

Use SQL aggregation against `clue_center_orders` and `clue_assignment_rounds`.

**Step 4: Verify**

Run:

```powershell
python -m pytest tests/test_api_clues.py -v
```

Expected: pass.

**Step 5: Commit**

```powershell
git add apps/api/dy_api/schemas.py apps/api/dy_api/routes/_data.py tests/test_api_clues.py
git commit -m "feat: add clue dashboard data contracts"
```

### Task 4: Add Clue API Routes

**Files:**
- Create: `apps/api/dy_api/routes/clues.py`
- Modify: `apps/api/dy_api/main.py`
- Modify: `apps/api/dy_api/routes/admin.py`
- Modify: `tests/test_api_clues.py`
- Create or modify: `tests/test_api_admin_clue_rules.py`

**Step 1: Write failing route tests**

Public routes:

```text
GET /api/v1/clues/filters
GET /api/v1/clues/overview
GET /api/v1/clues/assignment-rounds
```

Admin routes require login:

```text
GET /api/v1/admin/clue-reassign-rule
PUT /api/v1/admin/clue-reassign-rule
POST /api/v1/admin/clues/rebuild
```

Run:

```powershell
python -m pytest tests/test_api_clues.py tests/test_api_admin_clue_rules.py -v
```

Expected: fails because routes are missing.

**Step 2: Implement public routes**

Create `clues.py` using `get_data_store`, `generated_at`, and existing response envelope pattern.

**Step 3: Implement admin routes**

Extend `admin.py` with authenticated handlers. `POST /admin/clues/rebuild` can run a synchronous rebuild in MVP if the dataset size is acceptable for admin operations; otherwise queue a `job_runs` entry and background task.

**Step 4: Wire route in main**

Add:

```python
from dy_api.routes import clues
app.include_router(clues.router, prefix="/api/v1", tags=["clues"])
```

**Step 5: Verify**

Run:

```powershell
python -m pytest tests/test_api_clues.py tests/test_api_admin_clue_rules.py -v
```

Expected: pass.

**Step 6: Commit**

```powershell
git add apps/api/dy_api/routes/clues.py apps/api/dy_api/main.py apps/api/dy_api/routes/admin.py tests/test_api_clues.py tests/test_api_admin_clue_rules.py
git commit -m "feat: expose clue center APIs"
```

### Task 5: Add Frontend Types And API Client Methods

**Files:**
- Modify: `apps/web/src/types/dashboard.ts`
- Modify: `apps/web/src/api/client.ts`

**Step 1: Add TypeScript types**

Add:

- `ClueFilterMetadata`
- `ClueOverviewMetrics`
- `ClueAssignmentRound`
- `ClueAssignmentRoundData`
- `ClueReassignRuleData`
- `ClueReassignRuleUpdate`
- `ClueRebuildResult`

**Step 2: Add client functions**

Add:

- `fetchClueFilters`
- `fetchClueOverview`
- `fetchClueAssignmentRounds`
- `fetchClueReassignRule`
- `saveClueReassignRule`
- `rebuildClues`

**Step 3: Verify TypeScript**

Run:

```powershell
npm --prefix apps/web run build
```

Expected: may fail until pages are implemented; type errors should guide next tasks.

### Task 6: Build Read-Only Clue Center Page

**Files:**
- Create: `apps/web/src/pages/ClueCenterPage.tsx`
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/pages/HomePage.tsx`
- Modify: `apps/web/src/styles.css`

**Step 1: Implement route**

Route `/clues` to `ClueCenterPage` inside `Shell`.

**Step 2: Activate home card**

Update "线索跟进分配中心" card to link to `/clues`.

**Step 3: Build UI**

Use existing patterns:

- `MetricCard`
- `DataTable`
- `Filters`
- `SearchableStoreSelect`
- `ResourceState`

Avoid card-in-card nesting. Keep the page operational and dense; this is a work dashboard, not a landing page.

**Step 4: Display rules**

- Empty SLA means remaining time cell is blank.
- Phone column uses `phone_masked`.
- Follow result is read-only.
- No edit buttons in MVP.

**Step 5: Verify**

Run:

```powershell
npm --prefix apps/web run build
```

Expected: pass.

**Step 6: Commit**

```powershell
git add apps/web/src/pages/ClueCenterPage.tsx apps/web/src/App.tsx apps/web/src/pages/HomePage.tsx apps/web/src/styles.css apps/web/src/types/dashboard.ts apps/web/src/api/client.ts
git commit -m "feat: add clue center dashboard"
```

### Task 7: Build Admin Reallocation Rule Page

**Files:**
- Create: `apps/web/src/pages/AdminClueRulePage.tsx`
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/pages/AdminHomePage.tsx`
- Modify: `apps/web/src/styles.css`

**Step 1: Implement route**

Route:

```text
/admin/clues/rules
```

**Step 2: Add admin module card**

Add "线索再分配规则" to `AdminHomePage`.

**Step 3: Build form**

Fields:

- `reassign_sla_hours`

Behavior:

- blank value saves as `null`
- integer value between `1` and `168`
- show current updated time
- show explanatory text for null SLA

**Step 4: Add rebuild action**

Add a button to call `POST /api/v1/admin/clues/rebuild` after saving. If rebuild is queued, show job ID.

**Step 5: Verify**

Run:

```powershell
npm --prefix apps/web run build
```

Expected: pass.

**Step 6: Commit**

```powershell
git add apps/web/src/pages/AdminClueRulePage.tsx apps/web/src/App.tsx apps/web/src/pages/AdminHomePage.tsx apps/web/src/styles.css
git commit -m "feat: add clue reassign rule admin"
```

### Task 8: Update Mock Data And Frontend Fallbacks

**Files:**
- Create: `apps/web/src/data/mock/clue_center.json`
- Modify: `apps/web/src/data/mockData.ts`
- Modify: `apps/web/src/api/client.ts`

**Step 1: Add mock clue data**

Include:

- one active unfollowed clue
- one unreachable clue
- one successful self-store verified clue
- one failed pending reassign clue
- one no-SLA clue with blank remaining time

Do not include real phone numbers. Use fictional masked values.

**Step 2: Add fallback functions**

Match the existing mock fallback pattern in `client.ts`.

**Step 3: Verify**

Run:

```powershell
npm --prefix apps/web run build
```

Expected: pass.

**Step 4: Commit**

```powershell
git add apps/web/src/data/mock/clue_center.json apps/web/src/data/mockData.ts apps/web/src/api/client.ts
git commit -m "test: add clue center mock fallback"
```

### Task 9: Update Documentation

**Files:**
- Modify: `docs/data-model.md`
- Modify: `docs/api-contract.md`
- Modify: `docs/runbook.md`

**Step 1: Document tables**

Add:

- `raw_douyin_clues`
- `clue_center_orders`
- `clue_assignment_rounds`
- `clue_reassign_rule_settings`

**Step 2: Document API contract**

Add public clue endpoints and admin rule endpoints.

**Step 3: Document operational flow**

In `docs/runbook.md`, add:

- how to rebuild clue center tables
- how to set/null SLA
- what null SLA means
- privacy rule: only masked phone in UI/API

**Step 4: Commit**

```powershell
git add docs/data-model.md docs/api-contract.md docs/runbook.md
git commit -m "docs: document clue center MVP"
```

### Task 10: Full Verification

**Files:**
- Read only

**Step 1: Backend tests**

Run:

```powershell
python -m pytest tests/test_data_schema.py -v
python -m pytest tests/test_worker_clue_center.py -v
python -m pytest tests/test_api_clues.py tests/test_api_admin_clue_rules.py -v
python -m pytest
```

Expected: all pass.

**Step 2: Frontend build**

Run:

```powershell
npm --prefix apps/web run build
```

Expected: pass.

**Step 3: Whitespace and status**

Run:

```powershell
git diff --check
git status --short
```

Expected:

- no whitespace errors
- only intentional uncommitted files if final commit has not been made

### Task 11: Local Smoke Test

**Files:**
- Read only

**Step 1: Apply migration locally**

Use the existing local development command from `docs/runbook.md`. If using SQLite tests only, at least run `Base.metadata.create_all` through pytest.

**Step 2: Seed a tiny fixture**

Create test data in a local DB:

- one `raw_douyin_clues` eligible row
- one SKU product rule
- one `settlement_order_details` self-store verified row
- one null SLA config

**Step 3: Rebuild clue center**

Run the rebuild entrypoint from Task 2.

Expected:

- one row in `clue_center_orders`
- one row in `clue_assignment_rounds`
- `remaining_reassign_seconds = null`
- `is_self_store_verified = true`
- phone is masked

**Step 4: Browser smoke**

Start API and web dev server using existing repo commands. Open:

```text
/clues
/admin/clues/rules
```

Verify:

- clue card on home page opens `/clues`
- filters load
- metrics load
- table loads
- admin page allows blank SLA
- no full phone numbers appear in the rendered page

### Task 12: Deployment Notes

**Files:**
- Read only unless deployment docs need updates

**Step 1: Pre-deploy checks**

Run:

```powershell
python -m pytest
npm --prefix apps/web run build
git diff --check
```

**Step 2: Migration safety**

Before running Railway deploy/migration, confirm the migration is idempotent for existing `raw_douyin_clues`.

Expected:

- Railway already has `raw_douyin_clues`; migration should not fail.
- New derived tables should be created.

**Step 3: Rebuild after deploy**

After migration and deploy, call the admin rebuild endpoint or run the worker rebuild command.

Expected:

- dashboard totals align with eligible raw clue counts
- no full phone numbers in API responses
- no secrets or raw payloads in logs

---

## Acceptance Criteria

- `raw_douyin_clues` is represented in repo models and migration without breaking the already deployed table.
- `clue_center_orders` has one row per valid eligible `order_id`.
- `clue_assignment_rounds` has one first-round row per clue order.
- null SLA produces null `expires_at` and blank remaining time.
- configured SLA produces `expires_at` and remaining seconds.
- `failed` follow result enters pending reassign.
- `unreachable` counts as followed but not successful.
- self-store verification ratio uses `follow_result = 'success'` and `assigned_store_id = verify_store_id`.
- `/clues` page is linked from homepage and is read-only.
- `/admin/clues/rules` supports null SLA configuration.
- API and UI never return/display full phone numbers.
- Tests and frontend build pass.

## Open Follow-Ups For Later Versions

- Define actual reallocation algorithm after distance/latitude/longitude data exists.
- Add manual follow-result editing with audit trail.
- Add city/store-specific SLA rules.
- Add role-based phone visibility if full phone access is ever required.
- Add assignment notification workflow.
- Add scheduled rebuild or incremental update for new raw clues.
