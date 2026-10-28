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
IMAGE_NAME = "Verify browser image dependency compatibility"
PG_FILES = {
    "tests/test_dydata104_finance_state_matrix.py",
    "tests/test_account_qualification_postgres.py",
    "tests/test_historical_fee_correction_postgres.py",
    "tests/test_protected_billing_authority_postgres.py",
    "tests/test_product_sync_completeness_postgres.py",
    "tests/test_product_sync_sku_lookup_postgres.py",
    "tests/test_product_sync_failure_diagnostics.py",
    "tests/test_month_close_auto_bootstrap_postgres.py",
    "tests/test_missing_fee_repair_postgres.py",
    "tests/test_missing_fee_write_proof_postgres.py",
    "tests/test_settlement_verify_impact_selection.py",
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

MISSING_FEE_CASES = {
    "test_postgres_active_source_writer_rejects[retry_wait]",
    "test_postgres_active_source_writer_rejects[running]",
    "test_postgres_all_target_protection_facts_reject[confirmation]",
    "test_postgres_all_target_protection_facts_reject[confirmed]",
    "test_postgres_all_target_protection_facts_reject[historical-lock]",
    "test_postgres_all_target_protection_facts_reject[invoice]",
    "test_postgres_all_target_protection_facts_reject[locked]",
    "test_postgres_all_target_protection_facts_reject[orphan-dispute]",
    "test_postgres_any_historical_direction_status_month_rejects[2026-08-2-False]",
    "test_postgres_any_historical_direction_status_month_rejects[2026-08-3-False]",
    "test_postgres_any_historical_direction_status_month_rejects[2026-09-1-True]",
    "test_postgres_apply_commit_readback_and_exact_idempotence[metadata]",
    "test_postgres_apply_commit_readback_and_exact_idempotence[migration]",
    "test_postgres_existing_source_transaction_times_out_without_writes",
    "test_postgres_full_dependency_drift_rejects_zero_writes[binding]",
    "test_postgres_full_dependency_drift_rejects_zero_writes[new-rate]",
    "test_postgres_full_dependency_drift_rejects_zero_writes[rate]",
    "test_postgres_full_dependency_drift_rejects_zero_writes[raw-order]",
    "test_postgres_full_dependency_drift_rejects_zero_writes[receipt]",
    "test_postgres_full_dependency_drift_rejects_zero_writes[scope]",
    "test_postgres_full_dependency_drift_rejects_zero_writes[sibling]",
    "test_postgres_full_dependency_drift_rejects_zero_writes[sku]",
    "test_postgres_full_dependency_drift_rejects_zero_writes[store-name]",
    "test_postgres_heavy_claim_conflict_rejects",
    "test_postgres_preview_select_only",
    "test_postgres_relation_fences_block_insert_phantoms[config]",
    "test_postgres_relation_fences_block_insert_phantoms[protection]",
    "test_postgres_relation_fences_block_insert_phantoms[raw]",
    "test_postgres_remaining_wall_budget_clamps_statement_timeout",
    "test_postgres_reviewed_batch_representative_budget_receipt[10]",
    "test_postgres_reviewed_batch_representative_budget_receipt[20]",
    "test_postgres_reviewed_batch_representative_budget_receipt[373]",
    "test_postgres_reviewed_batch_representative_budget_receipt[50]",
    "test_postgres_transaction_characteristics_and_fixed_timeouts",
    "test_postgres_unexpected_writer_outputs_roll_back_entire_batch[adjustment-count]",
    "test_postgres_unexpected_writer_outputs_roll_back_entire_batch[budget]",
    "test_postgres_unexpected_writer_outputs_roll_back_entire_batch[fields]",
    "test_postgres_unexpected_writer_outputs_roll_back_entire_batch[outside]",
}
IMAGE_CASES = {
    "test_browser_pillow_rgb_image_round_trip[PNG]",
    "test_browser_pillow_rgb_image_round_trip[TIFF]",
    "test_browser_requests_urllib3_pool_handles_regular_and_chunked_responses",
}
WRITE_PROOF_CASES = {
    "test_representative_50_coupon_large_derived_tables_receipt",
    "test_actual_disabled_track_counts_connection_rejects",
    "test_missing_transaction_stat_result_fails_closed",
    "test_xact_counters_are_live_and_stable_across_idle_reads",
    "test_target_dq_delete_is_exact_and_allowed",
    "test_legacy_successful_audit_replays_without_rewriting_it",
    "test_replay_readback_ignores_stale_unexpired_identity_map[fee]", "test_replay_readback_ignores_stale_unexpired_identity_map[audit]",
    "test_postcheck_seal_rejects_commit_hook_sql",
    "test_database_internal_and_final_deferred_effects_reject[deferred_fee]",
    "test_database_internal_and_final_deferred_effects_reject[audit_sidecar]",
    "test_database_internal_and_final_deferred_effects_reject[nested_index]",
    "test_database_internal_and_final_deferred_effects_reject[nested_trigger_function]",
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
        "DYDATA_MISSING_FEE_TEST_DATABASE_URL": "dydata_delivery_test",
        "DYDATA_PUBLICATION_TEST_DATABASE_URL": "dydata_publication_test",
    }
    for key, database in expected.items():
        url = make_url(gate["env"][key])
        assert url.host == "127.0.0.1" and url.port == 5432
        assert url.database == database and url.drivername == "postgresql+psycopg"
    assert "CREATE DATABASE dydata_delivery_test" in gate["run"]
    selector_url = make_url(gate["env"]["DYDATA_T12_TEST_DATABASE_URL"])
    assert selector_url.host == "127.0.0.1" and selector_url.port == 55432
    assert selector_url.database == selector_url.username == "dydata_t12"
    selector_service = workflow["jobs"]["verify"]["services"]["settlement-postgres"]
    assert selector_service["image"] == "postgres:16"
    assert selector_service["ports"] == ["55432:5432"]
    assert selector_service["env"]["POSTGRES_USER"] == selector_service["env"]["POSTGRES_DB"] == "dydata_t12"
    assert selector_service["env"]["POSTGRES_PASSWORD"] == selector_url.password
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
        "tests/test_missing_fee_repair_postgres.py": "DYDATA_MISSING_FEE_TEST_DATABASE_URL",
        "tests/test_missing_fee_write_proof_postgres.py": "DYDATA_MISSING_FEE_TEST_DATABASE_URL",
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
@pytest.mark.parametrize("invalid_case", (None, "missing", "wrong_module", "skipped", "failure", "error"))
@pytest.mark.parametrize("module_name, guard_label", (
    ("test_settlement_verify_impact_selection", "verify impact"),
    ("test_product_sync_failure_diagnostics", "product failure diagnostics"),
))
def test_verify_impact_receipt_requires_eleven_successful_postgres_cases(
    name: str, invalid_case: str | None, module_name: str, guard_label: str,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = _step(_workflow(name), PG_NAME)
    guard = shlex.split(next(line for line in gate["run"].splitlines() if f"all eleven {guard_label}" in line))[2]
    document = Element("testsuites")
    suite = SubElement(document, "testsuite")
    for index in range(11):
        if index == 0 and invalid_case == "missing":
            continue
        module = "tests.test_other" if index == 0 and invalid_case == "wrong_module" else f"tests.{module_name}"
        case = SubElement(suite, "testcase", classname=module, name=f"verify_case_{index}[postgres]")
        if index == 0 and invalid_case in {"skipped", "failure", "error"}:
            SubElement(case, invalid_case)
    directory = tmp_path / "logs/ci"
    directory.mkdir(parents=True)
    ElementTree(document).write(directory / "dydata104-postgres.xml")
    monkeypatch.chdir(tmp_path)
    if invalid_case is None:
        exec(compile(guard, "<workflow-verify-impact-guard>", "exec"), {})
    else:
        with pytest.raises(AssertionError, match=guard_label):
            exec(compile(guard, "<workflow-verify-impact-guard>", "exec"), {})


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


@pytest.mark.parametrize("name", WORKFLOWS)
def test_browser_image_gate_uses_built_image_offline_and_single_readonly_test_mount(name: str) -> None:
    """Exercise installed image packages without mounting or importing host sources."""
    workflow = _workflow(name)
    steps = workflow["jobs"]["verify"]["steps"]
    gate = _step(workflow, IMAGE_NAME)
    build = _step(workflow, "Build Browser Docker image")
    assert "-t dy-dashboard-browser:ci" in build["run"]
    assert steps.index(gate) == steps.index(build) + 1
    assert not gate.get("if") and not gate.get("continue-on-error")
    assert gate["timeout-minutes"] == 5
    commands = [shlex.split(line) for line in gate["run"].splitlines() if line.startswith("docker run ")]
    assert len(commands) == 2
    for arguments in commands:
        assert arguments[arguments.index("--network") + 1] == "none"
        assert arguments[arguments.index("--entrypoint") + 1] == "python3"
        assert "--rm" in arguments and "dy-dashboard-browser:ci" in arguments
    imports, tests = commands
    assert "13.0.0" in imports[-1] and 'version("Pillow")' in imports[-1]
    assert "PIL.__version__" in imports[-1] and "from PIL import Image" in imports[-1]
    assert 'is_relative_to("/usr/local/lib")' in imports[-1]
    mounts = [tests[index + 1] for index, value in enumerate(tests) if value == "-v"]
    assert mounts == [
        "$PWD/tests/test_browser_image_dependency_compat.py:/tmp/test_browser_image_dependency_compat.py:ro",
        "$PWD/logs/ci:/verification",
    ]
    assert tests[tests.index("dy-dashboard-browser:ci") + 1:] == [
        "-m", "pytest", "-q", "-ra", "-p", "no:cacheprovider",
        "/tmp/test_browser_image_dependency_compat.py", "--junitxml=/verification/dydata104-browser-image.xml",
    ]
    receipt = _step(workflow, "Upload DYDATA-104 browser image verification receipt")
    assert receipt["if"] == "always()" and receipt["uses"] == "actions/upload-artifact@v4"
    assert receipt["with"]["path"] == "logs/ci/dydata104-browser-image.xml"
    assert steps.index(receipt) > steps.index(gate)
    assert "|| true" not in gate["run"] and "secrets." not in str(gate)


def _write_case_receipt(
    directory: Path, report: str, module: str, cases: set[str],
    *, tests: int | None = None, skipped: int = 0, failures: int = 0, errors: int = 0,
    invalid_case: str | None = None,
) -> None:
    document = Element("testsuites")
    suite = SubElement(document, "testsuite", tests=str(len(cases) if tests is None else tests),
                       skipped=str(skipped), failures=str(failures), errors=str(errors))
    for index, case in enumerate(sorted(cases)):
        classname = "tests.test_other" if index == 0 and invalid_case == "wrong_module" else module
        element = SubElement(suite, "testcase", classname=classname, name=case)
        if index == 0 and invalid_case in {"skipped", "failure", "error"}:
            SubElement(element, invalid_case)
    directory.mkdir(parents=True)
    ElementTree(document).write(directory / report)


@pytest.mark.parametrize("name", WORKFLOWS)
@pytest.mark.parametrize("missing_case", [None, *sorted(MISSING_FEE_CASES)])
def test_missing_fee_receipt_requires_real_apply_replay_rollback_drift_and_concurrency(
    name: str, missing_case: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every checked-in missing-fee PG scenario needs a successful actual receipt."""
    gate = _step(_workflow(name), PG_NAME)
    guard = shlex.split(next(line for line in gate["run"].splitlines() if "missing_fee_required = {" in line))[2]
    _write_case_receipt(tmp_path / "logs/ci", "dydata104-postgres.xml", "tests.test_missing_fee_repair_postgres",
                        MISSING_FEE_CASES - {missing_case})
    monkeypatch.chdir(tmp_path)
    if missing_case is None:
        exec(compile(guard, "<workflow-missing-fee-guard>", "exec"), {})
    else:
        with pytest.raises(AssertionError, match="missing-fee"):
            exec(compile(guard, "<workflow-missing-fee-guard>", "exec"), {})


@pytest.mark.parametrize("name", WORKFLOWS)
@pytest.mark.parametrize("gate_name,marker,report,module,cases", (
    (PG_NAME, "missing_fee_required = {", "dydata104-postgres.xml", "tests.test_missing_fee_repair_postgres", MISSING_FEE_CASES),
    (PG_NAME, "write_proof_required = {", "dydata104-postgres.xml", "tests.test_missing_fee_write_proof_postgres", WRITE_PROOF_CASES),
    (IMAGE_NAME, "image_required = {", "dydata104-browser-image.xml", "test_browser_image_dependency_compat", IMAGE_CASES),
))
@pytest.mark.parametrize("invalid_case", ("wrong_module", "skipped", "failure", "error"))
def test_new_receipt_guards_reject_cases_without_successful_execution(
    name: str, gate_name: str, marker: str, report: str, module: str, cases: set[str],
    invalid_case: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matching names alone cannot stand in for successful tests in the right module."""
    gate = _step(_workflow(name), gate_name)
    guard = shlex.split(next(line for line in gate["run"].splitlines() if marker in line))[2]
    _write_case_receipt(tmp_path / "logs/ci", report, module, cases, invalid_case=invalid_case)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(AssertionError):
        exec(compile(guard, "<workflow-new-case-guard>", "exec"), {})


@pytest.mark.parametrize("name", WORKFLOWS)
@pytest.mark.parametrize("missing_case", [None, *sorted(IMAGE_CASES)])
def test_browser_image_receipt_requires_all_three_compatibility_cases(
    name: str, missing_case: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Partial image coverage may not pass even if the host full suite skipped Pillow."""
    gate = _step(_workflow(name), IMAGE_NAME)
    guard = shlex.split(next(line for line in gate["run"].splitlines() if "image_required = {" in line))[2]
    _write_case_receipt(tmp_path / "logs/ci", "dydata104-browser-image.xml", "test_browser_image_dependency_compat",
                        IMAGE_CASES - {missing_case})
    monkeypatch.chdir(tmp_path)
    if missing_case is None:
        exec(compile(guard, "<workflow-image-case-guard>", "exec"), {})
    else:
        with pytest.raises(AssertionError, match="browser image"):
            exec(compile(guard, "<workflow-image-case-guard>", "exec"), {})


@pytest.mark.parametrize("name", WORKFLOWS)
@pytest.mark.parametrize("tests,skipped,failures,errors", (
    (3, 0, 0, 0), (0, 0, 0, 0), (2, 0, 0, 0), (4, 0, 0, 0),
    (3, 1, 0, 0), (3, 0, 1, 0), (3, 0, 0, 1),
))
def test_browser_image_junit_requires_exactly_three_passes_without_skips(
    name: str, tests: int, skipped: int, failures: int, errors: int,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Execute the exact image aggregate guard against incomplete or failed results."""
    gate = _step(_workflow(name), IMAGE_NAME)
    guard = shlex.split(next(line for line in gate["run"].splitlines() if line.startswith("python -c 'import xml.etree")))[2]
    _write_case_receipt(tmp_path / "logs/ci", "dydata104-browser-image.xml", "test_browser_image_dependency_compat",
                        IMAGE_CASES, tests=tests, skipped=skipped, failures=failures, errors=errors)
    monkeypatch.chdir(tmp_path)
    if tests == 3 and not (skipped or failures or errors):
        exec(compile(guard, "<workflow-image-junit-guard>", "exec"), {})
    else:
        with pytest.raises(AssertionError):
            exec(compile(guard, "<workflow-image-junit-guard>", "exec"), {})


def test_release_workflows_share_the_same_browser_image_contract() -> None:
    """Both release paths enforce identical installed-package and receipt contracts."""
    gates = [_step(_workflow(name), IMAGE_NAME) for name in WORKFLOWS]
    assert gates[0] == gates[1]


@pytest.mark.parametrize("name", WORKFLOWS)
@pytest.mark.parametrize("missing_case", [None, *sorted(WRITE_PROOF_CASES)])
def test_write_proof_receipt_requires_scale_and_database_effect_cases(
    name: str, missing_case: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = _step(_workflow(name), PG_NAME)
    guard = shlex.split(next(line for line in gate["run"].splitlines() if "write_proof_required = {" in line))[2]
    _write_case_receipt(tmp_path / "logs/ci", "dydata104-postgres.xml",
                        "tests.test_missing_fee_write_proof_postgres", WRITE_PROOF_CASES - {missing_case})
    monkeypatch.chdir(tmp_path)
    if missing_case is None:
        exec(compile(guard, "<workflow-write-proof-guard>", "exec"), {})
    else:
        with pytest.raises(AssertionError, match="write-proof"):
            exec(compile(guard, "<workflow-write-proof-guard>", "exec"), {})
