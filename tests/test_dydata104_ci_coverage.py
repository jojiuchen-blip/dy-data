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
    "tests/test_protected_billing_authority_postgres.py",
    "tests/test_product_sync_completeness_postgres.py",
    "tests/test_product_sync_sku_lookup_postgres.py",
    "tests/test_month_close_auto_bootstrap_postgres.py",
}
BROWSER_FILES = {
    "tests/test_dydata104_finance_preview_browser.py",
    "tests/test_dydata105_buttons_browser.py",
}
COORDINATOR_CASES = {
    "test_postgres_publication_only_complete_apply[metadata]",
    "test_postgres_publication_only_complete_apply[migration]",
    "test_postgres_publication_only_atomic_billing_rollback",
    "test_postgres_publication_only_refuses_existing_heavy_claim_lock",
}

BOOTSTRAP_CASES = {
    "test_postgres_automatic_bootstrap_rebuilds_and_publishes_real_full_month[False]",
    "test_postgres_automatic_bootstrap_rebuilds_and_publishes_real_full_month[True]",
    "test_postgres_concurrent_ticks_share_frozen_input_job_without_resetting_attempts",
    "test_postgres_full_without_active_rolls_back_unknown_october_aggregates",
    "test_postgres_unqualified_legacy_current_rolls_back_month_economics",
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
        "DYDATA_PROTECTED_TEST_DATABASE_URL": "dydata_delivery_test",
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
    arguments = shlex.split(next(line for line in gate["run"].splitlines() if "-m pytest" in line))
    assert {argument for argument in arguments if argument.endswith(".py")} == PG_FILES
    assert all((ROOT / filename).is_file() for filename in PG_FILES)
    assert not any(argument.startswith(("-k", "-m", "--deselect", "--ignore"))
                   for argument in arguments[arguments.index("pytest") + 1:])
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
        "tests/test_protected_billing_authority_postgres.py": "DYDATA_PROTECTED_TEST_DATABASE_URL",
    }
    for filename, variable in sources.items():
        assert f'os.getenv("{variable}")' in (ROOT / filename).read_text(encoding="utf-8")
    source = (ROOT / "tests/test_account_qualification_postgres.py").read_text(encoding="utf-8")
    assert "from test_dashboard_publication_migration import full_pg_stack" in source
    bootstrap = (ROOT / "tests/test_month_close_auto_bootstrap_postgres.py").read_text(encoding="utf-8")
    assert "from test_protected_billing_authority_postgres import postgres_engine" in bootstrap


@pytest.mark.parametrize("name", WORKFLOWS)
@pytest.mark.parametrize("missing_case", [None, *sorted(COORDINATOR_CASES)])
def test_coordinator_receipt_requires_both_schema_modes_rollback_and_heavy_lock(
    name: str, missing_case: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A nonempty passing core-only report cannot satisfy coordinator coverage."""
    gate = _step(_workflow(name), PG_NAME)
    guard = shlex.split(next(line for line in gate["run"].splitlines() if "required = {" in line))[2]
    document = Element("testsuites")
    suite = SubElement(document, "testsuite")
    SubElement(suite, "testcase", classname="tests.test_protected_billing_authority_postgres", name="test_postgres_whole_bill_authority_excludes_replacement_chain[store-a-2026-08]")
    for case in COORDINATOR_CASES - {missing_case}:
        SubElement(suite, "testcase", classname="tests.test_protected_billing_authority_postgres", name=case)
    directory = tmp_path / "logs/ci"
    directory.mkdir(parents=True)
    ElementTree(document).write(directory / "dydata104-postgres.xml")
    monkeypatch.chdir(tmp_path)
    if missing_case is None:
        exec(compile(guard, "<workflow-coordinator-guard>", "exec"), {})
    else:
        with pytest.raises(AssertionError, match="coordinator"):
            exec(compile(guard, "<workflow-coordinator-guard>", "exec"), {})


def test_release_workflows_share_the_same_pg_contract() -> None:
    """CI/CD and Tencent must enforce equal DB, selection and receipt contracts."""
    gates = [_step(_workflow(name), PG_NAME) for name in WORKFLOWS]
    assert gates[0]["env"] == gates[1]["env"]
    assert gates[0]["run"] == gates[1]["run"]
    assert gates[0]["timeout-minutes"] == gates[1]["timeout-minutes"]


@pytest.mark.parametrize("name", WORKFLOWS)
@pytest.mark.parametrize("missing_case", [None, *sorted(BOOTSTRAP_CASES)])
def test_bootstrap_receipt_requires_every_real_postgres_scenario(
    name: str, missing_case: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Other passing PG files cannot substitute for the five bootstrap cases."""
    gate = _step(_workflow(name), PG_NAME)
    guard = shlex.split(next(line for line in gate["run"].splitlines() if "bootstrap_required = {" in line))[2]
    document = Element("testsuites")
    suite = SubElement(document, "testsuite")
    for case in COORDINATOR_CASES:
        SubElement(suite, "testcase", classname="tests.test_protected_billing_authority_postgres", name=case)
    for case in BOOTSTRAP_CASES - {missing_case}:
        SubElement(suite, "testcase", classname="tests.test_month_close_auto_bootstrap_postgres", name=case)
    directory = tmp_path / "logs/ci"
    directory.mkdir(parents=True)
    ElementTree(document).write(directory / "dydata104-postgres.xml")
    monkeypatch.chdir(tmp_path)
    if missing_case is None:
        exec(compile(guard, "<workflow-bootstrap-guard>", "exec"), {})
    else:
        with pytest.raises(AssertionError, match="bootstrap"):
            exec(compile(guard, "<workflow-bootstrap-guard>", "exec"), {})


@pytest.mark.parametrize("name", WORKFLOWS)
@pytest.mark.parametrize("invalid_case", ("wrong_module", "skipped", "failure", "error"))
def test_bootstrap_receipt_rejects_cases_without_successful_execution(
    name: str, invalid_case: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matching names need the bootstrap module and a successful JUnit result."""
    gate = _step(_workflow(name), PG_NAME)
    guard = shlex.split(next(line for line in gate["run"].splitlines() if "bootstrap_required = {" in line))[2]
    document = Element("testsuites")
    suite = SubElement(document, "testsuite")
    for index, case in enumerate(sorted(BOOTSTRAP_CASES)):
        module = "tests.test_other_postgres" if index == 0 and invalid_case == "wrong_module" else "tests.test_month_close_auto_bootstrap_postgres"
        element = SubElement(suite, "testcase", classname=module, name=case)
        if index == 0 and invalid_case != "wrong_module":
            SubElement(element, invalid_case)
    directory = tmp_path / "logs/ci"
    directory.mkdir(parents=True)
    ElementTree(document).write(directory / "dydata104-postgres.xml")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(AssertionError, match="bootstrap"):
        exec(compile(guard, "<workflow-bootstrap-guard>", "exec"), {})
