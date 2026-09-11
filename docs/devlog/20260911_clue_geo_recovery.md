# September store geography recovery

User-authorized scope: recover only leads received on or after September 1,
2026 (Asia/Shanghai), stranded in headquarters by missing POI ownership or
store geographic data. The full store directory is not a product eligibility
group. August leads, other headquarters causes, old retired rounds and existing
business ownership must remain unchanged.

The new explicit operator command `apps.worker.clue_geo_recovery` is not called
by the scheduler. It first generates a read-only preview, then rechecks each
previewed record under a bounded PostgreSQL transaction before recovery.
It requires both source creation and first reception within the incident
window, one source POI matching the source store account, no conflicting
customer intention, no existing assignment or follow-up history, and exactly
one order master. Uncertain cases are counted and skipped.

Recovery creates a new formal source-store round and closes the erroneous
headquarters entry, preserving raw records, retired rounds and store flags.
The round explicitly records source creation as a time proxy
(`geo_recovery_clue_create_time`); this is not a claim of a verified Douyin
allocation timestamp. No new SLA or automatic expiry is enabled. It does not
invoke sales priority, distance ranking, rule publication or redistribution.

## Operator procedure

1. Verify the deployed version and all POI/account/coordinate mappings against
   the source directory. Keep real directories and exports outside Git.
2. Run a preview inside the API container with its configured database:

   ```sh
   python -m apps.worker.clue_geo_recovery --preview-directory /path/to/directory.json --output /path/to/preview.json
   ```

3. Review counts and per-record targets. Create and verify a scoped backup of
   masters, headquarters entries, assignment rounds, center projections and
   allocation audit logs. Preserve the preview and backup on durable storage.
4. Execute the approved preview with a new receipt path:

   ```sh
   python -m apps.worker.clue_geo_recovery --apply-plan /path/to/preview.json --actor authorized-operator --backup-reference /path/to/verified-backup --output /path/to/receipt.json
   ```

   Each batch is at most 100 leads. Lock wait is limited to 5 seconds and each
   SQL statement to 30 seconds. Concurrent ingestion/follow-up may briefly wait;
   contention fails the transaction rather than overriding another writer.
5. Independently read back restored master/round/center targets, headquarters
   closure, disabled expiry and audit counts. Confirm August records, unrelated
   headquarters causes, product groups and store eligibility were not changed.

Rerunning a preview cannot create a second active round. A failed transaction
rolls back its entire batch. Completed earlier batches remain represented by
database audit rows even if receipt writing is interrupted. Do not restore a
whole backup over newer business writes; inspect per-record evidence and only
compensate records without intervening follow-up or allocation.

## Validation

- Initial red: 16 tests failed because the recovery module did not exist.
- First implementation: 16 scope, replay, race-recheck and rollback tests passed.
- Independent review identified stale terminal projections; recovery now rechecks
  raw clues, orders, coupons and settlement verification under the same write lock.
- 27 targeted SQLite tests pass, including terminal evidence arriving after preview.
- Full local suite encountered Windows temporary-directory permission failures;
  clean rerun and the explicit PostgreSQL CI gate are pending.
- No schema or API contract changes. No foundation drift.
- Production recovery: not yet executed. Cloud access restored and all 1,778
  source POI coordinates independently verified. Regenerate the production
  preview using the final reviewed version before applying.
