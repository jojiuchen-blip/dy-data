"""Read-only comparison of missing-POI orders against the current complete head."""
import argparse
from collections import Counter
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from apps.api.dy_api.dashboard_publications import ranking_schema as frozen
from apps.api.dy_api.dashboard_publications.schema import heads, runs
from apps.api.dy_api.db import get_session_factory
from apps.api.dy_api.models import DimAwemeAccount, DimStorePoiMapping, RawAwemeBinding, RawDouyinOrder
from apps.api.dy_api.ranking_history import load_confirmed_aliases, restore_missing_poi
from apps.api.dy_api.ranking_identity import OrderAttributionIndex


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    if not 0 <= (args.end - args.start).days <= 366:
        parser.error("Use an interval of at most one year")
    tz = ZoneInfo("Asia/Shanghai")
    start = datetime.combine(args.start, time.min, tz)
    end = datetime.combine(args.end + timedelta(days=1), time.min, tz)
    limit = 250000
    with get_session_factory()() as session:
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        session.execute(text("SET LOCAL statement_timeout = '30s'"))
        head, cutoff = session.execute(select(runs.c.id, runs.c.cutoff).join(heads,
            heads.c.publication_id == runs.c.id).where(heads.c.module == "douyin-ranking",
            runs.c.status == "success")).one()
        accounts = session.scalars(select(DimAwemeAccount).limit(limit + 1)).all()
        bindings = session.scalars(select(RawAwemeBinding).limit(limit + 1)).all()
        pois = session.execute(select(DimStorePoiMapping.poi_id, DimStorePoiMapping.store_id).limit(limit + 1)).all()
        if max(len(accounts), len(bindings), len(pois)) > limit:
            raise RuntimeError("Dimension limit exceeded")
        before = OrderAttributionIndex(accounts=accounts, bindings=bindings, poi_to_store=pois)
        confirmed = load_confirmed_aliases(session, accounts, bindings, pois, limit, cutoff)
        source = RawDouyinOrder
        facts = frozen.orders
        totals = Counter()
        recovered = Counter()
        rows = session.execute(select(facts.c.occurred_at, source.owner_account_id,
            source.owner_douyin_uid, source.owner_account_name).join(source,
            source.order_id == facts.c.order_id).where(facts.c.publication_id == head,
            facts.c.is_jingcheng.is_(True), facts.c.store_id.is_(None),
            facts.c.reason == "missing_poi_mapping", facts.c.occurred_at >= start,
            facts.c.occurred_at < end).limit(limit + 1)).all()
        if len(rows) > limit:
            raise RuntimeError("Order limit exceeded; narrow the interval")
        for row in rows:
            baseline = before.resolve(occurred_at=row.occurred_at, owner_account_id=row.owner_account_id,
                owner_douyin_uid=row.owner_douyin_uid, owner_account_name=row.owner_account_name)
            if baseline.reason != "missing_poi_mapping":
                totals["changed_source_since_head"] += 1
                continue
            proposed = restore_missing_poi(baseline, confirmed, row)
            if proposed.store_id:
                recovered[proposed.store_id] += 1
            else:
                totals["insufficient_evidence"] += 1
        print("head", head, "static_missing", len(rows), "confirmed_orders", sum(recovered.values()))
        for key, count in sorted(totals.items()):
            print(key, count)
        for store, count in sorted(recovered.items()):
            print("confirmed_store", store, count)


if __name__ == "__main__":
    main()
