"""Exact catalog conversion preserves membership and immutable money facts."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, inspect, select

from apps.api.dy_api.models import (
    AccountPermissionAuditLog, DimSkuProductRule, JobRun, SettlementFeeResult,
    SettlementStatement, SettlementStatementLine, SkuFeeRule, User,
)
from scripts.convert_jingcheng_product_types import (
    ConversionError, _private_report_path, convert_product_types,
)

PROTECTED_MODELS = (SkuFeeRule, SettlementFeeResult, SettlementStatement, SettlementStatementLine)


def snapshot(session, models):
    return {model.__tablename__: [
        {attribute.key: str(getattr(row, attribute.key)) for attribute in inspect(model).column_attrs}
        for row in session.scalars(select(model).order_by(*inspect(model).primary_key))
    ] for model in models}


@pytest.fixture()
def conversion_context(db_session):
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    db_session.add(User(user_id="conversion-admin", username="catalog-admin", display_name="Catalog Admin",
                        role="admin", store_scope_mode="all", status="active"))
    for sku_id, scope, product_type in (
        ("target-empty", "精诚养车", ""), ("target-other", "精诚养车", "268保养"),
        ("target-already", "精诚养车", "精诚养车"), ("scope-code-only", "jingcheng", "人工类型"),
        ("name-only", "其他", "人工类型"), ("near-match", "精诚养车 ", "人工类型"),
        ("type-only", "", "精诚养车"),
    ):
        db_session.add(DimSkuProductRule(sku_id=sku_id, sku_name="精诚养车名称不能用于判断", product_id=f"product-{sku_id}",
            product_scope=scope, product_type=product_type, is_active_product=False,
            commission_rate=Decimal(".1234"), manual_modified_by="previous-actor"))
    db_session.add(SkuFeeRule(rule_version="historic-rule", idempotency_key_hash="historic-rule-key", request_payload_sha256="historic",
        sku_id="target-other", sku_name_snapshot="原名称", product_scope_snapshot="精诚养车", product_type_snapshot="268保养",
        promotion_service_fee_rate=Decimal(".061234"), management_service_fee_rate=Decimal(".030000"),
        effective_date=date(2026, 8, 1), effective_at=now, created_by="previous-actor", change_reason="historic", published_at=now))
    db_session.add(SettlementFeeResult(fee_result_id="historic-result", coupon_id="coupon", order_id="order", fee_direction=1,
        original_business_month="2026-09", rule_match_date=date(2026, 9, 1), sku_id="target-other", product_scope="精诚养车",
        product_type="268保养", sale_channel_normalized="live", source_amount_cent=10000, fee_base_cent=10000,
        fee_rate=Decimal(".061234"), fee_amount_cent=612, rule_version="historic-rule", scope_rule_version="scope-version",
        calculation_run_id="historic-run", calculated_at=now))
    db_session.add(SettlementStatement(statement_id="historic-statement", store_id="store", statement_month="2026-09",
        statement_status=4, promotion_original_fee_cent=612, promotion_net_fee_cent=612, locked_by="prior", locked_at=now,
        lock_version="original-lock", confirmed_by="prior", confirmed_at=now))
    db_session.add(SettlementStatementLine(statement_line_id="historic-line", statement_id="historic-statement", fee_direction=1,
        product_scope="精诚养车", product_type="268保养", original_base_cent=10000, net_base_cent=10000,
        original_fee_cent=612, net_fee_cent=612))
    db_session.commit()
    return {"actor": "catalog-admin", "change_reason": "DYDATA-104 confirmed classification", "idempotency_key": "catalog-conversion-1"}


def assert_conversion_preserves_money(db_session, conversion_context):
    catalog_before = snapshot(db_session, (DimSkuProductRule,))
    protected_before = snapshot(db_session, PROTECTED_MODELS)
    db_session.rollback()
    preview = convert_product_types(db_session, **conversion_context)
    assert not preview["applied"]
    assert preview["target_count"] == 3 and preview["changed_count"] == 2 and preview["unchanged_count"] == 1
    assert {item["sku_id"] for item in preview["diff"]} == {"target-empty", "target-other", "target-already"}
    assert {item["product_type"]: item["count"] for item in preview["before_groups"]} == {"": 1, "268保养": 1, "精诚养车": 1}
    assert snapshot(db_session, (DimSkuProductRule,)) == catalog_before
    assert db_session.scalar(select(func.count()).select_from(AccountPermissionAuditLog)) == 0
    db_session.rollback()
    applied = convert_product_types(db_session, **conversion_context, apply=True, preview_hash=preview["preview_hash"])
    assert applied["applied"] and not applied["rebuild_queued"]
    assert snapshot(db_session, PROTECTED_MODELS) == protected_before
    catalog_after = snapshot(db_session, (DimSkuProductRule,))["dim_sku_product_rules"]
    for before, after in zip(catalog_before["dim_sku_product_rules"], catalog_after, strict=True):
        if before["sku_id"] not in {"target-empty", "target-other"}:
            assert before == after
        else:
            assert after["product_type"] == "精诚养车"
            for field in set(before) - {"product_type", "manual_modified_at", "manual_modified_by", "updated_at"}:
                assert before[field] == after[field]
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0
    audit = db_session.scalar(select(AccountPermissionAuditLog))
    assert audit.action == "CATALOG_JINGCHENG_TYPE_CONVERSION"
    assert audit.actor_user_id == "conversion-admin" and audit.after_json["preview_hash"] == preview["preview_hash"]
    db_session.rollback()
    replay = convert_product_types(db_session, **conversion_context, apply=True, preview_hash=preview["preview_hash"])
    assert replay["replayed"] and replay["diff"] == applied["diff"]
    assert db_session.scalar(select(func.count()).select_from(AccountPermissionAuditLog)) == 1


def test_preview_apply_preserves_exact_targets_money_and_audit(db_session, conversion_context):
    assert_conversion_preserves_money(db_session, conversion_context)


@pytest.mark.parametrize("mutation", ["type", "scope", "timestamp", "rate", "insert", "delete", "noop-target"])
def test_stale_preview_detects_entire_exact_target_set(db_session, conversion_context, mutation):
    preview = convert_product_types(db_session, **conversion_context)
    target = db_session.scalar(select(DimSkuProductRule).where(DimSkuProductRule.sku_id == "target-other"))
    if mutation == "type":
        target.product_type = "concurrent"
    elif mutation == "scope":
        target.product_scope = "left-target-scope"
    elif mutation == "timestamp":
        target.manual_modified_at = datetime.now(timezone.utc)
    elif mutation == "rate":
        target.commission_rate = Decimal(".2222")
    elif mutation == "insert":
        db_session.add(DimSkuProductRule(sku_id="new-target", product_scope="精诚养车", product_type="new"))
    elif mutation == "delete":
        db_session.delete(target)
    else:
        target = db_session.scalar(select(DimSkuProductRule).where(DimSkuProductRule.sku_id == "target-already"))
        target.product_type = "changed-after-noop-preview"
    db_session.commit()
    before_apply = snapshot(db_session, (DimSkuProductRule,))
    db_session.rollback()
    with pytest.raises(ConversionError, match="stale"):
        convert_product_types(db_session, **conversion_context, apply=True, preview_hash=preview["preview_hash"])
    assert snapshot(db_session, (DimSkuProductRule,)) == before_apply
    assert db_session.scalar(select(func.count()).select_from(AccountPermissionAuditLog)) == 0


def assert_failed_conversion_rolls_back(db_session, conversion_context, monkeypatch):
    preview = convert_product_types(db_session, **conversion_context)
    before = snapshot(db_session, (DimSkuProductRule, *PROTECTED_MODELS))
    db_session.rollback()
    original = db_session.flush
    def fail_after_flush(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected conversion failure")
    monkeypatch.setattr(db_session, "flush", fail_after_flush)
    with pytest.raises(RuntimeError, match="injected"):
        convert_product_types(db_session, **conversion_context, apply=True, preview_hash=preview["preview_hash"])
    monkeypatch.setattr(db_session, "flush", original)
    assert snapshot(db_session, (DimSkuProductRule, *PROTECTED_MODELS)) == before
    assert db_session.scalar(select(func.count()).select_from(AccountPermissionAuditLog)) == 0


def test_failure_rolls_back_catalog_and_audit(db_session, conversion_context, monkeypatch):
    assert_failed_conversion_rolls_back(db_session, conversion_context, monkeypatch)


def test_apply_requires_preview_and_original_replay_hash(db_session, conversion_context):
    with pytest.raises(ConversionError, match="exact preview hash"):
        convert_product_types(db_session, **conversion_context, apply=True)
    preview = convert_product_types(db_session, **conversion_context)
    convert_product_types(db_session, **conversion_context, apply=True, preview_hash=preview["preview_hash"])
    with pytest.raises(ConversionError, match="original preview hash"):
        convert_product_types(db_session, **conversion_context, apply=True, preview_hash="0" * 64)
    with pytest.raises(ConversionError, match="different request"):
        convert_product_types(db_session, **{**conversion_context, "change_reason": "different reason"},
                              apply=True, preview_hash=preview["preview_hash"])
    assert convert_product_types(db_session, **{**conversion_context, "idempotency_key": "new-operation"})["changed_count"] == 0


@pytest.mark.parametrize("status", ["running", "retry_wait"])
def test_apply_fails_closed_around_active_source_writer(db_session, conversion_context, status):
    preview = convert_product_types(db_session, **conversion_context)
    db_session.add(JobRun(job_id="busy", job_name="product_sync", status=status))
    db_session.commit()
    with pytest.raises(ConversionError, match="source writer"):
        convert_product_types(db_session, **conversion_context, apply=True, preview_hash=preview["preview_hash"])


@pytest.mark.parametrize("actor", ["missing", "ops:", "ops:../x", "ops:with spaces"])
def test_invalid_actor_cannot_preview_or_apply(db_session, conversion_context, actor):
    with pytest.raises(ConversionError):
        convert_product_types(db_session, **{**conversion_context, "actor": actor})


def test_ops_identity_is_separate_audit_role(db_session, conversion_context):
    context = {**conversion_context, "actor": "ops:codex:DYDATA-104"}
    preview = convert_product_types(db_session, **context)
    convert_product_types(db_session, **context, apply=True, preview_hash=preview["preview_hash"])
    audit = db_session.scalar(select(AccountPermissionAuditLog))
    assert audit.actor_role == "ops" and audit.actor_user_id is None
    assert db_session.scalar(select(func.count()).select_from(User)) == 1


def test_report_path_refuses_tracked_or_unignored_files():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for path in (root / "README.md", root / "unignored-catalog-preview.json"):
        with pytest.raises(ConversionError, match="outside Git"):
            _private_report_path(path)


def test_non_target_change_does_not_expand_or_invalidate_target_set(db_session, conversion_context):
    preview = convert_product_types(db_session, **conversion_context)
    other = db_session.scalar(select(DimSkuProductRule).where(DimSkuProductRule.sku_id == "name-only"))
    other.product_type = "another-manual-type"
    db_session.commit()
    applied = convert_product_types(db_session, **conversion_context, apply=True, preview_hash=preview["preview_hash"])
    assert applied["changed_count"] == 2
    db_session.refresh(other)
    assert other.product_type == "another-manual-type" and other.product_scope == "其他"


@pytest.mark.parametrize("git_available", [True, False])
def test_cli_defaults_to_private_preview_and_refuses_non_postgres_apply(db_session, conversion_context, tmp_path, monkeypatch, capsys, git_available):
    import json
    from scripts import convert_jingcheng_product_types as command

    if not git_available:
        for variable in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"):
            monkeypatch.delenv(variable, raising=False)

        def unavailable(*args, **kwargs):
            raise FileNotFoundError("git executable unavailable")

        monkeypatch.setattr(command.subprocess, "run", unavailable)
    monkeypatch.setattr(command, "make_engine", lambda: db_session.get_bind())
    report = tmp_path / "preview.json"
    arguments = ["convert-jingcheng", "--report", str(report), "--actor", conversion_context["actor"],
                 "--change-reason", conversion_context["change_reason"], "--idempotency-key", conversion_context["idempotency_key"]]
    monkeypatch.setattr(command.sys, "argv", arguments)
    assert command.main() == 0
    document = json.loads(report.read_text(encoding="utf-8"))
    assert document["applied"] is False and document["changed_count"] == 2
    assert db_session.scalar(select(func.count()).select_from(AccountPermissionAuditLog)) == 0
    db_session.rollback()
    monkeypatch.setattr(command.sys, "argv", [*arguments[:2], str(tmp_path / "apply.json"), *arguments[3:],
                                             "--apply", "--preview-hash", document["preview_hash"]])
    assert command.main() == 1
    assert "requires PostgreSQL locking" in capsys.readouterr().err
    assert not (tmp_path / "apply.json").exists()
