"""Publication-only preview, reviewed apply and atomic financial protection."""
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import (
    Base, JobRun, SettlementFeeResult, SettlementMonthlyOverlay, SettlementProjectionActive,
    SettlementProjectionGeneration, SettlementStatement, SettlementStatementConfirmation,
    SettlementStatementEntry, SettlementStatementLine, SettlementRankingOverlay,
)
from apps.worker import settlement_rebuild as rebuild
from apps.worker.billing_source_capture import BillingSourceDriftError
from apps.worker.settlement_publication_only import (
    apply_settlement_publication, preview_settlement_publication,
)
from test_protected_billing_authority import _seed, _facts


def _setup(session):
    _seed(session)
    session.add(SettlementProjectionGeneration(generation_id="reviewed-base", state="published", input_fingerprint="f" * 64))
    session.flush()
    session.add(SettlementProjectionActive(projection_name="settlement", generation_id="reviewed-base"))
    session.add(SettlementStatement(statement_id="unprotected-bill", store_id="store-b", statement_month="2026-09",
        version_no=1, statement_status=2, promotion_original_fee_cent=50, promotion_net_fee_cent=50))
    session.commit()
    return sessionmaker(bind=session.get_bind(), autoflush=False, expire_on_commit=False)


def _protected_facts(session):
    session.expire_all()
    result = {table.name: sorted(repr(tuple(row)) for row in session.execute(select(table)))
              for table in Base.metadata.sorted_tables
              if table.name.startswith(("settlement_fee", "invoice", "promotion_invoice"))}
    for model in (SettlementStatement, SettlementStatementEntry, SettlementStatementLine, SettlementStatementConfirmation):
        result[model.__tablename__] = sorted(repr(tuple(row)) for row in session.execute(select(model.__table__).where(model.statement_id == "frozen-bill")))
    return result


def test_default_preview_contains_whole_month_header_versions_and_writes_nothing(db_session):
    factory = _setup(db_session)
    before = _facts(db_session)
    preview = preview_settlement_publication(factory, months=("2026-08",))
    assert preview["closure_months"] == ["2026-08", "2026-09"]
    assert preview["source_count"] == 4
    headers = {row["store_id"]: row for row in preview["expected_headers"]}
    assert (headers["store-a"]["promotion_net_fee_cent"], headers["store-a"]["management_net_fee_cent"], headers["store-a"]["action"], headers["store-a"]["expected_version"]) == (800, 500, "protected", 1)
    assert [(row["store_id"], row["expected_version"]) for row in preview["will_version_unprotected"]] == [("store-b", 2)]
    assert preview == preview_settlement_publication(factory, months=("2026-08",))
    assert "sources" not in preview and len(preview["preview_hash"]) == 64
    assert _facts(db_session) == before
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0


def test_cli_defaults_to_real_preview_and_apply_requires_hash(db_session, monkeypatch, capsys):
    import importlib.util
    from pathlib import Path
    import json

    factory = _setup(db_session)
    spec = importlib.util.spec_from_file_location("publication_ops", Path(__file__).resolve().parents[1] / "scripts/ops/publish_settlement_authority.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, "get_session_factory", lambda: factory)
    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run must not start a write worker")
    monkeypatch.setattr(cli, "start_resource_monitor", forbidden)
    assert cli.main(["--month", "2026-08"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "dry_run" and result["closure_months"] == ["2026-08", "2026-09"]
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0
    with pytest.raises(SystemExit) as exc:
        cli.main(["--month", "2026-08", "--apply"])
    assert exc.value.code == 2
    capsys.readouterr()
    stopped = []
    from types import SimpleNamespace
    monkeypatch.setattr(cli, "start_resource_monitor", lambda *_: SimpleNamespace(stop=lambda: stopped.append(True)))
    monkeypatch.setattr(cli, "current_resource_decision", lambda: SimpleNamespace(action=cli.ResourceAction.STOP))
    assert cli.main(["--month", "2026-08", "--apply", "--preview-hash", result["preview_hash"], "--admission-wait-seconds", "0"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "not_admitted"
    assert stopped == [True] and db_session.scalar(select(func.count()).select_from(JobRun)) == 0


def test_apply_publishes_without_fee_rebuild_and_versions_only_unprotected_bill(db_session, monkeypatch):
    factory = _setup(db_session)
    preview = preview_settlement_publication(factory, months=("2026-08",))
    before = _protected_facts(db_session)
    def forbidden(*args, **kwargs):
        raise AssertionError("publication-only must never rebuild fees")
    monkeypatch.setattr(rebuild, "rebuild_settlement", forbidden)
    monkeypatch.setattr(rebuild, "rebuild_dual_fee_results", forbidden)
    result = apply_settlement_publication(factory, months=("2026-08",), preview_hash=preview["preview_hash"])
    assert result["status"] == "success"
    assert result["billing"]["protected"] == 1 and result["billing"]["generated"] == 1
    assert result["projection"]["affected_months"] == ["2026-08", "2026-09"]
    db_session.expire_all()
    active = db_session.get(SettlementProjectionActive, "settlement")
    assert active.generation_id == result["projection"]["generation_id"] != "reviewed-base"
    rows = db_session.scalars(select(SettlementMonthlyOverlay).where(
        SettlementMonthlyOverlay.generation_id == active.generation_id,
        SettlementMonthlyOverlay.product_scope == "all", SettlementMonthlyOverlay.product_type == "all",
    ))
    assert {(row.store_id, row.month, row.promotion_net_fee_cent, row.management_net_fee_cent) for row in rows} == {
        ("store-a", "2026-08", 800, 500), ("store-b", "2026-09", 300, 0)}
    current = db_session.scalar(select(SettlementStatement).where(SettlementStatement.store_id == "store-b", SettlementStatement.is_current.is_(True)))
    assert current.version_no == 2 and current.promotion_net_fee_cent == 300
    ranks = db_session.scalars(select(SettlementRankingOverlay).where(
        SettlementRankingOverlay.generation_id == active.generation_id,
        SettlementRankingOverlay.product_scope == "all", SettlementRankingOverlay.product_type == "all",
    ))
    rank_values = {(row.store_id, row.period_type, row.period_key): (row.promotion_net_fee_cent, row.management_net_fee_cent) for row in ranks}
    assert rank_values[("store-a", 1, "2026-08")] == (800, 500)
    assert rank_values[("store-a", 2, "2026-09")] == (800, 500)
    assert rank_values[("store-b", 1, "2026-09")] == rank_values[("store-b", 2, "2026-09")] == (300, 0)
    _assert_real_finance_csv(db_session)
    assert _protected_facts(db_session) == before
    with pytest.raises(BillingSourceDriftError, match="preview changed"):
        apply_settlement_publication(factory, months=("2026-08",), preview_hash=preview["preview_hash"])
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 1


def _assert_real_finance_csv(session):
    import csv
    import io
    from pathlib import Path
    import sys
    from fastapi.testclient import TestClient

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
    from dy_api.auth import AuthContext, get_current_user
    from dy_api.main import create_app
    from dy_api.routes._data import get_session_dependency

    app = create_app()
    app.dependency_overrides[get_session_dependency] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id="publication-test", username="publication-test", display_name="Synthetic",
        role="admin", store_ids=("store-a", "store-b"), auth_type="user",
        store_scope_mode="specified", page_keys=("FIN03",),
    )
    client = TestClient(app)
    for direction, amount, count in (("PROMOTION", 800, 2), ("MANAGEMENT", 500, 1)):
        params = {"month": "2026-08", "feeDirection": direction, "storeId": "store-a"}
        response = client.get("/api/v1/admin/finance/order-details", params=params)
        assert response.status_code == 200, response.text
        rows = response.json()["data"]["list"]
        export = client.get("/api/v1/admin/finance/order-details/export", params=params)
        assert export.status_code == 200, export.text
        csv_rows = list(csv.DictReader(io.StringIO(export.content.decode("utf-8-sig"))))
        assert len(csv_rows) == len(rows) == count
        assert sum(int(row["frozen_fee_amount_cent"]) for row in csv_rows) == amount
        assert {row["statement_entry_id"] for row in csv_rows} == {row["statementEntryId"] for row in rows}
        assert all(row["product_name"] == "Frozen Product" and row["sku_id"] == "frozen-sku" and row["actual_fee_rate"] == "" for row in csv_rows)
        assert {row["row_type"] for row in csv_rows} == ({"ORIGINAL", "ADJUSTMENT"} if direction == "PROMOTION" else {"ORIGINAL"})


@pytest.mark.parametrize("change", ("normal-fee", "confirmation", "base"))
def test_apply_rejects_stale_preview_before_any_job_or_publication(db_session, change):
    factory = _setup(db_session)
    preview = preview_settlement_publication(factory, months=("2026-08",))
    if change == "normal-fee":
        db_session.scalar(select(SettlementFeeResult).where(SettlementFeeResult.fee_result_id == "normal")).fee_amount_cent += 1
    elif change == "confirmation":
        db_session.add(SettlementStatementConfirmation(confirmation_id="second-direction", statement_id="frozen-bill",
            fee_direction=2, confirmed_amount_cent=500, confirmation_status=1, confirmed_by="synthetic"))
    else:
        db_session.add(SettlementProjectionGeneration(generation_id="new-base", state="published", input_fingerprint="e" * 64))
        db_session.get(SettlementProjectionActive, "settlement").generation_id = "new-base"
    db_session.commit()
    before = _facts(db_session)
    with pytest.raises(BillingSourceDriftError, match="preview changed"):
        apply_settlement_publication(factory, months=("2026-08",), preview_hash=preview["preview_hash"])
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0
    assert _facts(db_session) == before


def test_billing_failure_rolls_back_publication_and_statement_switch(db_session, monkeypatch):
    factory = _setup(db_session)
    preview = preview_settlement_publication(factory, months=("2026-08",))
    before = _protected_facts(db_session)
    real_generate = rebuild.generate_pending_statements
    def blocked(*args, **kwargs):
        result = real_generate(*args, **kwargs)
        return {**result, "blocked": 1}
    monkeypatch.setattr(rebuild, "generate_pending_statements", blocked)
    with pytest.raises(RuntimeError, match="publication was not committed"):
        apply_settlement_publication(factory, months=("2026-08",), preview_hash=preview["preview_hash"])
    db_session.expire_all()
    assert db_session.get(SettlementProjectionActive, "settlement").generation_id == "reviewed-base"
    assert db_session.scalar(select(SettlementStatement).where(SettlementStatement.statement_id == "unprotected-bill")).is_current
    assert db_session.scalar(select(func.count()).select_from(SettlementStatement)) == 2
    assert _protected_facts(db_session) == before


def test_final_locked_recapture_rechecks_hash_even_when_protected_money_is_same(db_session, monkeypatch):
    factory = _setup(db_session)
    preview = preview_settlement_publication(factory, months=("2026-08",))
    ready = rebuild.mark_settlement_sparse_overlay_ready
    def add_confirmation_after_ready(*args, **kwargs):
        result = ready(*args, **kwargs)
        with factory.begin() as session:
            session.add(SettlementStatementConfirmation(confirmation_id="confirmed-during-build", statement_id="frozen-bill",
                fee_direction=2, confirmed_amount_cent=500, confirmation_status=1, confirmed_by="synthetic"))
        return result
    monkeypatch.setattr(rebuild, "mark_settlement_sparse_overlay_ready", add_confirmation_after_ready)
    with pytest.raises(BillingSourceDriftError, match="preview changed"):
        apply_settlement_publication(factory, months=("2026-08",), preview_hash=preview["preview_hash"])
    db_session.expire_all()
    assert db_session.get(SettlementProjectionActive, "settlement").generation_id == "reviewed-base"
    assert db_session.scalar(select(func.count()).select_from(SettlementStatement)) == 2
    assert db_session.scalar(select(JobRun)).status == "failed"


@pytest.mark.parametrize("admission", ("running-heavy", "resource-stop"))
def test_apply_obeys_existing_heavy_and_resource_admission(db_session, monkeypatch, admission):
    from types import SimpleNamespace

    factory = _setup(db_session)
    preview = preview_settlement_publication(factory, months=("2026-08",))
    if admission == "running-heavy":
        db_session.add(JobRun(job_id="other-heavy", job_name="settlement_rebuild", status="running"))
        db_session.commit()
    else:
        monkeypatch.setattr(rebuild, "current_resource_decision", lambda: SimpleNamespace(action="stop"))
    with pytest.raises(RuntimeError, match="admission refused"):
        apply_settlement_publication(factory, months=("2026-08",), preview_hash=preview["preview_hash"])
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == (1 if admission == "running-heavy" else 0)


def test_locked_month_is_explicitly_refused_by_preview_and_apply(db_session):
    factory = _setup(db_session)
    db_session.scalar(select(SettlementStatement).where(SettlementStatement.statement_id == "unprotected-bill")).statement_status = 4
    db_session.commit()
    with pytest.raises(rebuild.SettlementMonthLockedError, match="refuses locked"):
        preview_settlement_publication(factory, months=("2026-08",))
    with pytest.raises(rebuild.SettlementMonthLockedError):
        apply_settlement_publication(factory, months=("2026-08",), preview_hash="a" * 64)
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0


@pytest.mark.parametrize("runner", ("full", "month"))
def test_worker_recovery_dispatch_never_routes_publication_job_to_fee_rebuild(db_session, monkeypatch, runner):
    factory = _setup(db_session)
    from apps.worker import settlement_publication_only as only
    db_session.add(JobRun(job_id="publication-job", job_name="settlement_rebuild", status="queued",
                          metadata_json={"publication_only": {"protocol": only.PROTOCOL}}))
    db_session.commit()
    seen = []
    monkeypatch.setattr(only, "run_settlement_publication_job", lambda *args, **kwargs: seen.append(kwargs["job_id"]) or True)
    if runner == "full":
        assert rebuild.run_settlement_rebuild_job(factory=factory, job_id="publication-job")
    else:
        assert rebuild.run_settlement_month_rebuild_job(factory=factory, job_id="publication-job", business_month="2026-08")
    assert seen == ["publication-job"]
