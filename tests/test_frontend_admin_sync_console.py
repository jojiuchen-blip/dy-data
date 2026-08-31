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


def test_admin_home_hides_d10_sync_entry_without_both_permission_and_highest_admin() -> None:
    home = read_source("pages/AdminHomePage.tsx")

    assert 'pageKey: "D10"' in home
    assert "highestAdminOnly: true" in home
    assert "sessionUser?.is_highest_admin === true" in home
    assert "sessionUser.page_keys.includes(item.pageKey)" in home
    assert "setSessionUser(response.data)" in home


def test_confirmation_replaces_drawer_so_escape_only_closes_the_top_layer() -> None:
    room = read_source("components/admin-sync/ComponentRoom.tsx")
    dialog = read_source("components/admin-sync/SyncControlConfirmDialog.tsx")

    assert "control === null ? (" in room
    assert room.count("<SyncDetailDrawer") == 1
    assert room.count("<SyncControlConfirmDialog") == 1
    assert "returnFocusRef={lastTriggerRef}" in room
    assert "returnFocusRef={returnFocusRef}" in dialog
    assert "addEventListener" not in dialog


def test_control_request_keeps_one_idempotency_key_across_same_dialog_retries() -> None:
    room = read_source("components/admin-sync/ComponentRoom.tsx")
    dialog = read_source("components/admin-sync/SyncControlConfirmDialog.tsx")
    control_definition = room.split("type ControlRequest =", 1)[1].split(
        "const actionLabels", 1
    )[0]
    submit_control = room.split("const submitControl", 1)[1].split(
        "const controlTarget", 1
    )[0]
    catch_block = submit_control.split("catch (requestError)", 1)[1].split(
        "finally", 1
    )[0]

    assert control_definition.count("idempotencyKey: string") == 2
    assert room.count("idempotencyKey: nextIdempotencyKey") == 2
    assert submit_control.count("control.idempotencyKey") == 2
    assert "nextIdempotencyKey" not in submit_control
    assert "setControl(null)" not in catch_block
    assert "setControlError(message)" in catch_block
    assert "setReasonLocked(true)" in dialog
    assert "disabled={reasonLocked}" in dialog
    assert "同一请求可安全重试" in dialog


def test_ops_command_history_is_polled_and_renders_server_fact_statuses() -> None:
    room = read_source("components/admin-sync/ComponentRoom.tsx")
    history = read_source("components/admin-sync/OpsCommandHistory.tsx")
    presentation = read_source("components/admin-sync/syncPresentation.ts")
    client = read_source("api/client.ts")
    types = read_source("types/dashboard.ts")

    assert "fetchAdminOpsCommands(currentController.signal)" in room
    assert "setCommands(commandsResult.value.data.rows)" in room
    assert '<OpsCommandHistory commands={commands} error={commandsError} />' in room
    assert "export async function fetchAdminOpsCommands" in client
    assert '"/admin/operations/commands"' in client
    assert "AdminOpsCommandListData" in types
    for status in (
        "pending",
        "running",
        "success",
        "failed",
        "rejected",
        "expired",
        "cancelled",
    ):
        assert f'{status}: "' in presentation
        assert f'| "{status}"' in types or f'= "{status}"' in types
    assert "componentLabel(command.target_component)" in history
    assert "formatDateTime(timestamp.value)" in history
    assert "command.result_summary" in history
    assert "提交回执不视为执行成功" in history


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
    assert ".ops-command-history" in styles
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
