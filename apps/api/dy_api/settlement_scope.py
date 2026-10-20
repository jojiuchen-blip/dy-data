"""Resolve the append-only effective-month timeline for one account/channel."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import SettlementScopeRule


def resolve_settlement_scope_rule(
    session: Session,
    *,
    business_month: str,
    owner_account_id: str,
    channel: str,
) -> SettlementScopeRule | None:
    """Return the latest preceding rule, including an explicit inactive rule.

    Callers must examine ``is_active`` after selection. Filtering inactive rows
    here would silently revive an earlier enabled rule after a stop.
    ``channel`` is the normalized stored channel (``live`` or ``short_video``).
    """
    return session.scalar(
        select(SettlementScopeRule)
        .where(
            SettlementScopeRule.effective_month <= business_month,
            SettlementScopeRule.owner_account_id == owner_account_id,
            SettlementScopeRule.sale_channel_normalized == channel,
        )
        .order_by(SettlementScopeRule.effective_month.desc(), SettlementScopeRule.id.desc())
        .limit(1)
    )
