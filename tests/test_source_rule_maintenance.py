from scripts.switch_source_store_rules import replacement_payload, publish_replacements, switch
from tests.test_clue_allocation_engine import _publish_global_rule
from tests.test_clue_allocation_engine import _store
from apps.api.dy_api.models import DimStorePoiMapping
from scripts.repair_laike_store_availability import prepare


def test_source_rollout_and_configuration_restore_keep_old_versions(db_session):
    _, original = _publish_global_rule(db_session)
    before = switch(db_session)
    new = publish_replacements(db_session, before, source_mode=True)
    assert original.status == "retired"
    assert new[0]["snapshot"]["strategy_configs"][1]["params"]["selection_mode"] == "douyin_source_store"
    restored = publish_replacements(db_session, before, source_mode=False)
    assert replacement_payload(restored[0]["snapshot"], source_mode=False) == replacement_payload(before[0]["snapshot"], source_mode=False)


def test_roster_repair_previews_disabled_store_and_reports_unmapped_without_mutating(db_session):
    store = _store("account-id", candidate=False)
    db_session.add_all([store, DimStorePoiMapping(poi_id="poi-id", store_id="account-id")])
    db_session.flush()
    row = {"所属账户关联poi_ID": "poi-id", "经度": 120, "纬度": 30, "省份": "浙江", "城市": "杭州市", "门店名称": "test"}
    changes, issues = prepare(db_session, [row, {**row, "所属账户关联poi_ID": "unknown"}])
    assert len(changes) == 1
    assert changes[0][0].store_id == "account-id"
    assert changes[0][1]["participates_in_clue_allocation"] is True
    assert issues[0]["reason"] == "poi_unmapped_or_store_missing"
    assert store.participates_in_clue_allocation is False
