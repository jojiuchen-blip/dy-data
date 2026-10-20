"""Clue round de-duplication and date filtering on real PostgreSQL."""

from test_dashboard_publication_clues import assert_clue_parity, prepare_clues
from test_dashboard_publication_sales_postgres import publication_postgres_session


def test_clue_projection_on_postgresql(publication_postgres_session):
    prepare_clues(publication_postgres_session)
    assert_clue_parity(publication_postgres_session)
