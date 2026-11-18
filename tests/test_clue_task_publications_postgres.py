"""Actual source-trigger, worker and old/new publication checks on PostgreSQL."""
from datetime import timedelta

from alembic import command
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.dashboard_publications import clues, ranking
from apps.api.dy_api.dashboard_publications.lifecycle import resolve_publication
from apps.api.dy_api.dashboard_publications.schema import runs, source_counters
from apps.api.dy_api.models import DouyinRefundEvent, RawDouyinRefundRecord, RawDouyinVerifyRecord
from apps.worker.dashboard_publications import run_tick
from test_dashboard_publication_migration import full_pg_stack
from test_clue_task_publications import seed_tasks, test_new_publication_remains_readable_by_frozen_old_resolver_and_sql as assert_legacy_read_compatibility
from test_dashboard_publication_sales_postgres import publication_postgres_session
from test_clue_task_metrics import AT, CUTOFF, _follow


def test_frozen_678_resolver_and_ranking_sql_on_postgresql(publication_postgres_session):
    assert_legacy_read_compatibility(publication_postgres_session)


def test_source_changes_refresh_both_boards_and_preserve_pinned_first_date(full_pg_stack):
    config, engine = full_pg_stack
    command.upgrade(config, "head")
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        seed_tasks(session)
    registry = {"clue-overview": clues.build, "douyin-ranking": ranking.build}
    assert run_tick(factory, registry, now=CUTOFF) == {key: "published" for key in registry}
    with factory() as session:
        old = {key: resolve_publication(session, key).id for key in registry}
        assert clues.read(session, old["clue-overview"], {})["follow_any_numerator"] == 2
        _follow(session, "later-ingested-follow", task="self-task", order_id="self", hour=1)
        session.commit()
    assert run_tick(factory, registry, now=CUTOFF + timedelta(seconds=1)) == {key: "published" for key in registry}
    with factory() as session:
        newer = {key: resolve_publication(session, key).id for key in registry}
        assert all(old[key] != newer[key] for key in registry)
        assert clues.read(session, newer["clue-overview"], {})["follow_any_numerator"] == 3
        assert clues.read(session, old["clue-overview"], {})["follow_any_numerator"] == 2
        session.execute(update(RawDouyinVerifyRecord).where(RawDouyinVerifyRecord.verify_id == "no-clue-first").values(
            cancel_time=AT + timedelta(hours=2)))
        session.commit()
    assert run_tick(factory, registry, now=CUTOFF + timedelta(seconds=2)) == {key: "published" for key in registry}
    with factory() as session:
        current = {key: resolve_publication(session, key).id for key in registry}
        filters = {"assigned_store_id": "C", "assigned_date_start": "2026-11-17", "assigned_date_end": "2026-11-17"}
        assert clues.read(session, old["clue-overview"], filters)["self_store_verification_count"] == 1
        assert clues.read(session, current["clue-overview"], filters)["self_store_verification_count"] == 0
        report = ranking.read_report(session, current["douyin-ranking"], period_start=AT,
            period_end=AT + timedelta(days=1), store_id="C", product_scope="all")
        assert report["totals"]["self_store_verification_count"] == 0
        before = dict(session.execute(select(source_counters.c.source_name, source_counters.c.generation).where(
            source_counters.c.source_name.in_(("raw_douyin_refund_records", "douyin_refund_event")))).all())
        session.add(RawDouyinRefundRecord(source_record_key="new-refund", order_id="late", payload_hash="synthetic",
            normalized_refund_status=1, source_observed_at=AT + timedelta(hours=1)))
        session.add(DouyinRefundEvent(refund_event_id="new-refund-event", order_id="late", refund_type=1,
            refund_status=1, refund_amount_cent=0, occurred_at=AT + timedelta(hours=1),
            source_observed_at=AT + timedelta(hours=1)))
        session.commit()
        after = dict(session.execute(select(source_counters.c.source_name, source_counters.c.generation).where(
            source_counters.c.source_name.in_(before))).all())
        assert all(after[name] == before[name] + 1 for name in before)
    assert run_tick(factory, registry, now=CUTOFF + timedelta(seconds=3)) == {key: "published" for key in registry}


def test_missing_task_marker_forces_rebuild_without_resetting_counters(full_pg_stack):
    config, engine = full_pg_stack
    command.upgrade(config, "head")
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        seed_tasks(session)
    registry = {"clue-overview": clues.build}
    assert run_tick(factory, registry, now=CUTOFF)["clue-overview"] == "published"
    with factory() as session:
        old = resolve_publication(session, "clue-overview").id
        stats = dict(session.scalar(select(runs.c.stats_json).where(runs.c.id == old)))
        stats.pop("task_metrics_contract")
        session.execute(update(runs).where(runs.c.id == old).values(stats_json=stats))
        counters = dict(session.execute(select(source_counters.c.source_name, source_counters.c.generation)).all())
        session.commit()
    assert run_tick(factory, registry, now=CUTOFF + timedelta(seconds=1))["clue-overview"] == "published"
    with factory() as session:
        assert resolve_publication(session, "clue-overview").id != old
        assert dict(session.execute(select(source_counters.c.source_name, source_counters.c.generation)).all()) == counters
