"""Guard the nullable statement binding used by PostgreSQL report queries."""

import inspect
import re

from apps.api.dy_api.routes._data import DashboardDataStore


def test_statement_rate_query_types_nullable_statement_binding() -> None:
    source = inspect.getsource(DashboardDataStore._statement_report_lines)
    # SQLite accepts untyped NULL predicates; psycopg/PostgreSQL raises 42P08.
    assert not re.search(r":statement_line_id\s+IS\s+(?:NOT\s+)?NULL", source)
    assert source.count("CAST(:statement_line_id AS TEXT)") == 3
