"""Live clue evidence and analytics share the canonical task facts.

Read enrichment never backfills immutable assignment or follow-up history.
"""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from apps.api.dy_api.clue_task_metrics import load_clue_task_facts

SUCCESS_STATUSES = ("1", "401", "success", "verified", "已核销", "used", "fulfilled", "transaction_success")


def verification_exists_sql(*, self_store: bool | None = None) -> str:
    """Return a fixed correlated predicate for the authorized outer round r."""
    mapping = ""
    condition = ""
    if self_store is not None:
        mapping = """JOIN (
            SELECT poi_id, MIN(store_id) AS store_id
            FROM dim_store_poi_mappings GROUP BY poi_id
            HAVING COUNT(DISTINCT store_id) = 1
        ) verification_store ON verification_store.poi_id = verification.poi_id"""
        operator = "=" if self_store else "<>"
        condition = f"AND verification_store.store_id {operator} r.assigned_store_id"
    return f"""EXISTS (
        SELECT 1 FROM raw_douyin_order_coupons coupon
        JOIN raw_douyin_verify_records verification ON verification.coupon_id = coupon.coupon_id
        {mapping}
        WHERE coupon.order_id = r.order_id
          AND LOWER(TRIM(verification.verify_status)) IN ('1', '401', 'success', 'verified', '已核销', 'used', 'fulfilled', 'transaction_success')
          AND verification.verify_time >= r.assigned_at
          AND verification.verify_time <= :clue_verification_cutoff
          AND (verification.source_observed_at IS NULL OR verification.source_observed_at <= :clue_verification_cutoff)
          AND (verification.cancel_time IS NULL OR verification.cancel_time > :clue_verification_cutoff)
          {condition}
    )"""


def _utc(value: Any) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def enrich_verification_facts(session: Session, rows: list[dict[str, Any]], cutoff: datetime) -> None:
    """Enrich already-authorized rows without changing their access scope.

    The task loader retains all formal history for correct attribution while
    only the supplied rows are returned. No contacts or mutable operation
    permissions are loaded here.
    """
    if not rows:
        return
    facts = load_clue_task_facts(session, (row["order_id"] for row in rows), observed_through=_utc(cutoff))
    for row in rows:
        metric = facts.get(str(row.get("assignment_round_id", "")))
        details = metric.verification_facts if metric else ()
        chosen = min(details, key=lambda item: (
            not item.counts_for_store_verification_rate,
            item.verified_store_id != row.get("assigned_store_id"),
            item.verified_store_id is None, item.verified_at, item.verify_id,
        )) if details else None
        row["verified_at"] = chosen.verified_at if chosen else None
        row["verified_store_id"] = chosen.verified_store_id if chosen else None
        row["verified_store_name"] = chosen.verified_store_name if chosen else None
        row["verification_facts"] = [detail.as_dict() for detail in details]
        row["verification_summary"] = (
            "跨店核销、关单后核销" if chosen and chosen.is_cross_store and chosen.is_after_close
            else "跨店核销" if chosen and chosen.is_cross_store
            else "关单后核销" if chosen and chosen.is_after_close
            else "已核销" if chosen else None
        )
        for field in ("follow_24h_numerator", "follow_any_numerator", "follow_denominator",
                      "verification_numerator", "verification_denominator"):
            row[field] = getattr(metric, field) if metric else 0
