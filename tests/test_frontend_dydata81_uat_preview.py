from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "apps" / "web"
UAT_ENTRY = WEB_ROOT / "uat.html"
UAT_CONFIG = WEB_ROOT / "vite.uat.config.ts"
UAT_MAIN = WEB_ROOT / "src" / "uat" / "main.tsx"
UAT_APP = WEB_ROOT / "src" / "uat" / "UatPreviewApp.tsx"
UAT_STYLES = WEB_ROOT / "src" / "uat" / "uat-preview.css"


def read_uat_sources() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in (UAT_ENTRY, UAT_CONFIG, UAT_MAIN, UAT_APP, UAT_STYLES)
    )


def test_uat_preview_has_an_isolated_vite_entrypoint() -> None:
    assert UAT_ENTRY.is_file()
    assert UAT_CONFIG.is_file()
    assert UAT_MAIN.is_file()
    assert UAT_APP.is_file()
    assert UAT_STYLES.is_file()

    assert 'src="/src/uat/main.tsx"' in UAT_ENTRY.read_text(encoding="utf-8")
    assert "UatPreviewApp" in UAT_MAIN.read_text(encoding="utf-8")
    assert "uat.html" in UAT_CONFIG.read_text(encoding="utf-8")


def test_uat_preview_declares_its_browser_icon() -> None:
    entry = UAT_ENTRY.read_text(encoding="utf-8")

    assert 'rel="icon"' in entry


def test_uat_preview_keeps_the_confirmed_four_page_navigation_and_ranking_basis() -> None:
    source = read_uat_sources()

    navigation = ["全国门店榜单", "单店分账", "开票确认", "发票状态查看"]
    offsets = [source.index(item) for item in navigation]
    assert offsets == sorted(offsets)
    assert "订单费用明细" not in source
    assert '"/details"' not in source

    for label in (
        "排行依据",
        "销售金额（累计）",
        "核销金额（累计）",
        "当期推广服务费",
        "累计推广服务费",
        "排名",
        "门店",
    ):
        assert label in source


def test_uat_preview_embeds_fee_details_and_dispute_after_confirmation() -> None:
    app_source = UAT_APP.read_text(encoding="utf-8")

    for label in (
        "推广服务费确认",
        "管理服务费确认",
        "推广费明细",
        "管理费明细",
        "账单异议",
        "暂无可发起的账单异议",
    ):
        assert label in app_source

    assert 'role="tablist"' in app_source
    assert app_source.index("推广服务费确认") < app_source.index("推广费明细")
    assert app_source.index("推广费明细") < app_source.index("账单异议")


def test_uat_preview_dispute_entry_uses_the_confirmed_type_and_submission_contract() -> None:
    source = read_uat_sources()

    for label in (
        "发起账单异议",
        "确认发起账单异议",
        "异议类型",
        "费率错误",
        "订单/数据遗漏",
        "金额错误",
        "其他",
        "费用方向",
        "争议金额",
        "争议订单",
        "问题说明",
        "联系人",
        "手机号",
        "证明材料",
        "提交异议并开始检测",
    ):
        assert label in source

    assert "uat-dispute-trigger" in source
    assert "contactName" in source
    assert "contactPhone" in source
    assert "disputedAmountCent" in source
    assert "RATE_ERROR" in source
    assert "DATA_MISSING" in source
    assert "AMOUNT_ERROR" in source
    assert "ORDER-" not in source
    assert "12480.00" not in source


def test_uat_preview_uses_confirmed_invoice_reminders_and_rule_rhythm() -> None:
    source = read_uat_sources()

    for label in (
        "门店前往开票系统开具数电专票，再将发票信息上传系统，否则将无法收款。",
        "当月10号前开票提交，当月结算；10号后开票提交将在下月结算。",
        "月度结束",
        "系统核查",
        "账单确认",
        "自动确认",
        "发票提交",
        "厂端审核",
        "审核通过/已结算",
        "每月最后一日",
        "次月1日",
        "次月1—6日",
        "次月6日24:00",
        "当月10日前",
        "以厂端结果为准",
        "以实际结算为准",
        "购买方名称",
        "填写人电话",
        "税率",
        "开票日期",
        "20 位数电专票号码",
        "不含税金额",
        "税额",
        "价税合计",
        "账单总额",
        "已确认金额",
        "已开票金额",
        "审核通过/已结算金额",
        "待开票金额",
        "推广发票记录",
        "管理服务费发票信息",
        "差额台账",
    ):
        assert label in source

    assert "uat-invoice-rhythm" in source


def test_six_store_settlement_metrics_stay_in_one_desktop_row() -> None:
    app_source = UAT_APP.read_text(encoding="utf-8")
    style_source = UAT_STYLES.read_text(encoding="utf-8")

    assert "uat-metric-rail--${labels.length}" in app_source
    assert ".uat-metric-rail--6" in style_source


def test_invoice_rule_rhythm_stacks_all_steps_on_narrow_phones() -> None:
    style_source = UAT_STYLES.read_text(encoding="utf-8")
    narrow_screen_rules = style_source.split("@media (max-width: 700px)", maxsplit=1)[1]

    assert ".uat-invoice-rhythm ol" in narrow_screen_rules
    assert "grid-template-columns: 1fr;" in narrow_screen_rules


def test_invoice_rule_rhythm_highlights_the_current_page_node() -> None:
    app_source = UAT_APP.read_text(encoding="utf-8")
    style_source = UAT_STYLES.read_text(encoding="utf-8")

    assert "InvoiceRhythm" in app_source
    assert 'currentStep="invoice-submission"' in app_source
    assert 'aria-current={isCurrent ? "step" : undefined}' in app_source
    assert "uat-invoice-rhythm__step" in style_source
    assert "is-current" in style_source


def test_dispute_entry_stays_collapsed_until_it_opens_a_modal() -> None:
    app_source = UAT_APP.read_text(encoding="utf-8")
    style_source = UAT_STYLES.read_text(encoding="utf-8")

    assert 'const [step, setStep] = useState<DisputeStep>("empty")' in app_source
    assert 'backdropClassName="uat-dispute-modal"' in app_source
    assert 'import { Dialog }' in app_source
    assert 'open={step === "confirm"}' in app_source
    assert ".uat-dispute-modal" in style_source
    assert "position: fixed;" in style_source


def test_uat_preview_never_bakes_in_business_data_or_write_requests() -> None:
    source = read_uat_sources()

    for forbidden in (
        "¥0.00",
        "2026-07",
        "2026-08",
        "测试账期",
        "预览口径",
        "试运行",
        "Mock",
        "Demo",
        "fetch(",
        "POST ",
        "PUT ",
        "PATCH ",
        "DELETE ",
        "/finance/",
    ):
        assert forbidden not in source

    assert "暂无数据" in source
    assert "尚未生成" in source
