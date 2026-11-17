"""Keep the first successful store publication for each exact bill version."""
from datetime import UTC, datetime

from sqlalchemy import literal, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from apps.api.dy_api.models import SettlementStatement, SettlementStatementVisibility
from src.dy_data.billing_dates import SHANGHAI, confirmation_due_at

from .finance import dimensions, monthly
from .period_readiness import FORMAL_START


def record_statement_visibility(
    session: Session, publication_id: str, published_at: datetime, cutoff: datetime,
) -> None:
    """Insert visibility only for formal bill rows served by this new head."""
    readiness = session.scalar(select(dimensions.c.value).where(
        dimensions.c.publication_id == publication_id,
        dimensions.c.kind == "period_readiness",
        dimensions.c.key == "v1",
    ))
    if not isinstance(readiness, dict) or readiness.get("schema_version") != 1:
        return
    periods = readiness.get("months")
    if not isinstance(periods, dict):
        return
    current_month = cutoff.astimezone(SHANGHAI).strftime("%Y-%m")
    ready_months = [
        month for month, entry in periods.items()
        if FORMAL_START <= month < current_month and isinstance(entry, dict) and entry.get("ready") is True
    ]
    if not ready_months:
        return
    source = select(
        SettlementStatement.statement_id, literal(publication_id), literal(published_at),
    ).select_from(monthly.join(SettlementStatement,
        (SettlementStatement.statement_id == monthly.c.statement["statement_id"].as_string())
        & (SettlementStatement.store_id == monthly.c.store_id)
        & (SettlementStatement.statement_month == monthly.c.month),
    )).where(
        monthly.c.publication_id == publication_id,
        monthly.c.month.in_(ready_months),
        monthly.c.product_scope == "all",
        monthly.c.product_type == "all",
        SettlementStatement.is_current.is_(True),
        SettlementStatement.statement_status.in_((2, 3, 4)),
    )
    insert = postgresql_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    session.execute(insert(SettlementStatementVisibility).from_select(
        ["statement_id", "publication_id", "first_visible_at"], source,
    ).on_conflict_do_nothing(index_elements=["statement_id"]))


def bill_confirmation_window(session: Session, statement: SettlementStatement) -> dict:
    evidence = session.get(SettlementStatementVisibility, statement.statement_id)
    if evidence is None:
        return {"first_visible_at": None, "confirmation_due_at": None}
    first_visible_at = evidence.first_visible_at
    if first_visible_at.tzinfo is None:
        first_visible_at = first_visible_at.replace(tzinfo=UTC)
    return {
        "first_visible_at": first_visible_at,
        "confirmation_due_at": confirmation_due_at(
            statement.statement_month, first_visible_at=first_visible_at,
        ),
    }
