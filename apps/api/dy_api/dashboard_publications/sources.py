"""Source tracking and conservative multi-transaction materialization guard.

Migration installs statement triggers for SOURCE_TABLES. The guard delays
publication while a known business writer owns a multi-transaction operation;
it cannot certify an uninstrumented writer or repair a partially failed job.
"""

import hashlib
import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo
from sqlalchemy import func, inspect, or_, select, text
from sqlalchemy.orm import Session

from .schema import source_counters

_FINANCE_SHARED = (
    "historical_sale_attribution_decisions",
    "account_qualification_version",
    "dim_stores", "dim_sku_product_rules", "clue_center_orders", "raw_douyin_orders",
    "raw_douyin_verify_records", "settlement_order_details", "agg_store_ranking",
    "agg_store_monthly_settlement", "settlement_ranking_overlay", "settlement_monthly_overlay",
    "settlement_projection_active", "settlement_projection_generation",
    "settlement_projection_partition_manifest", "settlement_projection_compaction_closure",
    "settlement_statement",
)
MODULE_SOURCE_TABLES: dict[str, tuple[str, ...]] = {
    "douyin-ranking": (
        "raw_douyin_orders", "raw_douyin_clues", "clue_center_orders", "clue_assignment_rounds",
        "clue_follow_up_records", "raw_douyin_order_coupons", "raw_douyin_verify_records",
        "dim_aweme_accounts", "raw_aweme_bindings", "dim_store_poi_mappings", "dim_sku_product_rules",
        "ranking_store_org_history", "ranking_store_eligibility", "ranking_lead_org_bindings",
    ),
    "sales": ("settlement_order_details", "dim_stores", "dim_sku_product_rules"),
    "clue-overview": (
        "clue_assignment_rounds", "clue_center_orders", "clue_master_leads", "dim_sku_product_rules",
        "raw_douyin_orders", "raw_douyin_clues", "dim_stores", "dim_store_org_assignments",
        "ranking_store_org_history",
    ),
    "settlement": _FINANCE_SHARED + (
        "settlement_statement_line", "settlement_statement_entry", "settlement_fee_result",
        "settlement_fee_result_current", "settlement_fee_adjustment",
    ),
    "finance": _FINANCE_SHARED + (
        "settlement_statement_confirmation", "promotion_invoice", "promotion_invoice_allocation",
        "invoice_record", "invoice_status_event", "store_finance_profile",
        "management_carryforward_application", "sap_suggestion", "finance_operation_audit", "finance_import_batch",
    ),
}
SOURCE_TABLES = tuple(sorted({name for names in MODULE_SOURCE_TABLES.values() for name in names}))

# Only changed analytical contracts participate. Independent ranking keeps its
# original fingerprint payload and finance keeps its immutable amount contract.
MODULE_CONTRACT_VERSIONS = {
    "sales": "product-type-v2",
    "clue-overview": "product-type-v2",
    "settlement": "product-type-v2",
}


def effective_organization_version(session: Session, cutoff: datetime) -> tuple[str, str | None]:
    """Select the same one-roster boundary used by frozen clue organizations.

    No effective roster while future history exists means an empty historical
    catalog, not a revival of the compatibility roster. The token changes only
    at an actual effective version transition, not on every polling interval.
    """
    from ..ranking_schema_v1 import org_history

    if inspect(session.connection()).has_table(org_history.name):
        cutoff = cutoff.replace(tzinfo=UTC) if cutoff.tzinfo is None else cutoff.astimezone(UTC)
        bound = cutoff.replace(tzinfo=None) if session.get_bind().dialect.name == "sqlite" else cutoff
        version = session.scalar(select(org_history.c.mapping_version).where(
            org_history.c.effective_from <= bound,
        ).order_by(org_history.c.effective_from.desc(), org_history.c.mapping_version.desc()).limit(1))
        if version is not None:
            return "history", version
        if session.scalar(select(org_history.c.mapping_version).limit(1)) is not None:
            return "history", None
    return "legacy", None


def source_fingerprint(session: Session, module: str | None = None, *, now: datetime | None = None) -> str:
    """Read small counters and explicit time boundaries, never fact-row hashes."""
    required = set(SOURCE_TABLES if module is None else MODULE_SOURCE_TABLES[module])
    rows = session.execute(select(source_counters.c.source_name, source_counters.c.generation)
                           .where(source_counters.c.source_name.in_(required))
                           .order_by(source_counters.c.source_name)).all()
    if not required.issubset({row.source_name for row in rows}):
        # A half-installed tracker must never look like an unchanged source.
        from .lifecycle import PublicationError
        raise PublicationError("PUBLICATION_SOURCE_TRACKING_INCOMPLETE", "来源变化跟踪不完整，暂缓更新", 503)
    cutoff = now or datetime.now(UTC)
    cutoff = cutoff.replace(tzinfo=UTC) if cutoff.tzinfo is None else cutoff.astimezone(UTC)
    time_token = {}
    if module in {None, "clue-overview"}:
        time_token["clue_organization"] = effective_organization_version(session, cutoff)
    if module in {None, "finance", "settlement"}:
        time_token["shanghai_month"] = cutoff.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")
        from . import period_readiness
        time_token["financial_periods"] = period_readiness.fingerprint(period_readiness.capture(session, cutoff))
    payload = {"sources": [tuple(row) for row in rows], "time": time_token}
    if module in MODULE_CONTRACT_VERSIONS:
        payload["contract_version"] = MODULE_CONTRACT_VERSIONS[module]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def assert_sources_ready(session: Session, *, exclude_repair_run_id: str | None = None) -> None:
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
    from apps.api.dy_api.models import JobRun

    # A replay's event writes can finish before materialization/settlement.
    # Keep the last complete dashboard until that downstream work is verified.
    # The replay itself may exclude only its own repair audit, never a normal
    # source writer. Missing recovery metadata is deliberately not a release.
    pending_repair = session.scalar(select(JobRun.job_id).where(
        JobRun.job_name == "refund_evidence_replay",
        JobRun.job_id != (exclude_repair_run_id or ""),
        or_(
            JobRun.status.in_(("running", "retry_wait", "partial")),
            func.coalesce(JobRun.metadata_json["needs_downstream_processing"].as_boolean(), True).is_(True),
        ),
    ).limit(1))
    if pending_repair is not None:
        raise PublicationError("PUBLICATION_SOURCE_BUSY", "退款修复尚未完成后续核验，保留上一完整版本", 503)


def writer_lock_keys() -> tuple[int, ...]:
    """Share the actual writer lock identities without importing calculators."""
    # settlement_rebuild.SETTLEMENT_REBUILD_CLAIM_LOCK_KEY serializes claim
    # selection only. Holding it shared prevents a NEW rebuild from starting;
    # assert_sources_ready detects one already running. The other key is
    # clue_allocation._advisory_lock_key(MASTER_MATERIALIZATION_LOCK).
    # HEAVY_SYNC_CLAIM_LOCK_KEY also protects normal collection and bounded
    # refund replay admission. Detect already-running writers above, and hold
    # this shared lock to prevent a new claim after the readiness check.
    return (0x4459444154410087, 661893198734880846, int.from_bytes(
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
        "WHERE source_name = TG_TABLE_NAME; "
        "IF NOT FOUND THEN RAISE EXCEPTION 'dashboard publication source counter missing'; END IF; "
        "RETURN NULL; END $$",
        f"INSERT INTO dashboard_publication_source_counters (source_name, generation, changed_at) "
        f"VALUES ('{table_name}', 0, clock_timestamp()) ON CONFLICT (source_name) DO NOTHING",
        f'CREATE TRIGGER dashboard_publication_change AFTER INSERT OR UPDATE OR DELETE OR TRUNCATE '
        f'ON "{table_name}" FOR EACH STATEMENT EXECUTE FUNCTION dashboard_publication_track_change()',
    )
