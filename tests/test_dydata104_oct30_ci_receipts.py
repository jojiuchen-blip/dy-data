"""October 30 gates require each new module, not just unrelated passing tests."""
from pathlib import Path
import shlex
from xml.etree.ElementTree import Element, ElementTree, SubElement

import pytest

from test_dydata104_ci_coverage import BROWSER_NAME, PG_NAME, RECOVERY_NAME, WORKFLOWS, _step, _workflow


@pytest.mark.parametrize("workflow", WORKFLOWS)
@pytest.mark.parametrize("gate_name,report,counts,label", [
    (PG_NAME, "dydata104-postgres.xml", {
        "test_finance_import_chinese_templates": 22,
        "test_finance_sap_resolution_lineage": 11,
        "test_billing_auto_confirmation_postgres": 14,
        "test_commission_product_types_postgres": 10,
        "test_commission_authority_query_postgres": 18,
        "test_commission_authority_import_paths": 4,
        "test_ops_browser_observation": 58,
    }, "October 30 PostgreSQL modules"),
    (BROWSER_NAME, "dydata104-finance-browser.xml", {
        "test_dydata104_oct30_invoice_browser": 9,
        "test_finance_import_chinese_browser": 2,
    }, "October 30 invoice and committed import"),
])
@pytest.mark.parametrize("invalid", [None, "missing", "skipped", "wrong_module"])
def test_each_new_module_requires_successful_execution(
    workflow: str, gate_name: str, report: str, counts: dict[str, int], label: str,
    invalid: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = _step(_workflow(workflow), gate_name)
    guard = shlex.split(next(line for line in gate["run"].splitlines() if label in line))[2]
    document = Element("testsuites")
    suite = SubElement(document, "testsuite")
    for module_index, (module, count) in enumerate(counts.items()):
        for index in range(count):
            if module_index == index == 0 and invalid == "missing":
                continue
            classname = "tests.unrelated" if module_index == index == 0 and invalid == "wrong_module" else "tests." + module
            case = SubElement(suite, "testcase", classname=classname, name=f"synthetic_receipt_{index}")
            if module_index == index == 0 and invalid == "skipped":
                SubElement(case, "skipped")
    directory = tmp_path / "logs/ci"
    directory.mkdir(parents=True)
    ElementTree(document).write(directory / report)
    monkeypatch.chdir(tmp_path)
    if invalid is None:
        exec(compile(guard, "<synthetic-oct30-receipt>", "exec"), {})
    else:
        with pytest.raises(AssertionError, match="October 30"):
            exec(compile(guard, "<synthetic-oct30-receipt>", "exec"), {})


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_real_image_recovery_runs_after_build_and_uploads_receipt(workflow: str) -> None:
    definition = _workflow(workflow)
    steps = definition["jobs"]["verify"]["steps"]
    gate = _step(definition, RECOVERY_NAME)
    assert steps.index(_step(definition, "Build Browser Docker image")) < steps.index(gate)
    assert gate["env"]["DY_BROWSER_RECOVERY_IMAGE"] == "dy-dashboard-browser:ci"
    assert "tests/test_browser_process_recovery_image.py" in gate["run"]
    assert not gate.get("if") and not gate.get("continue-on-error")
    receipt = _step(definition, "Upload DYDATA-104 browser image verification receipt")
    assert "logs/ci/dydata104-browser-recovery.xml" in receipt["with"]["path"]
    assert receipt["if"] == "always()" and steps.index(receipt) > steps.index(gate)


@pytest.mark.parametrize("workflow", WORKFLOWS)
@pytest.mark.parametrize("count,skipped", [(3, 0), (0, 0), (2, 0), (3, 1)])
def test_real_image_recovery_requires_three_non_skipped_cases(
    workflow: str, count: int, skipped: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = _step(_workflow(workflow), RECOVERY_NAME)
    guard = shlex.split(next(line for line in gate["run"].splitlines() if "import xml.etree" in line))[2]
    document = Element("testsuites")
    SubElement(document, "testsuite", tests=str(count), skipped=str(skipped), failures="0", errors="0")
    directory = tmp_path / "logs/ci"
    directory.mkdir(parents=True)
    ElementTree(document).write(directory / "dydata104-browser-recovery.xml")
    monkeypatch.chdir(tmp_path)
    if count == 3 and skipped == 0:
        exec(compile(guard, "<synthetic-recovery-receipt>", "exec"), {})
    else:
        with pytest.raises(AssertionError, match="browser recovery"):
            exec(compile(guard, "<synthetic-recovery-receipt>", "exec"), {})
