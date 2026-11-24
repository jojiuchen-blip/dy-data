"""Real PostgreSQL publication/ingress locks and additive migration evidence."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from threading import Event
from types import SimpleNamespace
import time
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from apps.api.dy_api.clue_product_routing import batch_product_changes, bind_product_routing, load_product_store_ids, replace_product_grants
from apps.api.dy_api.clue_product_routing import ProductRoutingError, get_shared_rule, publish_shared_rule, replace_shared_rule_grants
import apps.api.dy_api.clue_product_routing as routing_service
from apps.api.dy_api.models import Base, ClueAllocationRuleVersion, ClueLeadRuleVersionBinding, ClueMasterLead, ClueProductRoutingConfig, ClueProductStoreListVersion, ClueSharedRuleMaintainer, DimSkuProductRule, User
from apps.worker.clue_rule_versions import RuleValidationError
from test_clue_product_routing import ADMIN, NOW, _batch, _lead, _seed


@pytest.fixture()
def product_pg_engine():
    url = os.getenv("DYDATA_CLUE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set DYDATA_CLUE_TEST_DATABASE_URL to a disposable local PostgreSQL database")
    parsed = make_url(url)
    assert parsed.host in {"localhost", "127.0.0.1"} and parsed.database.endswith("_test")
    schema = "product_routing_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema} -c lock_timeout=5000"})
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            _seed(session)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _wait_on_lock(engine, pid):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            if connection.execute(text("SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"), {"pid": pid}).scalar() == "Lock":
                return
        time.sleep(0.02)
    pytest.fail("competing transaction did not wait for product row lock")


def test_first_ingress_waits_for_switch_commit_then_freezes_new_version(product_pg_engine):
    with Session(product_pg_engine) as seed:
        _batch(seed, "publish_list", store_ids=["001"])
        seed.commit()
    ready = Event()
    pids = []
    def ingest():
        with Session(product_pg_engine) as session:
            lead = _lead("during-enable")
            session.add(lead)
            session.flush()
            pids.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            ready.set()
            binding = bind_product_routing(session, lead, "p-jc", NOW)
            result = (lead.routing_mode, binding.rule_version_id if binding else None)
            session.commit()
            return result
    with ThreadPoolExecutor(max_workers=1) as pool, Session(product_pg_engine) as switcher:
        result = _batch(switcher, "enable", authorization_note="已确认名单并授权开启")
        published_id = result["results"][0]["after"]["rule_version_id"]
        future = pool.submit(ingest)
        assert ready.wait(3)
        _wait_on_lock(product_pg_engine, pids[0])
        switcher.commit()
        assert future.result(timeout=5) == ("flow", published_id)
    with Session(product_pg_engine) as verify:
        assert verify.get(ClueLeadRuleVersionBinding, "during-enable").rule_version_id == published_id


def test_ingress_committed_before_switch_stays_direct_on_bare_byd(product_pg_engine):
    with Session(product_pg_engine) as setup:
        _batch(setup, "publish_list", ids=("p-byd",), store_ids=["001"])
        setup.commit()
    ready = Event()
    pids = []
    def enable():
        with Session(product_pg_engine) as session:
            pids.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            ready.set()
            result = _batch(session, "enable", ids=("p-byd",), authorization_note="本品确认并授权")
            session.commit()
            return result
    with ThreadPoolExecutor(max_workers=1) as pool, Session(product_pg_engine) as ingress:
        lead = _lead("before-enable")
        ingress.add(lead)
        assert bind_product_routing(ingress, lead, "p-byd", NOW) is None
        assert lead.routing_mode == "direct"
        future = pool.submit(enable)
        assert ready.wait(3)
        _wait_on_lock(product_pg_engine, pids[0])
        ingress.commit()
        assert future.result(timeout=5)["succeeded"] == 1
    with Session(product_pg_engine) as verify:
        assert verify.get(ClueMasterLead, "before-enable").routing_mode == "direct"
        assert verify.get(ClueLeadRuleVersionBinding, "before-enable") is None


def test_concurrent_same_idempotency_key_publishes_one_list(product_pg_engine):
    ready = Event()
    pids = []
    payload = {"product_ids": ["p-jc"], "action": "publish_list", "store_ids": ["001"], "preview": False}
    def replay():
        with Session(product_pg_engine) as session:
            pids.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            ready.set()
            response = batch_product_changes(session, ADMIN, payload, idempotency_key="concurrent-list")
            session.commit()
            return response
    with ThreadPoolExecutor(max_workers=1) as pool, Session(product_pg_engine) as first:
        response = batch_product_changes(first, ADMIN, payload, idempotency_key="concurrent-list")
        future = pool.submit(replay)
        assert ready.wait(3)
        _wait_on_lock(product_pg_engine, pids[0])
        first.commit()
        assert future.result(timeout=5) == response
    with Session(product_pg_engine) as verify:
        assert verify.scalar(select(func.count()).select_from(ClueProductStoreListVersion)) == 1
        assert not verify.get(ClueProductRoutingConfig, "p-jc").routing_enabled


def test_published_list_is_atomic_and_failed_replacement_keeps_previous(product_pg_engine):
    with Session(product_pg_engine) as writer:
        _batch(writer, "publish_list", store_ids=["001"])
        writer.commit()
        prior = writer.get(ClueProductRoutingConfig, "p-jc").active_list_version_id
        _batch(writer, "publish_list", store_ids=["002"])
        with Session(product_pg_engine) as reader:
            assert load_product_store_ids(reader, "p-jc") == {"001"}
        writer.rollback()
        assert writer.get(ClueProductRoutingConfig, "p-jc").active_list_version_id == prior
        failed = _batch(writer, "publish_list", store_ids=["missing"])
        assert failed["failed"] == 1
        writer.commit()
    with Session(product_pg_engine) as verify:
        assert load_product_store_ids(verify, "p-jc") == {"001"}


def test_waiting_product_manager_rechecks_revoked_grant(product_pg_engine):
    with Session(product_pg_engine) as setup:
        setup.add(User(user_id="manager", username="manager", display_name="Manager", role="store", status="active", is_initialized=True))
        setup.commit()
        replace_product_grants(setup, ADMIN, "p-jc", ["manager"])
        setup.commit()
    actor = SimpleNamespace(user_id="manager", username="manager", auth_type="user", role="store", store_scope_mode="none")
    ready = Event()
    pids = []
    def change_after_preview():
        with Session(product_pg_engine) as session:
            pids.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            ready.set()
            response = batch_product_changes(session, actor, {"product_ids": ["p-jc"], "action": "publish_list", "store_ids": ["001"], "preview": False})
            session.commit()
            return response
    with ThreadPoolExecutor(max_workers=1) as pool, Session(product_pg_engine) as revoker:
        replace_product_grants(revoker, ADMIN, "p-jc", [])
        future = pool.submit(change_after_preview)
        assert ready.wait(3)
        _wait_on_lock(product_pg_engine, pids[0])
        revoker.commit()
        response = future.result(timeout=5)
        assert response["failed"] == 1
        assert response["results"][0]["error"]["code"] == "PRODUCT_FORBIDDEN"
        assert response["results"][0]["before"] == {}
    with Session(product_pg_engine) as verify:
        assert load_product_store_ids(verify, "p-jc") == set()


def test_concurrent_field_patches_keep_the_committed_peer_fields(product_pg_engine):
    ready = Event()
    pids = []
    def second_patch():
        with Session(product_pg_engine) as session:
            pids.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            ready.set()
            result = _batch(session, "publish_rule", rules={"appointment_hours": 96})
            session.commit()
            return result
    with ThreadPoolExecutor(max_workers=1) as pool, Session(product_pg_engine) as first:
        first_result = _batch(first, "publish_rule", rules={"first_follow_up_sla_hours": 48})
        first_version_id = first_result["results"][0]["after"]["rule_version_id"]
        future = pool.submit(second_patch)
        assert ready.wait(3)
        _wait_on_lock(product_pg_engine, pids[0])
        first.commit()
        result = future.result(timeout=5)
        assert result["succeeded"] == 1
        assert result["results"][0]["after"]["first_follow_up_sla_hours"] == 48
        assert result["results"][0]["after"]["follow_up_policy"]["appointment_hours"] == 96
    with Session(product_pg_engine) as verify:
        first_version = verify.get(ClueAllocationRuleVersion, first_version_id)
        assert first_version.first_follow_up_sla_hours == 48
        assert first_version.snapshot["follow_up_policy"]["appointment_hours"] == 72
        assert first_version.status == "retired"


def test_enable_waits_for_list_publisher_and_rejects_stale_approval(product_pg_engine):
    with Session(product_pg_engine) as setup:
        _batch(setup, "publish_list", ids=("p-byd",), store_ids=["001"])
        setup.commit()
        approved_version = setup.get(ClueProductRoutingConfig, "p-byd").active_list_version_id
    ready = Event()
    pids = []
    def enable_with_approved_version():
        with Session(product_pg_engine) as session:
            pids.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            ready.set()
            result = _batch(session, "enable", ids=("p-byd",), authorization_note="仅确认预览的旧名单",
                expected_list_versions={"p-byd": approved_version})
            session.commit()
            return result
    with ThreadPoolExecutor(max_workers=1) as pool, Session(product_pg_engine) as publisher:
        _batch(publisher, "publish_list", ids=("p-byd",), store_ids=["002"])
        future = pool.submit(enable_with_approved_version)
        assert ready.wait(3)
        _wait_on_lock(product_pg_engine, pids[0])
        publisher.commit()
        result = future.result(timeout=5)
        assert result["failed"] == 1
        assert result["results"][0]["error"]["code"] == "LIST_VERSION_CHANGED"
        assert result["results"][0]["before"]["list_version"] != approved_version
    with Session(product_pg_engine) as verify:
        assert not verify.get(ClueProductRoutingConfig, "p-byd").routing_enabled
        assert load_product_store_ids(verify, "p-byd") == {"002"}
        assert verify.scalar(select(func.count()).select_from(ClueAllocationRuleVersion)) == 0


def test_first_byd_enable_waits_for_current_shared_base_publication(product_pg_engine):
    with Session(product_pg_engine) as setup:
        _batch(setup, "publish_list", ids=("p-byd",), store_ids=["001"])
        publish_shared_rule(setup, ADMIN, {"first_follow_up_sla_hours": 36}, preview=False)
        setup.commit()
        denied = _batch(setup, "publish_rule", ids=("p-byd",), rules={"first_follow_up_sla_hours": 60})
        assert denied["results"][0]["error"]["code"] == "PRODUCT_NOT_ENABLED"
        setup.commit()
    ready = Event()
    pids = []
    def first_enable():
        with Session(product_pg_engine) as session:
            pids.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            ready.set()
            result = _batch(session, "enable", ids=("p-byd",), authorization_note="确认名单并授权首次开启")
            session.commit()
            return result
    with ThreadPoolExecutor(max_workers=1) as pool, Session(product_pg_engine) as base_publisher:
        publish_shared_rule(base_publisher, ADMIN, {"first_follow_up_sla_hours": 48}, preview=False)
        base_id = get_shared_rule(base_publisher, ADMIN)["rule_version_id"]
        future = pool.submit(first_enable)
        assert ready.wait(3)
        _wait_on_lock(product_pg_engine, pids[0])
        base_publisher.commit()
        result = future.result(timeout=5)
        assert result["results"][0]["after"]["first_follow_up_sla_hours"] == 48
    with Session(product_pg_engine) as verify:
        config = verify.get(ClueProductRoutingConfig, "p-byd")
        assert config.first_enabled_at is not None
        version = verify.get(ClueAllocationRuleVersion, config.rule_version_id)
        assert version.snapshot["base_rule_version_id"] == base_id


def test_failed_rule_publication_rolls_back_retirement_but_peer_succeeds(product_pg_engine, monkeypatch):
    with Session(product_pg_engine) as setup:
        setup.add(DimSkuProductRule(sku_id="sku-other-jc", product_id="p-other-jc", product_name="Other JC", product_scope="精诚养车"))
        setup.commit()
        original = _batch(setup, "publish_rule", rules={"first_follow_up_sla_hours": 24})
        old_id = original["results"][0]["after"]["rule_version_id"]
        setup.commit()
    real_publish = routing_service._publish_version
    def fail_after_publication(session, rule, actor, settings, **kwargs):
        result = real_publish(session, rule, actor, settings, **kwargs)
        if rule.scope_key == "product:p-jc":
            raise RuleValidationError("synthetic post-publication failure")
        return result
    monkeypatch.setattr(routing_service, "_publish_version", fail_after_publication)
    with Session(product_pg_engine) as publisher:
        response = _batch(publisher, "publish_rule", ids=("p-jc", "p-other-jc"), rules={"first_follow_up_sla_hours": 48})
        assert response["succeeded"] == response["failed"] == 1
        publisher.commit()
    with Session(product_pg_engine) as verify:
        old = verify.get(ClueAllocationRuleVersion, old_id)
        assert old.status == "published"
        assert old.first_follow_up_sla_hours == 24
        assert verify.get(ClueProductRoutingConfig, "p-jc").rule_version_id == old_id
        other_id = verify.get(ClueProductRoutingConfig, "p-other-jc").rule_version_id
        assert verify.get(ClueAllocationRuleVersion, other_id).first_follow_up_sla_hours == 48


def test_waiting_shared_maintainer_cannot_publish_after_revocation(product_pg_engine):
    with Session(product_pg_engine) as setup:
        setup.add(User(user_id="shared-maintainer", username="shared-maintainer", display_name="Shared Maintainer",
            role="store", store_scope_mode="none", status="active", is_initialized=True))
        setup.commit()
        publish_shared_rule(setup, ADMIN, {"first_follow_up_sla_hours": 24}, preview=False)
        replace_shared_rule_grants(setup, ADMIN, ["shared-maintainer"])
        setup.commit()
    actor = SimpleNamespace(user_id="shared-maintainer", username="shared-maintainer", auth_type="user", role="store", store_scope_mode="none")
    ready = Event()
    pids = []
    def publish_after_preview():
        with Session(product_pg_engine) as session:
            pids.append(session.execute(text("SELECT pg_backend_pid()")).scalar_one())
            ready.set()
            try:
                publish_shared_rule(session, actor, {"first_follow_up_sla_hours": 60}, preview=False)
                session.commit()
                return "unexpected_success"
            except ProductRoutingError as exc:
                session.rollback()
                return exc.code
    with ThreadPoolExecutor(max_workers=1) as pool, Session(product_pg_engine) as revoker:
        replace_shared_rule_grants(revoker, ADMIN, [])
        future = pool.submit(publish_after_preview)
        assert ready.wait(3)
        _wait_on_lock(product_pg_engine, pids[0])
        revoker.commit()
        assert future.result(timeout=5) == "SHARED_RULE_FORBIDDEN"
    with Session(product_pg_engine) as verify:
        assert get_shared_rule(verify, ADMIN)["first_follow_up_sla_hours"] == 24
        assert verify.scalar(select(func.count()).select_from(ClueSharedRuleMaintainer)) == 0
        assert verify.get(User, "shared-maintainer").store_scope_mode == "none"
        assert verify.get(User, "shared-maintainer").role == "store"


def test_real_upgrade_from_monthly_0069_preserves_old_leads_and_defaults_off(monkeypatch):
    url = os.getenv("DYDATA_CLUE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set DYDATA_CLUE_TEST_DATABASE_URL to a disposable local PostgreSQL database")
    parsed = make_url(url)
    assert parsed.host in {"localhost", "127.0.0.1"} and parsed.database.endswith("_test")
    schema = "product_migration_" + uuid4().hex
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    migration_url = parsed.update_query_dict({"options": f"-c search_path={schema}"})
    monkeypatch.setenv("DY_DATABASE_URL", migration_url.render_as_string(hide_password=False))
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        command.upgrade(config, "20261118_0069")
        scoped = create_engine(migration_url)
        with scoped.begin() as connection:
            old = Table("clue_master_leads", MetaData(), autoload_with=connection)
            connection.execute(old.insert().values(lead_key="legacy-unassigned", source_clue_row_key="legacy-row", source_identity_key="legacy-identity",
                normalized_order_status="active", status_source="clue", lifecycle_status="active", allocation_state="pending_allocation",
                ended_without_assignment=False, created_at=NOW, updated_at=NOW))
            users = Table("users", MetaData(), autoload_with=connection)
            connection.execute(users.insert().values(user_id="existing-store-user", username="existing-store-user", display_name="Existing Store",
                role="store", store_scope_mode="none", status="active", is_initialized=True, password_hash="synthetic-test-hash",
                auth_version=7, cli_subject="synthetic-stable-subject", auth_generation=3, created_at=NOW, updated_at=NOW))
        command.upgrade(config, "20261119_0070")
        with scoped.connect() as connection:
            row = connection.execute(text("SELECT routing_mode,routing_product_id FROM clue_master_leads WHERE lead_key='legacy-unassigned'")).one()
            assert tuple(row) == (None, None)
            assert connection.execute(text("SELECT COUNT(*) FROM clue_product_routing_configs")).scalar_one() == 0
            assert connection.execute(text("SELECT COUNT(*) FROM clue_shared_rule_maintainers")).scalar_one() == 0
            existing_user = connection.execute(text("SELECT role,store_scope_mode,password_hash,auth_version,auth_generation FROM users WHERE user_id='existing-store-user'")).one()
            assert tuple(existing_user) == ("store", "none", "synthetic-test-hash", 7, 3)
            column = next(value for value in inspect(connection).get_columns("clue_assignment_rounds") if value["name"] == "appointment_at")
            assert column["type"].timezone is True
        command.downgrade(config, "20261118_0069")
        command.upgrade(config, "20261119_0070")
        with Session(scoped) as session:
            session.add(ClueSharedRuleMaintainer(user_id="existing-store-user", granted_by="synthetic-admin"))
            session.commit()
        with pytest.raises(RuntimeError, match="Product routing history exists"):
            command.downgrade(config, "20261118_0069")
        with scoped.begin() as connection:
            configs = Table("clue_product_routing_configs", MetaData(), autoload_with=connection)
            connection.execute(configs.insert().values(product_id="legacy-manual", routing_enabled=True,
                active_list_version_id="legacy-list", created_at=NOW, updated_at=NOW))
        command.upgrade(config, "head")
        with Session(scoped) as session:
            legacy = session.get(ClueProductRoutingConfig, "legacy-manual")
            assert (legacy.store_list_source, legacy.active_list_version_id, legacy.routing_enabled) == ("manual", "legacy-list", True)
            session.add(ClueProductRoutingConfig(product_id="new-default"))
            session.commit()
            assert session.get(ClueProductRoutingConfig, "new-default").routing_enabled is False
            legacy.store_list_source = "douyin"
            session.commit()
        with pytest.raises(RuntimeError, match="Restore automatic product store lists"):
            command.downgrade(config, "20261120_0073")
        with Session(scoped) as session:
            session.get(ClueProductRoutingConfig, "legacy-manual").store_list_source = "manual"
            session.commit()
        with pytest.raises(RuntimeError, match="Product routing history exists"):
            command.downgrade(config, "20261118_0069")
        scoped.dispose()
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()
