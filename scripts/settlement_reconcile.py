"""Offline DOM-table baseline parsing and conservative coupon-fee reconciliation.

No network or database access. CLI stdout contains aggregates only; private
records can be written only to an explicitly supplied, Git-ignored file.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


KEY_FIELDS = ("month", "direction", "order_id", "coupon_id", "store_id")
MONTH_PATTERN = re.compile(r"\d{4}-(?:0[1-9]|1[0-2])\Z")
TOTAL_LABELS = {"合计", "总计", "汇总", "小计", "总合计", "grandtotal", "total"}
SUMMARY_COLUMNS = {
    "2026-08": {"promotion_cent": "推广费", "management_cent": "管理服务费",
                "invoice_cent": "推广发票金额"},
    "2026-09": {"promotion_cent": "9月推广服务费", "management_cent": "9月管理服务费",
                "carryover_august_cent": "8月推广服务费未开票金额",
                "cumulative_invoice_due_cent": "累计应开推广费发票票总额",
                "invoice_cent": "推广发票金额"},
}


class ReconcileError(ValueError):
    """Input or output contract error, with messages that exclude private values."""


def parse_decimal(value: Any, *, percent: bool = False) -> Decimal | None:
    """Parse an explicit decimal without binary float arithmetic; blanks stay unknown."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise ReconcileError("boolean is not a decimal")
    text = str(value).strip().replace(",", "").replace("，", "")
    text = text.removeprefix("¥").removeprefix("￥").strip()
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    has_percent = text.endswith("%")
    if has_percent:
        text = text[:-1]
    try:
        result = Decimal(text)
    except InvalidOperation as error:
        raise ReconcileError("invalid decimal cell") from error
    if not result.is_finite() or (has_percent and not percent):
        raise ReconcileError("nonfinite or unexpected percent cell")
    return result / 100 if has_percent else result


def parse_cent(value: Any) -> int | None:
    """Convert yuan to cents with signed half-up rounding, including float tails."""
    number = parse_decimal(value)
    return None if number is None else int((number * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _is_total(row: list[str]) -> bool:
    # Only identifier/label cells can mark a total. Never search arbitrary names.
    return any(re.sub(r"\s+", "", cell).lower() in TOTAL_LABELS for cell in row[:3])


def _tables(document: dict[str, Any]) -> list[list[list[str]]]:
    tables = document.get("tables")
    if not isinstance(tables, list) or not tables:
        raise ReconcileError("document must contain nonempty tables")
    for table in tables:
        if not isinstance(table, list):
            raise ReconcileError("table must be an array")
        for row in table:
            if not isinstance(row, list) or any(not isinstance(cell, str) for cell in row):
                raise ReconcileError("DOM cells must be strings to preserve identifiers")
    return tables


def _column(header: list[str], *names: str) -> int:
    positions = [index for index, value in enumerate(header) if value.strip() in names]
    if len(positions) != 1:
        raise ReconcileError("required header missing or ambiguous")
    return positions[0]


def parse_rules(document: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Extract explicit SKU rules; do not infer SKU from product identifiers."""
    table = _tables(document)[0]
    header_index = next((index for index, row in enumerate(table) if "SKU ID" in row), None)
    if header_index is None:
        raise ReconcileError("rules SKU header missing")
    header = table[header_index]
    columns = {key: _column(header, label) for key, label in {
        "sku_id": "SKU ID", "product_id": "商品ID", "promotion_rate": "推广服务费率",
        "management_rate": "管理服务费率", "product_type": "产品线"}.items()}
    records = []
    excluded = Counter()
    for row in table[header_index + 1:]:
        if not any(cell.strip() for cell in row):
            excluded["blank"] += 1
        elif len(row) != len(header) or not re.fullmatch(r"[0-9]+", row[columns["sku_id"]].strip()):
            excluded["non_sku_row"] += 1
        else:
            record = {key: row[index].strip() for key, index in columns.items()}
            for field in ("promotion_rate", "management_rate"):
                rate = parse_decimal(record[field], percent=True)
                if rate is None or not 0 <= rate <= 1:
                    raise ReconcileError("rule rate missing or outside 0..1")
                record[field] = str(rate)
            records.append(record)
    counts = Counter(record["sku_id"] for record in records)
    return {"sku_rows": len(records), "unique_skus": len(counts),
            "duplicate_sku_keys": sum(count > 1 for count in counts.values()),
            "excluded_rows": dict(excluded),
            "rate_pairs": dict(Counter(record["promotion_rate"] + "/" + record["management_rate"] for record in records)),
            "product_type_counts": dict(Counter(record["product_type"] for record in records))}, records


def parse_summary(table: list[list[str]], month: str) -> dict[str, Any]:
    """Summarize store accrual, carryover and invoice cells as separate measures."""
    if month not in SUMMARY_COLUMNS or not table:
        raise ReconcileError("unsupported summary layout")
    header = table[0]
    columns = {key: _column(header, label) for key, label in SUMMARY_COLUMNS[month].items()}
    values: dict[str, list[int]] = defaultdict(list)
    unknown = Counter()
    excluded = Counter()
    identities = Counter()
    valid = 0
    for row in table[1:]:
        if not any(cell.strip() for cell in row):
            excluded["blank"] += 1
            continue
        if _is_total(row) or row == header:
            excluded["total_or_header"] += 1
            continue
        if len(row) != len(header) or not row[0].strip() or not row[1].strip():
            excluded["invalid_identity_or_width"] += 1
            continue
        valid += 1
        identities[row[1].strip()] += 1
        for key, index in columns.items():
            amount = parse_cent(row[index])
            if amount is None:
                unknown[key] += 1
            else:
                values[key].append(amount)
    return {"business_rows": valid, "excluded_rows": dict(excluded),
            "duplicate_sap_keys": sum(count > 1 for count in identities.values()),
            "measures": {key: {"known_sum_cent": sum(values[key]), "known_rows": len(values[key]),
                              "unknown_rows": unknown[key]} for key in columns}}


def parse_details(table: list[list[str]], month: str, *,
                  store_map: dict[str, str] | None = None,
                  coupon_map: dict[tuple[str, str], str] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Parse coupon rows into two fee directions without inventing store/SKU IDs."""
    if not MONTH_PATTERN.fullmatch(month) or not table:
        raise ReconcileError("invalid detail month or missing table")
    header = table[0]
    columns = {"order_id": _column(header, "订单编号"),
               "coupon_id": _column(header, "券码（已撤销核销加密）"),
               "redeemed_at": _column(header, "核销时间"),
               "receipt_cent": _column(header, "订单实收"),
               "rate": _column(header, "SKU ID(商品ID)对应推广费及管理服务费费率"),
               "promotion_cent": _column(header, "对应推广费金额"),
               "management_cent": _column(header, "管理服务费金额", "对应管理服务费金额"),
               "promotion_store": _column(header, "可获得推广服务费门店", "可收推广费门店"),
               "management_store": _column(header, "需要支付管理服务费门店")}
    records: list[dict[str, Any]] = []
    excluded = Counter()
    anomalies = Counter()
    coupon_keys = Counter()
    orders: dict[str, set[str]] = defaultdict(set)
    exact_rows = Counter()
    valid = 0
    for row_number, row in enumerate(table[1:], start=2):
        if not any(cell.strip() for cell in row):
            excluded["blank"] += 1
            continue
        if _is_total(row) or row == header:
            excluded["total_or_header"] += 1
            continue
        if len(row) != len(header):
            excluded["invalid_width"] += 1
            continue
        order_id, coupon_id = (row[columns[key]].strip() for key in ("order_id", "coupon_id"))
        if not order_id or not coupon_id:
            excluded["missing_order_or_coupon"] += 1
            continue
        date = row[columns["redeemed_at"]].strip()
        actual_month = date[:7] if re.match(r"\d{4}-\d{2}-\d{2}(?:\s|T|$)", date) else None
        if actual_month != month:
            excluded["other_month" if actual_month else "unknown_month"] += 1
            continue
        valid += 1
        orders[order_id].add(coupon_id)
        coupon_keys[(order_id, coupon_id)] += 1
        exact_rows[tuple(row)] += 1
        receipt = parse_cent(row[columns["receipt_cent"]])
        rate = parse_decimal(row[columns["rate"]], percent=True)
        if rate is not None and not 0 <= rate <= 1:
            raise ReconcileError("detail rate outside 0..1")
        for direction in ("promotion", "management"):
            reference = row[columns[direction + "_store"]].strip()
            amount = parse_cent(row[columns[direction + "_cent"]])
            record = {"month": month, "direction": direction, "order_id": order_id,
                      "coupon_id": (coupon_map or {}).get((order_id, coupon_id)),
                      "source_coupon_code": coupon_id, "store_id": (store_map or {}).get(reference),
                      "store_ref": reference or None, "amount_cent": amount,
                      "rate": str(rate) if rate is not None else None,
                      "receipt_cent": receipt, "sku_id": None, "source_row": row_number}
            records.append(record)
            if rate is not None and receipt is not None and amount is not None:
                expected = int((Decimal(receipt) * rate).quantize(Decimal(1), rounding=ROUND_HALF_UP))
                if expected != amount:
                    anomalies[direction + "_receipt_rate_difference_rows"] += 1
    return {"business_rows": valid, "excluded_rows": dict(excluded), "unique_orders": len(orders),
            "multi_coupon_order_keys": sum(len(coupons) > 1 for coupons in orders.values()),
            "duplicate_coupon_keys": sum(count > 1 for count in coupon_keys.values()),
            "exact_duplicate_row_excess": sum(count - 1 for count in exact_rows.values()),
            "missing_sku_rows": valid,
            "unknown_coupon_id_rows": sum(record["coupon_id"] is None for record in records) // 2,
            "anomalies": dict(anomalies),
            "directions": {direction: {
                "known_amount_sum_cent": sum(record["amount_cent"] for record in records
                                             if record["direction"] == direction and record["amount_cent"] is not None),
                "unknown_amount_rows": sum(record["amount_cent"] is None for record in records if record["direction"] == direction),
                "unknown_store_id_rows": sum(not record["store_id"] for record in records if record["direction"] == direction),
                "unique_store_refs": len({record["store_ref"] for record in records if record["direction"] == direction and record["store_ref"]})
            } for direction in ("promotion", "management")}}, records


def _validate_record(record: Any) -> None:
    if not isinstance(record, dict):
        raise ReconcileError("record must be an object")
    for key in (*KEY_FIELDS, "sku_id", "source_coupon_code"):
        value = record.get(key)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ReconcileError("identifiers must be nonempty JSON strings or null")
    if record.get("month") and not MONTH_PATTERN.fullmatch(record["month"]):
        raise ReconcileError("record month must be YYYY-MM")
    if record.get("direction") not in (None, "promotion", "management"):
        raise ReconcileError("unsupported fee direction")
    for key in ("amount_cent", "receipt_cent"):
        if record.get(key) is not None and type(record[key]) is not int:
            raise ReconcileError("cent fields must be integers or null")
    if record.get("rate") is not None:
        if not isinstance(record["rate"], str):
            raise ReconcileError("rate must be a decimal JSON string or null")
        rate = parse_decimal(record["rate"])
        if rate is None or not 0 <= rate <= 1:
            raise ReconcileError("rate outside 0..1")


def _compare_records(baseline: list[dict[str, Any]], system: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    for field, expected in {"schema_version": 1, "grain": "coupon_fee", "amount_basis": "accrued_fee"}.items():
        if system.get(field) != expected:
            raise ReconcileError("system grain/version/amount basis is incompatible")
    if not isinstance(system.get("records"), list):
        raise ReconcileError("system records must be an array")
    indexes: list[dict[tuple[str, ...], list[dict[str, Any]]]] = []
    stats = Counter({"matched_unique_keys": 0})
    differences: list[dict[str, Any]] = []
    for label, rows in (("baseline", baseline), ("system", system["records"])):
        index: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        stats[label + "_rows"] = len(rows)
        for record in rows:
            _validate_record(record)
            if any(record.get(field) is None for field in KEY_FIELDS):
                stats[label + "_unknown_key_rows"] += 1
                differences.append({"kind": "unknown_key", "side": label, "record": record})
            else:
                index[tuple(record[field] for field in KEY_FIELDS)].append(record)
        stats[label + "_duplicate_keys"] = sum(len(rows) > 1 for rows in index.values())
        stats[label + "_duplicate_excess_rows"] = sum(len(rows) - 1 for rows in index.values())
        indexes.append(index)
    left, right = indexes
    for key in sorted(left.keys() | right.keys()):
        baseline_rows, system_rows = left.get(key, []), right.get(key, [])
        if len(baseline_rows) > 1 or len(system_rows) > 1:
            stats["ambiguous_duplicate_keys"] += 1
            differences.append({"kind": "duplicate_key", "key": key,
                                "baseline": baseline_rows, "system": system_rows})
            continue
        if not baseline_rows or not system_rows:
            kind = "only_baseline" if baseline_rows else "only_system"
            stats[kind] += 1
            differences.append({"kind": kind, "key": key})
            continue
        stats["matched_unique_keys"] += 1
        before, after = baseline_rows[0], system_rows[0]
        for field in ("amount_cent", "rate", "receipt_cent", "sku_id"):
            known = before.get(field) is not None and after.get(field) is not None
            if field == "receipt_cent" and system.get("receipt_basis") != "order_receipt":
                known = False
            if not known:
                stats[field + "_unknown_pairs"] += 1
                continue
            first = parse_decimal(before[field]) if field == "rate" else before[field]
            second = parse_decimal(after[field]) if field == "rate" else after[field]
            stats[field + "_compared_pairs"] += 1
            if first != second:
                stats[field + "_difference_pairs"] += 1
                difference = {"kind": field + "_difference", "key": key,
                              "baseline": before[field], "system": after[field]}
                if field.endswith("_cent"):
                    difference["delta_cent"] = second - first
                    stats[field + "_delta_cent"] += second - first
                differences.append(difference)
    return {"status": "comparison_only_not_system_correctness", "counts": dict(stats)}, differences


def reconcile(baseline: list[dict[str, Any]], system: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compare unique keys with per-month/direction coverage and separate refund context."""
    summary, differences = _compare_records(baseline, system)
    scopes = {(record.get("month"), record.get("direction")) for record in baseline + system["records"]}
    summary["by_scope"] = []
    for month, direction in sorted(scopes, key=lambda scope: (scope[0] or "", scope[1] or "")):
        selected_baseline = [record for record in baseline
                             if record.get("month") == month and record.get("direction") == direction]
        selected_system = [record for record in system["records"]
                           if record.get("month") == month and record.get("direction") == direction]
        scoped, _ = _compare_records(selected_baseline, {**system, "records": selected_system})
        summary["by_scope"].append({"month": month, "direction": direction, "counts": scoped["counts"]})
    summary["coverage"] = ("unresolved_keys" if any(
        summary["counts"].get(side + "_unknown_key_rows", 0) or summary["counts"].get(side + "_duplicate_keys", 0)
        for side in ("baseline", "system")) else "complete_keys_only")
    summary["refund_context"] = {
        "system_rows_with_nonzero_refund_base": sum(type(record.get("refunded_amount_cent")) is int
                                                   and record["refunded_amount_cent"] != 0
                                                   for record in system["records"]),
        "system_unknown_refund_base_rows": sum(type(record.get("refunded_amount_cent")) is not int
                                              for record in system["records"]),
        "adjustments_compared": False,
    }
    return summary, differences


def read_json(path: Path) -> dict[str, Any]:
    """Read JSON without decoding numbers through binary floats."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"), parse_float=Decimal)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReconcileError("cannot read input JSON") from error
    if not isinstance(data, dict):
        raise ReconcileError("input must be a JSON object")
    return data


def read_store_map(path: Path) -> tuple[dict[str, str], dict[str, Any]]:
    """Load explicit store references, rejecting one reference mapped to multiple IDs."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReconcileError("cannot read store mapping JSON") from error
    if isinstance(data, dict):
        rows = [{"source_store_ref": key, "store_id": value} for key, value in data.items()]
    elif isinstance(data, list):
        rows = data
    else:
        raise ReconcileError("store mapping must be an object or array")
    mapping: dict[str, str] = {}
    duplicates = 0
    for row in rows:
        if not isinstance(row, dict):
            raise ReconcileError("store mapping row must be an object")
        reference, store_id = row.get("source_store_ref"), row.get("store_id")
        if not isinstance(reference, str) or not reference.strip() or reference != reference.strip():
            raise ReconcileError("store mapping reference must be a nonempty trimmed string")
        if not isinstance(store_id, str) or not store_id.strip() or store_id != store_id.strip():
            raise ReconcileError("store mapping ID must be a nonempty trimmed string")
        if reference in mapping:
            if mapping[reference] != store_id:
                raise ReconcileError("conflicting store mapping: one reference has multiple IDs")
            duplicates += 1
        mapping[reference] = store_id
    return mapping, {"source": "explicit_exact_store_reference_mapping", "unique_references": len(mapping),
                     "identical_duplicate_rows": duplicates}


def read_coupon_map(path: Path) -> tuple[dict[tuple[str, str], str], dict[str, Any]]:
    """Load explicit order/code-to-internal-ID facts; reject ambiguous identities."""
    try:
        rows = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReconcileError("cannot read coupon mapping JSON") from error
    if not isinstance(rows, list):
        raise ReconcileError("coupon mapping must be an array")
    mapping: dict[tuple[str, str], str] = {}
    reverse: dict[tuple[str, str], str] = {}
    duplicates = 0
    for row in rows:
        if not isinstance(row, dict):
            raise ReconcileError("coupon mapping row must be an object")
        fields = [row.get(field) for field in ("order_id", "source_coupon_code", "coupon_id")]
        if any(not isinstance(value, str) or not value.strip() or value != value.strip() for value in fields):
            raise ReconcileError("coupon mapping identifiers must be nonempty trimmed strings")
        order_id, source_code, coupon_id = fields
        key, reverse_key = (order_id, source_code), (order_id, coupon_id)
        if key in mapping and mapping[key] != coupon_id:
            raise ReconcileError("conflicting coupon mapping: one code has multiple IDs")
        if reverse_key in reverse and reverse[reverse_key] != source_code:
            raise ReconcileError("conflicting coupon mapping: one ID has multiple codes")
        duplicates += key in mapping
        mapping[key] = coupon_id
        reverse[reverse_key] = source_code
    return mapping, {"source": "explicit_order_and_coupon_code_mapping", "unique_code_keys": len(mapping),
                     "identical_duplicate_rows": duplicates}


def write_private_json(path: Path, data: Any) -> None:
    """Write private material only inside a Git repository's ignored path."""
    target = path.absolute()
    parent = target.parent
    existing = parent
    while not existing.exists():
        existing = existing.parent
    # Refuse symlinks anywhere in the intended output ancestry.
    if any(candidate.is_symlink() for candidate in (target, *target.parents)):
        raise ReconcileError("private output symlinks are prohibited")
    root_result = subprocess.run(["git", "-C", str(existing), "rev-parse", "--show-toplevel"],
                                 capture_output=True, text=True, encoding="utf-8", check=False)
    if root_result.returncode != 0:
        raise ReconcileError("private output must be inside a Git ignored directory")
    root = Path(root_result.stdout.strip()).resolve()
    try:
        relative = target.resolve().relative_to(root).as_posix()
    except ValueError as error:
        raise ReconcileError("private output escaped repository") from error
    ignored = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", "--", relative],
                             capture_output=True, check=False)
    tracked = subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", "--", relative],
                             capture_output=True, check=False)
    if ignored.returncode != 0 or tracked.returncode == 0:
        raise ReconcileError("private output must be untracked and Git ignored")
    parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Print a sanitized aggregate; private data requires an explicit ignored path."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--august", type=Path)
    parser.add_argument("--september", type=Path)
    parser.add_argument("--rules", type=Path)
    parser.add_argument("--store-map", type=Path, help="JSON array of {source_store_ref,store_id}; exact labels only")
    parser.add_argument("--store-map-source", choices=("explicit_reference", "management_redemption_poi", "sap_snapshot"),
                        default="explicit_reference", help="caller-declared provenance; no automatic inference")
    parser.add_argument("--coupon-map", type=Path, help="JSON array of explicit {order_id,source_coupon_code,coupon_id}")
    parser.add_argument("--system", type=Path)
    parser.add_argument("--private-output", type=Path, help="explicit Git ignored output for records and differences")
    args = parser.parse_args(argv)
    try:
        if not any((args.august, args.september, args.rules)):
            raise ReconcileError("at least one baseline input is required")
        summary: dict[str, Any] = {"status": "baseline_only_not_system_correctness", "months": {}}
        store_map = None
        if args.store_map:
            store_map, summary["store_mapping"] = read_store_map(args.store_map)
            summary["store_mapping"]["declared_provenance"] = args.store_map_source
        else:
            summary["store_mapping"] = {"source": "none", "unique_references": 0}
        coupon_map = None
        if args.coupon_map:
            coupon_map, summary["coupon_mapping"] = read_coupon_map(args.coupon_map)
        else:
            summary["coupon_mapping"] = {"source": "none", "unique_code_keys": 0}
        private: dict[str, Any] = {"schema_version": 1, "grain": "coupon_fee",
                                   "amount_basis": "accrued_fee", "receipt_basis": "order_receipt",
                                   "records": [], "carryover_records": []}
        if args.rules:
            summary["rules"], private["rules"] = parse_rules(read_json(args.rules))
        for month, path in (("2026-08", args.august), ("2026-09", args.september)):
            if path is None:
                continue
            tables = _tables(read_json(path))
            if len(tables) < 2:
                raise ReconcileError("monthly document missing summary/detail table")
            details, records = parse_details(tables[1], month, store_map=store_map, coupon_map=coupon_map)
            summary["months"][month] = {"store_summary": parse_summary(tables[0], month), "coupon_details": details}
            private["records"].extend(records)
            if month == "2026-09":
                if len(tables) < 5:
                    raise ReconcileError("September carryover table missing")
                carryover, carryover_records = parse_details(tables[4], "2026-08", store_map=store_map, coupon_map=coupon_map)
                summary["august_uninvoiced_carryover"] = carryover
                private["carryover_records"] = carryover_records
        if args.system:
            if not summary["months"]:
                raise ReconcileError("system comparison requires monthly detail baseline")
            summary["comparison"], private["differences"] = reconcile(private["records"], read_json(args.system))
        if args.private_output:
            write_private_json(args.private_output, private)
        sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        return 0
    except (ReconcileError, OSError) as error:
        # The error classes above intentionally never interpolate cells or paths.
        sys.stderr.write("reconciliation failed: " + (str(error) if isinstance(error, ReconcileError) else "file operation failed") + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
