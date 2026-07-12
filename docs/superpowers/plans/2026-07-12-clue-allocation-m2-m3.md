# M2/M3 线索分配引擎执行计划

> **Controller note:** Sequential execution on `feat/clue-allocation-m1`; source of truth is the approved product design and `docs/plans/2026-07-12-clue-allocation-m2-m3-controller-spec.md`.

## Phase 0: Baseline and contracts

1. Confirm clean branch and M1 migration head.
2. Add M2/M3 models and migrations without altering raw Douyin tables.
3. Keep legacy clue-center rows readable; self-owned rounds use explicit execution mode and a migration-safe unique-key namespace, so old `order_id-1` records cannot collide with actual self-owned round 1.

## Phase 1: DYDATA-11 Rule versioning

1. Write failing model/service/API tests for four-level matching, validation, immutability and authorization.
2. Implement rule versions, store groups, fixed strategy configs, `lead_key` bindings and audit-ready metadata.
3. Run scoped tests, migration schema test, full lint/build checks required by this repo.
4. Commit and append Linear evidence; retain In Progress.

## Phase 2: DYDATA-12 Allocation engine

1. Write failing tests for sales-store priority, nearby-city ranking, fallback, exclusion, skipped strategy, no candidate and decision snapshots.
2. Implement one engine entry point that returns a deterministic decision and persists it idempotently.
3. Wire active M1 leads into allocation only when an explicit allocation cycle/run invokes it; do not auto-reallocate all existing rows during development.
4. Update compatibility projection only when the self-owned round is current.
5. Commit and review.

## Phase 3: DYDATA-13 Follow-up state machine

1. Write failing tests for each of the five actions, SLA expiry, protection expiry, terminal order status, and phone permission.
2. Implement transitions through a single domain service, not duplicated API/worker logic.
3. Update API schemas/UI labels from legacy three actions to five actions without deleting legacy history values.
4. Add scheduled/due processing in pipeline with locks and idempotency.
5. Commit and review.

## Phase 4: DYDATA-14 and DYDATA-15 Operations

1. Add headquarters pool entry/audit models and enforce access policy at all routes/data-store methods.
2. Build high-admin allocation management UI around published API contracts; read-only admin view, no store access.
3. Use mock/local fixture data in UI tests and desktop/mobile visual checks.
4. Commit each logical slice and review.

## Phase 5: DYDATA-16 Trial, rebuild and cutover controls

1. Add allocation cycle models and preview/execute paths.
2. Make trial auto-expiry an explicit boolean.
3. Rebuild active leads into a new cycle, superseding old trial rounds without deletion.
4. Add high-risk confirmation/audit and real-follow-up guard.
5. Run full test suite/build and prepare local preview for user acceptance.

## Completion gates

- No production migration/import/rebuild/deploy/push without a new user instruction.
- Run independent spec and quality review after implementation.
- Leave `DYDATA-11` through `DYDATA-16` In Progress until user accepts local M2/M3 behavior.
