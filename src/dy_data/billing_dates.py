"""Shanghai calendar cutoffs shared by bill writers and compensation jobs."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")


def confirmation_due_at(
    statement_month: str, *, first_visible_at: datetime | None = None,
) -> datetime:
    """Return the normal cutoff, extended by two full days after visibility."""
    start = date.fromisoformat(f"{statement_month}-01")
    if start.strftime("%Y-%m") != statement_month:
        raise ValueError("statement_month must be YYYY-MM")
    following = (start.replace(day=28) + timedelta(days=4)).replace(day=7)
    normal_due = datetime.combine(following, time.min, tzinfo=SHANGHAI)
    if first_visible_at is None:
        return normal_due.astimezone(timezone.utc)
    if first_visible_at.tzinfo is None:
        first_visible_at = first_visible_at.replace(tzinfo=timezone.utc)
    grace_due = datetime.combine(
        first_visible_at.astimezone(SHANGHAI).date() + timedelta(days=3),
        time.min,
        tzinfo=SHANGHAI,
    )
    return max(normal_due, grace_due).astimezone(timezone.utc)
