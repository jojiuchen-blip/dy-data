from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MOCK_PATH = REPO_ROOT / "docs" / "commission-dashboard-navigation-mock.html"
SPEC_PATH = (
    REPO_ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-07-15-dydata-23-store-dashboard-visual-design.md"
)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_commission_mock_has_four_peer_routes_and_no_parent_dashboard() -> None:
    html = read_text(MOCK_PATH)

    routes = re.findall(
        r'<a href="#/([^"?]+)" data-route="([^"]+)">([^<]+)</a>',
        html,
    )
    assert routes == [
        ("ranking", "ranking", "全国门店榜单"),
        ("store", "store", "单店分账"),
        ("orders", "orders", "订单费用明细"),
        ("invoice", "invoice", "开票确认"),
    ]
    assert "数据看板" not in html
    assert 'aria-label="门店结算页面"' in html
    assert 'aria-current="page"' in html


def test_ranking_contract_uses_confirmed_filters_metrics_and_cumulative_state() -> None:
    html = read_text(MOCK_PATH)

    for label in ("日期范围", "产品范围", "商品类型", "门店搜索", "排名依据"):
        assert label in html
    assert '<option value="2026-07">2026/07</option>' in html
    assert '<option value="all">全部累计数据</option>' in html

    for metric in (
        "销售订单数量",
        "销售总金额",
        "核销收入",
        "厂端激励推广费",
    ):
        assert metric in html
    assert "累计自 2026-08 正式账期启用" in html
    assert "7 月测试数据不纳入累计" in html


def test_store_contract_keeps_five_metrics_and_approved_fee_notes() -> None:
    html = read_text(MOCK_PATH)

    for metric in (
        "销售总金额",
        "本店卖出订单已核销金额",
        "应收推广费",
        "本店核销金额",
        "应扣管理服务费",
    ):
        assert metric in html

    assert "本店通过抖音直播、短视频等卖出的订单，在当月已被核销" in html
    assert "本店在当月核销所有抖音渠道的订单" in html
    assert "<th>点击跳转</th>" in html
    assert "focus=workbench" in html
    for key in (
        "month",
        "store",
        "product_scope",
        "product_type",
        "direction",
        "ratio",
        "version",
    ):
        assert f"{key}=" in html
        assert f'"{key}"' in html
    assert "params.get(key)" in html
    assert html.count("&amp;version=V2026.07.1") == 6
    assert "账单版本" not in html
    assert "仅可查看本门店" not in html


def test_order_details_switch_by_fee_type_without_direction_filter() -> None:
    html = read_text(MOCK_PATH)

    assert "推广费订单明细" in html
    assert "管理服务费订单明细" in html
    assert 'aria-label="订单费用明细类型"' in html
    assert 'aria-label="订单费用明细筛选器"' in html
    assert "<span>费用方向</span>" not in html
    assert 'id="orders-workbench"' in html


def test_invoice_page_is_flow_only_and_has_five_nodes() -> None:
    html = read_text(MOCK_PATH)

    nodes = (
        "月度账单待确认",
        "门店确认账单",
        "门店开具推广费发票",
        "发票提交财务审核",
        "审核完成并进入结算",
    )
    for node in nodes:
        assert node in html
    assert html.count('class="invoice-step') == 5
    assert "当前功能暂未开放" in html
    assert "<form" not in html
    assert "<textarea" not in html


def test_mock_and_spec_are_self_contained_and_scope_production_out() -> None:
    html = read_text(MOCK_PATH)
    spec = read_text(SPEC_PATH)

    assert "http://" not in html
    assert "https://" not in html
    assert "C:" + r"\Users" not in html
    assert "不新增生产 API、数据库迁移或真实门店权限" in spec
    assert "不在本轮改造现有生产 React 路由" in spec
    assert "390px、768px、1440px" in spec
