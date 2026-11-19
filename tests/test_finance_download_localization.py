from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO, StringIO
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.requests import Request
from openpyxl import load_workbook

from apps.api.dy_api.download_localization import (
    download_filename,
    localized_csv,
    translate_csv,
)
from apps.api.dy_api.models import (
    DimStore,
    SettlementMonthlyOverlay,
    SettlementProjectionActive,
    SettlementProjectionGeneration,
    SettlementProjectionPartitionManifest,
    SettlementStatement,
    SettlementStatementConfirmation,
    SettlementStatementEntry,
)
from publication_fixture_helpers import publish_fixture
from test_api_finance_contract_g5 import (
    _act_as_store,
    _login,
    _seed_promotion_invoice,
    _seed_store_and_statement,
    client,
)
from test_dashboard_publication_finance_postgres import POSTGRES_URL, postgres_session
from apps.api.dy_api.routes.fee_admin import (
    IMPORT_HEADERS, PRODUCT_IMPORT_HEADERS, _read_import_rows, _read_tabular_rows, _render_result_file,
)


def _rows(response) -> list[dict[str, str]]:
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"\xef\xbb\xbf")
    return list(csv.DictReader(StringIO(response.content.decode("utf-8-sig"))))


@pytest.mark.parametrize("direction", ["PROMOTION", "MANAGEMENT"])
def test_real_invoice_download_localizes_pending_without_changing_finance_facts(
    client: TestClient, db_session: Session, direction: str,
) -> None:
    statement = _seed_store_and_statement(db_session, promotion_amount_cent=742905)
    statement.management_original_fee_cent = 742905
    statement.management_net_fee_cent = 742905
    db_session.add(SettlementStatementConfirmation(
        confirmation_id="download-confirmation", statement_id=statement.statement_id,
        fee_direction=1 if direction == "PROMOTION" else 2, confirmation_status=1,
        confirmed_amount_cent=742905, confirmed_by="store-user",
        confirmed_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
    ))
    db_session.commit()
    publish_fixture(db_session, "finance")
    _login(client)
    query = {"month": "2026-08", "feeDirection": direction, "metricScope": "MONTH"}
    raw = client.get("/api/v1/admin/finance/invoices/export", params=query)
    localized = client.get("/api/v1/admin/finance/invoices/export", params={**query, "locale": "zh-CN"})
    raw_rows, chinese_rows = _rows(raw), _rows(localized)
    assert len(raw_rows) == len(chinese_rows) == 1
    row = chinese_rows[0]
    assert row["开票状态"] == "待开票"
    assert row["处理状态"] == "待提交"
    assert row["发票金额（元）"] == ""
    assert row["发票号码"] == ""
    assert row["账期"] == "2026年08月"
    total_label = "推广费总额（元）" if direction == "PROMOTION" else "管理费总额（元）"
    assert Decimal(row[total_label]) * 100 == Decimal(raw_rows[0]["statement_amount_cent"])
    assert "账单金额（元）" not in row
    assert row["账单ID"] == raw_rows[0]["statement_id"]
    assert row["已确认金额（元）"] == "7429.05"
    assert localized.headers["x-publication-id"] == raw.headers["x-publication-id"]
    name = unquote(localized.headers["content-disposition"])
    assert ("推广服务费" if direction == "PROMOTION" else "管理服务费") + "开票记录_2026年08月_" in name
    assert all("_" not in field for field in row)
    assert raw_rows[0]["status"] == "PENDING_INVOICE"
    assert db_session.scalar(select(type(statement)).where(type(statement).statement_id == statement.statement_id)).promotion_net_fee_cent == 742905
    _act_as_store(client)
    denied = client.get("/api/v1/admin/finance/invoices/export", params={**query, "locale": "zh-CN"})
    assert denied.status_code == 403


@pytest.mark.parametrize("code,label", [
    (2, "已提交待厂家审核"), (3, "审核通过已结算"), (4, "已驳回待重传"),
])
def test_real_invoice_status_download_retains_ids_dates_and_precision(
    client: TestClient, db_session: Session, code: int, label: str,
) -> None:
    statement = _seed_store_and_statement(db_session)
    _seed_promotion_invoice(db_session, statement=statement, invoice_status=code)
    publish_fixture(db_session, "finance")
    _login(client)
    response = client.get("/api/v1/admin/finance/invoices/export", params={
        "month": "2026-08", "feeDirection": "PROMOTION", "locale": "zh-CN",
    })
    row = _rows(response)[0]
    assert row["开票状态"] == label
    assert row["发票号码"] == "'62345678901234567890"
    assert row["发票金额（元）"] == "10.00"
    assert row["开票日期"] == "2026年08月10日"
    assert row["登记时间"] == "2026年08月12日 16:00:00"
    assert row["推广费总额（元）"] == "10.00"


@pytest.mark.parametrize("direction", ["PROMOTION", "MANAGEMENT"])
def test_real_pending_projection_download_labels_amount_as_fee_total(
    client: TestClient, db_session: Session, direction: str,
) -> None:
    db_session.add(SettlementProjectionGeneration(
        generation_id="download-projection", state="published", input_fingerprint="download-projection",
    ))
    db_session.flush()
    db_session.add_all([
        SettlementProjectionPartitionManifest(
            generation_id="download-projection", artifact="monthly", partition_key="2026-10",
            source_kind="overlay", data_generation_id="download-projection",
        ),
        SettlementProjectionActive(projection_name="settlement", generation_id="download-projection"),
        DimStore(store_id="projected-store", store_name="试算门店"),
        SettlementMonthlyOverlay(
            generation_id="download-projection", partition_key="2026-10", month="2026-10",
            store_id="projected-store", product_scope="all", product_type="all",
            promotion_net_fee_cent=742905, management_net_fee_cent=742905,
        ),
    ])
    db_session.commit()
    publish_fixture(db_session, "finance")
    _login(client)
    query = {"month": "2026-10", "feeDirection": direction, "metricScope": "MONTH"}
    listed = client.get("/api/v1/admin/finance/invoices", params=query)
    assert listed.status_code == 200
    assert listed.json()["data"]["list"][0]["processingStatus"] == "PENDING_STATEMENT"
    response = client.get("/api/v1/admin/finance/invoices/export", params={**query, "locale": "zh-CN"})
    row = _rows(response)[0]
    total_label = "推广费总额（元）" if direction == "PROMOTION" else "管理费总额（元）"
    assert row[total_label] == "7429.05"
    assert "账单金额（元）" not in row
    assert row["处理状态"] == "待生成账单"
    assert row["账单ID"] == row["已确认金额（元）"] == row["发票金额（元）"] == ""
    assert db_session.scalar(select(func.count()).select_from(SettlementStatement)) == 0
    assert db_session.scalar(select(func.count()).select_from(SettlementStatementConfirmation)) == 0


@pytest.mark.parametrize("direction", ["PROMOTION", "MANAGEMENT"])
def test_real_finance_order_download_retains_frozen_amounts_and_filters(
    client: TestClient, db_session: Session, direction: str,
) -> None:
    statement = _seed_store_and_statement(db_session, promotion_amount_cent=359)
    statement.management_original_fee_cent = 359
    statement.management_net_fee_cent = 359
    db_session.add(SettlementStatementEntry(
        statement_entry_id="download-order-entry", statement_id=statement.statement_id,
        statement_line_id="download-order-line", source_type=1, source_record_id="download-order-source",
        original_fee_result_id="download-order-fee", coupon_id="download-order-coupon",
        order_id="12345678901234567890", fee_direction=1 if direction == "PROMOTION" else 2,
        original_business_month="2026-08", statement_posting_month="2026-08",
        product_scope="精诚养车", product_type="精诚养车", base_amount_cent=12345, fee_amount_cent=359,
        rule_version="download-rule", order_status_snapshot="converted", coupon_status_snapshot="VERIFIED",
        product_name_snapshot="=HYPERLINK(1)", sku_id_snapshot="download-sku", sku_name_snapshot="轮胎",
        sale_channel_snapshot="short_video", sale_time_snapshot=datetime(2026, 8, 1, 20, tzinfo=timezone.utc),
        verify_time_snapshot=datetime(2026, 8, 3, tzinfo=timezone.utc),
        received_amount_cent_snapshot=12345, fee_rate_snapshot=Decimal("0.02908"),
    ))
    db_session.commit()
    _login(client)
    query = {"month": "2026-08", "feeDirection": direction, "q": "12345678901234567890"}
    raw = client.get("/api/v1/admin/finance/order-details/export", params=query)
    chinese = client.get("/api/v1/admin/finance/order-details/export", params={**query, "locale": "zh-CN"})
    raw_rows, chinese_rows = _rows(raw), _rows(chinese)
    assert len(raw_rows) == len(chinese_rows) == 1
    row = chinese_rows[0]
    assert row["订单ID"] == "'12345678901234567890"
    assert row["账单明细ID"] == raw_rows[0]["statement_entry_id"]
    assert row["费用方向"] == ("推广服务费" if direction == "PROMOTION" else "管理服务费")
    assert row["订单状态"] == row["券状态"] == "已核销"
    assert row["商品名称"] == "'=HYPERLINK(1)"
    assert row["销售渠道"] == "短视频"
    assert row["销售时间"] == "2026年08月02日 04:00:00"
    assert row["冻结费用金额（元）"] == "3.59"
    assert row["冻结计费基数（元）"] == row["订单实收金额（元）"] == "123.45"
    assert Decimal(row["冻结费用金额（元）"]) * 100 == Decimal(raw_rows[0]["frozen_fee_amount_cent"])
    assert row["开票状态"] == ("" if direction == "PROMOTION" else "待开票")
    assert row["结算状态"] == "未结算"
    assert row["退款时间"] == ""
    assert not _rows(client.get("/api/v1/admin/finance/order-details/export", params={**query, "q": "absent", "locale": "zh-CN"}))


def test_localized_csv_handles_unknown_codes_safe_text_zero_negative_and_blank() -> None:
    text = localized_csv(
        ["status", "store_name", "order_id", "invoice_amount_cent", "registered_at", "invoice_date"],
        [
            {"status": "FUTURE_CODE", "store_name": " =HYPERLINK(1)", "order_id": "00001234567890123456", "invoice_amount_cent": -359, "registered_at": "2026-11-18T23:00:00Z"},
            {"status": "PENDING_INVOICE", "invoice_amount_cent": 0},
        ],
    )
    rows = list(csv.DictReader(StringIO(text)))
    assert rows[0]["开票状态"] == "未知（FUTURE_CODE）"
    assert rows[0]["门店名称"] == "' =HYPERLINK(1)"
    assert rows[0]["订单ID"] == "'00001234567890123456"
    assert rows[0]["发票金额（元）"] == "-3.59"
    assert rows[0]["登记时间"] == "2026年11月19日 07:00:00"
    assert rows[0]["开票日期"] == ""
    assert rows[1]["发票金额（元）"] == "0.00"


def test_order_fee_existing_chinese_columns_gain_units_and_readable_values() -> None:
    content = "订单ID,费用方向,原始发生月份,原始基数,原始费用,账单状态\r\n123,PROMOTION,2026-10,12345,-359,LOCKED\r\n"
    rows = list(csv.DictReader(StringIO(translate_csv(content))))
    assert rows == [{"订单ID": "123", "费用方向": "推广服务费", "原始发生月份": "2026年10月", "原始基数（元）": "123.45", "原始费用（元）": "-3.59", "账单状态": "已锁账"}]


@pytest.mark.parametrize("value,expected", [
    ("-1.01", "-1.01"), (Decimal("-0.01"), "-0.01"), (0, "0.00"),
    ("+1.01", "1.01"), ("13.37", "13.37"), ("9999999999999999.99", "9999999999999999.99"),
    (None, ""), ("", ""),
])
def test_balance_yuan_fields_preserve_numbers_and_blanks_without_reclassifying_text(value, expected):
    fields = ["original", "adjustment", "period_net", "opening", "net_due", "closing"]
    content = localized_csv(
        fields + ["sku_id", "store_name"],
        [{**dict.fromkeys(fields, value), "sku_id": "-1.01", "store_name": "=SUM(1,2)"}],
        context="门店账单抵扣明细-2026-11-v1",
    )
    row = next(csv.DictReader(StringIO(content)))
    assert all(row[field] == expected for field in fields)
    assert row["SKU ID"] == "'-1.01"
    assert row["门店名称"] == "'=SUM(1,2)"


@pytest.mark.parametrize("value", ["=SUM(1,2)", "-1+2", "+1+2", "@SUM(1)"])
def test_balance_amount_columns_keep_formula_protection(value):
    fields = ["original", "adjustment", "period_net", "opening", "net_due", "closing"]
    content = localized_csv(fields, [dict.fromkeys(fields, value)], context="门店账单抵扣明细-2026-11-v1")
    row = next(csv.DictReader(StringIO(content)))
    assert all(row[field] == "'" + value for field in fields)


def test_filename_uses_shanghai_export_day_and_headers_remain_empty() -> None:
    request = Request({"type": "http", "query_string": b"locale=zh-CN&month=2026-10"})
    assert download_filename(request, "finance-promotion-invoices", datetime(2026, 11, 18, 23, tzinfo=timezone.utc)) == "推广服务费开票记录_2026年10月_2026年11月19日.csv"
    assert localized_csv(["status", "invoice_amount_cent"], []) == "开票状态,发票金额（元）\r\n"
    assert localized_csv(["statement_amount_cent"], [], context="store-statement") == "账单金额（元）\r\n"


@pytest.mark.parametrize("kind,fields,values", [
    ("sku-product", PRODUCT_IMPORT_HEADERS, ["00001234567890123456", "精诚养车"]),
    ("sku-fee-rule", IMPORT_HEADERS, ["轮胎", "12345678901234567890", "0.06", "0.03"]),
])
def test_chinese_sku_templates_are_downloaded_and_can_be_imported(
    client: TestClient, kind, fields, values,
) -> None:
    _login(client)
    path = f"/api/v1/admin/{kind}-imports/template"
    original = client.get(path)
    chinese = client.get(path, params={"locale": "zh-CN"})
    assert chinese.status_code == original.status_code == 200
    english_headers = next(csv.reader(StringIO(original.content.decode("utf-8-sig"))))
    chinese_headers = next(csv.reader(StringIO(chinese.content.decode("utf-8-sig"))))
    assert tuple(english_headers) == fields
    assert all("_" not in field and field not in fields for field in chinese_headers)
    assert "导入模板.csv" in unquote(chinese.headers["content-disposition"])
    content = StringIO(newline="")
    writer = csv.writer(content)
    writer.writerow(chinese_headers)
    writer.writerow(values)
    raw = content.getvalue().encode("utf-8")
    rows = _read_import_rows(raw, ".csv") if kind == "sku-fee-rule" else _read_tabular_rows(raw, ".csv", fields)
    assert rows == [dict(zip(fields, values))]


@pytest.mark.parametrize("extension", [".csv", ".xlsx"])
def test_sku_result_localizes_business_columns_values_and_safe_identifiers(extension):
    row = SimpleNamespace(
        sku_name="=HYPERLINK(1)", sku_id="00001234567890123456",
        promotion_service_fee_rate=Decimal("0.06"), management_service_fee_rate=Decimal("0.03"),
        validation_status=3, validation_errors_json=[{"field": "skuId", "message": "未匹配商品"}],
        created_rule_version=None,
    )
    content, _ = _render_result_file([row], extension, chinese=True)
    if extension == ".xlsx":
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=False)
        rows = list(workbook.active.values)
        workbook.close()
    else:
        rows = list(csv.reader(StringIO(content.decode("utf-8-sig"))))
    assert tuple(rows[0]) == ("SKU名称", "SKU ID", "推广服务费率", "管理服务费率", "校验状态", "错误字段", "错误说明", "生成规则版本")
    assert rows[1][0] == "'=HYPERLINK(1)"
    assert rows[1][1] == "'00001234567890123456"
    assert tuple(rows[1][4:7]) == ("校验失败", "SKU ID", "未匹配商品")


@pytest.mark.skipif(not POSTGRES_URL, reason="dedicated PostgreSQL test URL not configured")
@pytest.mark.parametrize("direction", ["PROMOTION", "MANAGEMENT"])
@pytest.mark.parametrize("contract", ["invoice", "order", "pending_projection"])
def test_postgres_real_localized_download_parity(postgres_session, monkeypatch, direction, contract):
    with client.__wrapped__(monkeypatch, postgres_session) as postgres_client:
        assertions = {
            "invoice": test_real_invoice_download_localizes_pending_without_changing_finance_facts,
            "order": test_real_finance_order_download_retains_frozen_amounts_and_filters,
            "pending_projection": test_real_pending_projection_download_labels_amount_as_fee_total,
        }
        assertions[contract](postgres_client, postgres_session, direction)
