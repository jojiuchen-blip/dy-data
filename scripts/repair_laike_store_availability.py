"""Reconcile the full Laike roster; refuse partial or ambiguous production updates."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openpyxl import load_workbook
from sqlalchemy import select
from apps.api.dy_api.db import make_engine, make_session_factory
from apps.api.dy_api.models import DimStore, DimStorePoiMapping, utcnow
from apps.worker.clue_allocation import normalize_city_code
from scripts.switch_source_store_rules import save_exclusive


def load_roster(path):
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        values = iter(workbook.active.values)
        headers = next(values)
        required = {"所属账户关联poi_ID", "经度", "纬度", "省份", "城市", "门店名称"}
        if not required.issubset(headers):
            raise ValueError("unexpected roster headers")
        rows = [dict(zip(headers, row)) for row in values if any(value is not None for value in row)]
    finally:
        workbook.close()
    return rows, digest


def prepare(session, rows, *, reopen_closed=False):
    mappings = {row.poi_id: row.store_id for row in session.scalars(select(DimStorePoiMapping)).all()}
    ids = {mappings.get(str(row.get("所属账户关联poi_ID", "")).strip()) for row in rows}
    stores = {row.store_id: row for row in session.scalars(
        select(DimStore).where(DimStore.store_id.in_(ids - {None})).order_by(DimStore.store_id).with_for_update()
    ).all()}
    changes, issues, seen_pois, seen_stores = [], [], set(), set()
    for row in rows:
        poi = str(row.get("所属账户关联poi_ID", "")).strip()
        store = stores.get(mappings.get(poi))
        reason = None
        if poi in seen_pois:
            reason = "duplicate_poi"
        elif store is None:
            reason = "poi_unmapped_or_store_missing"
        elif store.store_id in seen_stores:
            reason = "multiple_roster_pois_for_one_store"
        elif not reopen_closed and (store.location_status == "closed" or "关闭" in (store.location_status_note or "")):
            reason = "closed_store_requires_business_confirmation"
        seen_pois.add(poi)
        try:
            lon, lat = Decimal(str(row["经度"])), Decimal(str(row["纬度"]))
            valid = lon.is_finite() and lat.is_finite() and -180 <= lon <= 180 and -90 <= lat <= 90 and (lon, lat) != (0, 0)
        except Exception:
            valid = False
        province, city = str(row.get("省份") or "").strip(), str(row.get("城市") or "").strip()
        if not valid or not province or not city:
            reason = reason or "invalid_geography"
        if reason:
            issues.append({"poi_id": poi, "name": row.get("门店名称"), "reason": reason})
            continue
        seen_stores.add(store.store_id)
        changes.append((store, {"is_active": True, "is_douyin_clue_applicable": True,
            "participates_in_clue_allocation": True, "location_status": "valid", "location_status_note": store.location_status_note,
            "longitude": lon, "latitude": lat, "standard_province": province, "standard_city": city,
            "city_code": normalize_city_code(city)}))
    return changes, issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--expected-count", required=True, type=int)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--reopen-closed", action="store_true", help="Only after confirming the listed closed stores have reopened")
    args = parser.parse_args()
    rows, digest = load_roster(args.input)
    if len(rows) != args.expected_count:
        raise ValueError("roster count differs from reviewed count")
    with make_session_factory(make_engine())() as session:
        changes, issues = prepare(session, rows, reopen_closed=args.reopen_closed)
        report = {"roster_count": len(rows), "ready_count": len(changes), "issues": issues, "sha256": digest}
        if args.apply:
            if issues:
                print(json.dumps(report, ensure_ascii=False))
                raise ValueError("resolve all roster issues before applying")
            save_exclusive(args.backup, {**report, "stores": [
                {column.name: getattr(store, column.name) for column in DimStore.__table__.columns}
                for store, _ in changes
            ]})
            now = utcnow()
            for store, values in changes:
                for key, value in values.items():
                    setattr(store, key, value)
                store.location_source = args.input.name
                store.location_updated_at = store.updated_at = now
            session.flush()
            assert all(store.is_active and store.is_douyin_clue_applicable and store.participates_in_clue_allocation
                       and store.location_status == "valid" for store, _ in changes)
            session.commit()
        else:
            session.rollback()
        print(json.dumps({"applied": args.apply, **report}, ensure_ascii=False))


if __name__ == "__main__":
    main()
