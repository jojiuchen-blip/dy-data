"""Shanghai calendar cutoffs shared by bill writers and compensation jobs."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def confirmation_due_at(statement_month: str) -> datetime:
    """Return next month's seventh day at 00:00 Shanghai, as aware UTC."""
    start = date.fromisoformat(f"{statement_month}-01")
    if start.strftime("%Y-%m") != statement_month:
        raise ValueError("statement_month must be YYYY-MM")
    following = (start.replace(day=28) + timedelta(days=4)).replace(day=7)
    return datetime(following.year, following.month, 7, tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(timezone.utc)
