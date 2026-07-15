from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web" / "src"


def _read(relative_path: str) -> str:
    return (WEB / relative_path).read_text(encoding="utf-8")


def test_legacy_reassign_rule_frontend_surface_is_removed() -> None:
    app_source = _read("App.tsx")
    shell_source = _read("components/Shell.tsx")
    home_source = _read("pages/AdminHomePage.tsx")
    client_source = _read("api/client.ts")
    types_source = _read("types/dashboard.ts")
    mock_data_source = _read("data/mockData.ts")
    clue_mock_source = _read("data/mock/clue_center.json")

    assert "AdminClueRulePage" not in app_source
    assert "/admin/clues/rules" not in app_source
    assert "/admin/clues/rules" not in shell_source
    assert "/admin/clues/rules" not in home_source
    assert not (WEB / "pages" / "AdminClueRulePage.tsx").exists()
    assert "ClueReassignRule" not in client_source
    assert "clue-reassign-rule" not in client_source
    assert "rebuildClues" not in client_source
    assert "ClueReassignRule" not in types_source
    assert "ClueReassignRule" not in mock_data_source
    assert '"rule": {' not in clue_mock_source
    assert '"rebuild": {' not in clue_mock_source


def test_allocation_module_has_exactly_four_subviews_and_sync_owns_maintenance_action() -> None:
    app_source = _read("App.tsx")
    allocation_source = _read("pages/AdminClueAllocationPage.tsx")
    sync_source = _read("pages/AdminSyncPage.tsx")
    shell_source = _read("components/Shell.tsx")
    client_source = _read("api/client.ts")

    expected_subviews = [
        ("rules", "分配规则"),
        ("trial", "分配试运行"),
        ("records", "分配记录"),
        ("headquarters", "总部线索池"),
    ]
    subview_items_match = re.search(
        r"const allocationSubviewItems:.*?= \[(?P<items>.*?)\];",
        allocation_source,
        re.DOTALL,
    )
    assert subview_items_match is not None
    assert re.findall(r'id: "([^"]+)"', subview_items_match.group("items")) == [
        view for view, _ in expected_subviews
    ]
    for view, label in expected_subviews:
        assert label in allocation_source
        assert f'activeSubview === "{view}"' in allocation_source

    assert 'id: "maintenance"' not in allocation_source
    assert 'activeSubview === "maintenance"' not in allocation_source
    assert "rebuildClueCenterMaterialization" not in allocation_source
    assert "rebuildClueCenterMaterialization" in client_source
    assert '"/admin/sync/clue-center/rebuild"' in client_source
    assert '"/admin/clues/rebuild"' not in client_source
    assert "rebuildClueCenterMaterialization" in sync_source
    assert "线索中心数据维护" in sync_source
    assert "不会重建任何分配试运行批次" in sync_source
    assert "disabled={!isHighestAdmin || rebuildingClueCenter}" in sync_source
    assert "rebuildClueAllocationTrial" in allocation_source
    assert '"/admin/clue-allocation/cycles/rebuild"' in client_source
    assert "<AdminSyncPage isHighestAdmin={user.is_highest_admin === true} />" in app_source
    assert 'user.role === "admin"' in app_source
    assert 'user.is_highest_admin ? "最高管理员" : "管理员"' in shell_source
