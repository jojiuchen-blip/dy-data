from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from apps.api.dy_api.clue_product_routing import batch_product_changes, load_product_store_ids
from apps.api.dy_api.db import make_session_factory
from apps.api.dy_api.models import (
    ClueProductRoutingConfig, ClueProductStoreListVersion, DimSkuProductRule,
    DimStore, DimStorePoiMapping, JobRun,
)
from apps.worker.clue_routing_store_sync import read_product_store_pois, run_daily_routing_store_sync


PRODUCT = "1234567890123456789"
POI = "9007199254740993"
MANUAL_POI = "9007199254740992"
DAY = datetime(2026, 11, 23, 6, tzinfo=timezone.utc)
ADMIN = SimpleNamespace(username="admin", auth_type="env_admin", can_manage_global_settings=True)


def _page(*rows, more=False, cursor=None):
    return {"data": {"error_code": 0, "products": list(rows), "has_more": more, "next_cursor": cursor}}


def _product(product_id=PRODUCT, pois=(POI,)):
    return {"product": {"product_id": product_id, "pois": [{"poi_id": poi} for poi in pois]}}


def _change(session, action, *, actor=ADMIN, **values):
    result = batch_product_changes(session, actor, {"action": action, "product_ids": [PRODUCT],
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
