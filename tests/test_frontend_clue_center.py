from pathlib import Path
import json
import re


WEB_SRC = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"


def read_source(relative_path: str) -> str:
    return (WEB_SRC / relative_path).read_text(encoding="utf-8")


def assert_in_order(source: str, values: list[str]) -> None:
    position = -1
    for value in values:
        next_position = source.find(value, position + 1)
        assert next_position > position, f"{value!r} should appear after prior field"
        position = next_position


def assert_column_align(source: str, key: str, align: str) -> None:
    match = re.search(
        rf'\{{\s+key: "{re.escape(key)}",(?P<body>.*?)\n    \}},',
        source,
        re.DOTALL,
    )
    assert match, f"Column {key!r} should be declared as a multiline column"
    assert f'align: "{align}"' in match.group("body")


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


def test_clue_contact_actions_stay_on_one_row() -> None:
    styles_source = read_source("styles.css")

    contact_cell_rules = re.search(
        r"\.clue-contact-cell \{(?P<body>.*?)\n\}",
        styles_source,
        re.DOTALL,
    )
    detail_trigger_rules = re.findall(
        r"\.clue-detail-trigger \{(?P<body>.*?)\n\}",
        styles_source,
        re.DOTALL,
    )
    table_phone_rules = re.search(
        r"\.phone-reveal--table \{(?P<body>.*?)\n\}",
        styles_source,
        re.DOTALL,
    )

    assert contact_cell_rules
    assert detail_trigger_rules
    assert table_phone_rules
    assert "display: inline-flex;" in contact_cell_rules.group("body")
    assert "align-items: center;" in contact_cell_rules.group("body")
    assert "flex-wrap: nowrap;" in contact_cell_rules.group("body")
    assert "flex-wrap: nowrap;" in table_phone_rules.group("body")
    assert any("white-space: nowrap;" in rule for rule in detail_trigger_rules)


def test_clue_center_does_not_display_douyin_follow_store_as_our_assignment() -> None:
    source = read_source("pages/ClueCenterPage.tsx")

    assert "线索当前归属" not in source
    assert "分配门店" not in source
    assert "归属门店" not in source
    assert "current_assigned_store_name" not in source
    assert "assigned_store_name" not in source


def test_clue_center_detail_follow_up_layout_and_actions() -> None:
    source = read_source("pages/ClueCenterPage.tsx")

    assert 'title="线索跟进详情"' in source
    assert "clue-followup-detail__grid" in source
    assert "clue-followup-contact-status" in source
    assert "clue-followup-detail__main" in source
    assert "clue-followup-detail__side" in source
    assert "联系方式 · 号码操作" in source
    assert "手机号与状态" in source
    assert "线索跟进历史" in source
    assert "商品与订单" in source
    assert "下单时间" in source
    assert "clue-followup-round-card" in source
    assert "clue-followup-round-records" in source
    assert "clue-followup-round-record" in source
    assert "recordsForRound" in source
    assert "跟进操作" in source
    assert 'value="unreachable"' in source
    assert "未接通" in source
    assert 'value="lost"' in source
    assert "线索战败" in source
    assert 'value="success"' in source
    assert "跟进成功" in source
    assert "本次跟进结论/备注" in source
    assert "保存本次跟进" in source
    assert "实时数据" not in source[source.index('title="线索跟进详情"') :]
    assert "当前有效轮次允许查看和复制完整号码" not in source[
        source.index('title="线索跟进详情"') :
    ]
    assert "本轮仍可处理" not in source[source.index('title="线索跟进详情"') :]
    assert "detailRoundLabel" not in source

    summary_start = source.index("clue-followup-contact-status")
    side_start = source.index("clue-followup-detail__side")
    order_start = source.index("clue-followup-product clue-followup-order")
    history_start = source.index("线索跟进历史")
    assert summary_start < side_start < order_start < history_start
    history_section = source[
        source.index("clue-followup-history") :
        source.index("</main>", source.index("clue-followup-history"))
    ]
    assert "detail.rounds.map" in history_section
    assert "const roundRecords = recordsForRound(" in history_section
    assert "round.assignment_round_id" in history_section
    assert "roundRecords.map" in history_section
    assert "本轮尚未登记跟进结果" in history_section
    assert "跟进轮次历史" not in history_section
    assert "线索生成时间" not in source[source.index('title="线索跟进详情"') :]
    assert "detailPhoneValue" not in source


def test_clue_followup_detail_modal_scrolls_on_mobile() -> None:
    styles_source = read_source("styles.css")

    modal_rules = styles_source[
        styles_source.index(".clue-followup-detail {") :
        styles_source.index(".clue-followup-detail .ui-dialog__body {")
    ]
    body_rules = styles_source[
        styles_source.index(".clue-followup-detail .ui-dialog__body {") :
        styles_source.index(".clue-detail-body")
    ]
    tablet_rules = styles_source[
        styles_source.index("@media (max-width: 920px)") :
        styles_source.index("@media (max-width: 640px)")
    ]
    mobile_rules = styles_source[styles_source.index("@media (max-width: 640px)") :]
    mobile_detail_rules = mobile_rules[
        mobile_rules.index(".clue-followup-detail {") :
        mobile_rules.index(".clue-detail-modal__header")
    ]
    tablet_grid_rules = tablet_rules[
        tablet_rules.index(".clue-followup-detail__grid {") :
        tablet_rules.index(".clue-followup-detail__main")
    ]

    assert "grid-template-rows: auto minmax(0, 1fr);" in modal_rules
    assert "width: min(1440px, calc(100vw - 48px));" in modal_rules
    assert "height: min(920px, calc(100dvh - 32px));" in modal_rules
    assert "max-height: min(920px, calc(100dvh - 32px));" in modal_rules
    assert "min-height: 0;" in body_rules
    assert "overflow: hidden;" in body_rules
    assert "overscroll-behavior: contain;" in body_rules
    assert "-webkit-overflow-scrolling: touch;" in body_rules
    assert "height: calc(100dvh - 24px);" in mobile_detail_rules
    assert "max-height: calc(100dvh - 24px);" in mobile_detail_rules
    assert '"summary"' in tablet_grid_rules
    assert '"side"' in tablet_grid_rules
    assert '"main"' in tablet_grid_rules


def test_clue_center_filters_follow_store_scope_spec() -> None:
    source = read_source("pages/ClueCenterPage.tsx")
    types_source = read_source("types/dashboard.ts")

    assert "currentUser" in source
    assert "showStoreLocationFilters" in source
    assert "currentUser.role !== \"store\" || currentUser.store_ids.length !== 1" in source
    assert "province" in source
    assert "verificationStatus" in source
    assert "assigned_store_id" in source

    filter_panel_id = source.index('id="clue-filter-panel"')
    filter_bar_start = source.rindex("<FilterBar", 0, filter_panel_id)
    filter_bar_end = source.index("</FilterBar>", filter_bar_start)
    filter_bar = source[filter_bar_start:filter_bar_end]
    assert "mobileFiltersOpen" in filter_bar
    assert "clue-filter-bar" in filter_bar
    assert "处理状态" not in filter_bar
    assert "roundStatus" not in filter_bar
    assert "round_status" not in filter_bar
    assert filter_bar.count("<SearchableStoreSelect") >= 3
    assert 'placeholder="搜索省份"' in filter_bar
    assert 'placeholder="搜索城市"' in filter_bar
    assert 'placeholder="搜索门店名称"' in filter_bar
    assert 'emptyMessage="未找到省份"' in filter_bar
    assert 'emptyMessage="未找到城市"' in filter_bar
    assert 'emptyMessage="未找到门店"' in filter_bar
    assert '<SelectField\n              label="省份"' not in filter_bar
    assert '<SelectField\n              label="城市"' not in filter_bar
    assert '<SelectField\n              label="门店"' not in filter_bar
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
            "收起筛选",
        ],
    )
    assert 'className="ghost-button clue-filter-collapse-mobile"' in filter_bar
    assert "setMobileFiltersOpen(false)" in filter_bar

    assert "assigned_provinces: string[];" in types_source
    assert "verification_statuses: string[];" in types_source
    assert "province?: string;" in types_source
    assert "verification_status?: string;" in types_source


def test_clue_center_splits_dashboard_and_detail_routes() -> None:
    app_source = read_source("App.tsx")
    shell_source = read_source("components/Shell.tsx")
    page_source = read_source("pages/ClueCenterPage.tsx")

    assert 'location.pathname === "/clues"' in app_source
    assert 'view="dashboard"' in app_source
    assert 'location.pathname === "/clues/details"' in app_source
    assert 'view="details"' in app_source
    assert '{ href: "/clues", label: "线索看板", icon: "chart" }' in shell_source
    assert (
        '{ href: "/clues/details", label: "线索明细", icon: "details" }'
        in shell_source
    )
    assert 'currentPath.startsWith("/clues/")' in shell_source
    assert 'view?: ClueCenterView' in page_source
    assert 'const isDetailsView = view === "details"' in page_source
    assert 'const pageHeadingTitle = isDetailsView ? "线索跟进列表" : "经营线索概览"' in page_source


def test_clue_center_removes_repeated_engineering_labels() -> None:
    page_source = read_source("pages/ClueCenterPage.tsx")

    for removed_label in [
        "Clue detail list",
        "Clue dashboard",
        "Follow-up detail",
        "<h2>线索明细</h2>",
    ]:
        assert removed_label not in page_source

    assert "当前筛选结果" in page_source
    assert 'className="result-count"' in page_source


def test_shell_uses_module_context_without_repeating_page_title() -> None:
    shell_source = read_source("components/Shell.tsx")
    styles_source = read_source("styles.css")
    topbar_start = shell_source.index('<header className="workspace-topbar">')
    topbar_end = shell_source.index("</header>", topbar_start)
    topbar_source = shell_source[topbar_start:topbar_end]

    assert "sectionLabels[section]" in shell_source
    assert "const renderSecondaryNav" in shell_source
    assert "dataWorkspacePaths" in shell_source
    assert '"/clues/details", "/details"' in shell_source
    assert "page-frame--data-workspace" in shell_source
    assert 'renderSecondaryNav("workspace-subnav--desktop")' in topbar_source
    assert topbar_source.index('workspace-subnav--desktop') < topbar_source.index(
        'className="workspace-actions"'
    )
    assert 'renderSecondaryNav("workspace-subnav--mobile")' in shell_source[
        topbar_end:
    ]
    assert ".workspace-subnav--desktop" in styles_source
    assert ".workspace-subnav--mobile" in styles_source
    assert 'className="workspace-context"' not in shell_source
    assert "workspace-kicker" not in shell_source
    assert "pageTitle" not in shell_source
    assert "workspace-title" not in shell_source
    assert ".workspace-context" not in styles_source
    assert ".workspace-kicker" not in styles_source
    assert ".workspace-title" not in styles_source


def test_workspace_pages_use_full_width_frame_by_default() -> None:
    styles_source = read_source("styles.css")

    workspace_frame_rules = styles_source[
        styles_source.index(".workspace-shell .page-frame {") :
        styles_source.index(".workspace-shell .page-frame--data-workspace {")
    ]

    assert "width: 100%;" in workspace_frame_rules
    assert "max-width: none;" in workspace_frame_rules
    assert "margin: 0;" in workspace_frame_rules
    assert "margin: 0 auto;" not in workspace_frame_rules
    assert "width: min(1460px, 100%);" not in workspace_frame_rules


def test_shell_has_feedback_submission_entry() -> None:
    shell_source = read_source("components/Shell.tsx")
    styles_source = read_source("styles.css")
    client_source = read_source("api/client.ts")
    types_source = read_source("types/dashboard.ts")

    assert 'className="rail-feedback-button"' in shell_source
    assert 'className="mobile-bottom-nav__feedback"' not in shell_source
    assert 'className="mobile-bottom-nav__mine"' in shell_source
    assert 'panelClassName="mine-panel"' in shell_source
    assert "openFeedbackFromMine" in shell_source
    assert "openSettingsFromMine" in shell_source
    assert "提交建议" in shell_source
    assert "handleFeedbackSubmit" in shell_source
    assert "submitFeedback" in shell_source
    assert "page_path: currentPath" in shell_source
    assert "grid-template-rows: auto 1fr auto;" in styles_source
    assert ".rail-feedback-button" in styles_source
    assert ".mobile-bottom-nav__mine" in styles_source
    assert ".mine-panel" in styles_source
    assert ".feedback-modal" in styles_source

    assert "export type FeedbackCategory" in types_source
    assert "export interface FeedbackSubmissionPayload" in types_source
    assert "export interface FeedbackSubmissionReceipt" in types_source
    assert "export async function submitFeedback" in client_source
    assert 'sendJson<FeedbackSubmissionReceipt>("/feedback"' in client_source


def test_admin_feedback_page_is_wired_to_shell_and_api_client() -> None:
    app_source = read_source("App.tsx")
    shell_source = read_source("components/Shell.tsx")
    home_source = read_source("pages/AdminHomePage.tsx")
    page_source = read_source("pages/AdminFeedbackPage.tsx")
    client_source = read_source("api/client.ts")
    types_source = read_source("types/dashboard.ts")

    assert "AdminFeedbackPage" in app_source
    assert 'location.pathname === "/admin/feedback"' in app_source
    assert '"/admin/feedback"' in shell_source
    assert 'label: "用户建议", icon: "feedback"' in shell_source
    assert 'href: "/admin/feedback"' in home_source

    assert "用户建议" in page_source
    assert "feedback-summary-row" in page_source
    assert "admin-feedback-filters" in page_source
    assert "updateFeedbackStatus" in page_source
    assert "fetchFeedback" in page_source
    assert "标记已读" in page_source
    assert "已处理" in page_source

    assert "export interface FeedbackRow" in types_source
    assert "export interface FeedbackListData" in types_source
    assert "export type FeedbackStatus" in types_source
    assert "export async function fetchFeedback" in client_source
    assert 'requestJson<FeedbackListData>("/admin/feedback"' in client_source
    assert "export async function updateFeedbackStatus" in client_source
    assert "/admin/feedback/${encodeURIComponent(feedbackId)}/status" in client_source


def test_mobile_shell_does_not_reserve_empty_desktop_topbar_space() -> None:
    styles_source = read_source("styles.css")
    mobile_shell_rules = styles_source[
        styles_source.index("@media (max-width: 920px)") :
        styles_source.index("@media (max-width: 640px)")
    ]
    topbar_rules = mobile_shell_rules[
        mobile_shell_rules.index(".workspace-topbar") :
        mobile_shell_rules.index(".workspace-actions")
    ]
    subnav_rules = mobile_shell_rules[
        mobile_shell_rules.index(".workspace-subnav--mobile") :
        mobile_shell_rules.index(".workspace-subnav--mobile a")
    ]

    assert "display: none;" in topbar_rules
    assert ".workspace-subnav {\n    display: none;" in mobile_shell_rules
    assert "display: flex;" in subnav_rules
    assert "top: 0;" in subnav_rules


def test_shell_data_table_header_uses_container_sticky_contract() -> None:
    styles_source = read_source("styles.css")
    token_source = read_source("design-tokens.css")
    data_table_source = read_source("components/DataTable.tsx")
    clue_page_source = read_source("pages/ClueCenterPage.tsx")
    order_details_source = read_source("pages/OrderDetailsPage.tsx")

    root_rules = token_source[
        token_source.index(":root") :
        token_source.index("}")
    ]
    base_header_rules = styles_source[
        styles_source.index(".data-table th {") :
        styles_source.index(".data-table td.is-sticky-column")
    ]
    sticky_column_header_rules = styles_source[
        styles_source.index(".data-table th.is-sticky-column") :
        styles_source.index(".data-table td.is-sticky-column-last")
    ]
    contained_sticky_rules = styles_source[
        styles_source.index(".table-wrap--contained-sticky {") :
        styles_source.index(".data-table-mobile-list")
    ]
    mobile_shell_rules = styles_source[
        styles_source.index("@media (max-width: 920px)") :
        styles_source.index("@media (max-width: 640px)")
    ]

    assert "--workspace-topbar-height: 58px;" in root_rules
    assert "--workspace-subnav-height: 51px;" in root_rules
    assert "--table-sticky-gap: 8px;" in root_rules
    assert "--z-table-sticky-column: 2;" in root_rules
    assert "--z-table-header: 3;" in root_rules
    assert "--z-table-header-corner: 5;" in root_rules
    assert "--table-sticky-top: calc(" in root_rules
    assert "var(--workspace-topbar-height) + var(--table-sticky-gap)" in root_rules
    assert "workspace-subnav-height) + var(--table-sticky-gap)" not in root_rules
    assert "top: 0;" in base_header_rules
    assert "z-index: var(--z-table-header);" in base_header_rules
    assert "z-index: var(--z-table-header-corner);" in sticky_column_header_rules
    assert "max-height: min(720px, calc(100vh - var(--table-sticky-top) - 16px));" in contained_sticky_rules
    assert "overflow: auto;" in contained_sticky_rules
    assert "overscroll-behavior: contain;" in contained_sticky_rules
    assert "scrollbar-gutter: stable;" in contained_sticky_rules
    assert ".table-wrap--contained-sticky .data-table th" in styles_source
    assert "0 12px 20px -18px var(--ink-shadow-45)" in styles_source
    assert '"table-wrap--contained-sticky"' in data_table_source
    assert 'stickyHeader="container"' in clue_page_source
    assert 'stickyHeader="container"' in order_details_source
    assert ".clue-table-view .data-table th" not in styles_source
    assert "overflow-x: visible;" not in styles_source
    assert "top: var(--table-sticky-top);" not in styles_source
    assert "0 calc(var(--table-sticky-gap) * -1) 0 var(--bg)" not in styles_source
    assert ".workspace-shell .page-frame .data-table th" not in styles_source
    assert "top: var(--table-sticky-top);" not in mobile_shell_rules


def test_detail_pages_use_fixed_data_workspace_with_inner_table_scroll() -> None:
    shell_source = read_source("components/Shell.tsx")
    styles_source = read_source("styles.css")
    clue_page_source = read_source("pages/ClueCenterPage.tsx")
    order_details_source = read_source("pages/OrderDetailsPage.tsx")

    desktop_frame_rules = styles_source[
        styles_source.index(".workspace-shell .page-frame--data-workspace {") :
        styles_source.index("\n.topbar {")
    ]
    data_stack_rules = styles_source[
        styles_source.index(".page-stack--data-workspace {") :
        styles_source.index(".clue-page-content {")
    ]
    data_section_rules = styles_source[
        styles_source.index(".content-section--data-workspace {") :
        styles_source.index(".table-wrap {")
    ]
    mobile_rules = styles_source[
        styles_source.index("@media (max-width: 920px)") :
        styles_source.index("@media (max-width: 640px)")
    ]

    assert "dataWorkspacePaths.has(currentPath)" in shell_source
    assert "className={pageFrameClassName}" in shell_source
    assert "width: 100%;" in desktop_frame_rules
    assert "height: calc(100vh - var(--workspace-topbar-height));" in desktop_frame_rules
    assert "overflow: hidden;" in desktop_frame_rules
    assert "display: flex;" in data_stack_rules
    assert "height: 100%;" in data_stack_rules
    assert "min-height: 0;" in data_stack_rules
    assert "flex: 1 1 auto;" in data_section_rules
    assert "overflow: hidden;" in data_section_rules
    assert ".content-section--data-workspace .table-wrap--contained-sticky" in data_section_rules
    assert ".content-section--data-workspace .table-pagination" in data_section_rules
    assert "max-height: none;" in data_section_rules
    assert "height: auto;" in mobile_rules
    assert "overflow: visible;" in mobile_rules

    assert "page-stack page-stack--data-workspace" in clue_page_source
    assert "clue-page-content clue-page-content--details" in clue_page_source
    assert "content-section content-section--data-workspace" in clue_page_source
    assert "<TablePagination" in clue_page_source
    assert "page-stack page-stack--data-workspace" in order_details_source
    assert "content-section content-section--data-workspace" in order_details_source
    assert "<TablePagination" in order_details_source


def test_data_table_alignment_defaults_center_but_keeps_long_text_left() -> None:
    data_table_source = read_source("components/DataTable.tsx")
    styles_source = read_source("styles.css")
    clue_page_source = read_source("pages/ClueCenterPage.tsx")
    order_details_source = read_source("pages/OrderDetailsPage.tsx")
    ranking_source = read_source("pages/StoreRankingPage.tsx")

    assert '`is-${column.align ?? "center"}`' in data_table_source
    assert ".data-table .is-left" in styles_source
    assert ".data-table .is-center" in styles_source
    assert ".data-table .is-right" in styles_source
    assert ".data-table .is-center .table-action-row" in styles_source

    assert_column_align(clue_page_source, "product_name", "left")
    assert_column_align(order_details_source, "order", "left")
    assert_column_align(order_details_source, "coupon", "left")
    assert_column_align(order_details_source, "productName", "left")
    assert_column_align(order_details_source, "saleStore", "left")
    assert_column_align(order_details_source, "verifyStore", "left")
    assert_column_align(ranking_source, "store", "left")


def test_detail_filters_use_compact_single_row_desktop_contract() -> None:
    styles_source = read_source("styles.css")
    clue_page_source = read_source("pages/ClueCenterPage.tsx")
    order_details_source = read_source("pages/OrderDetailsPage.tsx")

    desktop_density_rules = styles_source[
        styles_source.index("@media (min-width: 1380px)") :
        styles_source.index("\n.filter-field {")
    ]
    mobile_rules = styles_source[
        styles_source.index("@media (max-width: 640px)") :
        styles_source.index(".feedback-summary-row,")
    ]

    assert "filter-bar--compact clue-filter-bar" in clue_page_source
    assert "filter-bar--compact detail-filter-bar detail-filter-bar--single-line" in order_details_source
    assert order_details_source.count("<FilterBar") == 1
    assert "detail-filter-bar--secondary" not in order_details_source
    assert ".clue-filter-bar" in desktop_density_rules
    assert ".detail-filter-bar--single-line" in desktop_density_rules
    assert "minmax(92px, 0.55fr)" in desktop_density_rules
    assert ".clue-filter-bar,\n  .clue-rule-grid {\n    grid-template-columns: 1fr;" in mobile_rules


def test_mobile_clue_filter_panel_has_visible_collapse_action() -> None:
    styles_source = read_source("styles.css")

    base_collapse_rules = styles_source[
        styles_source.index(".clue-filter-collapse-mobile {") :
        styles_source.index("\n.filter-field {")
    ]
    mobile_phone_rules = styles_source[styles_source.index("@media (max-width: 640px)") :]
    mobile_collapse_rules = mobile_phone_rules[
        mobile_phone_rules.index(".clue-filter-collapse-mobile {") :
        mobile_phone_rules.index(".clue-table-view")
    ]

    assert "display: none;" in base_collapse_rules
    assert "display: flex;" in mobile_collapse_rules
    assert "min-height: var(--touch-target);" in mobile_collapse_rules
    assert "justify-content: center;" in mobile_collapse_rules


def test_admin_pages_use_shell_for_global_navigation_actions() -> None:
    admin_pages = [
        "pages/AdminHomePage.tsx",
        "pages/AdminSkuRulesPage.tsx",
        "pages/AdminClueRulePage.tsx",
        "pages/AdminFeedbackPage.tsx",
        "pages/AdminSyncPage.tsx",
        "pages/AdminAccountsPage.tsx",
    ]

    for relative_path in admin_pages:
        source = read_source(relative_path)
        assert "返回看板主页" not in source
        assert "返回后台首页" not in source
        assert "logoutAdmin" not in source
        assert "handleLogout" not in source

    for relative_path in admin_pages[:-1]:
        assert "系统管理后台" not in read_source(relative_path)

    accounts_source = read_source("pages/AdminAccountsPage.tsx")
    assert "账号体系" not in accounts_source
    assert "新建账号" in accounts_source


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
    assert "const phoneVisible = Boolean(revealedPhone)" in render_body
    assert 'phoneVisible ? "隐藏完整手机号" : "查看完整手机号"' in render_body
    assert 'name={phoneVisible ? "eyeClosed" : "eye"}' in render_body
    assert "hidePhone(row)" in render_body
    assert "const hidePhone" in source
    assert "delete next[row.order_id]" in source
    detail_phone_body = source[
        source.index("const canShowActiveDetailPhone") : source.index("const openClueDetail")
    ]
    assert "const canShowActiveDetailPhone" in detail_phone_body
    assert "detailPhoneValue" not in detail_phone_body
    assert '{renderPhoneContact(activeDetailRound, "detail")}' in source


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
