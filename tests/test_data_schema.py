from __future__ import annotations

from apps.api.dy_api.models import Base
from apps.api.dy_api.schemas import ClueAllocationRuleVersionData, ClueFollowUpRecordRow


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
        "sku_product_sync_history",
        "settlement_scope_rule",
        "sku_fee_rule",
        "sku_fee_rule_import_batch",
        "sku_fee_rule_import_row",
        "douyin_refund_event",
        "settlement_fee_result",
        "settlement_fee_result_current",
        "settlement_fee_adjustment",
        "settlement_statement",
        "settlement_statement_line",
        "settlement_statement_entry",
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
        "agg_store_ranking",
        "agg_store_monthly_settlement",
        "job_runs",
        "data_quality_issues",
    }

    assert expected_tables.issubset(set(Base.metadata.tables))
    assert "clue_reassign_rule_settings" not in Base.metadata.tables


def test_schema_has_natural_keys_for_idempotent_loads() -> None:
    tables = Base.metadata.tables

    assert [column.name for column in tables["raw_douyin_orders"].primary_key] == ["id"]
    assert [column.name for column in tables["raw_douyin_order_coupons"].primary_key] == ["id"]
    assert ("order_id",) in {
        tuple(constraint.columns.keys())
        for constraint in tables["raw_douyin_orders"].constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("coupon_id",) in {
        tuple(constraint.columns.keys())
        for constraint in tables["raw_douyin_order_coupons"].constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert not {
        tuple(constraint.columns.keys())
        for constraint in tables["raw_douyin_order_coupons"].constraints
        if constraint.__class__.__name__ == "ForeignKeyConstraint"
    }
    assert "idx_raw_douyin_order_coupons_raw_order" in {
        index.name for index in tables["raw_douyin_order_coupons"].indexes
    }
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
    assert [column.name for column in tables["dim_sku_product_rules"].primary_key] == ["id"]
    for column_name in (
        "sku_id",
        "sku_name",
        "product_id",
        "product_name",
        "spu_id",
        "product_scope",
        "product_type",
        "is_service_product",
        "creator_account_id",
        "creator_account_name",
        "owner_account_id",
        "owner_account_name",
        "product_status_raw",
        "product_status_normalized",
        "is_active_product",
        "sync_source",
        "sync_run_id",
        "last_synced_at",
        "manual_modified_by",
        "manual_modified_at",
        "gmt_create",
        "gmt_modified",
        # Compatibility-only fields kept during the staged cutover.
        "commission_rate",
    ):
        assert column_name in sku_rule_columns
    sku_rule_unique_constraints = {
        tuple(constraint.columns.keys())
        for constraint in tables["dim_sku_product_rules"].constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("sku_id",) in sku_rule_unique_constraints
    sku_rule_indexes = {
        tuple(index.columns.keys())
        for index in tables["dim_sku_product_rules"].indexes
    }
    assert ("product_id",) in sku_rule_indexes
    assert ("product_scope", "product_type") in sku_rule_indexes
    assert ("owner_account_id", "product_status_normalized") in sku_rule_indexes
    assert ("sync_run_id",) in sku_rule_indexes
    assert ("last_synced_at",) in sku_rule_indexes

    sync_history = tables["sku_product_sync_history"]
    assert [column.name for column in sync_history.primary_key] == ["id"]
    assert {
        "snapshot_id",
        "sync_run_id",
        "sku_id",
        "product_id",
        "spu_id",
        "sku_name",
        "product_name",
        "creator_account_id",
        "creator_account_name",
        "owner_account_id",
        "owner_account_name",
        "product_status_raw",
        "product_status_normalized",
        "payload_sha256",
        "observed_at",
        "raw_payload",
        "gmt_create",
        "gmt_modified",
    }.issubset(sync_history.columns.keys())

    settlement_scope = tables["settlement_scope_rule"]
    assert [column.name for column in settlement_scope.primary_key] == ["id"]
    assert {
        ("idempotency_key_hash", "sale_channel_normalized"),
        ("effective_month", "owner_account_id", "sale_channel_normalized"),
        ("scope_rule_version",),
    }.issubset(
        {
            tuple(constraint.columns.keys())
            for constraint in settlement_scope.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
    )

    fee_rule = tables["sku_fee_rule"]
    assert [column.name for column in fee_rule.primary_key] == ["id"]
    assert fee_rule.columns["promotion_service_fee_rate"].type.precision == 8
    assert fee_rule.columns["promotion_service_fee_rate"].type.scale == 6
    assert fee_rule.columns["management_service_fee_rate"].type.precision == 8
    assert fee_rule.columns["management_service_fee_rate"].type.scale == 6
    assert {
        ("rule_version",),
        ("idempotency_key_hash", "sku_id"),
        ("sku_id", "effective_date"),
    }.issubset(
        {
            tuple(constraint.columns.keys())
            for constraint in fee_rule.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
    )
    fee_checks = " ".join(
        str(constraint.sqltext)
        for constraint in fee_rule.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    )
    assert "promotion_service_fee_rate" in fee_checks
    assert "management_service_fee_rate" in fee_checks

    import_batch = tables["sku_fee_rule_import_batch"]
    assert [column.name for column in import_batch.primary_key] == ["id"]
    assert {
        "batch_id",
        "file_name",
        "file_sha256",
        "batch_status",
        "commit_mode",
        "effective_date",
        "total_count",
        "valid_count",
        "success_count",
        "failed_count",
        "uploaded_by",
        "validated_at",
        "committed_at",
        "commit_idempotency_key_hash",
        "commit_payload_sha256",
        "result_file_key",
        "gmt_create",
        "gmt_modified",
    }.issubset(import_batch.columns.keys())

    import_row = tables["sku_fee_rule_import_row"]
    assert [column.name for column in import_row.primary_key] == ["id"]
    assert ("batch_id", "row_number") in {
        tuple(constraint.columns.keys())
        for constraint in import_row.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert {
        "sku_id",
        "sku_name",
        "promotion_service_fee_rate",
        "management_service_fee_rate",
        "validation_status",
        "error_count",
        "error_field",
        "error_code",
        "error_message",
        "validation_errors_json",
        "created_rule_version",
        "source_row_json",
    }.issubset(import_row.columns.keys())

    refund_event = tables["douyin_refund_event"]
    assert [column.name for column in refund_event.primary_key] == ["id"]
    assert ("refund_event_id",) in {
        tuple(constraint.columns.keys())
        for constraint in refund_event.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert {
        "order_id",
        "coupon_id",
        "refund_type",
        "refund_status",
        "refund_amount_cent",
        "occurred_at",
        "successful_observed_at",
        "source_run_id",
        "raw_payload",
        "gmt_create",
        "gmt_modified",
    }.issubset(refund_event.columns.keys())

    fee_result = tables["settlement_fee_result"]
    assert [column.name for column in fee_result.primary_key] == ["id"]
    assert fee_result.columns["fee_rate"].type.precision == 8
    assert fee_result.columns["fee_rate"].type.scale == 6
    assert {
        ("fee_result_id",),
        ("coupon_id", "fee_direction", "result_version"),
    }.issubset(
        {
            tuple(constraint.columns.keys())
            for constraint in fee_result.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
    )
    assert {
        "original_business_month",
        "rule_match_date",
        "sale_store_id",
        "verify_store_id",
        "sku_id",
        "product_scope",
        "product_type",
        "sale_channel_normalized",
        "source_amount_cent",
        "refunded_amount_cent",
        "fee_base_cent",
        "fee_rate",
        "fee_amount_cent",
        "rule_version",
        "scope_rule_version",
        "result_status",
        "calculation_run_id",
        "calculated_at",
    }.issubset(fee_result.columns.keys())

    current_result = tables["settlement_fee_result_current"]
    assert {
        ("coupon_id", "fee_direction"),
        ("fee_result_id",),
    }.issubset(
        {
            tuple(constraint.columns.keys())
            for constraint in current_result.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
    )

    adjustment = tables["settlement_fee_adjustment"]
    assert [column.name for column in adjustment.primary_key] == ["id"]
    assert {
        "adjustment_id",
        "original_fee_result_id",
        "refund_event_id",
        "coupon_id",
        "order_id",
        "fee_direction",
        "original_business_month",
        "adjustment_posting_month",
        "adjustment_type",
        "adjustment_base_cent",
        "adjustment_fee_cent",
        "rule_version",
        "adjustment_reason",
        "occurred_at",
        "created_by",
    }.issubset(adjustment.columns.keys())

    statement = tables["settlement_statement"]
    assert [column.name for column in statement.primary_key] == ["id"]
    assert {
        ("statement_id",),
        ("store_id", "statement_month"),
        ("lock_version",),
    }.issubset(
        {
            tuple(constraint.columns.keys())
            for constraint in statement.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
    )

    statement_line = tables["settlement_statement_line"]
    assert {
        ("statement_line_id",),
        ("statement_id", "fee_direction", "product_scope", "product_type"),
    }.issubset(
        {
            tuple(constraint.columns.keys())
            for constraint in statement_line.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
    )
    statement_line_checks = " ".join(
        str(constraint.sqltext)
        for constraint in statement_line.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    )
    assert "net_base_cent" in statement_line_checks
    assert "net_fee_cent" in statement_line_checks

    statement_entry = tables["settlement_statement_entry"]
    assert {
        ("statement_entry_id",),
        ("source_type", "source_record_id"),
    }.issubset(
        {
            tuple(constraint.columns.keys())
            for constraint in statement_entry.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
    )
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
    assert "idempotency_key_hash" in tables["job_runs"].columns
    assert {
        "uq_job_runs_product_sync_active_slot",
        "uq_job_runs_product_sync_idempotency_key",
    }.issubset({index.name for index in tables["job_runs"].indexes})
    assert [column.name for column in tables["data_quality_issues"].primary_key] == ["issue_id"]

    ranking_pk = [column.name for column in tables["agg_store_ranking"].primary_key]
    monthly_pk = [column.name for column in tables["agg_store_monthly_settlement"].primary_key]
    assert ranking_pk == ["id"]
    assert monthly_pk == ["id"]
    ranking = tables["agg_store_ranking"]
    monthly = tables["agg_store_monthly_settlement"]
    assert {
        "period_type",
        "period_key",
        "product_scope",
        "sales_amount_cent",
        "verified_order_count",
        "verified_amount_cent",
        "promotion_net_fee_cent",
        "management_net_fee_cent",
        "net_settlement_reference_cent",
        "projection_run_id",
        "gmt_create",
        "gmt_modified",
    }.issubset(ranking.columns.keys())
    assert (
        "period_type",
        "period_key",
        "store_id",
        "product_scope",
        "product_type",
    ) in {
        tuple(constraint.columns.keys())
        for constraint in ranking.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert {
        "product_scope",
        "sales_order_count",
        "sales_amount_cent",
        "verified_order_count",
        "verified_amount_cent",
        "promotion_base_cent",
        "promotion_original_fee_cent",
        "promotion_adjustment_fee_cent",
        "promotion_net_fee_cent",
        "management_base_cent",
        "management_original_fee_cent",
        "management_adjustment_fee_cent",
        "management_net_fee_cent",
        "statement_status",
        "projection_run_id",
        "gmt_create",
        "gmt_modified",
    }.issubset(monthly.columns.keys())
    assert ("month", "store_id", "product_scope", "product_type") in {
        tuple(constraint.columns.keys())
        for constraint in monthly.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }

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


def test_follow_up_response_owns_soft_delete_fields() -> None:
    assert {"is_deleted", "deleted_at"}.issubset(ClueFollowUpRecordRow.model_fields)
    assert "is_deleted" not in ClueAllocationRuleVersionData.model_fields
    assert "deleted_at" not in ClueAllocationRuleVersionData.model_fields
