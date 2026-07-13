from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    Base,
    ClueAllocationRule,
    ClueAllocationRuleVersion,
    ClueLeadRuleVersionBinding,
    DimStore,
)
from apps.worker.clue_rule_versions import (
    RuleImmutableError,
    RuleValidationError,
    bind_lead_rule_version,
    create_rule,
    create_rule_version,
    create_store_group,
    delete_rule_version,
    publish_rule_version,
    resolve_published_rule_version,
    retire_rule_version,
    update_rule_version,
)


def _store(store_id: str, *, city_code: str) -> DimStore:
    return DimStore(
        store_id=store_id,
        store_name=store_id,
        is_active=True,
        standard_province=city_code,
        standard_city=city_code,
        city_code=city_code,
        longitude=Decimal("121.470000"),
        latitude=Decimal("31.230000"),
        is_douyin_clue_applicable=True,
        participates_in_clue_allocation=True,
        location_status="valid",
    )


def _strategy_configs() -> list[dict]:
    return [
        {
            "strategy_type": "sales_store_priority",
            "enabled": True,
            "execution_order": 1,
            "params": {"max_distance_km": 10},
        },
        {
            "strategy_type": "nearby_city_optimization",
            "enabled": True,
            "execution_order": 2,
            "params": {"max_distance_km": 15},
        },
        {
            "strategy_type": "city_fallback",
            "enabled": True,
            "execution_order": 3,
            "params": {},
        },
    ]


def _draft(session: Session, rule: ClueAllocationRule, **overrides) -> ClueAllocationRuleVersion:
    values = {
        "auto_expiry_enabled": True,
        "first_follow_up_sla_hours": 24,
        "protection_days": 7,
        "conversion_weight": Decimal("0.7"),
        "follow_24h_weight": Decimal("0.3"),
        "lookback_days": 30,
        "min_samples": 20,
        "strategy_configs": _strategy_configs(),
        "created_by": "system-admin",
    }
    values.update(overrides)
    return create_rule_version(session, rule.rule_id, **values)


def _published(session: Session, rule: ClueAllocationRule, **overrides) -> ClueAllocationRuleVersion:
    version = _draft(session, rule, **overrides)
    return publish_rule_version(session, version.rule_version_id, published_by="system-admin")


def test_rule_version_schema_keeps_bindings_independent_from_legacy_orders() -> None:
    tables = Base.metadata.tables

    assert {
        "clue_allocation_rules",
        "clue_allocation_rule_versions",
        "clue_allocation_strategy_configs",
        "clue_store_groups",
        "clue_store_group_members",
        "clue_lead_rule_version_bindings",
    }.issubset(tables)
    binding_columns = tables["clue_lead_rule_version_bindings"].columns
    assert "lead_key" in binding_columns
    assert "scope_resolution_snapshot" in binding_columns
    assert "rule_version_snapshot" in binding_columns
    assert "order_id" not in binding_columns
    assert "uq_clue_allocation_rule_versions_published" in {
        index.name for index in tables["clue_allocation_rule_versions"].indexes
    }


def test_scope_resolution_prefers_anchor_store_group_city_then_global(db_session: Session) -> None:
    db_session.add(_store("anchor-store", city_code="CN-SH"))
    db_session.commit()

    global_rule = create_rule(db_session, name="Global", scope_type="global", created_by="system-admin")
    global_version = _published(db_session, global_rule)

    city_rule = create_rule(
        db_session,
        name="Shanghai",
        scope_type="city",
        city_code="CN-SH",
        created_by="system-admin",
    )
    city_version = _published(db_session, city_rule)

    group = create_store_group(
        db_session,
        name="Shanghai group",
        member_store_ids=["anchor-store"],
        created_by="system-admin",
    )
    group_rule = create_rule(
        db_session,
        name="Group",
        scope_type="store_group",
        store_group_id=group.store_group_id,
        created_by="system-admin",
    )
    group_version = _published(db_session, group_rule)

    anchor_rule = create_rule(
        db_session,
        name="Anchor",
        scope_type="anchor_store",
        anchor_store_id="anchor-store",
        created_by="system-admin",
    )
    anchor_version = _published(db_session, anchor_rule)

    assert resolve_published_rule_version(
        db_session,
        anchor_store_id="anchor-store",
        anchor_city_code="CN-SH",
    ).rule_version.rule_version_id == anchor_version.rule_version_id

    retire_rule_version(db_session, anchor_version.rule_version_id, retired_by="system-admin")
    assert resolve_published_rule_version(
        db_session,
        anchor_store_id="anchor-store",
        anchor_city_code="CN-SH",
    ).rule_version.rule_version_id == group_version.rule_version_id

    retire_rule_version(db_session, group_version.rule_version_id, retired_by="system-admin")
    assert resolve_published_rule_version(
        db_session,
        anchor_store_id="anchor-store",
        anchor_city_code="CN-SH",
    ).rule_version.rule_version_id == city_version.rule_version_id

    retire_rule_version(db_session, city_version.rule_version_id, retired_by="system-admin")
    assert resolve_published_rule_version(
        db_session,
        anchor_store_id="anchor-store",
        anchor_city_code="CN-SH",
    ).rule_version.rule_version_id == global_version.rule_version_id


def test_first_rule_binding_is_persisted_and_never_overwritten(db_session: Session) -> None:
    db_session.add(_store("anchor-store", city_code="CN-SH"))
    db_session.commit()

    global_rule = create_rule(db_session, name="Global", scope_type="global", created_by="system-admin")
    global_version = _published(db_session, global_rule)

    first_binding = bind_lead_rule_version(
        db_session,
        lead_key="lead-1",
        anchor_store_id="anchor-store",
        anchor_city_code="CN-SH",
    )
    assert first_binding.rule_version_id == global_version.rule_version_id
    assert first_binding.scope_resolution_snapshot["matched_scope"] == "global"

    anchor_rule = create_rule(
        db_session,
        name="Anchor",
        scope_type="anchor_store",
        anchor_store_id="anchor-store",
        created_by="system-admin",
    )
    anchor_version = _published(db_session, anchor_rule)

    repeated_binding = bind_lead_rule_version(
        db_session,
        lead_key="lead-1",
        anchor_store_id="anchor-store",
        anchor_city_code="CN-SH",
    )
    new_binding = bind_lead_rule_version(
        db_session,
        lead_key="lead-2",
        anchor_store_id="anchor-store",
        anchor_city_code="CN-SH",
    )
    db_session.flush()

    assert repeated_binding.rule_version_id == global_version.rule_version_id
    assert new_binding.rule_version_id == anchor_version.rule_version_id
    assert db_session.scalar(select(func.count()).select_from(ClueLeadRuleVersionBinding)) == 2


def test_publish_requires_global_default_for_non_global_rules(db_session: Session) -> None:
    rule = create_rule(
        db_session,
        name="Shanghai",
        scope_type="city",
        city_code="CN-SH",
        created_by="system-admin",
    )
    version = _draft(db_session, rule)

    with pytest.raises(RuleValidationError, match="global default"):
        publish_rule_version(db_session, version.rule_version_id, published_by="system-admin")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"auto_expiry_enabled": None}, "explicit"),
        ({"first_follow_up_sla_hours": 0}, "sla"),
        ({"protection_days": 0}, "protection"),
        ({"conversion_weight": Decimal("0.8"), "follow_24h_weight": Decimal("0.3")}, "weights"),
        ({"lookback_days": 0}, "lookback"),
        ({"min_samples": 0}, "min_samples"),
        ({"strategy_configs": _strategy_configs()[:2]}, "fixed strategy"),
        (
            {
                "strategy_configs": [
                    {
                        "strategy_type": "sales_store_priority",
                        "enabled": True,
                        "execution_order": 1,
                        "params": {"max_distance_km": 10},
                    },
                    {
                        "strategy_type": "sales_store_priority",
                        "enabled": True,
                        "execution_order": 2,
                        "params": {"max_distance_km": 10},
                    },
                    {
                        "strategy_type": "city_fallback",
                        "enabled": True,
                        "execution_order": 3,
                        "params": {},
                    },
                ]
            },
            "fixed strategy",
        ),
        (
            {
                "strategy_configs": [
                    {
                        "strategy_type": "sales_store_priority",
                        "enabled": True,
                        "execution_order": 1,
                        "params": {"max_distance_km": 10},
                    },
                    {
                        "strategy_type": "nearby_city_optimization",
                        "enabled": True,
                        "execution_order": 1,
                        "params": {"max_distance_km": 15},
                    },
                    {
                        "strategy_type": "city_fallback",
                        "enabled": True,
                        "execution_order": 3,
                        "params": {},
                    },
                ]
            },
            "execution_order",
        ),
        (
            {
                "strategy_configs": [
                    {
                        "strategy_type": "sales_store_priority",
                        "enabled": True,
                        "execution_order": 1,
                        "params": {"max_distance_km": 0},
                    },
                    {
                        "strategy_type": "nearby_city_optimization",
                        "enabled": True,
                        "execution_order": 2,
                        "params": {"max_distance_km": 15},
                    },
                    {
                        "strategy_type": "city_fallback",
                        "enabled": True,
                        "execution_order": 3,
                        "params": {},
                    },
                ]
            },
            "max_distance_km",
        ),
    ],
)
def test_publish_rejects_invalid_version_configuration(
    db_session: Session,
    overrides: dict,
    message: str,
) -> None:
    global_rule = create_rule(db_session, name="Global", scope_type="global", created_by="system-admin")
    _published(db_session, global_rule)
    city_rule = create_rule(
        db_session,
        name="Shanghai",
        scope_type="city",
        city_code="CN-SH",
        created_by="system-admin",
    )
    version = _draft(db_session, city_rule, **overrides)

    with pytest.raises(RuleValidationError, match=message):
        publish_rule_version(db_session, version.rule_version_id, published_by="system-admin")


def test_auto_expiry_disabled_does_not_require_an_sla(db_session: Session) -> None:
    global_rule = create_rule(db_session, name="Global", scope_type="global", created_by="system-admin")
    version = _draft(
        db_session,
        global_rule,
        auto_expiry_enabled=False,
        first_follow_up_sla_hours=None,
    )

    published = publish_rule_version(db_session, version.rule_version_id, published_by="system-admin")

    assert published.status == "published"


def test_rule_scope_normalizes_city_codes_and_store_groups_are_non_overlapping(db_session: Session) -> None:
    db_session.add(_store("anchor-store", city_code="上海"))
    db_session.add(_store("other-store", city_code="上海"))
    db_session.commit()

    global_rule = create_rule(db_session, name="Global", scope_type="global", created_by="system-admin")
    _published(db_session, global_rule)
    city_rule = create_rule(
        db_session,
        name="Shanghai",
        scope_type="city",
        city_code="上海市",
        created_by="system-admin",
    )
    city_version = _published(db_session, city_rule)

    match = resolve_published_rule_version(
        db_session,
        anchor_store_id="other-store",
        anchor_city_code="上海",
    )
    assert match is not None
    assert match.rule_version.rule_version_id == city_version.rule_version_id

    create_store_group(
        db_session,
        name="Primary group",
        member_store_ids=["anchor-store"],
        created_by="system-admin",
    )
    with pytest.raises(RuleValidationError, match="only one allocation store group"):
        create_store_group(
            db_session,
            name="Overlapping group",
            member_store_ids=["anchor-store"],
            created_by="system-admin",
        )


def test_current_global_default_cannot_be_retired_without_replacement(db_session: Session) -> None:
    global_rule = create_rule(db_session, name="Global", scope_type="global", created_by="system-admin")
    global_version = _published(db_session, global_rule)

    with pytest.raises(RuleImmutableError, match="global default"):
        retire_rule_version(db_session, global_version.rule_version_id, retired_by="system-admin")


def test_published_versions_are_immutable_and_replaced_by_new_drafts(db_session: Session) -> None:
    rule = create_rule(db_session, name="Global", scope_type="global", created_by="system-admin")
    first_version = _published(db_session, rule)

    with pytest.raises(RuleImmutableError, match="draft"):
        update_rule_version(db_session, first_version.rule_version_id, protection_days=14)
    with pytest.raises(RuleImmutableError, match="draft"):
        delete_rule_version(db_session, first_version.rule_version_id)

    second_version = _draft(db_session, rule, protection_days=14)
    published_second = publish_rule_version(db_session, second_version.rule_version_id, published_by="system-admin")
    db_session.flush()

    assert db_session.get(ClueAllocationRuleVersion, first_version.rule_version_id).status == "retired"
    assert published_second.status == "published"
    assert published_second.version_no == first_version.version_no + 1
