from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    ClueAllocationRule,
    ClueAllocationRuleVersion,
    ClueAllocationStrategyConfig,
    ClueLeadRuleVersionBinding,
    ClueStoreGroup,
    ClueStoreGroupMember,
    DimStore,
    utcnow,
)


SCOPE_TYPES = {"global", "city", "store_group", "anchor_store"}
STRATEGY_TYPES = {"sales_store_priority", "nearby_city_optimization", "city_fallback"}
DISTANCE_STRATEGY_TYPES = {"sales_store_priority", "nearby_city_optimization"}
MAX_SLA_HOURS = 168
MAX_PROTECTION_DAYS = 365
MAX_LOOKBACK_DAYS = 365
MAX_MIN_SAMPLES = 10_000
MAX_DISTANCE_KM = Decimal("1000")


class RuleVersionError(ValueError):
    pass


class RuleNotFoundError(RuleVersionError):
    pass


class RuleValidationError(RuleVersionError):
    pass


class RuleImmutableError(RuleVersionError):
    pass


class RuleResolutionError(RuleVersionError):
    pass


@dataclass(frozen=True)
class PublishedRuleMatch:
    rule: ClueAllocationRule
    rule_version: ClueAllocationRuleVersion


def create_store_group(
    session: Session,
    *,
    name: str,
    member_store_ids: Sequence[str] = (),
    created_by: str | None = None,
) -> ClueStoreGroup:
    group_name = _required_text(name, "name")
    if session.scalar(select(ClueStoreGroup.store_group_id).where(ClueStoreGroup.group_name == group_name)):
        raise RuleValidationError("store group name already exists")

    member_ids = _normalized_store_ids(member_store_ids)
    _validate_store_ids(session, member_ids)
    _validate_store_group_members_available(session, member_ids)
    group = ClueStoreGroup(
        store_group_id=_new_id("store-group"),
        group_name=group_name,
        created_by=created_by,
    )
    session.add(group)
    session.add_all(
        [
            ClueStoreGroupMember(store_group_id=group.store_group_id, store_id=store_id)
            for store_id in member_ids
        ]
    )
    session.flush()
    return group


def replace_store_group_members(
    session: Session,
    store_group_id: str,
    *,
    member_store_ids: Sequence[str],
) -> ClueStoreGroup:
    group = _get_store_group(session, store_group_id)
    member_ids = _normalized_store_ids(member_store_ids)
    _validate_store_ids(session, member_ids)
    _validate_store_group_members_available(
        session,
        member_ids,
        excluding_store_group_id=group.store_group_id,
    )
    session.execute(
        delete(ClueStoreGroupMember).where(ClueStoreGroupMember.store_group_id == group.store_group_id)
    )
    session.add_all(
        [
            ClueStoreGroupMember(store_group_id=group.store_group_id, store_id=store_id)
            for store_id in member_ids
        ]
    )
    group.updated_at = utcnow()
    session.flush()
    return group


def create_rule(
    session: Session,
    *,
    name: str,
    scope_type: str,
    city_code: str | None = None,
    store_group_id: str | None = None,
    anchor_store_id: str | None = None,
    created_by: str | None = None,
) -> ClueAllocationRule:
    session.flush()
    normalized_scope_type = _required_text(scope_type, "scope_type")
    scope = _normalize_scope(
        scope_type=normalized_scope_type,
        city_code=city_code,
        store_group_id=store_group_id,
        anchor_store_id=anchor_store_id,
    )
    if session.scalar(select(ClueAllocationRule.rule_id).where(ClueAllocationRule.scope_key == scope["scope_key"])):
        raise RuleValidationError("a logical rule already exists for this scope")
    if scope["scope_store_group_id"]:
        _get_store_group(session, scope["scope_store_group_id"])
    if scope["scope_anchor_store_id"] and session.get(DimStore, scope["scope_anchor_store_id"]) is None:
        raise RuleValidationError("anchor_store_id does not reference a known store")

    rule = ClueAllocationRule(
        rule_id=_new_id("rule"),
        rule_name=_required_text(name, "name"),
        created_by=created_by,
        **scope,
    )
    session.add(rule)
    session.flush()
    return rule


def create_rule_version(
    session: Session,
    rule_id: str,
    *,
    auto_expiry_enabled: bool | None,
    first_follow_up_sla_hours: int | None,
    protection_days: int | None,
    conversion_weight: Decimal | float | int | None,
    follow_24h_weight: Decimal | float | int | None,
    lookback_days: int | None,
    min_samples: int | None,
    strategy_configs: Sequence[Mapping[str, Any]],
    created_by: str | None = None,
) -> ClueAllocationRuleVersion:
    session.flush()
    rule = _get_rule(session, rule_id)
    current_max = session.scalar(
        select(func.max(ClueAllocationRuleVersion.version_no)).where(ClueAllocationRuleVersion.rule_id == rule.rule_id)
    )
    version = ClueAllocationRuleVersion(
        rule_version_id=_new_id("rule-version"),
        rule_id=rule.rule_id,
        version_no=int(current_max or 0) + 1,
        status="draft",
        auto_expiry_enabled=auto_expiry_enabled,
        first_follow_up_sla_hours=first_follow_up_sla_hours,
        protection_days=protection_days,
        conversion_weight=_as_decimal_or_none(conversion_weight, "conversion_weight"),
        follow_24h_weight=_as_decimal_or_none(follow_24h_weight, "follow_24h_weight"),
        lookback_days=lookback_days,
        min_samples=min_samples,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(version)
    _replace_strategy_configs(session, version.rule_version_id, strategy_configs)
    session.flush()
    return version


def update_rule_version(
    session: Session,
    rule_version_id: str,
    **changes: Any,
) -> ClueAllocationRuleVersion:
    version = _get_rule_version(session, rule_version_id)
    _require_draft(version)

    mutable_fields = {
        "auto_expiry_enabled",
        "first_follow_up_sla_hours",
        "protection_days",
        "conversion_weight",
        "follow_24h_weight",
        "lookback_days",
        "min_samples",
        "updated_by",
    }
    unknown_fields = set(changes) - mutable_fields - {"strategy_configs"}
    if unknown_fields:
        raise RuleValidationError(f"unsupported rule version fields: {', '.join(sorted(unknown_fields))}")
    for field_name in mutable_fields:
        if field_name not in changes:
            continue
        value = changes[field_name]
        if field_name in {"conversion_weight", "follow_24h_weight"}:
            value = _as_decimal_or_none(value, field_name)
        setattr(version, field_name, value)
    if "strategy_configs" in changes:
        _replace_strategy_configs(session, version.rule_version_id, changes["strategy_configs"])
    version.updated_at = utcnow()
    session.flush()
    return version


def delete_rule_version(session: Session, rule_version_id: str) -> None:
    version = _get_rule_version(session, rule_version_id)
    _require_draft(version)
    session.delete(version)
    session.flush()


def publish_rule_version(
    session: Session,
    rule_version_id: str,
    *,
    published_by: str | None = None,
) -> ClueAllocationRuleVersion:
    version = _get_rule_version(session, rule_version_id)
    _require_draft(version)
    session.flush()
    rule = _get_rule(session, version.rule_id)
    _validate_for_publish(session, rule, version)

    now = utcnow()
    previous_versions = session.scalars(
        select(ClueAllocationRuleVersion)
        .where(ClueAllocationRuleVersion.rule_id == rule.rule_id)
        .where(ClueAllocationRuleVersion.status == "published")
    ).all()
    for previous in previous_versions:
        previous.status = "retired"
        previous.retired_by = published_by
        previous.retired_at = now
        previous.updated_at = now
    # The storage layer enforces one published version per logical rule. Persist
    # retirements before publishing the replacement so SQLite and PostgreSQL see
    # a valid state throughout the transition.
    session.flush()

    version.status = "published"
    version.published_by = published_by
    version.published_at = now
    version.updated_by = published_by
    version.updated_at = now
    session.flush()
    return version


def retire_rule_version(
    session: Session,
    rule_version_id: str,
    *,
    retired_by: str | None = None,
) -> ClueAllocationRuleVersion:
    version = _get_rule_version(session, rule_version_id)
    if version.status != "published":
        raise RuleImmutableError("only published versions can be retired")
    rule = _get_rule(session, version.rule_id)
    if rule.scope_type == "global":
        raise RuleImmutableError("the current global default can only be replaced by publishing a new version")
    now = utcnow()
    version.status = "retired"
    version.retired_by = retired_by
    version.retired_at = now
    version.updated_at = now
    session.flush()
    return version


def resolve_published_rule_version(
    session: Session,
    *,
    anchor_store_id: str | None,
    anchor_city_code: str | None,
) -> PublishedRuleMatch | None:
    if anchor_store_id:
        match = _published_match(
            session,
            ClueAllocationRule.scope_type == "anchor_store",
            ClueAllocationRule.scope_anchor_store_id == anchor_store_id,
        )
        if match:
            return match

        group_ids = session.scalars(
            select(ClueStoreGroupMember.store_group_id).where(ClueStoreGroupMember.store_id == anchor_store_id)
        ).all()
        if group_ids:
            match = _published_match(
                session,
                ClueAllocationRule.scope_type == "store_group",
                ClueAllocationRule.scope_store_group_id.in_(group_ids),
            )
            if match:
                return match

    if anchor_city_code:
        match = _published_match(
            session,
            ClueAllocationRule.scope_type == "city",
            ClueAllocationRule.scope_city_code == anchor_city_code,
        )
        if match:
            return match

    return _published_match(session, ClueAllocationRule.scope_type == "global")


def bind_lead_rule_version(
    session: Session,
    *,
    lead_key: str,
    anchor_store_id: str | None,
    anchor_city_code: str | None,
) -> ClueLeadRuleVersionBinding:
    session.flush()
    normalized_lead_key = _required_text(lead_key, "lead_key")
    existing = session.get(ClueLeadRuleVersionBinding, normalized_lead_key)
    if existing is not None:
        return existing

    match = resolve_published_rule_version(
        session,
        anchor_store_id=anchor_store_id,
        anchor_city_code=anchor_city_code,
    )
    if match is None:
        raise RuleResolutionError("no published clue allocation rule matches this lead")

    binding = ClueLeadRuleVersionBinding(
        lead_key=normalized_lead_key,
        rule_version_id=match.rule_version.rule_version_id,
        scope_type=match.rule.scope_type,
        scope_key=match.rule.scope_key,
        scope_resolution_snapshot={
            "matched_scope": match.rule.scope_type,
            "scope_key": match.rule.scope_key,
            "rule_id": match.rule.rule_id,
            "rule_version_id": match.rule_version.rule_version_id,
            "version_no": match.rule_version.version_no,
            "scope_city_code": match.rule.scope_city_code,
            "scope_store_group_id": match.rule.scope_store_group_id,
            "scope_anchor_store_id": match.rule.scope_anchor_store_id,
            "anchor_store_id": anchor_store_id,
            "anchor_city_code": anchor_city_code,
        },
        rule_version_snapshot=_rule_version_snapshot(session, match.rule_version),
    )
    try:
        with session.begin_nested():
            session.add(binding)
            session.flush()
    except IntegrityError:
        # A concurrent allocator may have bound the same lead first. Preserve
        # that immutable winner instead of failing the allocation run.
        winner = session.get(ClueLeadRuleVersionBinding, normalized_lead_key)
        if winner is not None:
            return winner
        raise
    return binding


def _normalize_scope(
    *,
    scope_type: str,
    city_code: str | None,
    store_group_id: str | None,
    anchor_store_id: str | None,
) -> dict[str, str | None]:
    if scope_type not in SCOPE_TYPES:
        raise RuleValidationError(f"scope_type must be one of: {', '.join(sorted(SCOPE_TYPES))}")
    normalized_city = _canonical_city_code(city_code)
    normalized_group = _optional_text(store_group_id)
    normalized_anchor = _optional_text(anchor_store_id)
    targets = {
        "city": normalized_city,
        "store_group": normalized_group,
        "anchor_store": normalized_anchor,
    }
    if scope_type == "global":
        if any(targets.values()):
            raise RuleValidationError("global scope cannot include a city, store group, or anchor store")
        return {
            "scope_type": scope_type,
            "scope_key": "global",
            "scope_city_code": None,
            "scope_store_group_id": None,
            "scope_anchor_store_id": None,
        }

    selected_target = targets[scope_type]
    if not selected_target:
        raise RuleValidationError(f"{scope_type} scope requires its target identifier")
    if any(value for name, value in targets.items() if name != scope_type):
        raise RuleValidationError("a logical rule scope can only declare one target")
    return {
        "scope_type": scope_type,
        "scope_key": f"{scope_type}:{selected_target}",
        "scope_city_code": normalized_city if scope_type == "city" else None,
        "scope_store_group_id": normalized_group if scope_type == "store_group" else None,
        "scope_anchor_store_id": normalized_anchor if scope_type == "anchor_store" else None,
    }


def _replace_strategy_configs(
    session: Session,
    rule_version_id: str,
    strategy_configs: Sequence[Mapping[str, Any]],
) -> None:
    if not isinstance(strategy_configs, Sequence) or isinstance(strategy_configs, (str, bytes)):
        raise RuleValidationError("strategy_configs must be a list")
    session.execute(
        delete(ClueAllocationStrategyConfig).where(
            ClueAllocationStrategyConfig.rule_version_id == rule_version_id
        )
    )
    rows: list[ClueAllocationStrategyConfig] = []
    for config in strategy_configs:
        if not isinstance(config, Mapping):
            raise RuleValidationError("each strategy config must be an object")
        params = config.get("params", {})
        if not isinstance(params, Mapping):
            raise RuleValidationError("strategy config params must be an object")
        rows.append(
            ClueAllocationStrategyConfig(
                strategy_config_id=_new_id("strategy-config"),
                rule_version_id=rule_version_id,
                strategy_type=str(config.get("strategy_type") or "").strip(),
                enabled=config.get("enabled"),
                execution_order=config.get("execution_order"),
                params_json=dict(params),
            )
        )
    session.add_all(rows)


def _validate_for_publish(
    session: Session,
    rule: ClueAllocationRule,
    version: ClueAllocationRuleVersion,
) -> None:
    if rule.scope_type != "global":
        has_global_default = session.scalar(
            select(ClueAllocationRuleVersion.rule_version_id)
            .join(ClueAllocationRule, ClueAllocationRule.rule_id == ClueAllocationRuleVersion.rule_id)
            .where(ClueAllocationRule.scope_type == "global")
            .where(ClueAllocationRuleVersion.status == "published")
            .limit(1)
        )
        if not has_global_default:
            raise RuleValidationError("a published global default rule is required before publishing this scope")

    if version.auto_expiry_enabled is None:
        raise RuleValidationError("auto_expiry_enabled must be explicit")
    if not isinstance(version.auto_expiry_enabled, bool):
        raise RuleValidationError("auto_expiry_enabled must be a boolean")
    if version.auto_expiry_enabled or version.first_follow_up_sla_hours is not None:
        _validate_integer_range(
            version.first_follow_up_sla_hours,
            "first_follow_up_sla_hours",
            minimum=1,
            maximum=MAX_SLA_HOURS,
        )
    _validate_integer_range(
        version.protection_days,
        "protection_days",
        minimum=1,
        maximum=MAX_PROTECTION_DAYS,
    )
    _validate_integer_range(version.lookback_days, "lookback_days", minimum=1, maximum=MAX_LOOKBACK_DAYS)
    _validate_integer_range(version.min_samples, "min_samples", minimum=1, maximum=MAX_MIN_SAMPLES)

    conversion_weight = _validate_weight(version.conversion_weight, "conversion_weight")
    follow_24h_weight = _validate_weight(version.follow_24h_weight, "follow_24h_weight")
    if conversion_weight + follow_24h_weight != Decimal("1"):
        raise RuleValidationError("score weights must sum to 1")

    configs = session.scalars(
        select(ClueAllocationStrategyConfig)
        .where(ClueAllocationStrategyConfig.rule_version_id == version.rule_version_id)
        .order_by(ClueAllocationStrategyConfig.execution_order, ClueAllocationStrategyConfig.strategy_config_id)
    ).all()
    if len(configs) != len(STRATEGY_TYPES) or {config.strategy_type for config in configs} != STRATEGY_TYPES:
        raise RuleValidationError("all three fixed strategy types must be present exactly once")
    if len({config.strategy_type for config in configs}) != len(configs):
        raise RuleValidationError("all three fixed strategy types must be present exactly once")

    orders: list[int] = []
    for config in configs:
        if not isinstance(config.enabled, bool):
            raise RuleValidationError("strategy enabled must be a boolean")
        if not isinstance(config.execution_order, int) or isinstance(config.execution_order, bool):
            raise RuleValidationError("strategy execution_order must be a positive integer")
        if config.execution_order <= 0:
            raise RuleValidationError("strategy execution_order must be a positive integer")
        orders.append(config.execution_order)
        if config.strategy_type in DISTANCE_STRATEGY_TYPES:
            _validate_distance(config.params_json, config.strategy_type)
        elif "max_distance_km" in (config.params_json or {}):
            _validate_distance(config.params_json, config.strategy_type)
    if len(set(orders)) != len(orders):
        raise RuleValidationError("strategy execution_order values must be unique")


def _published_match(session: Session, *conditions) -> PublishedRuleMatch | None:
    row = session.execute(
        select(ClueAllocationRule, ClueAllocationRuleVersion)
        .join(
            ClueAllocationRuleVersion,
            ClueAllocationRuleVersion.rule_id == ClueAllocationRule.rule_id,
        )
        .where(ClueAllocationRuleVersion.status == "published", *conditions)
        .order_by(ClueAllocationRuleVersion.published_at.desc(), ClueAllocationRule.rule_id)
        .limit(1)
    ).first()
    if row is None:
        return None
    rule, version = row
    return PublishedRuleMatch(rule=rule, rule_version=version)


def _rule_version_snapshot(session: Session, version: ClueAllocationRuleVersion) -> dict[str, Any]:
    configs = session.scalars(
        select(ClueAllocationStrategyConfig)
        .where(ClueAllocationStrategyConfig.rule_version_id == version.rule_version_id)
        .order_by(ClueAllocationStrategyConfig.execution_order, ClueAllocationStrategyConfig.strategy_config_id)
    ).all()
    return {
        "rule_version_id": version.rule_version_id,
        "version_no": version.version_no,
        "auto_expiry_enabled": version.auto_expiry_enabled,
        "first_follow_up_sla_hours": version.first_follow_up_sla_hours,
        "protection_days": version.protection_days,
        "conversion_weight": _decimal_to_float(version.conversion_weight),
        "follow_24h_weight": _decimal_to_float(version.follow_24h_weight),
        "lookback_days": version.lookback_days,
        "min_samples": version.min_samples,
        "strategy_configs": [
            {
                "strategy_type": config.strategy_type,
                "enabled": config.enabled,
                "execution_order": config.execution_order,
                "params": dict(config.params_json or {}),
            }
            for config in configs
        ],
    }


def _validate_distance(params: Mapping[str, Any] | None, strategy_type: str) -> None:
    value = (params or {}).get("max_distance_km")
    if isinstance(value, bool):
        raise RuleValidationError(f"{strategy_type}.max_distance_km must be a positive number")
    try:
        distance = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise RuleValidationError(f"{strategy_type}.max_distance_km must be a positive number") from None
    if distance <= 0 or distance > MAX_DISTANCE_KM:
        raise RuleValidationError(f"{strategy_type}.max_distance_km must be between 0 and {MAX_DISTANCE_KM}")


def _validate_weight(value: Decimal | None, name: str) -> Decimal:
    if value is None:
        raise RuleValidationError(f"{name} is required")
    if value < 0 or value > 1:
        raise RuleValidationError(f"{name} must be between 0 and 1")
    return value


def _validate_integer_range(value: int | None, name: str, *, minimum: int, maximum: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum or value > maximum:
        raise RuleValidationError(f"{name} must be between {minimum} and {maximum}")


def _normalized_store_ids(member_store_ids: Sequence[str]) -> list[str]:
    if isinstance(member_store_ids, (str, bytes)):
        raise RuleValidationError("member_store_ids must be a list")
    normalized = [_required_text(store_id, "member_store_id") for store_id in member_store_ids]
    if len(set(normalized)) != len(normalized):
        raise RuleValidationError("store group members must be unique")
    return sorted(normalized)


def _validate_store_ids(session: Session, store_ids: Sequence[str]) -> None:
    if not store_ids:
        return
    known_store_ids = set(
        session.scalars(select(DimStore.store_id).where(DimStore.store_id.in_(store_ids))).all()
    )
    missing = sorted(set(store_ids) - known_store_ids)
    if missing:
        raise RuleValidationError(f"unknown store ids: {', '.join(missing)}")


def _validate_store_group_members_available(
    session: Session,
    store_ids: Sequence[str],
    *,
    excluding_store_group_id: str | None = None,
) -> None:
    if not store_ids:
        return
    statement = select(ClueStoreGroupMember.store_id).where(ClueStoreGroupMember.store_id.in_(store_ids))
    if excluding_store_group_id:
        statement = statement.where(ClueStoreGroupMember.store_group_id != excluding_store_group_id)
    occupied_store_ids = sorted(set(session.scalars(statement).all()))
    if occupied_store_ids:
        raise RuleValidationError(
            f"stores can belong to only one allocation store group: {', '.join(occupied_store_ids)}"
        )


def _get_rule(session: Session, rule_id: str) -> ClueAllocationRule:
    rule = session.get(ClueAllocationRule, rule_id)
    if rule is None:
        raise RuleNotFoundError("clue allocation rule was not found")
    return rule


def _get_rule_version(session: Session, rule_version_id: str) -> ClueAllocationRuleVersion:
    version = session.get(ClueAllocationRuleVersion, rule_version_id)
    if version is None:
        raise RuleNotFoundError("clue allocation rule version was not found")
    return version


def _get_store_group(session: Session, store_group_id: str) -> ClueStoreGroup:
    group = session.get(ClueStoreGroup, store_group_id)
    if group is None:
        raise RuleNotFoundError("clue store group was not found")
    return group


def _require_draft(version: ClueAllocationRuleVersion) -> None:
    if version.status != "draft":
        raise RuleImmutableError("only draft versions can be changed or deleted")


def _required_text(value: Any, name: str) -> str:
    normalized = _optional_text(value)
    if not normalized:
        raise RuleValidationError(f"{name} is required")
    return normalized


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _canonical_city_code(value: str | None) -> str | None:
    city_code = _optional_text(value)
    if not city_code:
        return None
    return city_code[:-1] if city_code.endswith("市") else city_code


def _as_decimal_or_none(value: Decimal | float | int | None, name: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise RuleValidationError(f"{name} must be numeric")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise RuleValidationError(f"{name} must be numeric") from None


def _decimal_to_float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"
