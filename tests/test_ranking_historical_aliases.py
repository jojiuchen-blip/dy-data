from types import SimpleNamespace as Row
import pytest

from apps.api.dy_api.ranking_history import confirmed_order_aliases, historical_aliases, restore_missing_poi
from apps.api.dy_api.ranking_identity import OrderAttributionResult


def fixture():
    dim = Row(account_id="a", store_id="a", nickname="new", binding_status="认证成功", valid_from=None, valid_to=None)
    old = Row(binding_key="old-key", account_id="a", douyin_id="d", poi_id=None, binding_status="active",
        douyin_nickname="old", account_name="company", raw_payload={"scene_id":"a", "account_id":"a",
        "status":1, "account_type":20, "integration_content":{"user_info":{"aweme_id":"d"}}})
    new = Row(binding_key="new-key", account_id="a", douyin_id="d", poi_id="p", binding_status="认证成功",
        douyin_nickname="new", account_name="company", raw_payload={"账号类型":"子机构门店号"})
    return [dim], [old, new], [("p", "a")]


def simulate(data, observations, *, reason="missing_poi_mapping", sources=("raw_aweme_binding:old-key:name",)):
    aliases = confirmed_order_aliases(historical_aliases(*data), observations)
    before = OrderAttributionResult(None, reason, sources, False)
    order = Row(owner_account_id="encrypted", owner_account_name="old", owner_douyin_uid=None)
    return restore_missing_poi(before, aliases, order)


OBSERVED = [("encrypted", "old", None), ("encrypted", "new", None)]


def test_historical_owner_requires_independent_join_on_both_sides():
    result = simulate(fixture(), OBSERVED)
    assert (result.store_id, result.reason, result.historical_period_unverified) == (
        "a", "resolved_historical_store_account", True)


def test_stable_store_and_handle_pair_does_not_require_a_sale_under_the_new_name():
    data = fixture()
    data[0][0].nickname, data[0][0].binding_status = "another handle", "未知状态"
    assert simulate(data, [("encrypted", "old", None)]).store_id == "a"


def test_personal_unbind_is_not_a_store_account_unbind_for_the_same_poi():
    dims, rows, pois = fixture()
    rows.append(Row(**(vars(rows[1]) | {"binding_key":"personal", "binding_status":"已解绑",
        "raw_payload":{"账号类型":"个人号"}})))
    assert simulate((dims, rows, pois), OBSERVED).store_id == "a"
    rows[-1].raw_payload = {"账号类型":"子机构门店号"}
    assert simulate((dims, rows, pois), OBSERVED).store_id is None


@pytest.mark.parametrize("observations", [
    [("encrypted", "old", None), ("other", "old", None)],
    OBSERVED + [("encrypted", "third", None)], OBSERVED + [("encrypted","new","other-uid")],
])
def test_unlinked_order_owner_does_not_inherit_store(observations):
    assert simulate(fixture(), observations).store_id is None


@pytest.mark.parametrize("conflict", ["poi", "duplicate_store", "rebound", "old_name", "account",
    "user", "expired", "unbound", "scene", "regional"])
def test_conflicting_or_unproven_sources_stay_unresolved(conflict):
    dims, rows, pois = fixture()
    old, new = rows
    if conflict == "poi":
        rows.append(Row(**(vars(new) | {"poi_id":"other"})))
    elif conflict == "duplicate_store":
        pois.append(("p","other"))
    elif conflict == "rebound":
        rows.append(Row(**(vars(new) | {"account_id":"other"})))
    elif conflict == "old_name":
        rows.append(Row(**(vars(old) | {"account_id":"other","douyin_id":"other-id"})))
    elif conflict == "account":
        dims[0].store_id = "other"
    elif conflict == "user":
        old.raw_payload["integration_content"]["user_info"]["aweme_id"] = "other"
    elif conflict == "expired":
        old.raw_payload["bind_end_time"] = 1
    elif conflict == "unbound":
        rows.append(Row(**(vars(new) | {"binding_status":"已解绑"})))
    elif conflict == "scene":
        old.raw_payload["scene_id"] = "other"
    else:
        new.raw_payload["账号类型"] = "子机构区域号"
    assert simulate((dims, rows, pois), OBSERVED).store_id is None


def test_never_overrides_an_explicit_id_candidate_or_conflict():
    assert simulate(fixture(), OBSERVED, sources=("raw_aweme_binding:old-key:owner_account_id",)).store_id is None
    assert simulate(fixture(), OBSERVED, reason="conflicting_name_binding").store_id is None
