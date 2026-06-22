from __future__ import annotations

from apps.api.dy_api.models import Base


def test_production_mvp_tables_are_declared() -> None:
    expected_tables = {
        "raw_douyin_orders",
        "raw_douyin_order_coupons",
        "raw_douyin_verify_records",
        "raw_douyin_clues",
        "raw_aweme_bindings",
        "dim_stores",
        "dim_store_poi_mappings",
        "dim_sku_product_rules",
        "dim_non_commission_owner_accounts",
        "dim_aweme_accounts",
        "users",
        "user_store_scopes",
        "settlement_order_details",
        "clue_center_orders",
        "clue_assignment_rounds",
        "clue_reassign_rule_settings",
        "agg_store_ranking",
        "agg_store_monthly_settlement",
        "job_runs",
        "data_quality_issues",
    }

    assert expected_tables.issubset(set(Base.metadata.tables))


def test_schema_has_natural_keys_for_idempotent_loads() -> None:
    tables = Base.metadata.tables

    assert [column.name for column in tables["raw_douyin_orders"].primary_key] == ["order_id"]
    assert [column.name for column in tables["raw_douyin_order_coupons"].primary_key] == ["coupon_id"]
    assert [column.name for column in tables["raw_douyin_verify_records"].primary_key] == ["verify_id"]
    assert [column.name for column in tables["raw_douyin_clues"].primary_key] == ["clue_row_key"]
    assert [column.name for column in tables["settlement_order_details"].primary_key] == ["coupon_id"]
    assert [column.name for column in tables["clue_center_orders"].primary_key] == ["order_id"]
    assert "phone_plain" in tables["clue_center_orders"].columns
    assert [column.name for column in tables["clue_assignment_rounds"].primary_key] == ["assignment_round_id"]
    assert [column.name for column in tables["clue_reassign_rule_settings"].primary_key] == ["setting_key"]
    assert [column.name for column in tables["users"].primary_key] == ["user_id"]
    assert [column.name for column in tables["user_store_scopes"].primary_key] == [
        "user_id",
        "store_id",
    ]
    assert [column.name for column in tables["dim_non_commission_owner_accounts"].primary_key] == [
        "normalized_owner_account_name"
    ]
    assert [column.name for column in tables["job_runs"].primary_key] == ["job_id"]
    assert [column.name for column in tables["data_quality_issues"].primary_key] == ["issue_id"]

    ranking_pk = [column.name for column in tables["agg_store_ranking"].primary_key]
    monthly_pk = [column.name for column in tables["agg_store_monthly_settlement"].primary_key]
    assert ranking_pk == ["month", "product_type", "store_id"]
    assert monthly_pk == ["month", "store_id", "product_type"]
