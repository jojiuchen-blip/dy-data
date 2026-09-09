"""Publication must acquire the active pointer before source slot locks."""
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from apps.worker import settlement_rebuild


@pytest.mark.parametrize("actual", [None, "other", "base"])
def test_billing_capture_locks_and_checks_base(actual):
    statements = []

    def scalar(statement):
        statements.append(statement)
        return SimpleNamespace(generation_id=actual) if actual else None

    session = SimpleNamespace(scalar=scalar)
    if actual == "base":
        settlement_rebuild._lock_billing_publication_base(session, "base")
    else:
        with pytest.raises(RuntimeError, match="active pointer changed"):
            settlement_rebuild._lock_billing_publication_base(session, "base")
    assert "FOR UPDATE" in str(statements[0].compile(dialect=postgresql.dialect()))
    assert statements[0].get_execution_options()["populate_existing"] is True
