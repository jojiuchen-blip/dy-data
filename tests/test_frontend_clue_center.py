from pathlib import Path
import json


WEB_SRC = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"


def read_source(relative_path: str) -> str:
    return (WEB_SRC / relative_path).read_text(encoding="utf-8")


def assert_in_order(source: str, values: list[str]) -> None:
    position = -1
    for value in values:
        next_position = source.find(value, position + 1)
        assert next_position > position, f"{value!r} should appear after prior field"
        position = next_position


def test_clue_center_list_field_order_and_removed_internal_fields() -> None:
    source = read_source("pages/ClueCenterPage.tsx")

    assert_in_order(
        source,
        [
            'title: "联系方式"',
            'title: "线索状态"',
            'title: "分配轮次"',
            'title: "本轮跟进时间"',
            'title: "商品名称"',
            'title: "商品类型"',
            'title: "线索生成时间"',
            'title: "本轮失效时间"',
        ],
    )

    for removed_label in [
        "线索轮次ID",
        "当前轮次",
        "距离再分配剩余时间",
        "自店核销",
        "轮次状态",
        "再分配时间",
    ]:
        assert removed_label not in source


def test_clue_center_does_not_display_douyin_follow_store_as_our_assignment() -> None:
    source = read_source("pages/ClueCenterPage.tsx")

    assert "线索当前归属" not in source
    assert "分配门店" not in source
    assert "归属门店" not in source
    assert "current_assigned_store_name" not in source
    assert "assigned_store_name" not in source


def test_clue_center_detail_follow_up_layout_and_actions() -> None:
    source = read_source("pages/ClueCenterPage.tsx")

    assert "线索跟进详情" in source
    assert "clue-followup-detail__grid" in source
    assert "clue-followup-detail__main" in source
    assert "clue-followup-detail__side" in source
    assert "跟进历史" in source
    assert "跟进操作" in source
    assert 'value="unreachable"' in source
    assert "未接通" in source
    assert 'value="lost"' in source
    assert "线索战败" in source
    assert 'value="success"' in source
    assert "跟进成功" in source
    assert "本次跟进结论/备注" in source
    assert "保存跟进" in source

    summary_start = source.index("clue-followup-detail__summary")
    history_start = source.index("跟进历史")
    side_start = source.index("clue-followup-detail__side")
    assert summary_start < history_start < side_start


def test_clue_center_filters_follow_store_scope_spec() -> None:
    source = read_source("pages/ClueCenterPage.tsx")
    types_source = read_source("types/dashboard.ts")

    assert "currentUser" in source
    assert "showStoreLocationFilters" in source
    assert "currentUser.role !== \"store\" || currentUser.store_ids.length !== 1" in source
    assert "province" in source
    assert "verificationStatus" in source
    assert "assigned_store_id" in source

    filter_bar_start = source.index('<FilterBar className="clue-filter-bar">')
    filter_bar_end = source.index("</FilterBar>", filter_bar_start)
    filter_bar = source[filter_bar_start:filter_bar_end]
    assert "处理状态" not in filter_bar
    assert "roundStatus" not in filter_bar
    assert "round_status" not in filter_bar
    assert_in_order(
        filter_bar,
        [
            "showStoreLocationFilters",
            'label="省份"',
            'label="城市"',
            'label="门店"',
            'label="线索生成日期起"',
            'label="线索生成日期止"',
            'label="线索状态"',
            'label="商品类型"',
            'label="核销状态"',
            "清空筛选",
        ],
    )

    assert "assigned_provinces: string[];" in types_source
    assert "verification_statuses: string[];" in types_source
    assert "province?: string;" in types_source
    assert "verification_status?: string;" in types_source


def test_clue_follow_up_types_and_api_client_are_declared() -> None:
    types_source = read_source("types/dashboard.ts")
    client_source = read_source("api/client.ts")

    assert "export interface ClueFollowUpRecord" in types_source
    assert "follow_up_record_id: string;" in types_source
    assert "follow_up_records: ClueFollowUpRecord[];" in types_source
    assert 'follow_result: "unreachable" | "lost" | "success";' in types_source
    assert "export interface ClueFollowUpPayload" in types_source
    assert "assignment_round_id: string;" in types_source
    assert "note: string | null;" in types_source

    assert "saveClueFollowUp" in client_source
    assert "/follow-up" in client_source
    assert "sendJson<ClueFollowUpRecord>" in client_source
    assert "body: payload" in client_source


def test_clue_phone_permission_and_copy_use_full_phone_only() -> None:
    source = read_source("pages/ClueCenterPage.tsx")

    assert "canViewFullPhone" in source
    can_view_body = source[
        source.index("function canViewFullPhone") : source.index(
            "function getPhoneUnavailableReason"
        )
    ]
    assert "row.is_current_round" in can_view_body
    assert 'row.round_effective_status === "active"' in can_view_body
    assert "getPhoneUnavailableReason" in source
    assert "已失效不可跟进" in source
    assert "订单已完成" in source
    assert "不可跟进" in source
    assert "navigator.clipboard.writeText(fullPhone)" in source
    assert "writeText(phoneMasked)" not in source
    assert "writeText(row.phone_masked)" not in source
    assert "fetchClueOrderPhone" in source
    render_body = source[
        source.index("const renderPhoneContact") : source.index("useEffect(() => {")
    ]
    assert "const mayRevealFullPhone = canViewFullPhone(row)" in render_body
    assert "mayRevealFullPhone ? revealedPhones[row.order_id] : undefined" in render_body
    detail_phone_body = source[
        source.index("const canShowActiveDetailPhone") : source.index("const openClueDetail")
    ]
    assert "const canShowActiveDetailPhone" in detail_phone_body
    assert "canShowActiveDetailPhone ? revealedPhones[activeDetailRound.order_id] : undefined" in detail_phone_body


def test_clue_mock_data_covers_active_followed_lost_and_history() -> None:
    mock = json.loads(
        (WEB_SRC / "data" / "mock" / "clue_center.json").read_text(
            encoding="utf-8",
        ),
    )
    rows = mock["assignment_rounds"]["data"]["rows"]

    statuses = {
        (row["lead_status"], row["round_status"], row["follow_result"])
        for row in rows
    }
    assert ("active", "active_unfollowed", "pending") in statuses
    assert ("active", "active_followed", "unreachable") in statuses
    assert ("pending_reassign", "failed_pending_reassign", "lost") in statuses
    assert any(
        lead_status == "pending_reassign"
        and round_status == "expired_pending_reassign"
        for lead_status, round_status, _ in statuses
    )
    assert any(row.get("product_name") for row in rows)

    multi_round_details = [
        detail["data"]
        for detail in mock["order_details"].values()
        if len(detail["data"]["rounds"]) >= 2
    ]
    assert multi_round_details
    assert any(detail["follow_up_records"] for detail in multi_round_details)


def test_sensitive_clue_actions_do_not_fallback_to_mock_on_api_denial() -> None:
    client_source = read_source("api/client.ts")
    phone_segment = client_source[
        client_source.index("export function fetchClueOrderPhone") : client_source.index(
            "export function saveClueFollowUp"
        )
    ]
    follow_up_segment = client_source[
        client_source.index("export function saveClueFollowUp") : client_source.index(
            "export async function loginAdmin"
        )
    ]

    assert "fallbackOnError: false" in phone_segment
    assert "fallbackOnError: false" in follow_up_segment


def test_follow_lost_reason_has_store_label() -> None:
    source = read_source("pages/ClueCenterPage.tsx")
    client_source = read_source("api/client.ts")
    mock_source = read_source("data/mock/clue_center.json")

    assert "follow_lost" in source
    assert '"follow_lost": "线索战败"' in source
    assert 'row.reassign_reason = "follow_lost"' in client_source
    assert '"reassign_reason": "follow_lost"' in mock_source
