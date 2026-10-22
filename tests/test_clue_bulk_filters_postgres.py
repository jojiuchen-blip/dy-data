"""Opt-in current-map resolution and 1000-ID query parity on isolated PostgreSQL."""
import csv
import io
import sys
from pathlib import Path

from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from apps.api.dy_api.clue_store_filters import resolve_store_identifiers
from apps.api.dy_api.models import DimAwemeAccount, DimStore, DimStorePoiMapping
from dy_api.routes._data import DashboardDataStore
from test_clue_follow_up_postgres import postgres_engine  # noqa: F401


def test_current_maps_and_1000_store_query_export_parity(postgres_engine, monkeypatch):
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    with Session(postgres_engine) as session:
        session.add_all([DimStore(store_id="audit-store", store_name="Synthetic One"),
                         DimStore(store_id="second-store", store_name="Synthetic Two")])
        session.flush()
        ids = [str(10**18 + i) for i in range(1000)]
        session.add_all([DimAwemeAccount(account_id=identifier, store_id="audit-store") for identifier in ids])
        session.add(DimStorePoiMapping(poi_id=ids[0], store_id="second-store"))
        session.commit()
        resolved = resolve_store_identifiers(session, "\n".join(ids), ("audit-store", "second-store"))
        assert resolved["matched_identifier_count"] == 1000
        assert resolved["matched_store_count"] == 2
        assert resolve_store_identifiers(session, "audit-store", None)["unmatched_identifiers"] == ["audit-store"]
        data_store = DashboardDataStore(session)
        selected = ["audit-store", *[f"absent-{index}" for index in range(999)]]
        filters = {"assigned_store_ids": selected, "scope_store_ids": ("audit-store",), "page": 1, "page_size": 1}
        actor = {"role": "admin", "store_scope_mode": "specified", "store_ids": ["audit-store"]}
        rows = data_store.clue_assignment_rounds(filters, actor)
        exported = data_store.clue_assignment_rounds_export_csv(filters, actor)
        csv_rows = list(csv.DictReader(io.StringIO(exported.lstrip("\ufeff"))))
        assert rows["pagination"]["total"] == len(csv_rows) == 1
        assert csv_rows[0]["assignment_round_id"] == rows["rows"][0]["assignment_round_id"]
        for selection in ([], ["outside-store"]):
            assert data_store.clue_assignment_rounds({**filters, "assigned_store_ids": selection}, actor)["pagination"]["total"] == 0
