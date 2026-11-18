"""Real PostgreSQL coverage for the report's task evidence and scope contract."""

import test_clue_store_follow_up_summary as cases
from test_dashboard_publication_sales_postgres import publication_postgres_session


def test_postgres_summary_preserves_report_partitions(publication_postgres_session):
    cases.test_clue_store_follow_up_summary_partitions_rounds_and_matches_overview(publication_postgres_session)


def test_postgres_summary_rejects_untraceable_deleted_and_late_records(publication_postgres_session):
    cases.test_summary_requires_valid_manual_records_and_counts_each_received_task_once(publication_postgres_session)
    # The handoff example has its own source rows; the same authorized-store
    # report must use the complete order history before selecting a task.
    cases.test_summary_matches_records_to_each_task_window_across_store_handoff(publication_postgres_session)


def test_postgres_summary_evidence_queries_stay_bounded(publication_postgres_session):
    cases.test_summary_loads_manual_evidence_in_bounded_batches_instead_of_per_store_or_task(publication_postgres_session)


def test_postgres_summary_http_and_export_keep_scope(publication_postgres_session, monkeypatch):
    cases.test_real_summary_and_export_share_authorized_tasks_products_and_headquarters_history(
        publication_postgres_session, monkeypatch,
    )
