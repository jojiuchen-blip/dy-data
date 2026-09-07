"""Shared row-refresh helpers for clue state writers.

The callers in this module must acquire the relevant master rows first.  This
module only refreshes dirty historical children that are already in the
session; it deliberately does not scan the complete round ledger.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import ClueAssignmentRound


def refresh_dirty_rounds_for_locked_leads(
    session: Session,
    lead_keys: Iterable[str],
) -> dict[str, ClueAssignmentRound]:
    """Refresh and lock dirty rounds belonging to already-locked masters.

    ``Session.dirty`` is used only as a bounded candidate source.  The
    database decides ownership and supplies the authoritative values while
    the rows are locked.  Callers must have acquired all master locks before
    invoking this helper; it acquires only the round portion of the shared
    master -> round -> center order.  The caller acquires center rows after
    all needed round rows have been locked.
    """

    normalized_lead_keys = sorted(
        {
            str(lead_key).strip()
            for lead_key in lead_keys
            if lead_key is not None and str(lead_key).strip()
        }
    )
    if not normalized_lead_keys:
        return {}

    with session.no_autoflush:
        candidate_round_ids: set[str] = set()
        for row in tuple(session.dirty):
            if not isinstance(row, ClueAssignmentRound):
                continue
            identity = inspect(row).identity
            if not identity or identity[0] is None:
                continue
            # The mapped PK attribute may itself have been edited in this
            # session.  ``identity`` is SQLAlchemy's original persistent key.
            candidate_round_ids.add(str(identity[0]))
        if not candidate_round_ids:
            return {}

        rounds = session.scalars(
            select(ClueAssignmentRound)
            .where(ClueAssignmentRound.assignment_round_id.in_(candidate_round_ids))
            .where(ClueAssignmentRound.lead_key.in_(normalized_lead_keys))
            .order_by(ClueAssignmentRound.assignment_round_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
        if not rounds:
            return {}

    return {row.assignment_round_id: row for row in rounds}
