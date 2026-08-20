from pathlib import Path


WEB_SRC = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"


def read_source(relative_path: str) -> str:
    return (WEB_SRC / relative_path).read_text(encoding="utf-8")


def test_rules_page_exposes_three_tabs_and_four_step_workflow() -> None:
    page = read_source("pages/AdminSkuRulesPage.tsx")
    import_drawer = read_source("components/AdminSkuRuleImportDrawer.tsx")

    assert 'type RulesTab = "settings" | "history" | "exceptions"' in page
    for copy in [
        "规则设置",
        "发布记录",
        "例外账号",
        "1 批量选择 SKU",
        "2 确认分佣比例",
        "3 检查预选",
        "4 确认发布",
        "SKU 查询与批量选择",
        "SKU-ID分佣比例确认",
        "发布确认",
    ]:
        assert copy in page

    assert page.index("SKU 查询与批量选择") < page.index("SKU-ID分佣比例确认")
    assert "applyRateAndReview" in page
    assert "scrollIntoView" in page
    assert "批量导入设置" in import_drawer
    assert "importDrawerOpen" in page


def test_rules_page_keeps_history_exceptions_and_two_sku_status_lists() -> None:
    page = read_source("pages/AdminSkuRulesPage.tsx")

    assert "发布来源" in page
    assert "手工发布" in page
    assert "批量导入" in page
    assert "订单归属账号不分佣" in page
    assert "已启用分佣商品列表" in page
    assert "未启用分佣商品列表" in page
    assert "enabledSkuIds" in page

    for column in [
        "SKU ID",
        "商品名称",
        "产品范围",
        "商品类型",
        "分账比例",
        "参与分账",
        "订单数",
        "核销券数",
        "状态",
    ]:
        assert column in page


def test_rules_page_removes_legacy_and_classification_sections() -> None:
    page = read_source("pages/AdminSkuRulesPage.tsx")

    assert "<AdminSkuGovernancePanel" not in page
    assert "旧单费率兼容区" not in page
    assert "商品人工分类" not in page
    assert "批量选择当前筛选结果" not in page
    assert "支持单个、批量选择" in page
    assert "换行、空格、中英文逗号或分号" in page


def test_rules_page_confirms_before_publishing_selected_skus() -> None:
    page = read_source("pages/AdminSkuRulesPage.tsx")

    assert 'title="分佣规则发布确认"' in page
    assert "publishSelectedRules" in page
    assert "publishSkuFeeRule" in page
    assert "createIdempotencyKey" in page
    assert "推广服务费比例" in page
    assert "管理服务费比例" in page
    assert "生效日期" in page
    assert "变更原因" in page


def test_import_drawer_preserves_prevalidation_errors_and_atomic_commit() -> None:
    drawer = read_source("components/AdminSkuRuleImportDrawer.tsx")

    for copy in ["整批未写入", "上传并预校验", "确认原子提交"]:
        assert copy in drawer
    assert "rowNumber" in drawer
    assert "error.field" in drawer
    assert "error.message" in drawer
    assert "PENDING_COMMIT" in drawer


def test_rules_stepper_is_sticky_clickable_and_tracks_the_visible_step() -> None:
    page = read_source("pages/AdminSkuRulesPage.tsx")
    styles = read_source("styles.css")

    assert "IntersectionObserver" in page
    assert "activeStep" in page
    assert "aria-current" in page
    assert "scrollToStep" in page
    assert 'className="commission-stepper__button"' in page
    stepper_styles = styles[
        styles.index(".commission-stepper {") :
        styles.index(".commission-workspace {")
    ]
    assert "position: sticky" in stepper_styles
    assert ".commission-stepper li.is-active" in stepper_styles


def test_rules_moves_import_to_step_one_and_removes_duplicate_browse_search() -> None:
    page = read_source("pages/AdminSkuRulesPage.tsx")

    assert "浏览搜索" not in page
    assert page.index("批量导入设置") < page.index("2. SKU-ID分佣比例确认")
    assert 'href="/admin/product-types"' in page
    assert "请前往商品口径页面配置产品类型" in page


def test_rules_enabled_and_disabled_tabs_have_strong_status_styles() -> None:
    styles = read_source("styles.css")
    catalog_styles = styles[
        styles.index(".commission-sku-catalog > .ui-tabs--segmented") :
        styles.index(".commission-confirmation-list")
    ]

    assert "border: 2px solid var(--brand-orange)" in catalog_styles
    assert "background: var(--brand-orange)" in catalog_styles
    assert "color: var(--surface)" in catalog_styles
