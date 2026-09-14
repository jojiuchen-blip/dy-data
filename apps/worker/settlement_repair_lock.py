"""R87-L: fixed, transaction-local PostgreSQL source/finance write exclusion.

Call once at the beginning of EACH short data/publication transaction, before
business reads, row/advisory locks, or writes. Claim the job in a separate
transaction first; this helper neither establishes authority nor locks job_runs.
Do not hold this lock while invoking a publisher that opens other sessions.

SHARE ROW EXCLUSIVE conflicts with ordinary INSERT/UPDATE/DELETE's ROW EXCLUSIVE
and with itself. Unlike two SHARE holders, two repairs cannot both read and then
deadlock upgrading to writes. Plain SELECT is allowed. SELECT FOR UPDATE is NOT
excluded: pre-existing row/advisory lock holders and other multi-table writers
can still deadlock. Timeouts/errors abort the whole caller transaction; retry
only with a fresh session and fresh business/lease validation, never in here.

READ COMMITTED is required so reads AFTER acquisition see writers that committed
while LOCK waited. Fixed table locks prevent new source/financial phantoms only
until this transaction ends. Reacquire and revalidate between publisher phases.
Statement timeout bounds each SQL statement, not total transaction wall time;
the coordinator must also bound computation and perform its final lease fence.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session, SessionTransactionOrigin

from apps.api.dy_api.models import Base


# Reviewed against settle_coupon_local / rebuild_dual_fee_results and their
# lookup/adjustment helpers in settlement.py; billing_source_capture.py;
# billing_statements._protected / generate_pending_statements; bounded scope;
# projection_lineage (including raw-SQL compaction closure); and repositories'
# mapping -> _capture_job_impact -> ClueMaterializationWorkItem side effects.
# This is an intentionally fixed whole-table set, NOT inferred from user input
# or all Base tables. Any new reader in those paths needs a coverage review.
SETTLEMENT_REPAIR_LOCK_TABLES: tuple[str, ...] = tuple(sorted((
    # Raw inputs and identity/rule lookups.
    "raw_douyin_orders", "raw_douyin_order_coupons", "raw_douyin_verify_records",
    "douyin_refund_event", "raw_aweme_bindings", "dim_aweme_accounts",
    "dim_non_commission_owner_accounts", "dim_sku_product_rules", "dim_stores",
    "dim_store_poi_mappings", "sku_fee_rule", "settlement_scope_rule",
    # Local economic facts and cross-month adjustment closure.
    "settlement_order_details", "settlement_fee_result", "settlement_fee_result_current",
    "settlement_fee_adjustment", "settlement_carryforward_source",
    "settlement_carryforward_application",
    # Protected financial facts, bill inputs and generated records.
    "settlement_statement", "settlement_statement_line", "settlement_statement_entry",
    "settlement_statement_confirmation", "settlement_dispute", "invoice_record",
    "promotion_invoice_allocation", "store_finance_profile", "finance_operation_audit",
    # Published/base lineage, actual partitions and frozen source manifests.
    "agg_store_monthly_settlement", "agg_store_ranking", "settlement_projection_active",
    "settlement_projection_generation", "settlement_projection_partition_manifest",
    "settlement_projection_compaction_closure", "settlement_monthly_overlay",
    "settlement_ranking_overlay", "settlement_billing_source_bundle", "job_events",
    # Mapping capture/DQI writes and their deduplication reads; NOT job_runs.
    "job_impacts", "clue_materialization_work_items", "data_quality_issues",
)))


def acquire_settlement_repair_lock(
    session: Session,
    *,
    lock_timeout_ms: int = 2000,
    statement_timeout_ms: int = 15000,
) -> tuple[str, ...]:
    """Acquire the fixed lock set until the caller commits/rolls back.

    Use a fresh Session inside explicit ``session.begin()``. No savepoints,
    preloaded ORM entities or pending writes are accepted. Prior Core SQL reads
    cannot be detected here: the caller must not perform business reads first.
    All models must share this session's single PostgreSQL bind and trusted
    search_path (the repository's unqualified model-table contract).

    Returns the ordered table names for non-sensitive audit evidence. Does not
    commit, flush, renew a lease, run queries on job_runs, or retry failures.
    A database/setup error after connection acquisition rolls back the entire
    transaction, including locks already obtained. Local settings revert on end.
    """
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        raise ValueError("settlement repair exclusion requires PostgreSQL")
    if (not session.is_active or not session.in_transaction()
            or session.in_nested_transaction()
            or session.get_transaction().origin is not SessionTransactionOrigin.BEGIN):
        raise ValueError("repair lock requires a fresh explicit root transaction")
    if session.new or session.dirty or session.deleted or session.identity_map:
        raise ValueError("repair lock must precede business reads and writes")
    if (type(lock_timeout_ms) is not int or not 1 <= lock_timeout_ms <= 5000
            or type(statement_timeout_ms) is not int
            or not lock_timeout_ms <= statement_timeout_ms <= 60000):
        raise ValueError("invalid bounded repair timeouts")
    # Fail before locking if the reviewed inventory no longer matches metadata.
    for name in SETTLEMENT_REPAIR_LOCK_TABLES:
        table = Base.metadata.tables.get(name)
        if table is None or table.name != name or table.schema is not None:
            raise ValueError("repair lock inventory does not match model metadata")
        if session.get_bind(clause=table) is not bind:
            raise ValueError("repair lock requires a single bind for every covered table")
    # Identifiers below come ONLY from the internal fixed inventory above.
    statement = "LOCK TABLE " + ", ".join(
        '"' + name + '"' for name in SETTLEMENT_REPAIR_LOCK_TABLES
    ) + " IN SHARE ROW EXCLUSIVE MODE"
    try:
        connection = session.connection()
        if (connection.get_isolation_level() != "READ COMMITTED"
                or connection.get_execution_options().get("isolation_level") == "AUTOCOMMIT"
                or connection.connection.dbapi_connection.autocommit is True):
            raise ValueError("repair lock requires transactional READ COMMITTED")
        with session.no_autoflush:
            session.execute(text(
                "SELECT set_config('lock_timeout', :lock_timeout, true), "
                "set_config('statement_timeout', :statement_timeout, true)"
            ), {
                "lock_timeout": f"{lock_timeout_ms}ms",
                "statement_timeout": f"{statement_timeout_ms}ms",
            })
            # One statement bounds total acquisition by statement_timeout as well
            # as each wait by lock_timeout. All repairs use the same table order.
            session.execute(text(statement))
    except BaseException:
        session.rollback()
        raise
    return SETTLEMENT_REPAIR_LOCK_TABLES
