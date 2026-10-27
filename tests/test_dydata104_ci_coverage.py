"""Release verification must execute the opt-in DYDATA-104 contracts."""

from __future__ import annotations

import shlex
from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree, SubElement

import pytest
import yaml
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ("ci-cd.yml", "tencent-lighthouse-deploy.yml")
PG_NAME = "Verify DYDATA-104 financial operations and month-end evidence on PostgreSQL"
BROWSER_NAME = "Verify DYDATA-104 financial preview and operation buttons in Chromium"
PG_FILES = {
    "tests/test_dydata104_finance_state_matrix.py",
    "tests/test_account_qualification_postgres.py",
    "tests/test_historical_fee_correction_postgres.py",
    "tests/test_product_sync_completeness_postgres.py",
    "tests/test_product_sync_sku_lookup_postgres.py",
}
BROWSER_FILES = {
    "tests/test_dydata104_finance_preview_browser.py",
    "tests/test_dydata105_buttons_browser.py",
}


def _workflow(name: str) -> dict:
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def _step(workflow: dict, name: str) -> dict:
    return next(item for item in workflow["jobs"]["verify"]["steps"] if item.get("name") == name)


@pytest.mark.parametrize("name", WORKFLOWS)
def test_opt_in_databases_and_explicit_cases_are_verified_before_release(name: str) -> None:
    """Assert actual fixture URL contracts and prerequisite ordering."""
    workflow = _workflow(name)
    steps = workflow["jobs"]["verify"]["steps"]
    gate = _step(workflow, PG_NAME)
    expected = {
        "DYDATA_FINANCE_TEST_DATABASE_URL": "dydata_delivery_test",
        "DYDATA_HISTORICAL_FEE_TEST_DATABASE_URL": "dydata_delivery_test",
        "DYDATA_PUBLICATION_TEST_DATABASE_URL": "dydata_publication_test",
    }
    for key, database in expected.items():
        url = make_url(gate["env"][key])
        assert url.host == "127.0.0.1" and url.port == 5432
        assert url.database == database and url.drivername == "postgresql+psycopg"
    assert "CREATE DATABASE dydata_delivery_test" in gate["run"]
    publication = _step(workflow, "Verify static dashboard publications on PostgreSQL")
    assert "CREATE DATABASE dydata_publication_test" in publication["run"]
    assert steps.index(publication) < steps.index(gate)
    assert steps.index(gate) < steps.index(_step(workflow, "Run tests"))
    for filename in PG_FILES:
        assert (ROOT / filename).is_file()
        assert filename in shlex.split(next(line for line in gate["run"].splitlines() if "-m pytest" in line))
    assert not gate.get("if") and not gate.get("continue-on-error")
    assert gate["timeout-minutes"] == 30
    assert "secrets." not in str(gate) and "|| true" not in gate["run"]
    assert workflow["permissions"] == {"contents": "read"}
    needs = workflow["jobs"]["deploy"]["needs"]
    assert "verify" in ([needs] if isinstance(needs, str) else needs)


@pytest.mark.parametrize("name", WORKFLOWS)
def test_real_browser_gate_has_dependencies_and_durable_receipts(name: str) -> None:
    """Browsers may not silently fall back to skip before deploy."""
    workflow = _workflow(name)
    steps = workflow["jobs"]["verify"]["steps"]
    gate = _step(workflow, BROWSER_NAME)
    for prerequisite in ("Install frontend dependencies", "Install Playwright browser"):
        assert steps.index(_step(workflow, prerequisite)) < steps.index(gate)
    for filename in BROWSER_FILES:
        assert (ROOT / filename).is_file() and filename in gate["run"]
    assert not gate.get("if") and not gate.get("continue-on-error")
    receipts = _step(workflow, "Upload DYDATA-104 verification receipts")
    assert receipts["if"] == "always()" and receipts["uses"] == "actions/upload-artifact@v4"
    assert "${{ github.workflow }}" not in receipts["with"]["name"]  # CI/CD contains '/'.
    for path in ("logs/ci/dydata104-postgres.xml", "logs/ci/dydata104-finance-browser.xml"):
        assert path in receipts["with"]["path"]


@pytest.mark.parametrize("name", WORKFLOWS)
@pytest.mark.parametrize("gate_name", (PG_NAME, BROWSER_NAME))
@pytest.mark.parametrize("tests,skipped,failures,errors", (
    (2, 0, 0, 0), (0, 0, 0, 0), (2, 1, 0, 0), (2, 0, 1, 0), (2, 0, 0, 1),
))
def test_junit_guard_rejects_skips_empty_collections_and_failures(
    name: str, gate_name: str, tests: int, skipped: int, failures: int, errors: int,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Execute the exact inline workflow guard against controlled JUnit results."""
    gate = _step(_workflow(name), gate_name)
    lines = gate["run"].splitlines()
    guard = shlex.split(next(line for line in lines if line.startswith("python -c 'import xml.etree")))[2]
    report = "dydata104-postgres.xml" if gate_name == PG_NAME else "dydata104-finance-browser.xml"
    directory = tmp_path / "logs/ci"
    directory.mkdir(parents=True)
    document = Element("testsuites")
    SubElement(document, "testsuite", tests=str(tests), skipped=str(skipped), failures=str(failures), errors=str(errors))
    ElementTree(document).write(directory / report)
    monkeypatch.chdir(tmp_path)
    if tests == 0 or skipped or failures or errors:
        with pytest.raises(AssertionError):
            exec(compile(guard, "<workflow-junit-guard>", "exec"), {})
    else:
        exec(compile(guard, "<workflow-junit-guard>", "exec"), {})


def test_fixture_environment_inventory_matches_checked_in_sources() -> None:
    """Keep environment wiring tied to fixture source, not filename guesses."""
    sources = {
        "tests/test_dydata104_finance_state_matrix.py": "DYDATA_FINANCE_TEST_DATABASE_URL",
        "tests/test_historical_fee_correction_postgres.py": "DYDATA_HISTORICAL_FEE_TEST_DATABASE_URL",
        "tests/test_dashboard_publication_migration.py": "DYDATA_PUBLICATION_TEST_DATABASE_URL",
        "tests/test_dashboard_publication_finance_postgres.py": "DYDATA_PUBLICATION_TEST_DATABASE_URL",
    }
    for filename, variable in sources.items():
        assert f'os.getenv("{variable}")' in (ROOT / filename).read_text(encoding="utf-8")
    source = (ROOT / "tests/test_account_qualification_postgres.py").read_text(encoding="utf-8")
    assert "from test_dashboard_publication_migration import full_pg_stack" in source
