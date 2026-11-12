"""Both supported API import paths must build one unambiguous authority query."""

import importlib
from pathlib import Path
import sys

import pytest

from test_dydata104_finance_state_matrix import db_session  # noqa: F401


API_ROOT = str(Path(__file__).resolve().parents[1] / "apps" / "api")
if API_ROOT not in sys.path:
    sys.path.insert(0, API_ROOT)


@pytest.mark.parametrize("module_name", (
    "apps.api.dy_api.dashboard_publications.commission_types",
    "dy_api.dashboard_publications.commission_types",
))
@pytest.mark.parametrize("operation", ("coverage", "partitions"))
def test_authority_query_executes_through_worker_and_api_imports(db_session, module_name, operation):
    module = importlib.import_module(module_name)
    # Even an empty database rejected the API-path query: its CTE selected one
    # ORM table while the default protection predicate introduced another copy.
    assert getattr(module, operation)(db_session, ("2026-08", "2026-09")) == []
