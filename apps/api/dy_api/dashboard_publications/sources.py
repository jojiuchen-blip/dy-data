"""Source tracking and conservative multi-transaction materialization guard.

Migration installs statement triggers for SOURCE_TABLES. The guard delays
publication while a known business writer owns a multi-transaction operation;
it cannot certify an uninstrumented writer or repair a partially failed job.
"""

import hashlib
import json
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from .schema import source_counters

SOURCE_TABLES = (
    "raw_douyin_orders", "raw_douyin_order_coupons", "raw_douyin_verify_records",
    "raw_douyin_refund_records", "douyin_refund_event", "raw_douyin_clues",
    "raw_aweme_bindings", "dim_aweme_accounts", "dim_store_poi_mappings",
    "dim_sku_product_rules", "dim_stores", "dim_store_org_assignments",
    "dim_non_commission_owner_accounts", "settlement_order_details",
    "clue_center_orders", "clue_assignment_rounds", "clue_follow_up_records",
    "clue_master_leads", "ranking_store_org_history", "ranking_store_eligibility",
    "settlement_projection_active", "settlement_monthly_overlay", "settlement_ranking_overlay",
    "agg_store_ranking", "agg_store_monthly_settlement", "settlement_fee_result",
    "settlement_fee_result_current", "settlement_fee_adjustment", "settlement_statement",
    "settlement_statement_line", "settlement_statement_entry", "settlement_statement_confirmation",
    "settlement_carryforward_source", "settlement_carryforward_application",
    "finance_import_batch", "finance_import_row",
)


def source_fingerprint(session: Session) -> str:
    """Read only small migration-owned counters; never fingerprint fact rows."""
    rows = session.execute(select(source_counters.c.source_name, source_counters.c.generation)
                           .order_by(source_counters.c.source_name)).all()
    existing = set(inspect(session.connection()).get_table_names())
    required = set(SOURCE_TABLES) & existing
    if not required.issubset({row.source_name for row in rows}):
        # A half-installed tracker must never look like an unchanged source.
        raise RuntimeError("dashboard publication source tracking is incomplete")
    return hashlib.sha256(json.dumps([tuple(row) for row in rows], separators=(",", ":")).encode()).hexdigest()


def assert_sources_ready(session: Session) -> None:
    """Fail closed around known multi-transaction writers, without blocking them."""
    from .lifecycle import PublicationError  # Avoid the lifecycle/source import cycle.

    existing = set(inspect(session.connection()).get_table_names())
    if "job_runs" not in existing:
        raise PublicationError("PUBLICATION_SOURCE_STATE_UNKNOWN", "缺少来源任务状态，暂缓更新", 503)
    busy = session.execute(text(
        "SELECT 1 FROM job_runs WHERE status IN ('running', 'retry_wait') "
        "AND (job_kind IN ('date_sync', 'parent_sync', 'finalize', 'product_sync') "
        "OR job_name IN ('collect_and_settle', 'settlement_rebuild', 'manual_backend_aweme_export', "
        "'manual_sync', 'collect_once', 'settlement_compaction')) LIMIT 1"
    )).first()
    if busy:
        raise PublicationError("PUBLICATION_SOURCE_BUSY", "业务数据正在物化，保留上一完整版本", 503)


def writer_lock_keys() -> tuple[int, ...]:
    """Share the actual writer lock identities without importing calculators."""
    # settlement_rebuild.SETTLEMENT_REBUILD_CLAIM_LOCK_KEY serializes claim
    # selection only. Holding it shared prevents a NEW rebuild from starting;
    # assert_sources_ready detects one already running. The other key is
    # clue_allocation._advisory_lock_key(MASTER_MATERIALIZATION_LOCK).
    return (0x4459444154410087, int.from_bytes(
        hashlib.sha256(b"clue-allocation-master-materialization").digest()[:8], "big", signed=True,
    ))


def tracking_ddl(table_name: str) -> tuple[str, ...]:
    """Return allowlisted PostgreSQL DDL for the integrating migration.

    Install the function once, seed each existing table's counter, then install
    its trigger. Counter increments and source DML roll back together.
    """
    if table_name not in SOURCE_TABLES:
        raise ValueError("source table is not allowlisted")
    return (
        "CREATE OR REPLACE FUNCTION dashboard_publication_track_change() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN UPDATE dashboard_publication_source_counters "
        "SET generation = generation + 1, changed_at = clock_timestamp() "
        "WHERE source_name = TG_TABLE_NAME; RETURN NULL; END $$",
        f"INSERT INTO dashboard_publication_source_counters (source_name, generation, changed_at) "
        f"VALUES ('{table_name}', 0, clock_timestamp()) ON CONFLICT (source_name) DO NOTHING",
        f'CREATE TRIGGER dashboard_publication_change AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE '
        f'ON "{table_name}" FOR EACH STATEMENT EXECUTE FUNCTION dashboard_publication_track_change()',
    )
