from pathlib import Path


WEB_SRC = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"


def read_source(relative_path: str) -> str:
    return (WEB_SRC / relative_path).read_text(encoding="utf-8")


def test_component_room_and_task_rail_use_live_operations_contract() -> None:
    page = read_source("pages/AdminSyncPage.tsx")
    room = read_source("components/admin-sync/ComponentRoom.tsx")
    card = read_source("components/admin-sync/ComponentCard.tsx")
    rail = read_source("components/admin-sync/SyncTaskRail.tsx")
    client = read_source("api/client.ts")
    types = read_source("types/dashboard.ts")

    assert "if (!isHighestAdmin)" in page
    assert "<ComponentRoom" in page
    assert page.index("<ComponentRoom") < page.index("<AdminProductSyncPanel")
    assert "fetchAdminOperationsOverview" in room
    assert "AbortController" in room
    assert "document.hidden" in room
    assert "5000" in room and "15000" in room
    assert "signal?: AbortSignal" in client
    assert '"/admin/operations/overview"' in client
    assert "AdminOperationsOverview" in types
    assert "observed_status" in types
    assert "aria-label={`查看${label}详情`}" in card
    assert "StatusChip" in card
    assert "button" in rail and "onSelectJob" in rail


def test_detail_drawer_reuses_accessible_dialog_and_restores_focus() -> None:
    drawer = read_source("components/admin-sync/SyncDetailDrawer.tsx")
    room = read_source("components/admin-sync/ComponentRoom.tsx")

    assert "<Dialog" in drawer
    assert "returnFocusRef={returnFocusRef}" in drawer
    assert 'panelClassName="sync-detail-drawer"' in drawer
    assert "lastTriggerRef" in room
    assert "Escape" not in drawer
    assert "prefers-reduced-motion" in read_source("styles.css")


def test_control_confirmation_is_intent_only_and_restart_is_strictly_allowlisted() -> None:
    room = read_source("components/admin-sync/ComponentRoom.tsx")
    dialog = read_source("components/admin-sync/SyncControlConfirmDialog.tsx")
    presentation = read_source("components/admin-sync/syncPresentation.ts")
    client = read_source("api/client.ts")

    assert 'new Set(["worker", "browser"])' in presentation
    assert "allow_restart" in room
    assert "API、Postgres、Proxy 和宿主机不提供重启入口" in room
    assert "当前活动任务" in dialog
    assert "租约恢复" in dialog
    assert "命令已提交" in room
    assert "submitAdminOpsCommand" in client
    assert '"Idempotency-Key"' in client
    assert "docker" not in client.lower()


def test_component_room_styles_use_tokens_and_responsive_single_column() -> None:
    styles = read_source("styles.css")

    assert ".component-room-layout" in styles
    assert ".component-room-grid" in styles
    assert ".sync-task-rail" in styles
    assert ".sync-detail-drawer" in styles
    assert "grid-template-columns: minmax(0, 1fr)" in styles
    assert "var(--radius-lg)" in styles
    assert "var(--shadow-card)" in styles


def test_mature_sync_workflow_remains_wired_below_the_control_console() -> None:
    page = read_source("pages/AdminSyncPage.tsx")

    assert "<AdminProductSyncPanel />" in page
    assert "fetchSyncAdmin" in page
    assert "saveSyncConfig" in page
    assert 'id="manual-sync-task"' in page
    assert "手动补拉" in page
