from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web" / "src"


def _read(relative_path: str) -> str:
    return (WEB / relative_path).read_text(encoding="utf-8")


def _segment(source: str, start: str, end: str) -> str:
    return source[source.index(start) : source.index(end, source.index(start))]


def test_f09_real_order_detail_errors_are_not_replaced_with_demo_rows() -> None:
    source = _read("api/client.ts")
    detail = _segment(
        source,
        "export function fetchClueOrderDetail",
        "export function exportClueAssignmentRounds",
    )

    assert "{ fallbackOnError: false }" in detail
    assert "fetchClueOrderDetail" in _read("pages/ClueCenterPage.tsx")


def test_f11_allocation_list_clients_send_server_pagination() -> None:
    source = _read("api/client.ts")
    contracts = [
        ("fetchClueAllocationEligibleLeads", "/admin/clue-allocation/eligible-leads"),
        ("fetchClueAllocationCycles", "/admin/clue-allocation/cycles"),
        ("fetchClueAllocationAuditLogs", "/admin/clue-allocation/audit-logs"),
        ("fetchClueAllocationRules", "/admin/clue-allocation/rules"),
        ("fetchClueAllocationDecisions", "/admin/clue-allocation/decisions"),
        ("fetchClueAllocationStoreScores", "/admin/clue-allocation/store-scores"),
    ]

    for function_name, endpoint in contracts:
        start = source.index(f"export async function {function_name}")
        end = source.find("export ", start + 8)
        segment = source[start:] if end < 0 else source[start:end]
        assert "page = 1" in segment, function_name
        assert "pageSize = 50" in segment, function_name
        assert "{ page, page_size: pageSize }" in segment, function_name
        assert endpoint in segment, function_name


def test_f11_demo_lists_apply_the_same_page_contract() -> None:
    source = _read("demo/clueDemoRepository.ts")
    for method_name in [
        "getEligibleLeads",
        "getCycles",
        "getAuditLogs",
        "getRules",
        "getDecisions",
        "getStoreScores",
    ]:
        start = source.index(f"  {method_name}(")
        end = source.find("\n  ", source.find("):", start) + 3)
        while end >= 0 and end + 3 < len(source) and source[end + 3] in " \t":
            end = source.find("\n  ", end + 3)
        segment = source[start:] if end < 0 else source[start:end]
        assert "page = 1" in segment, method_name
        assert "pageSize = 50" in segment, method_name
    assert source.count("paginate(rows, page, pageSize)") >= 5
    assert "const pagedRows = paginate(" in source


def test_f11_page_keeps_totals_and_ignores_stale_resource_responses() -> None:
    source = _read("pages/AdminClueAllocationPage.tsx")

    for pagination_state in [
        "eligiblePagination",
        "cyclesPagination",
        "decisionsPagination",
        "auditPagination",
        "rulesPagination",
    ]:
        assert pagination_state in source
    assert "scoreData?.pagination.total" in source
    assert "resourceRequestIds" in source
    assert "isCurrentResourceRequest" in source
    assert source.count("<TablePagination") >= 9
    assert "全选当前页" in source
    assert "翻页后可选择其他批次" in source
