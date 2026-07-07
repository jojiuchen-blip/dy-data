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
        "user_feedback_submissions",
        "product_type_visibility_settings",
        "settlement_order_details",
        "clue_center_orders",
        "clue_assignment_rounds",
        "clue_follow_up_records",
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
    assert [column.name for column in tables["clue_follow_up_records"].primary_key] == ["follow_up_record_id"]
    follow_up_columns = tables["clue_follow_up_records"].columns
    for column_name in (
        "order_id",
        "assignment_round_id",
        "round_no",
        "assigned_store_id",
        "follow_result",
        "note",
        "operator_user_id",
        "operator_username",
        "created_at",
    ):
        assert column_name in follow_up_columns
    assert [column.name for column in tables["clue_reassign_rule_settings"].primary_key] == ["setting_key"]
    assert [column.name for column in tables["users"].primary_key] == ["user_id"]
    assert [column.name for column in tables["user_store_scopes"].primary_key] == [
        "user_id",
        "store_id",
    ]
    assert [column.name for column in tables["user_feedback_submissions"].primary_key] == [
        "feedback_id"
    ]
    feedback_columns = tables["user_feedback_submissions"].columns
    for column_name in (
        "category",
        "content",
        "contact",
        "page_path",
        "user_id",
        "username",
        "user_role",
        "status",
        "created_at",
    ):
        assert column_name in feedback_columns
    assert [column.name for column in tables["dim_non_commission_owner_accounts"].primary_key] == [
        "normalized_owner_account_name"
    ]
    sku_rule_columns = tables["dim_sku_product_rules"].columns
    assert "product_scope" in sku_rule_columns
    sku_rule_indexes = {
        tuple(index.columns.keys())
        for index in tables["dim_sku_product_rules"].indexes
    }
    assert ("product_scope",) in sku_rule_indexes
    assert ("product_type",) in sku_rule_indexes
    assert [column.name for column in tables["product_type_visibility_settings"].primary_key] == [
        "setting_key"
    ]
    visibility_columns = tables["product_type_visibility_settings"].columns
    for column_name in (
        "enabled",
        "visible_product_scopes",
        "visible_product_types",
        "default_product_type",
        "updated_by",
        "updated_at",
    ):
        assert column_name in visibility_columns
    assert [column.name for column in tables["job_runs"].primary_key] == ["job_id"]
    assert [column.name for column in tables["data_quality_issues"].primary_key] == ["issue_id"]

    ranking_pk = [column.name for column in tables["agg_store_ranking"].primary_key]
    monthly_pk = [column.name for column in tables["agg_store_monthly_settlement"].primary_key]
    assert ranking_pk == ["month", "product_type", "store_id"]
    assert monthly_pk == ["month", "store_id", "product_type"]

    follow_up_indexes = {
        tuple(index.columns.keys())
        for index in tables["clue_follow_up_records"].indexes
    }
    assert ("order_id",) in follow_up_indexes
    assert ("assignment_round_id",) in follow_up_indexes
    assert ("assigned_store_id",) in follow_up_indexes
    assert ("created_at",) in follow_up_indexes

    feedback_indexes = {
        tuple(index.columns.keys())
        for index in tables["user_feedback_submissions"].indexes
    }
    assert ("category",) in feedback_indexes
    assert ("status",) in feedback_indexes
    assert ("user_id",) in feedback_indexes
    assert ("created_at",) in feedback_indexes
