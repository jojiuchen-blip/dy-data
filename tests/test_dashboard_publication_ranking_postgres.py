"""Disposable PostgreSQL read-plan, distinct and projection lifecycle evidence."""
import os
from time import perf_counter
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, literal_column, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from apps.api.dy_api.dashboard_publications import ranking
from apps.api.dy_api.dashboard_publications import ranking_schema as frozen
from apps.api.dy_api.dashboard_publications.schema import metadata, runs
from apps.worker.ranking_preview_fixture import AT, CUTOFF, END, START


@pytest.fixture
def pg():
    raw = os.getenv("DYDATA_PUBLICATION_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("set DYDATA_PUBLICATION_TEST_DATABASE_URL to a disposable local PostgreSQL test database")
    url = make_url(raw)
    assert url.host in {"localhost", "127.0.0.1", "::1"}
    assert "test" in (url.database or "").lower()
    schema = "ranking_publication_test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def seed_frozen(session, count):
    session.execute(runs.insert().values(id="pub", module="douyin_ranking", status="building",
        cutoff=CUTOFF, created_at=CUTOFF, stats_json={}))
    session.execute(frozen.info.insert().values(publication_id="pub", cutoff=CUTOFF))
    session.execute(frozen.organizations.insert(), [dict(publication_id="pub", mapping_version="v1", store_id=store,
        service_store_code=store, store_name=store, effective_from=START, group_key="group", group_name="集团") for store in ("A", "B")])
    session.execute(frozen.eligibility.insert(), [dict(publication_id="pub", eligibility_version="v1",
        service_store_code=store, effective_from=START) for store in ("A", "B")])
    for offset in range(0, count, 1000):
        session.execute(frozen.orders.insert(), [dict(publication_id="pub", order_id=str(number), occurred_at=AT,
            store_id="A", is_jingcheng=True, reason=None, historical_unverified=False)
            for number in range(offset, min(offset + 1000, count))])
        session.execute(frozen.rounds.insert(), [dict(publication_id="pub", round_id=str(number),
            order_id=str(number // 2), lead_key=str(number // 2), store_id="A", mapping_version="v1",
            assigned_at=AT, is_jingcheng=True, follow_24h=number % 2, follow_any=1, self_verified=1,
            under_observation=False, first_assignment_changed=False) for number in range(offset, min(offset + 1000, count))])
    session.commit()


def test_sql_aggregates_before_hydration_at_scale(pg):
    with Session(pg) as session:
        seed_frozen(session, 100000)
        returned_rows, plans, statements = [], [], []

        def inspect_sql(connection, cursor, statement, parameters, context, executemany):
            if context.execution_options.get("ranking_explain"):
                return
            statements.append(statement)
            assert statement.lstrip().upper().startswith(("SELECT", "WITH"))
            assert "raw_douyin" not in statement and "clue_assignment_rounds" not in statement
            if "ranking_fragments" in statement:
                plan = connection.exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement,
                    parameters, execution_options={"ranking_explain": True}).scalar_one()
                plans.append(plan)

        def record_rows(connection, cursor, statement, parameters, context, executemany):
            if not context.execution_options.get("ranking_explain") and cursor.rowcount >= 0:
                returned_rows.append(cursor.rowcount)

        event.listen(pg, "before_cursor_execute", inspect_sql)
        event.listen(pg, "after_cursor_execute", record_rows)
        try:
            started = perf_counter()
            report = ranking.read_report(session, "pub", period_start=START, period_end=END, level="store")
            elapsed = perf_counter() - started
        finally:
            event.remove(pg, "before_cursor_execute", inspect_sql)
            event.remove(pg, "after_cursor_execute", record_rows)
        assert report["totals"]["order_count"] == 100000
        assert report["totals"]["follow_denominator"] == 100000
        assert report["totals"]["verification_denominator"] == 50000
        assert report["totals"]["store_count"] == 2
        assert max(returned_rows, default=0) <= 4
        assert len(statements) <= 12
        assert plans and all(item[0]["Plan"]["Actual Rows"] <= 4 for item in plans)
        started = perf_counter()
        ranking.read_report(session, "pub", period_start=START, period_end=END, level="store")
        plain_elapsed = perf_counter() - started
        # EXPLAIN above deliberately reruns the aggregate SQL; this includes
        # those diagnostic executions, so this is a broad regression budget.
        assert elapsed < 5, f"100k-order/round report including EXPLAIN: {elapsed:.3f}s"
        print(f"100k orders + 100k rounds; {len(statements)} SELECTs; max materialized rows={max(returned_rows)}; with EXPLAIN={elapsed:.3f}s; plain={plain_elapsed:.3f}s")


def test_cascade_only_projection_and_persistent_first_binding(pg):
    with Session(pg) as session:
        seed_frozen(session, 2)
        session.execute(frozen.lead_bindings.insert().values(lead_key="persistent", first_assigned_at=AT, mapping_version="v1"))
        session.execute(runs.delete().where(runs.c.id == "pub"))
        session.commit()
        for table in (frozen.orders, frozen.rounds, frozen.organizations, frozen.eligibility, frozen.info):
            assert not session.execute(select(table)).first()
        assert session.scalar(select(frozen.lead_bindings.c.lead_key)) == "persistent"


def test_filter_months_use_shanghai_not_postgres_session_timezone(pg):
    from datetime import datetime, timezone

    with Session(pg) as session:
        seed_frozen(session, 2)
        session.execute(text("SET TIME ZONE 'America/Los_Angeles'"))
        session.execute(frozen.orders.insert(), [dict(publication_id="pub", order_id="boundary-" + str(number),
            occurred_at=datetime(2025, 12, 31, 15 + number, tzinfo=timezone.utc), store_id="A",
            is_jingcheng=True, reason=None, historical_unverified=False) for number in (0, 1)])
        report = ranking.read_filters(session, "pub")
        assert report["sale_months"] == ["2026-09", "2026-01", "2025-12"]
        assert report["years"] == [2026, 2025]
        assert report["snapshot_id"] == "pub"


def test_real_builder_postgres_parity_rollback_and_source_independence(pg):
    from apps.api.dy_api.models import (
        Base, ClueAssignmentRound, ClueFollowUpRecord, DimAwemeAccount, DimSkuProductRule,
        DimStore, DimStorePoiMapping, RawDouyinOrder, RawDouyinOrderCoupon, RawDouyinVerifyRecord,
    )
    from apps.api.dy_api.ranking_schema_v1 import metadata as old_metadata, org_history, eligibility
    from apps.api.dy_api.ranking_snapshots import calculate_snapshot, read_snapshot_report

    Base.metadata.create_all(pg)
    old_metadata.create_all(pg)
    with Session(pg) as session:
        session.add(DimStore(store_id="A", store_name="门店A", service_store_code="A"))
        session.flush()
        session.add_all([DimAwemeAccount(account_id="account", store_id="A", binding_status="active"),
            DimSkuProductRule(sku_id="JC", product_scope="精诚养车"),
            DimStorePoiMapping(store_id="A", poi_id="poi"),
            RawDouyinOrder(order_id="order", sku_id="JC", owner_account_id="account", sale_time=AT)])
        session.flush()
        order = session.scalar(select(RawDouyinOrder))
        session.add_all([RawDouyinOrderCoupon(coupon_id="coupon", order_id="order", raw_order_id=order.id),
            RawDouyinVerifyRecord(verify_id="verify", coupon_id="coupon", poi_id="poi", verify_status="1", verify_time=AT),
            ClueAssignmentRound(assignment_round_id="round", order_id="order", assigned_store_id="A", assigned_at=AT,
                execution_mode="formal", round_status="active"),
            ClueFollowUpRecord(follow_up_record_id="follow", assignment_round_id="round", order_id="order",
                assigned_store_id="A", round_no=1, created_at=AT, follow_result="appointment")])
        session.execute(org_history.insert().values(mapping_version="v1", store_id="A", service_store_code="A",
            store_name="门店A", effective_from=START, group_key="g", group_name="集团", source_hash="test"))
        session.execute(eligibility.insert().values(eligibility_version="e1", service_store_code="A",
            product_scope="精诚养车", effective_from=START, source_hash="test"))
        session.commit()
        session.execute(runs.insert().values(id="rolled-back", module="douyin_ranking", status="building",
            cutoff=CUTOFF, created_at=CUTOFF, stats_json={}))
        stats = ranking.build(session, "rolled-back", CUTOFF)
        assert stats["rounds"] == 1
        session.rollback()
        assert session.scalar(select(func.count()).select_from(frozen.rounds)) == 0
        assert session.scalar(select(func.count()).select_from(frozen.lead_bindings)) == 0
        session.execute(runs.insert().values(id="pub", module="douyin_ranking", status="building",
            cutoff=CUTOFF, created_at=CUTOFF, stats_json={}))
        ranking.build(session, "pub", CUTOFF)
        session.commit()
        calculate_snapshot(session, run_id="old", period_start=START, period_end=END, observed_through=CUTOFF,
            roster_at=START, eligibility_version="e1", data_mode="business")
        old = read_snapshot_report(session, run_id="old", period_start=START, period_end=END)
        new = ranking.read_report(session, "pub", period_start=START, period_end=END)
        assert new["rows"] == old["rows"]
        assert new["totals"] == old["totals"]
        assert new["quality_json"] == old["quality_json"]
        session.execute(RawDouyinVerifyRecord.__table__.delete())
        session.execute(ClueFollowUpRecord.__table__.delete())
        session.commit()
        assert ranking.read_report(session, "pub", period_start=START, period_end=END) == new


def test_round_membership_is_batch_bounded_and_uses_source_indexes(pg, monkeypatch):
    from apps.api.dy_api.dashboard_publications import ranking_build
    from apps.api.dy_api.models import Base, ClueAssignmentRound, ClueCenterOrder, RawDouyinClue, RawDouyinOrder
    from apps.api.dy_api.ranking_schema_v1 import metadata as old_metadata
    from test_dashboard_publication_ranking import old_membership, seed_membership_cases

    Base.metadata.create_all(pg)
    old_metadata.create_all(pg)
    with Session(pg) as session:
        expected = seed_membership_cases(session)
        # Unlike the original scale fixture, all membership sources are large
        # and overlap. Unrelated rows must never be hydrated as membership.
        for table, key, product_column in (
            (RawDouyinOrder.__table__, "order_id", "sku_id"),
            (RawDouyinClue.__table__, "clue_row_key", "product_id"),
            (ClueCenterOrder.__table__, "order_id", "product_id"),
        ):
            columns = [key, product_column]
            expressions = ["'noise-' || number", "'member-sku'"]
            if key != "order_id":
                columns.append("order_id")
                expressions.append("'noise-' || number")
            if table is ClueCenterOrder.__table__:
                columns.extend(("lead_status", "current_round_status"))
                expressions.extend(("'assigned'", "'active'"))
            session.execute(table.insert().from_select(columns, select(*(
                literal_column(value) for value in expressions)).select_from(text("generate_series(1,20000) AS number"))))
            session.execute(text("ANALYZE " + table.name))
        session.commit()
        assert old_membership(session, expected) == expected
        queries = []

        def capture(connection, cursor, statement, parameters, context, executemany):
            if statement.lstrip().startswith("SELECT DISTINCT") and any(
                "FROM " + model.__tablename__ in statement for model in (RawDouyinOrder, RawDouyinClue, ClueCenterOrder)
            ):
                queries.append((statement, parameters))

        monkeypatch.setattr(ranking_build, "BATCH_SIZE", 2)
        session.execute(text("SET LOCAL work_mem = '16MB'"))
        session.execute(runs.insert().values(id="pub", module="douyin-ranking", status="building",
            cutoff=CUTOFF, created_at=CUTOFF, stats_json={}))
        event.listen(pg, "before_cursor_execute", capture)
        try:
            ranking.build(session, "pub", CUTOFF)
        finally:
            event.remove(pg, "before_cursor_execute", capture)
        actual = dict(session.execute(select(frozen.rounds.c.order_id, frozen.rounds.c.is_jingcheng).where(
            frozen.rounds.c.publication_id == "pub")).all())
        assert actual == expected
        assert len(queries) == 12  # Four round batches, three membership sources each.
        evidence = []
        for statement, parameters in queries:
            batch_parameters = [value for key, value in parameters.items() if key.startswith("order_id_")]
            assert 1 <= len(batch_parameters) <= 2
            assert set(batch_parameters).issubset(expected)
            plan = session.connection().exec_driver_sql(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters).scalar_one()[0]

            def nodes(node):
                yield node
                for child in node.get("Plans", []):
                    yield from nodes(child)

            source_nodes = [node for node in nodes(plan["Plan"]) if node.get("Relation Name")]
            assert source_nodes
            assert all(node["Node Type"] in {"Index Scan", "Index Only Scan", "Bitmap Heap Scan"} for node in source_nodes)
            assert plan["Plan"]["Actual Rows"] <= len(batch_parameters)
            # One requested order deliberately has two raw-clue rows.
            assert sum(node["Actual Rows"] for node in source_nodes) <= len(batch_parameters) + 1
            assert not any("SubPlan" in node.get("Parent Relationship", "") for node in nodes(plan["Plan"]))
            evidence.append({"relation": source_nodes[0]["Relation Name"], "batch": len(batch_parameters),
                "node": source_nodes[0]["Node Type"], "execution_ms": plan["Execution Time"],
                "source_rows": sum(node["Actual Rows"] for node in source_nodes)})
        print("ROUND_MEMBERSHIP_BATCH_PLANS=" + str(evidence))
        session.rollback()
