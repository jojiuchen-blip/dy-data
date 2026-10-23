"""Synthetic offline settlement baseline and reconciliation contract tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from scripts.settlement_reconcile import (
    ReconcileError, main, parse_cent, parse_details, parse_rules, parse_summary,
    read_coupon_map, read_store_map, reconcile, write_private_json,
)


DETAIL_HEADER = ["订单编号", "券码（已撤销核销加密）", "核销时间", "订单实收",
                 "SKU ID(商品ID)对应推广费及管理服务费费率", "对应推广费金额",
                 "管理服务费金额", "可获得推广服务费门店", "需要支付管理服务费门店"]


def _row(order: str = "000123456789012345678901", coupon: str = "00001",
         month: str = "2026-09", amount: str = "1.00") -> list[str]:
    return [order, coupon, month + "-01 12:00:00", "10.00", "0.1", amount, amount, "店甲", "店乙"]


def _record(**updates: object) -> dict:
    result = {"month": "2026-09", "direction": "promotion", "order_id": "000123456789012345678901",
              "coupon_id": "00001", "store_id": "001", "amount_cent": 100,
              "receipt_cent": 1000, "rate": "0.1", "sku_id": None}
    result.update(updates)
    return result


def _system(records: list[dict], **updates: object) -> dict:
    result = {"schema_version": 1, "grain": "coupon_fee", "amount_basis": "accrued_fee",
              "receipt_basis": "order_receipt", "records": records}
    result.update(updates)
    return result


@pytest.mark.parametrize(("value", "expected"), [("0.30000000000000004", 30), ("-1.005", -101),
                                                  ("￥1,234.565", 123457), ("(1.005)", -101),
                                                  ("", None), ("0", 0)])
def test_decimal_money_preserves_signed_cents(value: str, expected: int | None) -> None:
    assert parse_cent(value) == expected


@pytest.mark.parametrize("value", ["NaN", "Infinity", "10%", True, "secret-invalid-cell"])
def test_invalid_decimal_error_does_not_echo_cell(value: object) -> None:
    with pytest.raises(ReconcileError) as error:
        parse_cent(value)
    assert str(value) not in str(error.value)


def test_detail_preserves_large_text_ids_and_never_guesses_store_or_sku() -> None:
    summary, records = parse_details([DETAIL_HEADER, _row()], "2026-09")
    assert summary["business_rows"] == 1
    assert records[0]["order_id"] == "000123456789012345678901"
    assert records[0]["source_coupon_code"] == "00001"
    assert records[0]["coupon_id"] is None
    assert records[0]["store_id"] is None
    assert records[0]["sku_id"] is None
    assert records[0]["amount_cent"] == 100
    assert records[1]["direction"] == "management"


def test_detail_excludes_total_blank_and_august_from_september() -> None:
    summary, records = parse_details([DETAIL_HEADER, _row(), _row(month="2026-08"),
                                     [""] * len(DETAIL_HEADER), ["合计"] + ["999"] * 8,
                                     DETAIL_HEADER], "2026-09")
    assert summary["business_rows"] == 1
    assert summary["excluded_rows"] == {"other_month": 1, "blank": 1, "total_or_header": 2}
    assert len(records) == 2


def test_multiple_coupons_and_duplicate_coupon_are_distinct_quality_signals() -> None:
    summary, _ = parse_details([DETAIL_HEADER, _row(), _row(coupon="00002"), _row()], "2026-09")
    assert summary["unique_orders"] == 1
    assert summary["multi_coupon_order_keys"] == 1
    assert summary["duplicate_coupon_keys"] == 1
    assert summary["exact_duplicate_row_excess"] == 1


def test_duplicate_single_coupon_is_not_a_multi_coupon_order() -> None:
    summary, _ = parse_details([DETAIL_HEADER, _row(), _row()], "2026-09")
    assert summary["multi_coupon_order_keys"] == 0
    assert summary["duplicate_coupon_keys"] == 1


def test_negative_fee_and_float_tail_follow_row_rounding() -> None:
    summary, records = parse_details([DETAIL_HEADER, _row(amount="-0.30000000000000004")], "2026-09")
    assert records[0]["amount_cent"] == -30
    assert summary["anomalies"]["promotion_receipt_rate_difference_rows"] == 1


def test_summary_keeps_accrual_carryover_due_and_invoice_separate() -> None:
    header = ["可收推广费门店", "门店SAP编码", "9月推广服务费", "9月管理服务费",
              "8月推广服务费未开票金额", "累计应开推广费发票票总额", "推广发票金额"]
    result = parse_summary([header, ["店甲", "0001", "10", "5", "3", "13", "9"],
                            ["店乙", "0001", "", "0", "", "0", ""],
                            ["总计", "", "10", "5", "3", "13", "9"]], "2026-09")
    assert result["business_rows"] == 2
    assert result["duplicate_sap_keys"] == 1
    assert result["measures"]["promotion_cent"] == {"known_sum_cent": 1000, "known_rows": 1, "unknown_rows": 1}
    assert result["measures"]["carryover_august_cent"]["known_sum_cent"] == 300
    assert result["measures"]["cumulative_invoice_due_cent"]["known_sum_cent"] == 1300
    assert result["measures"]["invoice_cent"]["known_sum_cent"] == 900


def test_rule_parser_requires_explicit_sku_and_retains_leading_zero() -> None:
    summary, records = parse_rules({"tables": [[["title"],
        ["商品ID", "SKU ID", "推广服务费率", "管理服务费率", "产品线"],
        ["01234567890123456789", "000123", "10%", "5%", "A"],
        ["999", "", "10%", "5%", "A"]]]})
    assert summary["sku_rows"] == 1
    assert records[0]["sku_id"] == "000123"
    assert records[0]["promotion_rate"] == "0.1"
    assert summary["excluded_rows"] == {"non_sku_row": 1}


def test_reconcile_duplicate_key_is_not_summed_or_subtracted() -> None:
    result, differences = reconcile([_record(), _record()], _system([_record(amount_cent=200)]))
    assert result["counts"]["ambiguous_duplicate_keys"] == 1
    assert "amount_cent_delta_cent" not in result["counts"]
    assert differences[0]["kind"] == "duplicate_key"


def test_reconcile_multiple_coupons_match_independently() -> None:
    rows = [_record(), _record(coupon_id="00002")]
    result, _ = reconcile(rows, _system(rows))
    assert result["counts"]["matched_unique_keys"] == 2
    assert result["counts"]["baseline_duplicate_keys"] == 0


def test_comparison_reports_amount_rate_unknown_and_missing_keys() -> None:
    baseline = [_record(), _record(coupon_id="left"), _record(store_id=None)]
    system = _system([_record(amount_cent=103, rate="0.05"), _record(coupon_id="right")])
    result, _ = reconcile(baseline, system)
    counts = result["counts"]
    assert counts["amount_cent_delta_cent"] == 3
    assert counts["rate_difference_pairs"] == 1
    assert counts["sku_id_unknown_pairs"] == 1
    assert counts["baseline_unknown_key_rows"] == 1
    assert counts["only_baseline"] == counts["only_system"] == 1
    assert result["coverage"] == "unresolved_keys"
    assert result["by_scope"][0]["counts"] == counts


def test_refund_context_is_separate_and_does_not_apply_adjustments() -> None:
    result, _ = reconcile([_record()], _system([_record(refunded_amount_cent=500)]))
    assert result["refund_context"]["system_rows_with_nonzero_refund_base"] == 1
    assert result["refund_context"]["adjustments_compared"] is False
    assert result["counts"]["amount_cent_compared_pairs"] == 1
    assert "amount_cent_delta_cent" not in result["counts"]


def test_receipt_comparison_requires_same_declared_basis() -> None:
    result, _ = reconcile([_record()], _system([_record(receipt_cent=999)], receipt_basis=None))
    assert result["counts"]["receipt_cent_unknown_pairs"] == 1
    assert "receipt_cent_delta_cent" not in result["counts"]


@pytest.mark.parametrize("updates", [{"grain": "order"}, {"amount_basis": "invoice"},
                                     {"schema_version": 2}])
def test_incompatible_grain_or_money_basis_is_refused(updates: dict) -> None:
    with pytest.raises(ReconcileError):
        reconcile([_record()], _system([_record()], **updates))


@pytest.mark.parametrize("updates", [{"order_id": 12345678901234567890}, {"amount_cent": 1.5},
                                     {"amount_cent": True}, {"rate": 0.1}])
def test_standardized_input_rejects_numeric_ids_and_float_money(updates: dict) -> None:
    with pytest.raises(ReconcileError):
        reconcile([_record()], _system([_record(**updates)]))


def test_private_output_refuses_nonignored_and_tracked_paths(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("/private/\n", encoding="utf-8")
    with pytest.raises(ReconcileError, match="Git ignored"):
        write_private_json(tmp_path / "public.json", {"private": "secret"})
    write_private_json(tmp_path / "private" / "report.json", {"private": "secret"})
    assert json.loads((tmp_path / "private" / "report.json").read_text()) == {"private": "secret"}
    subprocess.run(["git", "-C", str(tmp_path), "add", "-f", "private/report.json"], check=True)
    with pytest.raises(ReconcileError, match="Git ignored"):
        write_private_json(tmp_path / "private" / "report.json", {"private": "new"})


def test_cli_stdout_is_aggregate_only(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    header = ["服务门店", "SAP编码", "推广费", "管理服务费", "推广发票金额"]
    data = {"tables": [[header, ["private-store-label", "private-sap", "1", "1", ""]],
                       [DETAIL_HEADER, _row()]]}
    source = tmp_path / "source.json"
    # August mismatch is deliberately excluded, not silently converted.
    source.write_text(json.dumps(data), encoding="utf-8")
    assert main(["--august", str(source)]) == 0
    output = capsys.readouterr().out
    assert "private-store-label" not in output
    assert "private-sap" not in output
    assert "000123456789012345678901" not in output
    assert json.loads(output)["months"]["2026-08"]["coupon_details"]["business_rows"] == 0


def test_explicit_mapping_array_rejects_ambiguous_names(tmp_path: Path) -> None:
    source = tmp_path / "map.json"
    source.write_text(json.dumps([{"source_store_ref": "店甲", "store_id": "001"},
                                  {"source_store_ref": "店甲", "store_id": "002"}]), encoding="utf-8")
    with pytest.raises(ReconcileError, match="multiple IDs"):
        read_store_map(source)


def test_explicit_mapping_preserves_ids_and_two_fee_owners(tmp_path: Path) -> None:
    source = tmp_path / "map.json"
    source.write_text(json.dumps([{"source_store_ref": "店甲", "store_id": "001"},
                                  {"source_store_ref": "店乙", "store_id": "002"}]), encoding="utf-8")
    mapping, provenance = read_store_map(source)
    _, records = parse_details([DETAIL_HEADER, _row()], "2026-09", store_map=mapping)
    assert [record["store_id"] for record in records] == ["001", "002"]
    assert provenance["unique_references"] == 2


def test_cli_never_merges_september_carryover_into_august_current(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    header = ["可收推广费门店", "门店SAP编码", "9月推广服务费", "9月管理服务费",
              "8月推广服务费未开票金额", "累计应开推广费发票票总额", "推广发票金额"]
    source = tmp_path / "september.json"
    source.write_text(json.dumps({"tables": [[header], [DETAIL_HEADER, _row()], [], [],
                                              [DETAIL_HEADER, _row(month="2026-08")]]}), encoding="utf-8")
    assert main(["--september", str(source)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert list(result["months"]) == ["2026-09"]
    assert result["months"]["2026-09"]["coupon_details"]["business_rows"] == 1
    assert result["august_uninvoiced_carryover"]["business_rows"] == 1


def test_coupon_code_is_distinct_from_internal_id_with_explicit_bridge(tmp_path: Path) -> None:
    source = tmp_path / "coupon-map.json"
    source.write_text(json.dumps([{"order_id": _row()[0], "source_coupon_code": "00001",
                                  "coupon_id": "0000000001234567890"}]), encoding="utf-8")
    mapping, provenance = read_coupon_map(source)
    summary, records = parse_details([DETAIL_HEADER, _row(), _row(coupon="00002")], "2026-09", coupon_map=mapping)
    assert records[0]["source_coupon_code"] == "00001"
    assert records[0]["coupon_id"] == "0000000001234567890"
    assert records[2]["coupon_id"] is None
    assert summary["unknown_coupon_id_rows"] == 1
    assert provenance["unique_code_keys"] == 1


@pytest.mark.parametrize("second", [{"order_id": "order", "source_coupon_code": "code", "coupon_id": "other-id"},
                                  {"order_id": "order", "source_coupon_code": "other-code", "coupon_id": "id"}])
def test_coupon_bridge_rejects_conflicting_code_or_internal_id(tmp_path: Path, second: dict) -> None:
    source = tmp_path / "coupon-map.json"
    source.write_text(json.dumps([{"order_id": "order", "source_coupon_code": "code", "coupon_id": "id"}, second]), encoding="utf-8")
    with pytest.raises(ReconcileError, match="conflicting coupon mapping"):
        read_coupon_map(source)
