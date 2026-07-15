from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web" / "src"


def _read(relative_path: str) -> str:
    return (WEB / relative_path).read_text(encoding="utf-8")


def test_m3_allocation_control_is_admin_readable_and_highest_admin_writable() -> None:
    app_source = _read("App.tsx")
    shell_source = _read("components/Shell.tsx")
    home_source = _read("pages/AdminHomePage.tsx")

    assert 'pathname === "/admin/clue-allocation"' in app_source
    assert 'pathname === "/admin/clue-allocation/rules"' in app_source
    assert "AdminClueAllocationPage" in app_source
    assert "user.role === \"admin\"" in app_source
    assert '{ href: "/admin/clue-allocation", label: "线索分配" }' in shell_source
    assert 'href: "/admin/clue-allocation"' in home_source
    assert 'title: "线索分配"' in home_source
    assert "isHighestAdmin" in _read("pages/AdminClueAllocationPage.tsx")


def test_m3_allocation_control_uses_preview_then_confirmed_execution() -> None:
    page_source = _read("pages/AdminClueAllocationPage.tsx")
    client_source = _read("api/client.ts")
    type_source = _read("types/dashboard.ts")

    assert "fetchClueAllocationEligibleLeads" in page_source
    assert "fetchClueHeadquartersPool" in page_source
    assert "previewClueAllocationCycle" in page_source
    assert "runClueAllocationTrial" in page_source
    assert "rebuildClueAllocationTrial" in page_source
    assert 'confirm: true' in page_source
    assert "window.confirm" in page_source
    assert "允许覆盖已有跟进记录" in page_source
    assert "preview_token" in page_source
    assert "source_cycle_id" in page_source
    assert "phone" not in page_source.lower()

    for endpoint in [
        "/admin/clue-allocation/eligible-leads",
        "/admin/clue-allocation/headquarters-pool",
        "/admin/clue-allocation/cycles/preview",
        "/admin/clue-allocation/cycles/trial",
        "/admin/clue-allocation/cycles/rebuild",
    ]:
        assert endpoint in client_source
    assert "usingMock: false" in client_source
    assert "export interface ClueAllocationCycleRequest" in type_source
    assert "export interface ClueHeadquartersPoolEntry" in type_source


def test_m3_allocation_control_has_mobile_safe_layout() -> None:
    styles = _read("styles.css")

    assert ".clue-allocation-preview__body" in styles
    assert ".clue-allocation-control__actions" in styles
    assert ".clue-allocation-admin-table-wrap" in styles
    assert "@media (max-width: 640px)" in styles


def test_m3_management_surface_exposes_rule_score_and_decision_evidence_safely() -> None:
    page_source = _read("pages/AdminClueAllocationPage.tsx")
    client_source = _read("api/client.ts")
    type_source = _read("types/dashboard.ts")

    for value in [
        "规则范围与版本",
        "固定分配策略",
        "最近分配决策",
        "门店评分快照",
        "新建草案版本",
        "发布版本",
        "退役版本",
        "移动端仅可查看",
    ]:
        assert value in page_source
    assert "window.matchMedia" in page_source
    assert "isWritable" in page_source

    for name, endpoint in [
        ("fetchClueAllocationRules", "/admin/clue-allocation/rules"),
        ("fetchClueAllocationRuleDetail", "/admin/clue-allocation/rules/"),
        ("fetchClueAllocationDecisions", "/admin/clue-allocation/decisions"),
        ("fetchClueAllocationStoreScores", "/admin/clue-allocation/store-scores"),
        ("createClueAllocationRuleVersion", "/versions"),
        ("publishClueAllocationRuleVersion", "/publish"),
        ("retireClueAllocationRuleVersion", "/retire"),
    ]:
        assert name in client_source
        assert endpoint in client_source

    for declaration in [
        "export interface ClueAllocationRule",
        "export interface ClueAllocationRuleVersion",
        "export interface ClueAllocationDecision",
        "export interface StoreScoreSnapshot",
        "export interface ClueAllocationRuleVersionWrite",
    ]:
        assert declaration in type_source


def test_m3_rule_management_has_a_compact_read_only_mobile_layout() -> None:
    styles = _read("styles.css")

    for selector in [
        ".clue-allocation-management-grid",
        ".clue-allocation-rule-editor",
        ".clue-allocation-rule-versions",
        ".clue-allocation-version-metrics",
        ".clue-allocation-strategy-list",
    ]:
        assert selector in styles

    mobile_styles = styles[styles.index("@media (max-width: 640px)") :]
    assert ".clue-allocation-management-grid" in mobile_styles
    assert "grid-template-columns: 1fr;" in mobile_styles
