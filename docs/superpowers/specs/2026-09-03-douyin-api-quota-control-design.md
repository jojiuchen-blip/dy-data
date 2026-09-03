# Douyin OpenAPI quota control

## Goal

Keep collection within the production application's confirmed endpoint quotas while preserving the existing daily-job, retry, materialization, and settlement semantics.

Production application profile:

- application: `销量数据分析`
- app id: `aws9nunf0av2egfw`
- orders: 20 requests/second
- verify records: 100 requests/second
- certificates: 35 requests/second
- refunds: 100 requests/day
- shop POIs: 400 requests/second
- clues: 100 requests/minute
- product list/detail: 20 requests/second

The deployed soft limits reserve headroom below the platform limits. Reviewed endpoints may be tightened through backend configuration without changing source code; configuration cannot raise a confirmed platform limit.

## Scope

- Add an application-aware endpoint limit profile.
- Pace second/minute endpoints before sending requests.
- Persist daily quota reservations in PostgreSQL so subprocesses and restarts share one budget.
- Surface a deterministic retry-after value when a daily budget is exhausted.
- Wire the policy through the existing worker client factory.
- Add migration, configuration examples, and focused tests.

## Non-goals

- No production environment edits, deployment, or data synchronization.
- No admin UI for editing limits in this increment.
- No change to collection payloads, materialization semantics, or settlement calculations.
- No guessed hard quota for endpoints not shown in the authenticated application console. Those endpoints use only the conservative default request interval.

## Design

### Configuration

The built-in profile is selected by `DOUYIN_APP_ID`. The worker rejects an application without a reviewed built-in profile. `DOUYIN_API_LIMITS_JSON` may only tighten limits for endpoints already in that profile, and `DOUYIN_REQUEST_SLEEP_SECONDS` sets the conservative floor between requests. The quota environment must be one of the reviewed runtime environments and must match `DY_AGENT_ENVIRONMENT` when both values are set. Invalid configuration fails closed during client construction.

### Request pacing

Every client request carries a stable endpoint key. A process-local monotonic governor spaces requests by the stricter of:

- the configured default interval; and
- the endpoint window divided by its effective soft quota.

Retries must acquire the limiter again because every retry consumes upstream quota. A daily-only quota is not spread uniformly across 24 hours: it uses the conservative default request interval plus the durable daily budget, so a multi-page refund pull can finish without waiting all day.

### Durable daily budget

`douyin_api_quota_usage` stores one row per environment, app, account, endpoint, and Shanghai business date. An atomic upsert reserves one request before transport. The production refund soft quota is 90/day, leaving ten calls for operational/manual recovery.

When the soft quota is exhausted, the client raises a sanitized quota exception carrying the endpoint and seconds until the next Shanghai day. Existing task supervision classifies it as `douyin_rate_limited` and schedules the retry using that duration.

### Safety

- App secrets, tokens, request payloads, and phone data are never written to the quota table or logs.
- A reservation is intentionally retained when transport fails because the upstream may already have counted the request.
- Unknown endpoints are paced but do not receive an invented daily cap.

## Follow-up phase

This increment controls request frequency and shared daily consumption without changing collection semantics. A separate reliability phase should split the existing daily collection transaction into source/page checkpoints. That phase is needed so a failure after several successful pages can resume from a durable checkpoint instead of repeating already-consumed upstream calls. It must preserve idempotent raw-data upserts and keep materialization/settlement outside page-level transactions.

## Acceptance gates

- Endpoint profile values match the authenticated console evidence above.
- Clue calls are spaced below 100/minute.
- The 91st production-app refund request in one Shanghai day is rejected before HTTP transport.
- Two independent database sessions cannot reserve the same final daily slot.
- A quota exception produces a retry delay aligned with the next Shanghai day.
- Existing Douyin client, collector, daily orchestrator, migration, and Compose tests pass.
- `git diff --check` passes and unrelated working-tree changes remain untouched.
