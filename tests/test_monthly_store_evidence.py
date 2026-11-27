from datetime import UTC, date, datetime
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from apps.api.dy_api.models import (
    AccountQualificationObservation,
    AccountQualificationSnapshot,
    AccountQualificationVersion,
    DimAwemeAccount,
    DimStore,
    DimStorePoiMapping,
    JobImpact,
    MonthlyStoreEvidenceSnapshot,
    RawAwemeBinding,
)
from apps.worker.account_qualification import AccountQualificationError, digest, qualified_sale_match
from apps.worker.monthly_store_evidence import (
    MissingStoreEvidenceError,
    StoreEvidenceError,
    freeze_store_evidence,
    frozen_store_evidence,
    preview_store_evidence,
    store_evidence_condition,
)


def make_version(session, *, certified=False, conflict=False):
    records = [{"account_id": "account-1", "douyin_id": "name-1", "poi_id": "poi-1"}]
    if certified:
        records[0].update(account_type="子机构门店号", binding_status="认证成功", douyin_nickname="Frozen sales name")
    if conflict:
        records.append({**records[0], "binding_status": "已解绑"})
    content = digest({"policy": "test-roster", "records": records})
    session.add(AccountQualificationSnapshot(content_sha256=content, policy_version="test-roster",
        records_json=records, record_count=len(records)))
    session.flush()
    session.add(AccountQualificationObservation(observation_id="observed", source_run_id="source-run",
        source_type="backend_workbook", started_at=datetime(2026, 10, 31, 15, tzinfo=UTC),
        ended_at=datetime(2026, 10, 31, 15, 30, tzinfo=UTC), state="success", complete=True,
        content_sha256=content, proof_json={}))
    session.flush()
    version = AccountQualificationVersion(version_id="qualification-2026-10", business_month="2026-10",
        cutoff_at=datetime(2026, 10, 31, 16, tzinfo=UTC), observation_id="observed",
        content_sha256=content, policy_version="test-roster", frozen_at=datetime(2026, 11, 1, tzinfo=UTC))
    session.add(version)
    for store in ("store-a", "store-b", "account-1"):
        session.add(DimStore(store_id=store, store_name=store, created_at=datetime(2026, 9, 1, tzinfo=UTC)))
    session.flush()
    return version


def fact(store="store-a", **overrides):
    return {"kind": "account", "key": "account-1", "store_id": store,
        "source_reference": "verified-October-account-file/row-2", "source_sha256": "a" * 64,
        "observed_at": "2026-10-31T15:00:00+00:00", "valid_from": "2026-10-01",
        "valid_to": "2026-10-31", **overrides}


def test_preview_never_writes_and_current_identity_is_not_evidence(db_session):
    version = make_version(db_session)
    db_session.add(DimAwemeAccount(account_id="account-1", store_id="account-1",
        updated_at=datetime(2026, 9, 1, tzinfo=UTC)))
    db_session.add(DimStorePoiMapping(poi_id="poi-1", store_id="store-b", mapping_source="current-only"))
    db_session.flush()
    preview = preview_store_evidence(db_session, qualification_version=version)
    assert preview["records"] == []
    assert db_session.scalar(select(MonthlyStoreEvidenceSnapshot)) is None
    with pytest.raises(MissingStoreEvidenceError):
        frozen_store_evidence(db_session, qualification_version=version)


def test_freeze_retries_reuse_version_and_preserve_explicit_conflicts(db_session):
    version = make_version(db_session)
    facts = [fact(), fact("store-b", kind="poi", key="poi-1")]
    first = freeze_store_evidence(db_session, qualification_version=version, facts=facts)
    again = freeze_store_evidence(db_session, qualification_version=version, facts=reversed(facts))
    assert first.version_id == again.version_id
    assert first.account_store_ids("account-1") == {"store-a"}
    assert first.poi_store_ids("poi-1") == {"store-b"}
    assert first.poi_store_ids("unmapped") == set()
    assert first.as_context()["content_sha256"] == first.content_sha256
    db_session.commit()
    assert frozen_store_evidence(db_session, qualification_version=version).version_id == first.version_id


@pytest.mark.parametrize("overrides,reason", [
    ({"valid_from": "2026-11-01"}, "store_evidence_outside_business_period"),
    ({"valid_to": "2026-10-30"}, "store_evidence_outside_business_period"),
    ({"observed_at": "2026-11-01T00:00:00+08:00"}, "store_evidence_outside_business_period"),
    ({"source_sha256": ""}, "store_evidence_source_proof_missing"),
    ({"store_id": "no-store"}, "store_evidence_store_missing"),
    ({"key": "other-account"}, "store_evidence_key_outside_frozen_roster"),
])
def test_reviewed_facts_require_period_source_and_frozen_identity(db_session, overrides, reason):
    version = make_version(db_session)
    with pytest.raises(StoreEvidenceError, match=reason):
        freeze_store_evidence(db_session, qualification_version=version, facts=[fact(**overrides)])
    assert db_session.scalar(select(MonthlyStoreEvidenceSnapshot)) is None


def test_new_verified_supplement_appends_and_pinned_retry_reads_old_version(db_session):
    version = make_version(db_session)
    first = freeze_store_evidence(db_session, qualification_version=version)
    new = freeze_store_evidence(db_session, qualification_version=version, facts=[fact()])
    assert new.version_id != first.version_id
    assert frozen_store_evidence(db_session, qualification_version=version).version_id == new.version_id
    assert frozen_store_evidence(db_session, qualification_version=version,
        version_id=first.version_id).account_store_ids("account-1") == set()
    db_session.add(DimAwemeAccount(account_id="account-1", store_id="store-b",
        updated_at=datetime(2026, 11, 1, tzinfo=UTC)))
    db_session.flush()
    assert frozen_store_evidence(db_session, qualification_version=version).account_store_ids("account-1") == {"store-a"}
    with pytest.raises(StoreEvidenceError, match="pinned_version_missing"):
        frozen_store_evidence(db_session, qualification_version=version, version_id="bad-pin")


def reviewed_confirmation(**changes):
    return {
        "business_month": "2026-10", "account_id": "account-1", "douyin_id": "name-1",
        "store_id": "store-a", "confirmed_at": "2026-11-26T16:00:12+08:00",
        "reviewed_by": "business-reviewer", "approval_reference": "issue/example/explicit-month-approval",
        **changes,
    }


def test_explicit_month_confirmation_retains_actual_date_and_appends_to_frozen_sources(db_session):
    version = make_version(db_session, certified=True)
    alias = fact(kind="alias", key="Other proven sales name", account_id="account-1", douyin_id="name-1")
    base = freeze_store_evidence(db_session, qualification_version=version,
        facts=[alias])
    order = SimpleNamespace(owner_account_name="Frozen sales name",
        raw_payload={"order_sale_info": {"transfer_nickName": "Frozen sales name"}})
    with pytest.raises(AccountQualificationError, match="qualification_name_store_unmapped"):
        qualified_sale_match(db_session, version=version, order=order)
    confirmation = reviewed_confirmation()
    preview = preview_store_evidence(db_session, qualification_version=version, confirmed_account_link=confirmation)
    assert db_session.scalar(select(MonthlyStoreEvidenceSnapshot.version_id)) == base.version_id
    assert all(record in preview["records"] for record in base.records)
    row = next(record for record in preview["records"] if record["kind"] == "account")
    assert row["observed_at"] == "2026-11-26T08:00:12+00:00"
    assert row["source_reference"] == confirmation["approval_reference"]
    assert row["source_values"]["business_month"] == "2026-10"
    applied = freeze_store_evidence(db_session, qualification_version=version,
        confirmed_account_link=confirmation, expected_content_sha256=preview["content_sha256"])
    retry = freeze_store_evidence(db_session, qualification_version=version,
        confirmed_account_link=confirmation, expected_content_sha256=preview["content_sha256"])
    assert applied.version_id == retry.version_id
    assert applied.account_store_ids("account-1") == {"store-a"}
    assert applied.alias_identities("Other proven sales name") == base.alias_identities("Other proven sales name")
    assert qualified_sale_match(db_session, version=version, order=order).store_id == "store-a"
    db_session.info["monthly_store_evidence_version_id"] = base.version_id
    with pytest.raises(AccountQualificationError, match="qualification_name_store_unmapped"):
        qualified_sale_match(db_session, version=version, order=order)


def test_month_confirmation_rejects_contradictory_statuses_for_one_merchant_identity(db_session):
    version = make_version(db_session, certified=True, conflict=True)
    base = freeze_store_evidence(db_session, qualification_version=version)
    with pytest.raises(StoreEvidenceError, match="qualification_name_record_conflict"):
        freeze_store_evidence(db_session, qualification_version=version,
            confirmed_account_link=reviewed_confirmation())
    assert db_session.scalar(select(MonthlyStoreEvidenceSnapshot.version_id)) == base.version_id


@pytest.mark.parametrize(("change", "reason"), [
    ({"douyin_id": "wrong-identity"}, "confirmation_identity_not_qualified"),
    ({"business_month": "2026-11"}, "confirmation_period_mismatch"),
    ({"store_id": "store-b"}, "confirmation_conflicts_with_frozen_evidence"),
])
def test_month_confirmation_cannot_change_the_identity_period_or_conflicting_store(db_session, change, reason):
    version = make_version(db_session, certified=True)
    base = freeze_store_evidence(db_session, qualification_version=version,
        facts=[fact(kind="poi", key="poi-1")])
    with pytest.raises(StoreEvidenceError, match=reason):
        freeze_store_evidence(db_session, qualification_version=version,
            confirmed_account_link=reviewed_confirmation(**change))
    assert db_session.scalar(select(MonthlyStoreEvidenceSnapshot.version_id)) == base.version_id


def test_history_reconstructs_last_known_period_mapping_and_excludes_future(db_session):
    version = make_version(db_session)
    for identity, store, at in ((1, "store-a", datetime(2026, 10, 1, tzinfo=UTC)),
                               (2, "store-b", datetime(2026, 11, 1, tzinfo=UTC))):
        db_session.add(JobImpact(id=identity, impact_key="impact-" + str(identity),
            entity_type="store_poi_mapping", entity_key="poi-1", change_kind="update",
            old_values_json={}, new_values_json={"store_id": store, "poi_id": "poi-1"},
            affected_closure_json={}, created_at=at))
    db_session.add(DimAwemeAccount(account_id="account-1", store_id="store-a",
        valid_from=date(2026, 10, 1), valid_to=date(2026, 10, 31),
        updated_at=datetime(2026, 10, 1, tzinfo=UTC)))
    db_session.flush()
    result = freeze_store_evidence(db_session, qualification_version=version)
    assert result.poi_store_ids("poi-1") == {"store-a"}
    assert result.account_store_ids("account-1") == {"store-a"}


def test_preview_hash_and_materialized_digest_are_checked(db_session):
    version = make_version(db_session)
    with pytest.raises(StoreEvidenceError, match="preview_changed"):
        freeze_store_evidence(db_session, qualification_version=version, facts=[fact()],
            expected_content_sha256="0" * 64)
    result = freeze_store_evidence(db_session, qualification_version=version, facts=[fact()])
    # Simulate corruption without using the ORM update path, which is guarded.
    db_session.execute(update(MonthlyStoreEvidenceSnapshot).where(
        MonthlyStoreEvidenceSnapshot.version_id == result.version_id).values(content_sha256="b" * 64))
    db_session.expire_all()
    db_session.info.pop("monthly_store_evidence_cache", None)
    with pytest.raises(StoreEvidenceError, match="digest_mismatch"):
        frozen_store_evidence(db_session, qualification_version=version)


def test_orm_cannot_rewrite_frozen_mapping(db_session):
    version = make_version(db_session)
    result = freeze_store_evidence(db_session, qualification_version=version)
    row = db_session.get(MonthlyStoreEvidenceSnapshot, result.version_id)
    row.records_json = [{"tampered": True}]
    with pytest.raises(ValueError, match="immutable"):
        db_session.flush()


def test_aliases_keep_exact_identity_conflicts_without_normalizing_names(db_session):
    version = make_version(db_session)
    alias = fact(kind="alias", key="literal ｜ historical name", account_id="account-1", douyin_id="name-1")
    alias.pop("store_id")
    result = freeze_store_evidence(db_session, qualification_version=version, facts=[alias])
    assert result.alias_identities("literal ｜ historical name") == {("account-1", "name-1")}
    assert result.alias_identities("literal 丨 historical name") == set()
    assert result.account_store_ids("account-1") == set()
    bad_alias = {**alias, "douyin_id": "some-other-identity"}
    with pytest.raises(StoreEvidenceError, match="alias_identity_outside_frozen_roster"):
        freeze_store_evidence(db_session, qualification_version=version, facts=[bad_alias])


def test_known_alias_period_uses_order_sale_day_in_shanghai_independently_of_month_end(db_session):
    version = make_version(db_session)
    alias = fact(kind="alias", key="old literal name", account_id="account-1", douyin_id="name-1",
                 valid_to="2026-10-10")
    alias.pop("store_id")
    result = freeze_store_evidence(db_session, qualification_version=version, facts=[alias])
    assert result.alias_identities("old literal name", at=date(2026, 10, 5)) == {("account-1", "name-1")}
    assert result.alias_identities("old literal name", at=date(2026, 10, 20)) == set()
    assert result.alias_identities("old literal name", at=datetime(2026, 10, 10, 16, tzinfo=UTC)) == set()
    assert result.alias_identities("old literal name") == {("account-1", "name-1")}
    with pytest.raises(StoreEvidenceError, match="outside_business_period"):
        freeze_store_evidence(db_session, qualification_version=version,
                              facts=[{**alias, "valid_from": "2026-10-11"}])


def test_latest_scope_admits_new_evidence_and_explicit_pin_admits_exact_previous_version(db_session):
    version = make_version(db_session)
    first = freeze_store_evidence(db_session, qualification_version=version)
    db_session.add(RawAwemeBinding(binding_key="first", raw_payload={"map": first.as_context()}))
    second = freeze_store_evidence(db_session, qualification_version=version, facts=[fact()])
    db_session.add(RawAwemeBinding(binding_key="second", raw_payload={"map": second.as_context()}))
    db_session.flush()
    expression = RawAwemeBinding.raw_payload["map"]
    query = select(RawAwemeBinding.binding_key)
    assert set(db_session.scalars(query.where(store_evidence_condition(version, expression)))) == {"second"}
    assert set(db_session.scalars(query.where(store_evidence_condition(
        version, expression, pinned_version_id=first.version_id)))) == {"first"}
    assert set(db_session.scalars(query.where(store_evidence_condition(
        version, expression, pinned_version_id="missing-pin")))) == set()


def test_historical_tombstone_invalidates_stale_live_map(db_session):
    version = make_version(db_session)
    db_session.add(DimStorePoiMapping(poi_id="poi-1", store_id="store-a", mapping_source="verified-source",
        source_observed_at=datetime(2026, 10, 1, tzinfo=UTC)))
    db_session.add(JobImpact(impact_key="removed", entity_type="store_poi_mapping", entity_key="poi-1",
        old_values_json={"store_id": "store-a"}, new_values_json={}, affected_closure_json={},
        change_kind="delete", created_at=datetime(2026, 10, 15, tzinfo=UTC)))
    db_session.flush()
    assert freeze_store_evidence(db_session, qualification_version=version).poi_store_ids("poi-1") == set()


def test_equal_time_contrary_history_is_kept_as_conflicting_evidence(db_session):
    version = make_version(db_session)
    for store in ("store-a", "store-b"):
        db_session.add(JobImpact(impact_key="same-time-" + store, entity_type="store_poi_mapping", entity_key="poi-1",
            old_values_json={}, new_values_json={"store_id": store}, affected_closure_json={},
            change_kind="update", created_at=datetime(2026, 10, 15, tzinfo=UTC)))
    db_session.flush()
    assert freeze_store_evidence(db_session, qualification_version=version).poi_store_ids("poi-1") == {"store-a", "store-b"}


def test_reviewed_period_fact_allows_late_imported_historical_catalogue(db_session):
    version = make_version(db_session)
    db_session.add(DimStore(store_id="late-import", store_name="late imported historical catalogue",
        created_at=datetime(2026, 11, 10, tzinfo=UTC)))
    db_session.flush()
    result = freeze_store_evidence(db_session, qualification_version=version, facts=[fact("late-import")])
    assert result.account_store_ids("account-1") == {"late-import"}


def test_ops_preview_apply_and_repeated_apply_bind_exact_reviewed_digest(db_session, monkeypatch, tmp_path, capsys):
    from scripts.ops import freeze_monthly_store_evidence as cli

    version = make_version(db_session)
    version_sha = version.content_sha256
    db_session.commit()
    factory = sessionmaker(bind=db_session.get_bind())
    monkeypatch.setattr(cli, "get_session_factory", lambda: factory)
    path = tmp_path / "reviewed-facts.json"
    path.write_text(json.dumps({"business_month": "2026-10",
        "qualification_content_sha256": version_sha, "reviewed_by": "test-reviewer", "facts": [fact()]}))
    args = ["--month", "2026-10", "--qualification-sha256", version_sha, "--facts-file", str(path)]
    assert cli.main(args) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["applied"] is False
    assert db_session.scalar(select(MonthlyStoreEvidenceSnapshot)) is None
    assert cli.main(args + ["--apply", "--preview-sha256", preview["content_sha256"]]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["applied"] is True
    assert cli.main(args + ["--apply", "--preview-sha256", preview["content_sha256"]]) == 0
    assert json.loads(capsys.readouterr().out)["version_id"] == first["version_id"]
    db_session.expire_all()
    row = db_session.get(MonthlyStoreEvidenceSnapshot, first["version_id"])
    assert row.records_json[0]["reviewed_by"] == "test-reviewer"
