# Automatic Collection Production Closure Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the server-side automatic collection pipeline needed for launch: Douyin Open API collection, backend browser export collection, idempotent database upserts, settlement rebuild, job observability, and Docker deployment validation.

**Architecture:** Keep the public dashboard read-only and free of collection controls. Add production worker collectors that call Douyin APIs and Chromium/noVNC browser automation from the backend, normalize source records, write raw/dimension tables, then trigger settlement materialization from the database. Existing `scripts/exports/*` remain diagnostic/manual tools; the launch path is `apps.worker` plus PostgreSQL.

**Tech Stack:** Python, FastAPI data models, SQLAlchemy, Alembic, PostgreSQL, pytest, Docker Compose, Python Playwright over Chromium CDP, openpyxl for downloaded workbook parsing, React/Vite only for dashboard display.

---

## Current State

- Implemented: PostgreSQL schema, Alembic migration, raw tables, dimension tables, settlement detail and aggregate tables, `job_runs`, `data_quality_issues`.
- Implemented: `apps/worker/repositories.py` has idempotent upsert helpers for orders, coupons, verify records, aweme bindings, stores, POI mappings, SKU rules, aweme accounts, and job runs.
- Implemented: `apps/worker/settlement.py` rebuilds settlement details and aggregates from DB rows.
- Implemented: `apps/worker/scheduler.py` only runs settlement rebuild; it does not collect Douyin source data.
- Partial: `scripts/exports/export_raw_orders.py`, `scripts/exports/douyin_verify_record_export.py`, and `scripts/exports/export_craftsman_bind_info.py` can fetch/export data, but they save files and are not the production DB ingestion path.
- Partial: `scripts/exports/auto_export_backend_aweme_chromium.py` is only a job-tracking wrapper. It still requires a concrete browser automation command.
- Missing: a backend worker pipeline that automatically collects, normalizes, upserts, recalculates, records status, and can be run by Docker Compose without frontend interaction.

## Launch Definition Of Done

- Dashboard remains public read-only; no login prompt and no collection/admin controls in frontend.
- Data collection is a backend service behavior only.
- Worker can run one-shot and scheduled collection through Docker Compose.
- Open API collection covers orders, order coupons, verify records, shop POIs, and craftsman/aweme binding records needed by settlement.
- Browser automation covers backend sub-organization/aweme data that cannot be collected completely through Open API.
- Every collection run writes `job_runs` with status, counts, source window, and sanitized errors.
- Raw and dimension writes are idempotent; repeated collection of the same window does not duplicate rows.
- Settlement rebuild runs after successful collection and dashboard pages read the refreshed DB result.
- Automated tests pass, frontend build passes, Alembic/Postgres path passes, and Docker Compose one-shot smoke is documented.
- No credentials, cookies, browser profiles, real data exports, logs, SQLite files, `dist`, or `node_modules` are committed.

## Phase 1: Worker Collector Foundation

### Task 1: Add Collector Types And Windows

**Files:**
- Create: `apps/worker/collectors/__init__.py`
- Create: `apps/worker/collectors/types.py`
- Create: `apps/worker/collectors/windows.py`
- Test: `tests/test_worker_collection_windows.py`

**Step 1: Write the failing tests**

Test these cases:
- Default backfill start is `2026-01-01 00:00:00 Asia/Shanghai` when no explicit start is passed.
- Scheduled collection uses an overlap window, for example last 7 days, to catch late status changes.
- `CollectionStats` can add phase counts and expose `success_count` / `failed_count` for `job_runs`.

Example assertions:

```python
def test_collection_window_uses_overlap_for_incremental_runs():
    window = resolve_collection_window(now=dt("2026-06-12T10:00:00+08:00"), overlap_days=7)
    assert window.start.isoformat() == "2026-06-05T00:00:00+08:00"
    assert window.end.isoformat() == "2026-06-12T10:00:00+08:00"
```

**Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_worker_collection_windows.py -v
```

Expected: fails because the collector package does not exist.

**Step 3: Implement minimal foundation**

Add dataclasses:
- `CollectionWindow(start, end, timezone_name)`
- `PhaseStats(name, fetched, upserted, skipped, failed)`
- `CollectionStats(run_id, phases, source_window, metadata)`

Add env-backed helpers:
- `DOUYIN_COLLECT_START`
- `DOUYIN_COLLECT_END`
- `DOUYIN_COLLECT_OVERLAP_DAYS`
- `DOUYIN_COLLECT_TIMEZONE`, default `Asia/Shanghai`

**Step 4: Run test to verify it passes**

Run:

```powershell
python -m pytest tests/test_worker_collection_windows.py -v
```

Expected: pass.

**Step 5: Commit**

```powershell
git add apps/worker/collectors tests/test_worker_collection_windows.py
git commit -m "feat: add worker collection window foundation"
```

### Task 2: Add Importable Douyin Open API Client

**Files:**
- Modify: `src/dy_data/douyin_client.py`
- Test: `tests/test_douyin_openapi_client.py`

**Step 1: Write the failing tests**

Mock HTTP calls and verify:
- Client token request sends `client_key`, `client_secret`, and `client_credential`.
- Order query sends `Rpc-Transit-Life-Account`.
- Verify record query and shop POI query return raw JSON payloads without formatting them into CSV rows.
- API error responses raise a sanitized exception that does not include secrets.

**Step 2: Run test to verify it fails**

```powershell
python -m pytest tests/test_douyin_openapi_client.py -v
```

Expected: fails because only constants/header helper exist.

**Step 3: Implement minimal client**

Add:
- `DouyinCredentials(app_id, app_secret, account_id)`
- `DouyinApiError`
- `DouyinOpenApiClient`
- `get_client_token()`
- `query_orders(start, end, page_size, cursor=None)`
- `query_verify_records(start, end, poi_id=None, page_size=20, cursor=None)`
- `query_shop_pois(relation_type, cursor=None)`
- `query_craftsman_bind_info(cursor=None, size=50)`

Keep returned payloads raw; field interpretation belongs in normalizers.

**Step 4: Run test to verify it passes**

```powershell
python -m pytest tests/test_douyin_openapi_client.py -v
```

Expected: pass.

**Step 5: Commit**

```powershell
git add src/dy_data/douyin_client.py tests/test_douyin_openapi_client.py
git commit -m "feat: add douyin open api client"
```

## Phase 2: API Data Collectors And DB Upserts

### Task 3: Implement Order Collector

**Files:**
- Create: `apps/worker/collectors/orders.py`
- Test: `tests/test_worker_order_collector.py`

**Step 1: Write the failing tests**

Use a fake client returning one order with one or more certificate/coupon records. Assert:
- `raw_douyin_orders` gets one row.
- `raw_douyin_order_coupons` gets one row per coupon/certificate ID.
- `source_run_id` is set on both tables.
- Re-running the same payload updates existing rows instead of duplicating them.
- Key source fields are preserved in `raw_payload`.

**Step 2: Run test to verify it fails**

```powershell
python -m pytest tests/test_worker_order_collector.py -v
```

**Step 3: Implement minimal collector**

Add:
- `collect_orders(session, client, window, source_run_id) -> PhaseStats`
- raw payload extraction helpers for:
  - `order_id`
  - `order_status`
  - `sku_id`
  - `product_name`
  - `pay_time`
  - `create_order_time`
  - `paid_amount_cent`
  - `owner_account_id`
  - `owner_douyin_uid`
  - `owner_account_name`
  - `sale_role`
  - `sale_channel`
  - `intention_poi_id`
  - coupon/certificate IDs and coupon refund/status fields

Do not write CSV files in this production path.

**Step 4: Run test to verify it passes**

```powershell
python -m pytest tests/test_worker_order_collector.py -v
```

**Step 5: Commit**

```powershell
git add apps/worker/collectors/orders.py tests/test_worker_order_collector.py
git commit -m "feat: collect douyin orders into database"
```

### Task 4: Implement Verify Record And POI Collector

**Files:**
- Create: `apps/worker/collectors/verify_records.py`
- Test: `tests/test_worker_verify_collector.py`

**Step 1: Write the failing tests**

Use fake shop POI and verify record payloads. Assert:
- POI records upsert into `dim_store_poi_mappings` when an existing store mapping is known or manually configured.
- Verify records upsert into `raw_douyin_verify_records`.
- Repeated runs are idempotent.
- Cancelled/revoked records keep `verify_status` and `cancel_time` so settlement can exclude them.

**Step 2: Run test to verify it fails**

```powershell
python -m pytest tests/test_worker_verify_collector.py -v
```

**Step 3: Implement minimal collector**

Add:
- `collect_shop_pois(session, client, source_run_id) -> PhaseStats`
- `collect_verify_records(session, client, window, source_run_id) -> PhaseStats`
- configured POI fallback from `DOUYIN_POI_IDS` / `DOUYIN_POI_NAME_MAP`
- chunking with `DOUYIN_VERIFY_CHUNK_DAYS`

**Step 4: Run test to verify it passes**

```powershell
python -m pytest tests/test_worker_verify_collector.py -v
```

**Step 5: Commit**

```powershell
git add apps/worker/collectors/verify_records.py tests/test_worker_verify_collector.py
git commit -m "feat: collect douyin verify records into database"
```

### Task 5: Implement Craftsman/Aweme Binding Collector

**Files:**
- Create: `apps/worker/collectors/aweme_bindings.py`
- Test: `tests/test_worker_aweme_binding_collector.py`

**Step 1: Write the failing tests**

Use fake craftsman binding payloads. Assert:
- `raw_aweme_bindings` is upserted by stable binding key.
- `dim_aweme_accounts` is populated or updated from binding data when account ID/nickname are available.
- Binding status changes update existing rows.
- Raw payload is retained for diagnostics.

**Step 2: Run test to verify it fails**

```powershell
python -m pytest tests/test_worker_aweme_binding_collector.py -v
```

**Step 3: Implement minimal collector**

Add:
- `collect_aweme_bindings(session, client, source_run_id) -> PhaseStats`
- mapping from craftsman payload fields into `RawAwemeBinding`
- best-effort update into `DimAwemeAccount`

**Step 4: Run test to verify it passes**

```powershell
python -m pytest tests/test_worker_aweme_binding_collector.py -v
```

**Step 5: Commit**

```powershell
git add apps/worker/collectors/aweme_bindings.py tests/test_worker_aweme_binding_collector.py
git commit -m "feat: collect aweme bindings into database"
```

## Phase 3: Collection Orchestration

### Task 6: Add Collect-And-Settle Pipeline

**Files:**
- Create: `apps/worker/pipeline.py`
- Modify: `apps/worker/scheduler.py`
- Test: `tests/test_worker_collection_pipeline.py`

**Step 1: Write the failing tests**

Use fake collectors and fake settlement runner. Assert:
- A `job_runs` row starts as `running`.
- Successful collection calls phases in order: shop POIs, aweme bindings, orders, verify records, settlement.
- Success marks `job_runs.status = success`.
- Collector exceptions mark `job_runs.status = failed` with sanitized error.
- Settlement is not run if collection fails.

**Step 2: Run test to verify it fails**

```powershell
python -m pytest tests/test_worker_collection_pipeline.py -v
```

**Step 3: Implement minimal pipeline**

Add:
- `run_collection_job(session, client, window, job_id=None) -> CollectionStats`
- `run_collect_and_settle(session, job_id=None) -> CollectionStats`
- scheduler env:
  - `WORKER_MODE=collect_and_settle|settlement_only`
  - default should be `collect_and_settle` for production
  - keep `settlement_only` as an emergency/debug mode

Use a single `source_run_id` through raw upserts and settlement rebuild.

**Step 4: Run test to verify it passes**

```powershell
python -m pytest tests/test_worker_collection_pipeline.py -v
```

**Step 5: Commit**

```powershell
git add apps/worker/pipeline.py apps/worker/scheduler.py tests/test_worker_collection_pipeline.py
git commit -m "feat: orchestrate collection and settlement jobs"
```

### Task 7: Add One-Shot Worker CLI

**Files:**
- Create: `apps/worker/collect_once.py`
- Test: `tests/test_worker_collect_once_cli.py`

**Step 1: Write the failing tests**

Assert CLI args map to env/window settings:
- `--start`
- `--end`
- `--settlement-only`
- `--skip-browser-export`

**Step 2: Run test to verify it fails**

```powershell
python -m pytest tests/test_worker_collect_once_cli.py -v
```

**Step 3: Implement CLI**

Example production command:

```powershell
python -m apps.worker.collect_once --start 2026-01-01 --end 2026-06-12
```

**Step 4: Run test to verify it passes**

```powershell
python -m pytest tests/test_worker_collect_once_cli.py -v
```

**Step 5: Commit**

```powershell
git add apps/worker/collect_once.py tests/test_worker_collect_once_cli.py
git commit -m "feat: add one-shot collection worker command"
```

## Phase 4: Backend Browser Automation For Sub-Organization Data

### Task 8: Add Browser Export Parser

**Files:**
- Create: `apps/worker/browser_exports/__init__.py`
- Create: `apps/worker/browser_exports/backend_aweme_parser.py`
- Test: `tests/test_backend_aweme_parser.py`

**Step 1: Write the failing tests**

Generate a small in-memory XLSX workbook with columns used by the current diagnostics, then assert parser returns normalized records:
- douyin ID
- nickname
- account ID or account name
- POI/store hints when present
- binding status

**Step 2: Run test to verify it fails**

```powershell
python -m pytest tests/test_backend_aweme_parser.py -v
```

**Step 3: Implement parser**

Use `openpyxl` only. Do not require a live browser in unit tests.

**Step 4: Run test to verify it passes**

```powershell
python -m pytest tests/test_backend_aweme_parser.py -v
```

**Step 5: Commit**

```powershell
git add apps/worker/browser_exports tests/test_backend_aweme_parser.py
git commit -m "feat: parse backend aweme exports"
```

### Task 9: Add Concrete Chromium/CDP Export Automation

**Files:**
- Modify: `requirements.txt`
- Create: `apps/worker/browser_exports/backend_aweme.py`
- Test: `tests/test_backend_aweme_export_job.py`
- Modify: `scripts/exports/auto_export_backend_aweme_chromium.py` only if wrapper env contract needs adjustment.

**Step 1: Write the failing tests**

Do not test the live Douyin website in unit tests. Test:
- Missing CDP URL fails with sanitized error.
- Export command requires an existing browser login/session marker or returns a clear "manual login required" error.
- Parsed XLSX rows are upserted into `raw_aweme_bindings` and `dim_aweme_accounts`.

**Step 2: Run test to verify it fails**

```powershell
python -m pytest tests/test_backend_aweme_export_job.py -v
```

**Step 3: Implement browser automation**

Add `playwright` to `requirements.txt`.

Implement `python -m apps.worker.browser_exports.backend_aweme`:
- connect to `BROWSER_CDP_URL` with `chromium.connect_over_cdp`
- use the persistent browser profile from the `browser` container
- navigate to the Douyin backend page
- detect whether login is required and fail clearly without exposing cookies
- trigger the sub-organization/aweme export
- wait for the downloaded workbook in `BROWSER_EXPORT_RUN_DIR`
- parse workbook with `backend_aweme_parser.py`
- upsert records through repository helpers
- record counts in stdout and `job_runs` metadata

Keep the manual noVNC login outside the public dashboard. The dashboard must not display collection controls.

**Step 4: Run test to verify it passes**

```powershell
python -m pytest tests/test_backend_aweme_export_job.py -v
```

**Step 5: Commit**

```powershell
git add requirements.txt apps/worker/browser_exports tests/test_backend_aweme_export_job.py scripts/exports/auto_export_backend_aweme_chromium.py
git commit -m "feat: automate backend aweme browser export"
```

## Phase 5: Docker, Runbook, And Safety

### Task 10: Wire Docker Compose Worker Defaults

**Files:**
- Modify: `deploy/compose.yaml`
- Modify: `deploy/browser/Dockerfile` only if CDP/download behavior is missing
- Test: `tests/test_deploy_compose_config.py`

**Step 1: Write the failing tests**

Parse `deploy/compose.yaml` and assert:
- worker default command runs scheduler.
- worker has env for Douyin credentials, collection window, CDP URL, browser export dirs.
- browser profile and downloads are volumes, not tracked files.
- noVNC/browser service is not exposed as a public unauthenticated frontend feature.

**Step 2: Run test to verify it fails**

```powershell
python -m pytest tests/test_deploy_compose_config.py -v
```

**Step 3: Implement compose wiring**

Add env defaults:
- `WORKER_MODE`
- `DOUYIN_COLLECT_START`
- `DOUYIN_COLLECT_OVERLAP_DAYS`
- `DOUYIN_VERIFY_CHUNK_DAYS`
- `BROWSER_EXPORT_COMMAND=python -m apps.worker.browser_exports.backend_aweme`

**Step 4: Run test to verify it passes**

```powershell
python -m pytest tests/test_deploy_compose_config.py -v
```

**Step 5: Commit**

```powershell
git add deploy/compose.yaml deploy/browser/Dockerfile tests/test_deploy_compose_config.py
git commit -m "feat: wire collection worker in docker compose"
```

### Task 11: Update Production Runbook

**Files:**
- Modify: `docs/runbook.md`
- Modify: `docs/技术架构与部署规划.md`
- Modify: `docs/data-model.md` if new env fields or metadata are added

**Step 1: Write documentation checklist**

Runbook must include:
- required env vars
- first-time noVNC login/bootstrap steps
- one-shot backfill command
- daily scheduled worker behavior
- how to inspect `job_runs`
- how to verify dashboard pages after collection
- how to rotate Douyin credentials/session without frontend changes
- explicit statement that collection is backend-only

**Step 2: Update docs**

Keep secrets as placeholder names only. Do not include real cookies, account IDs, local downloads, or real exported data.

**Step 3: Check docs for accidental secrets**

```powershell
rg -n "(cookie|access_token|client_secret|password|passwd|authorization|C:\\\\Users|browser-profile|Downloads)" docs deploy apps scripts
```

Expected: only placeholders, docs explaining redaction, or code identifiers.

**Step 4: Commit**

```powershell
git add docs/runbook.md docs/技术架构与部署规划.md docs/data-model.md
git commit -m "docs: document backend collection operations"
```

## Phase 6: End-To-End Verification

### Task 12: Full Local Automated Gates

**Files:**
- No source files unless fixes are needed.

**Step 1: Run backend tests**

```powershell
python -m pytest
```

Expected: all tests pass.

**Step 2: Run frontend build**

```powershell
Set-Location apps\web
npm run build
Set-Location ..\..
```

Expected: build passes.

**Step 3: Run diff checks**

```powershell
git diff --check
git status --short --branch
```

Expected: no whitespace errors; only intended tracked changes before commit.

**Step 4: Commit any narrow fixes**

```powershell
git add <fixed-files>
git commit -m "fix: stabilize automatic collection pipeline"
```

### Task 13: Docker/Postgres/Alembic/Worker Smoke

**Files:**
- No source files unless fixes are needed.

**Step 1: Validate compose config**

```powershell
docker compose -f deploy\compose.yaml config
```

Expected: config renders successfully.

**Step 2: Run migration**

```powershell
docker compose -p dy-data-collection-smoke -f deploy\compose.yaml run --rm migrate
```

Expected: Alembic upgrades to head.

**Step 3: Run one-shot worker with fake or stub credentials in test mode**

Add a test-mode fake client only if needed; do not hit Douyin real APIs in automated CI.

```powershell
docker compose -p dy-data-collection-smoke -f deploy\compose.yaml run --rm worker python -m apps.worker.collect_once --start 2026-01-01 --end 2026-01-02 --skip-browser-export
```

Expected: command exits successfully in fake/test mode and writes expected job status.

**Step 4: Tear down smoke project**

```powershell
docker compose -p dy-data-collection-smoke -f deploy\compose.yaml down -v
```

### Task 14: Real Douyin Credential Smoke

**Files:**
- No source files.
- Do not commit generated data.

**Step 1: Set real environment outside git**

Use `.env` or shell environment ignored by git:
- `DOUYIN_APP_ID`
- `DOUYIN_APP_SECRET`
- `DOUYIN_ACCOUNT_ID`
- required POI/store mapping values
- browser/noVNC password if browser export is enabled

**Step 2: Run a narrow real API collection**

Use a tiny window first:

```powershell
docker compose -f deploy\compose.yaml run --rm worker python -m apps.worker.collect_once --start 2026-01-01 --end 2026-01-02 --skip-browser-export
```

Expected:
- order/verify/binding API phases either collect rows or record a clear no-data result.
- `job_runs.status = success`.
- no secrets appear in logs.

**Step 3: Run browser export smoke**

First login manually through the protected noVNC entry, then:

```powershell
docker compose -f deploy\compose.yaml run --rm worker python scripts/exports/auto_export_backend_aweme_chromium.py --command "python -m apps.worker.browser_exports.backend_aweme"
```

Expected:
- browser automation either collects the workbook and upserts rows, or fails with a clear manual-login/page-change error.
- successful run updates `raw_aweme_bindings` and `dim_aweme_accounts`.

**Step 4: Verify dashboard results**

Open the local frontend/proxy and verify:
- page 1 loads from API data
- page 2 loads from API data
- page 3 loads from API data
- page 2 card/table jumps to page 3 keep URL filters and matching detail rows
- page 3 pagination, filters, and order/coupon search work
- no frontend collection/admin controls are visible

## Final Gate

Before pushing the automatic collection work:

```powershell
python -m pytest
Set-Location apps\web; npm run build; Set-Location ..\..
docker compose -f deploy\compose.yaml config
git diff --check
git status --short --branch
```

Then:

```powershell
git push origin feat/fullstack-mvp-integration
```

Final report must state:
- code change summary
- exact test/build/docker results
- whether real Douyin API collection was verified
- whether browser/noVNC export was verified
- local access URL
- pushed branch and commit hash
- remaining launch risks
