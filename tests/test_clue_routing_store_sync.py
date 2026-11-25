from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from apps.api.dy_api.clue_product_routing import batch_product_changes, list_products, load_product_store_ids
from apps.api.dy_api.db import make_session_factory
from apps.api.dy_api.models import (
    ClueProductDouyinStoreScope, ClueProductRoutingConfig, ClueProductStoreListVersion, DimSkuProductRule,
    DimStore, DimStorePoiMapping, JobRun,
)
from apps.worker.clue_routing_store_sync import read_product_store_pois, run_daily_routing_store_sync


PRODUCT = "1234567890123456789"
BYD_PRODUCT = "2234567890123456789"
POI = "9007199254740993"
MANUAL_POI = "9007199254740992"
DAY = datetime(2026, 11, 23, 6, tzinfo=timezone.utc)
ADMIN = SimpleNamespace(username="admin", auth_type="env_admin", can_manage_global_settings=True)


def _page(*rows, more=False, cursor=None):
    return {"data": {"error_code": 0, "products": list(rows), "has_more": more, "next_cursor": cursor}}


def _product(product_id=PRODUCT, pois=(POI,)):
    return {"product": {"product_id": product_id, "pois": [{"poi_id": poi} for poi in pois]}}


def _change(session, action, *, actor=ADMIN, product_id=PRODUCT, **values):
    result = batch_product_changes(session, actor, {"action": action, "product_ids": [product_id],
                                                    "preview": False, **values})
    session.commit()
    return result["results"][0]


def _seed(session):
    session.add_all([
        DimSkuProductRule(sku_id="sku", product_id=PRODUCT, product_scope="精诚养车"),
        DimStore(store_id="001", store_name="甲店"),
        DimStore(store_id="002", store_name="乙店"),
    ])
    session.flush()
    session.add_all([DimStorePoiMapping(store_id="002", poi_id=POI), DimStorePoiMapping(store_id="001", poi_id=MANUAL_POI)])
    session.commit()


def test_read_all_product_pages_keeps_int64_poi_exact():
    calls = []

    def fetch(cursor):
        calls.append(cursor)
        return _page(_product("1234"), more=True, cursor="next") if cursor is None else _page(_product(pois=(int(POI),)))

    assert read_product_store_pois(fetch, {PRODUCT}) == {PRODUCT: {POI}}
    assert calls == [None, "next"]


@pytest.mark.parametrize("payload", [
    _page(_product(), more=True, cursor="repeat"),
    {"data": {"error_code": 2119005, "products": [], "has_more": False}},
    {"data": {"products": [_product()], "has_more": "false"}},
    {**_page(_product()), "extra": {"error_code": 2190004}},
    {**_page(_product()), "BaseResp": {"StatusCode": 2190004}},
])
def test_incomplete_response_is_rejected(payload):
    with pytest.raises(ValueError):
        read_product_store_pois(lambda _: payload, {PRODUCT})


def test_pending_allows_manual_then_daily_refresh_and_admin_restores_manual(db_session):
    _seed(db_session)
    db_session_factory = make_session_factory(db_session.get_bind())
    original = _change(db_session, "publish_list", store_ids=["001"])["after"]["list_version"]
    assert _change(db_session, "request_auto_list")["after"]["store_list_source"] == "auto_pending"
    assert _change(db_session, "publish_list", store_ids=["001"])["status"] == "success"
    _change(db_session, "enable", authorization_note="approved", expected_list_versions={PRODUCT: original})

    fetch = lambda _: _page(_product(pois=(MANUAL_POI,)))
    job_id = run_daily_routing_store_sync(db_session_factory, now=DAY, fetch_page=fetch)
    db_session.expire_all()
    assert db_session.get(JobRun, job_id).status == "success"
    assert load_product_store_ids(db_session, PRODUCT) == {"001"}
    assert _change(db_session, "publish_list", store_ids=["001"])["error"]["code"] == "AUTO_STORE_LIST_ACTIVE"
    assert run_daily_routing_store_sync(db_session_factory, now=DAY, fetch_page=fetch) is None
    assert db_session.scalar(select(func.count()).select_from(ClueProductStoreListVersion)) == 2

    run_daily_routing_store_sync(db_session_factory, now=DAY + timedelta(days=1), fetch_page=lambda _: _page(_product()))
    db_session.expire_all()
    assert load_product_store_ids(db_session, PRODUCT) == {"002"}
    failed_day = run_daily_routing_store_sync(db_session_factory, now=DAY + timedelta(days=2),
                                             fetch_page=lambda _: _page(_product(pois=())))
    db_session.expire_all()
    assert db_session.get(JobRun, failed_day).status == "failed"
    assert load_product_store_ids(db_session, PRODUCT) == {"002"}

    restored = _change(db_session, "restore_manual_list")
    assert restored["after"]["list_version"] == original
    assert restored["after"]["store_ids"] == ["001"]
    assert restored["after"]["routing_enabled"] is True
    assert load_product_store_ids(db_session, PRODUCT) == {"001"}
    assert _change(db_session, "publish_list", store_ids=["002"])["status"] == "success"


@pytest.mark.parametrize("row", [_product(pois=()), _product(pois=("9007199254740994",)), {"product": {"product_id": PRODUCT}}, _product()])
def test_bad_store_scope_keeps_the_manual_version(db_session, row):
    _seed(db_session)
    db_session_factory = make_session_factory(db_session.get_bind())
    original = _change(db_session, "publish_list", store_ids=["001"])["after"]["list_version"]
    _change(db_session, "request_auto_list")
    job_id = run_daily_routing_store_sync(db_session_factory, now=DAY, fetch_page=lambda _: _page(row))
    db_session.expire_all()
    assert db_session.get(JobRun, job_id).status == "failed"
    config = db_session.get(ClueProductRoutingConfig, PRODUCT)
    assert config.active_list_version_id == original
    assert config.store_list_source == "auto_pending"


def test_closed_store_is_excluded_before_first_scope_comparison(db_session):
    _seed(db_session)
    db_session.get(DimStore, "002").location_status = "closed"
    db_session.commit()
    factory = make_session_factory(db_session.get_bind())
    _change(db_session, "publish_list", store_ids=["001"])
    _change(db_session, "request_auto_list")
    run = run_daily_routing_store_sync(factory, now=DAY, fetch_page=lambda _: _page(_product(pois=(MANUAL_POI, POI))))
    db_session.expire_all()
    assert db_session.get(JobRun, run).status == "success"
    assert load_product_store_ids(db_session, PRODUCT) == {"001"}


def test_in_flight_pull_cannot_override_manual_revert_or_reenrollment(db_session):
    _seed(db_session)
    factory = make_session_factory(db_session.get_bind())
    original = _change(db_session, "publish_list", store_ids=["001"])["after"]["list_version"]
    _change(db_session, "request_auto_list")

    def fetch(_):
        _change(db_session, "restore_manual_list")
        _change(db_session, "request_auto_list")
        return _page(_product())

    run = run_daily_routing_store_sync(factory, now=DAY, fetch_page=fetch)
    db_session.expire_all()
    assert db_session.get(JobRun, run).metadata_json["outcomes"]["source_changed"] == 1
    assert db_session.get(ClueProductRoutingConfig, PRODUCT).active_list_version_id == original


def test_delayed_snapshot_cannot_replace_newer_day(db_session):
    _seed(db_session)
    factory = make_session_factory(db_session.get_bind())
    _change(db_session, "publish_list", store_ids=["001"])
    _change(db_session, "request_auto_list")
    run_daily_routing_store_sync(factory, now=DAY, fetch_page=lambda _: _page(_product(pois=(MANUAL_POI,))))

    def fetch_delayed(_):
        run_daily_routing_store_sync(factory, now=DAY + timedelta(days=2), fetch_page=lambda _: _page(_product()))
        return _page(_product(pois=(MANUAL_POI,)))

    delayed_run = run_daily_routing_store_sync(factory, now=DAY + timedelta(days=1), fetch_page=fetch_delayed)
    db_session.expire_all()
    assert db_session.get(JobRun, delayed_run).metadata_json["outcomes"]["stale_run"] == 1
    assert load_product_store_ids(db_session, PRODUCT) == {"002"}


def test_catalogue_discovers_both_scopes_without_enrolment_and_preserves_last_valid_list(db_session):
    _seed(db_session)
    factory = make_session_factory(db_session.get_bind())
    run = run_daily_routing_store_sync(factory, now=DAY, fetch_page=lambda _: _page(_product(), _product(BYD_PRODUCT)))
    db_session.expire_all()
    assert db_session.get(JobRun, run).success_count == 2
    rows = {row["product_id"]: row for row in list_products(db_session, ADMIN)["rows"]}
    assert rows[PRODUCT]["product_scope"] == "jingcheng"
    assert rows[BYD_PRODUCT]["product_scope"] == "byd"
    assert rows[BYD_PRODUCT]["douyin_store_scope"]["store_count"] == 1
    assert rows[BYD_PRODUCT]["routing_enabled"] is False
    assert rows[BYD_PRODUCT]["store_ids"] == []
    assert db_session.get(ClueProductDouyinStoreScope, BYD_PRODUCT).store_ids == ["002"]

    run_daily_routing_store_sync(factory, now=DAY + timedelta(days=1),
        fetch_page=lambda _: _page(_product(BYD_PRODUCT, pois=("9007199254740994",))))
    db_session.expire_all()
    snapshot = db_session.get(ClueProductDouyinStoreScope, BYD_PRODUCT)
    assert snapshot.status == "poi_mapping_incomplete"
    assert snapshot.store_ids == ["002"]
    assert snapshot.last_success_at.date() == DAY.date()
    assert db_session.get(ClueProductDouyinStoreScope, PRODUCT).status == "missing_product"

    run_daily_routing_store_sync(factory, now=DAY + timedelta(days=2),
        fetch_page=lambda _: _page(_product(BYD_PRODUCT, pois=(MANUAL_POI,)), more=True, cursor="stuck"))
    db_session.expire_all()
    snapshot = db_session.get(ClueProductDouyinStoreScope, BYD_PRODUCT)
    assert snapshot.status == "source_error"
    assert snapshot.store_ids == ["002"]


def test_byd_auto_source_can_publish_first_list_without_enabling_routing(db_session):
    _seed(db_session)
    factory = make_session_factory(db_session.get_bind())
    fetch = lambda _: _page(_product(), _product(BYD_PRODUCT))
    run_daily_routing_store_sync(factory, now=DAY, fetch_page=fetch)
    db_session.expire_all()
    pending = _change(db_session, "request_auto_list", product_id=BYD_PRODUCT)
    assert pending["status"] == "success"
    run_daily_routing_store_sync(factory, now=DAY + timedelta(days=1), fetch_page=fetch)
    db_session.expire_all()
    config = db_session.get(ClueProductRoutingConfig, BYD_PRODUCT)
    assert config.store_list_source == "douyin"
    assert config.routing_enabled is False
    assert load_product_store_ids(db_session, BYD_PRODUCT) == {"002"}

    restored = _change(db_session, "restore_manual_list", product_id=BYD_PRODUCT)
    assert restored["after"]["store_list_source"] == "manual"
    assert restored["after"]["store_ids"] == ["002"]
    upload = _change(db_session, "publish_list", product_id=BYD_PRODUCT, store_ids=["001"])
    assert upload["status"] == "success"
    run_daily_routing_store_sync(factory, now=DAY + timedelta(days=2), fetch_page=fetch)
    db_session.expire_all()
    config = db_session.get(ClueProductRoutingConfig, BYD_PRODUCT)
    assert config.manual_list_version_id == upload["after"]["list_version"]
    assert config.store_list_source == "manual"
    assert load_product_store_ids(db_session, BYD_PRODUCT) == {"001"}
    assert db_session.get(ClueProductDouyinStoreScope, BYD_PRODUCT).store_ids == ["002"]


def test_admin_can_adopt_previewed_catalogue_scope_and_must_review_a_changed_snapshot(db_session):
    _seed(db_session)
    factory = make_session_factory(db_session.get_bind())
    run_daily_routing_store_sync(factory, now=DAY, fetch_page=lambda _: _page(_product(BYD_PRODUCT)))
    db_session.expire_all()
    payload = {"action": "request_auto_list", "product_ids": [BYD_PRODUCT], "preview": True}
    preview = batch_product_changes(db_session, ADMIN, payload)["results"][0]["after"]
    assert preview["store_list_source"] == "douyin"
    assert preview["store_ids"] == ["002"]
    expected = {BYD_PRODUCT: preview["douyin_store_scope"]["checked_at"]}

    run_daily_routing_store_sync(factory, now=DAY + timedelta(days=1),
                                 fetch_page=lambda _: _page(_product(BYD_PRODUCT, pois=(MANUAL_POI,))))
    db_session.expire_all()
    result = _change(db_session, "request_auto_list", product_id=BYD_PRODUCT, expected_douyin_scope_checks=expected)
    assert result["error"]["code"] == "DOUYIN_SCOPE_CHANGED"
    assert not load_product_store_ids(db_session, BYD_PRODUCT)

    updated = batch_product_changes(db_session, ADMIN, payload)["results"][0]["after"]
    expected = {BYD_PRODUCT: updated["douyin_store_scope"]["checked_at"]}
    result = _change(db_session, "request_auto_list", product_id=BYD_PRODUCT, expected_douyin_scope_checks=expected)
    assert result["after"]["store_list_source"] == "douyin"
    assert result["after"]["routing_enabled"] is False
    assert load_product_store_ids(db_session, BYD_PRODUCT) == {"001"}


def test_daily_worker_skips_unconfigured_connection_without_creating_a_failure(db_session, monkeypatch, tmp_path):
    settings = tmp_path / "config.json"
    settings.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DY_DATA_CONFIG", str(settings))
    monkeypatch.setenv("DOUYIN_ROUTING_STORE_SYNC_ENABLED", "true")
    for name in ("DOUYIN_APP_ID", "DOUYIN_APP_SECRET", "DOUYIN_ACCOUNT_ID"):
        monkeypatch.delenv(name, raising=False)
    factory = make_session_factory(db_session.get_bind())

    assert run_daily_routing_store_sync(factory, now=DAY) is None
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0


def test_daily_worker_scans_every_status_with_full_pois(db_session, monkeypatch):
    _seed(db_session)
    factory = make_session_factory(db_session.get_bind())
    requests = []

    def query_online_products(**kwargs):
        requests.append(kwargs)
        status, cursor = kwargs["status"], kwargs["cursor"]
        if status == 1:
            return _page(_product(), more=True, cursor="online-next") if cursor is None else _page(_product(BYD_PRODUCT))
        if status == 2:
            return _page(_product("3234567890123456789", pois=(MANUAL_POI,)))
        return _page()

    monkeypatch.setattr("apps.worker.pipeline.build_douyin_client_from_env",
                        lambda: SimpleNamespace(query_online_products=query_online_products))
    monkeypatch.setenv("DOUYIN_ROUTING_STORE_SYNC_ENABLED", "true")
    for name in ("DOUYIN_APP_ID", "DOUYIN_APP_SECRET", "DOUYIN_ACCOUNT_ID"):
        monkeypatch.setenv(name, "configured-for-test")
    run = run_daily_routing_store_sync(factory, now=DAY)
    db_session.expire_all()
    assert [(row["status"], row["cursor"]) for row in requests] == [(1, None), (1, "online-next"), (2, None), (3, None)]
    assert all(row["query_all_poi"] is True and row["count"] == 20 and row["goods_query_type"] == 2 for row in requests)
    assert db_session.get(JobRun, run).metadata_json["catalogue_outcomes"] == {"valid": 3}
