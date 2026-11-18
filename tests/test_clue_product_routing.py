from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from apps.api.dy_api.clue_product_routing import (
    ProductRoutingError, batch_product_changes, bind_product_routing, get_shared_rule,
    has_published_product_store_list, list_products, load_product_store_ids,
    publish_shared_rule, replace_product_grants,
)
from apps.api.dy_api.models import (
    ClueAllocationAuditLog, ClueAllocationRuleVersion, ClueLeadRuleVersionBinding,
    ClueMasterLead, ClueProductRoutingConfig, ClueProductStoreListVersion,
    DimSkuProductRule, DimStore, User,
)


NOW = datetime(2026, 11, 18, 8, tzinfo=timezone.utc)
ADMIN = SimpleNamespace(user_id=None, username="business-admin", role="admin", auth_type="env_admin",
                        can_manage_global_settings=True, store_scope_mode="all")


def _seed(session):
    session.add_all([
        DimSkuProductRule(sku_id="sku-jc", product_id="p-jc", product_name="精诚套餐", product_scope="精诚养车"),
        DimSkuProductRule(sku_id="sku-byd", product_id="p-byd", product_name="本品套餐", product_scope="本品"),
        DimStore(store_id="001", store_name="One"), DimStore(store_id="002", store_name="Two"),
    ])
    session.commit()


def _batch(session, action, ids=("p-jc",), **extra):
    return batch_product_changes(session, ADMIN, {"product_ids": list(ids), "action": action, "preview": False, **extra})


def _lead(key):
    return ClueMasterLead(lead_key=key, source_clue_row_key=key, source_identity_key=key,
                          anchor_store_id="001", anchor_city_code="city", anchor_longitude=120, anchor_latitude=30)


def test_new_byd_direct_binding_needs_neither_a_rule_nor_a_list(db_session):
    lead = _lead("new-byd")
    db_session.add(lead)
    assert bind_product_routing(db_session, lead, "unlisted-byd", NOW) is None
    db_session.commit()
    assert lead.routing_mode == "direct"
    assert lead.routing_product_id == "unlisted-byd"
    assert not has_published_product_store_list(db_session, "unlisted-byd")
    assert db_session.scalar(select(func.count()).select_from(ClueAllocationRuleVersion)) == 0
    assert bind_product_routing(db_session, lead, "different-product", NOW) is None
    assert lead.routing_product_id == "unlisted-byd"


def test_first_ingress_freezes_rule_while_next_selection_reads_latest_list(db_session):
    _seed(db_session)
    assert _batch(db_session, "publish_list", store_ids=["001"])["succeeded"] == 1
    assert not db_session.get(ClueProductRoutingConfig, "p-jc").routing_enabled
    assert _batch(db_session, "enable")["results"][0]["error"]["code"] == "AUTHORIZATION_REQUIRED"
    assert _batch(db_session, "enable", authorization_note="负责人已确认有效名单并授权开启")["succeeded"] == 1
    lead = _lead("new-jc")
    db_session.add(lead)
    binding = bind_product_routing(db_session, lead, "p-jc", NOW)
    frozen_version = binding.rule_version_id
    frozen_snapshot = dict(binding.rule_version_snapshot)
    assert lead.routing_mode == "flow"
    assert frozen_snapshot["follow_up_policy"]["appointment_hours"] == 72
    assert frozen_snapshot["product_scope"] == "jingcheng"
    assert [row["params"].get("max_distance_km") for row in frozen_snapshot["strategy_configs"][:2]] == [10, 10]
    assert _batch(db_session, "publish_rule", rules={"first_follow_up_sla_hours": 48})["succeeded"] == 1
    assert _batch(db_session, "disable")["succeeded"] == 1
    assert _batch(db_session, "publish_list", store_ids=["002"])["succeeded"] == 1
    assert load_product_store_ids(db_session, "p-jc") == {"002"}
    assert bind_product_routing(db_session, lead, "p-jc", NOW).rule_version_id == frozen_version
    assert binding.rule_version_snapshot == frozen_snapshot
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(ClueLeadRuleVersionBinding, lead.lead_key).rule_version_id == frozen_version


def test_failed_product_keeps_previous_list_and_successful_peer_publishes(db_session):
    _seed(db_session)
    _batch(db_session, "publish_list", store_ids=["001"])
    old = db_session.get(ClueProductRoutingConfig, "p-jc").active_list_version_id
    result = _batch(db_session, "publish_list", ids=("p-jc", "p-byd"), lists=[
        {"product_id": "p-jc", "store_ids": ["unknown"]},
        {"product_id": "p-byd", "store_ids": ["002"]},
    ])
    assert result["succeeded"] == result["failed"] == 1
    assert db_session.get(ClueProductRoutingConfig, "p-jc").active_list_version_id == old
    assert load_product_store_ids(db_session, "p-jc") == {"001"}
    assert load_product_store_ids(db_session, "p-byd") == {"002"}


def test_cross_page_scope_and_grants_do_not_grant_delegation(db_session):
    _seed(db_session)
    user = User(user_id="manager", username="manager", display_name="Manager", role="store", status="active", is_initialized=True)
    db_session.add(user)
    db_session.commit()
    replace_product_grants(db_session, ADMIN, "p-jc", [user.user_id])
    manager = SimpleNamespace(user_id="manager", username="manager", auth_type="user", role="store", store_scope_mode="none")
    listing = list_products(db_session, manager, page_size=1)
    assert listing["total"] == 1
    assert listing["rows"][0]["product_id"] == "p-jc"
    assert not listing["can_manage_grants"]
    changed = batch_product_changes(db_session, manager, {
        "all_matching": True, "filters": {"q": "套餐", "product_scope": "all"},
        "action": "publish_list", "store_ids": ["001"], "preview": False,
    })
    assert changed["total"] == changed["succeeded"] == 1
    assert db_session.get(ClueProductRoutingConfig, "p-byd") is None
    unauthorized = batch_product_changes(db_session, manager, {"product_ids": ["p-byd"], "action": "disable", "preview": False})
    assert unauthorized["results"][0]["error"]["code"] == "PRODUCT_FORBIDDEN"
    assert unauthorized["results"][0]["before"] == {}
    with pytest.raises(ProductRoutingError, match="仅全部门店范围管理员"):
        replace_product_grants(db_session, manager, "p-jc", ["manager"])


def test_preview_is_read_only_and_idempotency_replays_without_new_versions(db_session):
    _seed(db_session)
    payload = {"product_ids": ["p-jc"], "action": "publish_list", "store_ids": ["001"], "preview": True}
    assert batch_product_changes(db_session, ADMIN, payload)["results"][0]["status"] == "preview"
    assert db_session.get(ClueProductRoutingConfig, "p-jc") is None
    assert db_session.scalar(select(func.count()).select_from(ClueAllocationAuditLog)) == 0
    payload["preview"] = False
    first = batch_product_changes(db_session, ADMIN, payload, idempotency_key="apply-list-1")
    db_session.commit()
    second = batch_product_changes(db_session, ADMIN, payload, idempotency_key="apply-list-1")
    assert first == second
    assert db_session.scalar(select(func.count()).select_from(ClueProductStoreListVersion)) == 1
    assert db_session.scalar(select(func.count()).select_from(ClueAllocationAuditLog)) == 1
    with pytest.raises(ProductRoutingError, match="同一幂等标识"):
        batch_product_changes(db_session, ADMIN, {**payload, "store_ids": ["002"]}, idempotency_key="apply-list-1")


def test_byd_uses_identified_shared_base_and_never_a_pilot_exception(db_session):
    _seed(db_session)
    publish_shared_rule(db_session, ADMIN, {"first_follow_up_sla_hours": 36}, preview=False)
    base_id = get_shared_rule(db_session, ADMIN)["rule_version_id"]
    _batch(db_session, "publish_rule", rules={"first_follow_up_sla_hours": 48})
    _batch(db_session, "publish_list", ids=("p-byd",), store_ids=["001"])
    enabled = _batch(db_session, "enable", ids=("p-byd",), authorization_note="本品负责人确认名单并正式授权")
    row = enabled["results"][0]["after"]
    assert row["first_follow_up_sla_hours"] == 36
    version = db_session.get(ClueAllocationRuleVersion, row["rule_version_id"])
    assert version.snapshot["base_rule_version_id"] == base_id
    publish_shared_rule(db_session, ADMIN, {"first_follow_up_sla_hours": 24}, preview=False)
    assert version.first_follow_up_sla_hours == 36
