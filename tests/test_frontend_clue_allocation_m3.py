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
    assert "hasPageAccess(user, location.pathname)" in app_source
    assert '{ href: "/admin/clue-allocation", label: "线索分配规则", pageKey: "D05" }' in shell_source
    assert 'href: "/admin/clue-allocation"' in home_source
    assert 'title: "线索分配"' in home_source
    assert "isHighestAdmin" in _read("pages/AdminClueAllocationPage.tsx")


def test_m3_allocation_control_uses_preview_then_confirmed_execution() -> None:
    page_source = _read("pages/AdminClueAllocationPage.tsx")
    client_source = _read("api/client.ts")
    type_source = _read("types/dashboard.ts")
    demo_source = _read("demo/clueDemoRepository.ts")

    assert "fetchClueAllocationEligibleLeads" in page_source
    assert "fetchClueHeadquartersPool" in page_source
    assert "previewClueAllocationCycle" in page_source
    assert "runClueAllocationTrial" in page_source
    assert "rebuildClueAllocationTrial" in page_source
    assert 'confirmation_text: "确认试运行"' in page_source
    assert 'confirmation_text: "确认重建试运行"' in page_source
    assert "ConfirmDialog" in page_source
    assert "window.confirm" not in page_source
    assert "允许覆盖已有跟进记录" in page_source
    assert "preview_token" in page_source
    assert "source_cycle_id" in page_source
    assert "phone" not in page_source.lower()

    for endpoint in [
        "/admin/clue-allocation/eligible-leads",
        "/admin/clue-allocation/headquarters-pool",
        "/admin/clue-allocation/cycle-previews",
        "/admin/clue-allocation/trial-cycles",
        "/admin/clue-allocation/rebuild-cycles",
    ]:
        assert endpoint in client_source
    for legacy_endpoint in [
        "/admin/clue-allocation/cycles/preview",
        "/admin/clue-allocation/cycles/trial",
        "/admin/clue-allocation/cycles/rebuild",
    ]:
        assert legacy_endpoint not in client_source
    assert 'handlePreview("trial_rebuild")' in page_source
    assert 'operation: "trial" | "trial_rebuild"' in type_source
    assert 'payload.confirmation_text !== "确认试运行"' in demo_source
    assert 'payload.confirmation_text !== "确认重建试运行"' in demo_source
    assert "this.state.eligibleLeads = businessState.eligibleLeads" in demo_source
    assert "decision.assignment_round_id = null" in demo_source
    assert 'decision.dataset_kind = "trial"' in demo_source
    assert 'cycle_mode: cycleType' in demo_source
    assert "usingMock: false" in client_source
    assert "export interface ClueAllocationCycleRequest" in type_source
    assert "export interface ClueHeadquartersPoolEntry" in type_source
    assert "createStableIdempotencyKey" in client_source
    assert "payload.preview_token" in client_source
    assert "completedCycleResults" in demo_source


def test_m3_allocation_records_expose_persisted_cycle_item_details() -> None:
    page_source = _read("pages/AdminClueAllocationPage.tsx")
    client_source = _read("api/client.ts")
    type_source = _read("types/dashboard.ts")
    styles = _read("styles.css")

    assert "fetchClueAllocationCycle" in page_source
    assert "分配批次详情" in page_source
    assert "查看详情" in page_source
    assert "cycleItemColumns" in page_source
    for field in [
        "item.rule_binding_id",
        "item.decision_id",
        "item.assignment_round_id",
        "item.headquarters_pool_entry_id",
        "item.started_at",
        "item.completed_at",
        "item.error_code",
    ]:
        assert field in page_source
    assert "/admin/clue-allocation/cycles/${encodeURIComponent(cycleId)}" in client_source
    assert "export interface ClueAllocationCycleItem" in type_source
    assert "export interface ClueAllocationCycleDetailData" in type_source
    assert ".clue-allocation-cycle-dialog" in styles


def test_m3_each_allocation_subview_only_loads_its_own_api_group() -> None:
    page_source = _read("pages/AdminClueAllocationPage.tsx")

    assert 'if (activeSubview === "trial")' in page_source
    assert 'else if (activeSubview === "records")' in page_source
    assert 'else if (activeSubview === "headquarters")' in page_source
    assert "fetchClueAllocationEligibleLeads()," in page_source
    assert "const auditData = await fetchClueAllocationAuditLogs();" in page_source
    assert "if (isHighestAdmin)" in page_source
    assert "{isHighestAdmin ? (" in page_source
    assert "fetchClueHeadquartersPool({" in page_source
    assert "fetchClueAllocationRules();" in page_source


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


def test_m3_rule_lifecycle_refreshes_selected_version_detail_after_writes() -> None:
    page_source = _read("pages/AdminClueAllocationPage.tsx")

    assert "const refreshSelectedRuleDetail = async" in page_source
    assert page_source.count("await refreshSelectedRuleDetail();") >= 3


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


def test_m3_headquarters_pool_exposes_approved_filters_and_inventory_summary() -> None:
    page_source = _read("pages/AdminClueAllocationPage.tsx")
    client_source = _read("api/client.ts")
    type_source = _read("types/dashboard.ts")
    styles = _read("styles.css")

    for label in [
        "总部池状态",
        "入池原因",
        "入池日期起",
        "入池日期止",
        "订单状态",
        "锚点城市",
        "搜索",
        "订单号或主线索键",
        "清空筛选",
        "当前库存",
        "筛选结果",
    ]:
        assert label in page_source

    for query_key in [
        "entry_status",
        "reason_code",
        "entered_date_start",
        "entered_date_end",
        "normalized_order_status",
        "city_code",
        "q",
        "page",
        "page_size",
    ]:
        assert query_key in client_source

    assert "ClueHeadquartersPoolFilters" in client_source
    assert "displayOrderStatus(headquartersOrderStatus(entry))" in page_source
    assert "headquartersPool.summary.current_inventory" in page_source
    assert "export interface ClueHeadquartersPoolSummary" in type_source
    assert "export interface ClueHeadquartersPoolFilterOptions" in type_source
    assert ".clue-headquarters-filter-bar" in styles


def test_m3_headquarters_pool_locks_canonical_reason_contract_and_unknown_copy() -> None:
    page_source = _read("pages/AdminClueAllocationPage.tsx")
    client_source = _read("api/client.ts")
    type_source = _read("types/dashboard.ts")
    demo_source = _read("demo/clueDemoRepository.ts")
    labels_source = _read("utils/userFacingLabels.ts")

    for query_key in [
        "entry_status",
        "reason_code",
        "entered_date_start",
        "entered_date_end",
        "normalized_order_status",
        "city_code",
        "q",
        "page",
        "page_size",
    ]:
        assert query_key in client_source
    for field in ["reason_code", "reason_label", "normalized_order_status"]:
        assert f"{field}: string" in type_source
    for option in [
        "entry_statuses",
        "reason_codes",
        "normalized_order_statuses",
        "city_codes",
    ]:
        assert option in type_source
        assert option in page_source or option in demo_source
    for reason_code in [
        "missing_follow_poi",
        "anchor_store_unmapped",
        "anchor_geo_invalid",
        "no_published_rule",
        "all_strategies_disabled",
        "no_eligible_candidate",
        "all_strategies_exhausted",
        "data_inconsistency",
        "follow_poi_missing",
        "follow_poi_unmapped",
        "follow_poi_store_missing",
        "anchor_coordinates_invalid",
        "anchor_province_missing",
        "anchor_city_missing",
        "anchor_city_code_missing",
        "no_candidate",
        "strategies_exhausted",
        "headquarters_pool_retained",
    ]:
        assert reason_code in labels_source
    assert "关键事实不一致，待总部治理" in labels_source
    assert "entry.reason_code || entry.reason" in page_source
    assert "entry.normalized_order_status || entry.order_status" in page_source
    assert "entry.lead_key.toLowerCase()" in demo_source
