"""Product-scoped publication, explicit authorization and first-ingress binding.

The rule version freezes at ingress. Store-list membership is deliberately
resolved from its current published pointer at each subsequent store selection.
All mutation functions participate in their caller's transaction.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, exists, func, or_, select, union_all
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.dy_api.clue_product_routing_policy import DEFAULT_FOLLOW_UP_POLICY, normalize_follow_up_policy
from apps.api.dy_api.models import (
    ClueAllocationAuditLog, ClueAllocationRule, ClueAllocationRuleVersion,
    ClueCenterOrder, ClueLeadRuleVersionBinding, ClueMasterLead,
    ClueProductRoutingConfig, ClueProductRoutingGrant, ClueProductRoutingOperation,
    ClueProductStoreListMember, ClueProductStoreListVersion, ClueSharedRuleMaintainer, DimSkuProductRule,
    DimStore, RawDouyinClue, User, utcnow,
)
from apps.worker.clue_rule_versions import (
    RuleVersionError, bind_lead_rule_version, create_rule_version, publish_rule_version,
    resolve_published_rule_version, rule_version_snapshot,
)


SHARED_BASE_SCOPE_KEY = "product_base:jingcheng"
PRODUCT_PROCESSING_CHUNK_SIZE = 200
SHARED_BASE_LOCK_KEY = 5942041150069
RULE_PATCH_KEYS = frozenset(DEFAULT_FOLLOW_UP_POLICY) | {"first_follow_up_sla_hours", "follow_up_policy"}


class ProductRoutingError(ValueError):
    """A safe business failure, suitable for per-product public feedback."""

    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def product_scope_for_id(session: Session, product_id: str | None) -> str:
    """Use the existing Jingcheng catalog, including IDs supplied as SKU IDs."""
    if not product_id:
        return "byd"
    is_jingcheng = session.scalar(select(exists().where(
        DimSkuProductRule.product_scope == "精诚养车",
        or_(DimSkuProductRule.product_id == product_id, DimSkuProductRule.sku_id == product_id),
    )))
    return "jingcheng" if is_jingcheng else "byd"


def has_published_product_store_list(session: Session, product_id: str | None) -> bool:
    """Distinguish an absent/invalid list pointer from an actual publication."""
    if not product_id:
        return False
    return bool(session.scalar(select(exists().where(
        ClueProductRoutingConfig.product_id == product_id,
        ClueProductStoreListVersion.list_version_id == ClueProductRoutingConfig.active_list_version_id,
        ClueProductStoreListVersion.product_id == product_id,
        ClueProductStoreListMember.list_version_id == ClueProductStoreListVersion.list_version_id,
    ))))


def load_product_store_ids(session: Session, product_id: str | None) -> set[str]:
    """Return only membership of the product's current successful publication."""
    if not product_id:
        return set()
    return set(session.scalars(select(ClueProductStoreListMember.store_id)
        .join(ClueProductStoreListVersion, ClueProductStoreListVersion.list_version_id == ClueProductStoreListMember.list_version_id)
        .join(ClueProductRoutingConfig, ClueProductRoutingConfig.active_list_version_id == ClueProductStoreListVersion.list_version_id)
        .where(ClueProductRoutingConfig.product_id == product_id, ClueProductStoreListVersion.product_id == product_id)).all())


def bind_product_routing(
    session: Session, lead: ClueMasterLead, product_id: str | None, now: datetime,
) -> ClueLeadRuleVersionBinding | None:
    """Freeze the routing owner and version exactly once on a newly ingested lead.

    Callers must invoke this only for new leads. NULL on existing leads remains
    the legacy boundary and is never backfilled by publication or collection.
    The product row lock serializes a first ingress against a manual switch.
    """
    if lead.routing_mode is not None:
        return session.get(ClueLeadRuleVersionBinding, lead.lead_key)
    normalized_product_id = str(product_id).strip() if product_id is not None else None
    normalized_product_id = normalized_product_id or None
    config = None
    if normalized_product_id:
        # Use the same durable row for both ingress and enable/disable. Creating
        # an OFF pointer is safe and never installs or enables a routing rule.
        config = _locked_config(session, normalized_product_id)
    lead.routing_product_id = normalized_product_id
    if config is not None and config.routing_enabled:
        lead.routing_mode = "flow"
        version = session.get(ClueAllocationRuleVersion, config.rule_version_id) if config.rule_version_id else None
        if version is None:
            # Preserve the flow decision even if external configuration damage
            # removed its version; allocation must route this to headquarters.
            session.flush()
            return None
        existing = session.get(ClueLeadRuleVersionBinding, lead.lead_key)
        if existing is not None:
            return existing
        snapshot = rule_version_snapshot(session, version)
        snapshot.update({"product_id": normalized_product_id,
                         "product_scope": product_scope_for_id(session, normalized_product_id)})
        binding = ClueLeadRuleVersionBinding(
            lead_key=lead.lead_key, rule_version_id=version.rule_version_id,
            scope_type="product", scope_key=f"product:{normalized_product_id}",
            rule_version_snapshot=snapshot, bound_at=now,
            scope_resolution_snapshot={
                "matched_scope": "product", "product_id": normalized_product_id,
                "product_scope": snapshot["product_scope"], "rule_id": version.rule_id,
                "rule_version_id": version.rule_version_id,
                "routing_anchor_frozen": bool(lead.anchor_store_id and lead.anchor_city_code
                    and lead.anchor_longitude is not None and lead.anchor_latitude is not None),
                "anchor_store_id": lead.anchor_store_id, "anchor_city_code": lead.anchor_city_code,
                "anchor_longitude": str(lead.anchor_longitude) if lead.anchor_longitude is not None else None,
                "anchor_latitude": str(lead.anchor_latitude) if lead.anchor_latitude is not None else None,
            },
        )
        session.add(binding)
        session.flush()
        return binding
    lead.routing_mode = "original" if normalized_product_id is None or product_scope_for_id(session, normalized_product_id) == "jingcheng" else "direct"
    if lead.routing_mode == "original":
        match = resolve_published_rule_version(session, anchor_store_id=lead.anchor_store_id,
                                               anchor_city_code=lead.anchor_city_code)
        if match is not None:
            binding = bind_lead_rule_version(session, lead_key=lead.lead_key,
                anchor_store_id=lead.anchor_store_id, anchor_city_code=lead.anchor_city_code)
            binding.bound_at = now
            session.flush()
            return binding
    session.flush()
    return None


def can_manage_product(session: Session, actor: Any, product_id: str) -> bool:
    """Recheck current product grants, independent of page or store scope."""
    if _can_manage_grants(session, actor):
        return True
    user_id = getattr(actor, "user_id", None)
    if not user_id or getattr(actor, "auth_type", "") != "user":
        return False
    return bool(session.scalar(select(exists().where(
        ClueProductRoutingGrant.product_id == product_id,
        ClueProductRoutingGrant.user_id == user_id,
        User.user_id == ClueProductRoutingGrant.user_id, User.status == "active", User.is_initialized.is_(True),
    ))))


def list_products(
    session: Session, actor: Any, *, q: str = "", product_scope: str = "all",
    page: int = 1, page_size: int = 50,
) -> dict[str, Any]:
    """List the current actor's manageable products, with one row per ID."""
    query = _product_query(session, actor, q=q, product_scope=product_scope)
    total = int(session.scalar(select(func.count()).select_from(query.subquery())) or 0)
    selected = session.execute(query.order_by("product_id").offset((page - 1) * page_size).limit(page_size)).mappings().all()
    rows = _product_snapshots(session, actor, [dict(row) for row in selected])
    return {"rows": rows, "total": total, "page": page, "page_size": page_size,
            "can_manage_grants": _can_manage_grants(session, actor),
            "can_manage_shared_rule": _can_manage_shared_rule(session, actor)}


def batch_product_changes(
    session: Session, actor: Any, payload: Mapping[str, Any], *,
    request_id: str | None = None, idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Preview without writes or apply each product within an isolated savepoint."""
    preview = bool(payload.get("preview", True))
    _require_human_actor(actor)
    if not preview and payload.get("all_matching"):
        raise ProductRoutingError("PREVIEW_REQUIRED", "正式提交须使用预览确认的明确商品 ID，不能重新展开筛选范围", http_status=422)
    operation = None
    digest = _digest(dict(payload))
    if not preview and idempotency_key:
        operation = _locked_operation(session, actor, idempotency_key, digest)
        if operation.result_json:
            # A revoked manager must not replay formerly accessible snapshots.
            for result in operation.result_json.get("results", []):
                if (result.get("before") or result.get("after")) and not can_manage_product(session, actor, result["product_id"]):
                    raise ProductRoutingError("PRODUCT_FORBIDDEN", "商品管理权限已变更，请重新预览", http_status=403)
            return deepcopy(operation.result_json)
    if not preview and payload.get("action") in {"publish_rule", "enable"}:
        _lock_rule_publications(session)
    filters = dict(payload.get("filters") or {})
    if payload.get("all_matching"):
        matching = _product_query(session, actor, **filters).subquery()
        product_ids = list(session.scalars(select(matching.c.product_id).order_by(matching.c.product_id)))
    else:
        product_ids = _normalized_ids(payload.get("product_ids") or ())
    results = []
    for product_id, catalog_row, cached_preview in _product_change_rows(session, actor, product_ids, preview=preview):
        before: dict[str, Any] = {}
        try:
            with (nullcontext() if preview else session.begin_nested()):
                if not (cached_preview.get("can_manage", False) if preview and cached_preview else can_manage_product(session, actor, product_id)):
                    raise ProductRoutingError("PRODUCT_FORBIDDEN", "该商品不存在或无管理权限", http_status=403)
                if catalog_row is None:
                    raise ProductRoutingError("PRODUCT_NOT_FOUND", "商品不存在")
                if not preview:
                    _locked_config(session, product_id)
                    # Grants can be revoked between preview and commit.
                    if not can_manage_product(session, actor, product_id):
                        raise ProductRoutingError("PRODUCT_FORBIDDEN", "该商品不存在或无管理权限", http_status=403)
                before = cached_preview if preview and cached_preview else _product_snapshot(session, actor, catalog_row)
                after = _preview_change(session, before, payload)
                if not preview:
                    config = _apply_change(session, actor, product_id, payload, after)
                    after.pop("proposed_change", None)
                    after.update({"routing_enabled": config.routing_enabled,
                                  "rule_version_id": config.rule_version_id,
                                  "list_version": config.active_list_version_id})
                    if config.rule_version_id:
                        applied_version = session.get(ClueAllocationRuleVersion, config.rule_version_id)
                        after.update(_rule_settings(_shared_snapshot(session, applied_version)))
                    _audit(session, actor, f"product_routing_{payload['action']}", product_id,
                           before, after, request_id=request_id,
                           detail={"authorization_note": str(payload.get("authorization_note") or "").strip()})
                results.append({"product_id": product_id, "status": "preview" if preview else "success",
                                "before": before, "after": after})
        except ProductRoutingError as exc:
            results.append({"product_id": product_id, "status": "failed", "before": before, "after": before,
                            "error": {"code": exc.code, "message": exc.message}})
            if not preview:
                _audit(session, actor, f"product_routing_{payload['action']}", product_id,
                       before, before, request_id=request_id, error=exc.code)
        except RuleVersionError:
            results.append({"product_id": product_id, "status": "failed", "before": before, "after": before,
                            "error": {"code": "INVALID_RULE", "message": "规则发布校验失败，原配置已保留，请检查后重试"}})
            if not preview:
                _audit(session, actor, f"product_routing_{payload['action']}", product_id,
                       before, before, request_id=request_id, error="INVALID_RULE")
        except SQLAlchemyError:
            results.append({"product_id": product_id, "status": "failed", "before": before, "after": before,
                            "error": {"code": "CONFLICT", "message": "商品发布冲突，原配置已保留，请单独重试"}})
            if not preview:
                _audit(session, actor, f"product_routing_{payload['action']}", product_id,
                       before, before, request_id=request_id, error="CONFLICT")
    response = {"results": results, "total": len(results),
                "succeeded": sum(row["status"] != "failed" for row in results),
                "failed": sum(row["status"] == "failed" for row in results)}
    if operation is not None:
        operation.result_json = deepcopy(response)
    if not preview:
        session.flush()
    return response


def get_product_grants(session: Session, actor: Any, product_id: str) -> dict[str, Any]:
    """Return product grants and eligible accounts only to global managers."""
    _require_grant_manager(session, actor)
    if _catalog_row(session, product_id) is None:
        raise ProductRoutingError("PRODUCT_NOT_FOUND", "商品不存在", http_status=404)
    users = session.scalars(select(User).where(User.status == "active", User.is_initialized.is_(True)).order_by(User.username)).all()
    ids = list(session.scalars(select(ClueProductRoutingGrant.user_id).where(
        ClueProductRoutingGrant.product_id == product_id).order_by(ClueProductRoutingGrant.user_id)))
    return {"product_id": product_id, "user_ids": ids,
            "users": [{"user_id": user.user_id, "username": user.username, "display_name": user.display_name} for user in users]}


def replace_product_grants(
    session: Session, actor: Any, product_id: str, user_ids: Sequence[str], *, request_id: str | None = None,
) -> dict[str, Any]:
    """Atomically replace one product's grant set without delegating grants."""
    _require_grant_manager(session, actor)
    _locked_config(session, product_id)
    _require_grant_manager(session, actor)
    before = get_product_grants(session, actor, product_id)
    normalized = _normalized_ids(user_ids)
    eligible = set(session.scalars(select(User.user_id).where(User.user_id.in_(normalized), User.status == "active", User.is_initialized.is_(True))))
    if eligible != set(normalized):
        raise ProductRoutingError("INVALID_GRANTEE", "只能授权已初始化且启用的账号", http_status=422)
    if set(before["user_ids"]) != set(normalized):
        session.execute(delete(ClueProductRoutingGrant).where(ClueProductRoutingGrant.product_id == product_id))
        session.add_all([ClueProductRoutingGrant(product_id=product_id, user_id=user_id, granted_by=_actor_key(actor)) for user_id in normalized])
        session.flush()
        _audit(session, actor, "product_routing_grants", product_id,
               {"user_ids": before["user_ids"]}, {"user_ids": normalized}, request_id=request_id)
    return get_product_grants(session, actor, product_id)


def get_shared_rule(session: Session, actor: Any) -> dict[str, Any]:
    """Read the explicitly identified Jingcheng base, never a pilot exception."""
    _require_shared_rule_maintainer(session, actor)
    version = _shared_base_version(session)
    return _shared_snapshot(session, version)


def publish_shared_rule(
    session: Session, actor: Any, rules: Mapping[str, Any], *, preview: bool = True,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Publish a new shared base without altering any existing product pointer."""
    _require_shared_rule_maintainer(session, actor)
    if not preview:
        _lock_rule_publications(session)
        _require_shared_rule_maintainer(session, actor)
    base = _ensure_shared_base_rule(session, actor) if not preview else None
    before = get_shared_rule(session, actor)
    after = {**before, **_patched_rule(before, rules)}
    if not preview:
        assert base is not None
        version = _shared_base_version(session)
        if version is None or _rule_settings(_shared_snapshot(session, version)) != _rule_settings(after):
            version = _publish_version(session, base, actor, after, product_scope="jingcheng")
        after = _shared_snapshot(session, version)
        _audit(session, actor, "product_routing_shared_rule", None, before, after, request_id=request_id)
    return {"before": before, "after": after, "status": "preview" if preview else "success"}


def get_shared_rule_grants(session: Session, actor: Any) -> dict[str, Any]:
    """Expose maintainer membership and eligible accounts only to global admins."""
    _require_grant_manager(session, actor)
    users = session.scalars(select(User).where(User.status == "active", User.is_initialized.is_(True)).order_by(User.username)).all()
    ids = list(session.scalars(select(ClueSharedRuleMaintainer.user_id).order_by(ClueSharedRuleMaintainer.user_id)))
    return {"user_ids": ids, "users": [
        {"user_id": user.user_id, "username": user.username, "display_name": user.display_name} for user in users]}


def replace_shared_rule_grants(
    session: Session, actor: Any, user_ids: Sequence[str], *, request_id: str | None = None,
) -> dict[str, Any]:
    """Replace explicit maintainers without granting product or store authority."""
    _require_grant_manager(session, actor)
    _lock_rule_publications(session)
    _require_grant_manager(session, actor)
    before = get_shared_rule_grants(session, actor)
    normalized = _normalized_ids(user_ids)
    eligible = set(session.scalars(select(User.user_id).where(
        User.user_id.in_(normalized), User.status == "active", User.is_initialized.is_(True))))
    if eligible != set(normalized):
        raise ProductRoutingError("INVALID_GRANTEE", "只能授权已初始化且启用的账号", http_status=422)
    if set(before["user_ids"]) != set(normalized):
        session.execute(delete(ClueSharedRuleMaintainer))
        session.add_all([ClueSharedRuleMaintainer(user_id=user_id, granted_by=_actor_key(actor)) for user_id in normalized])
        session.flush()
        _audit(session, actor, "product_routing_shared_grants", None,
               {"user_ids": before["user_ids"]}, {"user_ids": normalized}, request_id=request_id,
               detail={"scope_key": SHARED_BASE_SCOPE_KEY})
    return get_shared_rule_grants(session, actor)


def _catalog():
    sources = union_all(
        select(DimSkuProductRule.product_id.label("product_id"), DimSkuProductRule.product_name.label("product_name")),
        select(RawDouyinClue.product_id, RawDouyinClue.product_name),
        select(ClueCenterOrder.product_id, ClueCenterOrder.product_name),
    ).subquery()
    return select(sources.c.product_id, func.max(sources.c.product_name).label("product_name")).where(
        sources.c.product_id.is_not(None), func.trim(sources.c.product_id) != "").group_by(sources.c.product_id).subquery("routing_product_catalog")


def _product_query(session: Session, actor: Any, *, q: str = "", product_scope: str = "all"):
    catalog = _catalog()
    statement = select(catalog.c.product_id, catalog.c.product_name)
    if not _can_manage_grants(session, actor):
        statement = statement.where(catalog.c.product_id.in_(select(ClueProductRoutingGrant.product_id).where(
            ClueProductRoutingGrant.user_id == getattr(actor, "user_id", None))))
    if q.strip():
        statement = statement.where(or_(catalog.c.product_id.contains(q.strip(), autoescape=True),
                                        catalog.c.product_name.contains(q.strip(), autoescape=True)))
    membership = exists().where(DimSkuProductRule.product_scope == "精诚养车", or_(
        DimSkuProductRule.product_id == catalog.c.product_id, DimSkuProductRule.sku_id == catalog.c.product_id))
    if product_scope == "jingcheng":
        statement = statement.where(membership)
    elif product_scope == "byd":
        statement = statement.where(~membership)
    elif product_scope != "all":
        raise ProductRoutingError("INVALID_SCOPE", "请选择全部商品、精诚养车或比亚迪本品", http_status=422)
    return statement


def _catalog_row(session: Session, product_id: str) -> dict[str, Any] | None:
    catalog = _catalog()
    row = session.execute(select(catalog).where(catalog.c.product_id == product_id)).mappings().first()
    return dict(row) if row else None


def _product_change_rows(session: Session, actor: Any, product_ids: list[str], *, preview: bool):
    # A processing chunk is a database/memory boundary, never a selection cap.
    # The full authorized filter result can span any number of these chunks.
    for offset in range(0, len(product_ids), PRODUCT_PROCESSING_CHUNK_SIZE):
        chunk = product_ids[offset:offset + PRODUCT_PROCESSING_CHUNK_SIZE]
        catalog = _catalog()
        rows = [dict(row) for row in session.execute(select(catalog).where(catalog.c.product_id.in_(chunk))).mappings()]
        catalogs = {row["product_id"]: row for row in rows}
        previews = {row["product_id"]: row for row in _product_snapshots(session, actor, rows)} if preview else {}
        for product_id in chunk:
            yield product_id, catalogs.get(product_id), previews.get(product_id)


def _product_snapshot(session: Session, actor: Any, catalog_row: Mapping[str, Any]) -> dict[str, Any]:
    return _product_snapshots(session, actor, [catalog_row])[0]


def _product_snapshots(session: Session, actor: Any, catalog_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not catalog_rows:
        return []
    product_ids = [row["product_id"] for row in catalog_rows]
    configs = {row.product_id: row for row in session.scalars(select(ClueProductRoutingConfig).where(
        ClueProductRoutingConfig.product_id.in_(product_ids)))}
    versions = {row.rule_version_id: row for row in session.scalars(select(ClueAllocationRuleVersion).where(
        ClueAllocationRuleVersion.rule_version_id.in_([row.rule_version_id for row in configs.values() if row.rule_version_id])))}
    member_ids: dict[str, list[str]] = {}
    for product_id, store_id in session.execute(select(ClueProductStoreListVersion.product_id, ClueProductStoreListMember.store_id)
            .join(ClueProductStoreListMember, ClueProductStoreListMember.list_version_id == ClueProductStoreListVersion.list_version_id)
            .join(ClueProductRoutingConfig, ClueProductRoutingConfig.active_list_version_id == ClueProductStoreListVersion.list_version_id)
            .where(ClueProductRoutingConfig.product_id.in_(product_ids),
                   ClueProductRoutingConfig.product_id == ClueProductStoreListVersion.product_id)):
        member_ids.setdefault(product_id, []).append(store_id)
    jingcheng = set()
    for product_id, sku_id in session.execute(select(DimSkuProductRule.product_id, DimSkuProductRule.sku_id).where(
            DimSkuProductRule.product_scope == "精诚养车", or_(DimSkuProductRule.product_id.in_(product_ids), DimSkuProductRule.sku_id.in_(product_ids)))):
        jingcheng.update((product_id, sku_id))
    is_global = _can_manage_grants(session, actor)
    granted = set() if is_global else set(session.scalars(select(ClueProductRoutingGrant.product_id).where(
        ClueProductRoutingGrant.product_id.in_(product_ids), ClueProductRoutingGrant.user_id == getattr(actor, "user_id", None))))
    default_settings = _shared_snapshot(session, _shared_base_version(session))
    rows = []
    for catalog in catalog_rows:
        product_id = catalog["product_id"]
        config = configs.get(product_id)
        version = versions.get(config.rule_version_id) if config else None
        settings = _shared_snapshot(session, version) if version else default_settings
        rows.append({"product_id": product_id, "product_name": catalog["product_name"] or product_id,
            "product_scope": "jingcheng" if product_id in jingcheng else "byd",
            "routing_enabled": bool(config and config.routing_enabled),
            "rule_version_id": config.rule_version_id if config else None,
            "first_follow_up_sla_hours": settings["first_follow_up_sla_hours"],
            "follow_up_policy": deepcopy(settings["follow_up_policy"]),
            "store_ids": sorted(member_ids.get(product_id, [])),
            "list_version": config.active_list_version_id if config else None,
            "can_manage": is_global or product_id in granted})
    return rows


def _preview_change(session: Session, before: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    after = deepcopy(dict(before))
    action = payload["action"]
    if action == "publish_list":
        lists = payload.get("lists")
        store_ids = payload.get("store_ids") if lists is None else next((row["store_ids"] for row in lists if row["product_id"].strip() == before["product_id"]), None)
        if store_ids is None:
            raise ProductRoutingError("STORE_IDS_REQUIRED", "该商品缺少适用门店名单")
        normalized = _normalized_ids(store_ids)
        if not normalized:
            raise ProductRoutingError("STORE_IDS_REQUIRED", "有效名单至少需要一家已知门店")
        known = set(session.scalars(select(DimStore.store_id).where(DimStore.store_id.in_(normalized))))
        if known != set(normalized):
            raise ProductRoutingError("UNKNOWN_STORE_IDS", "名单包含未知门店编码，请校正后重试")
        after["store_ids"] = normalized
    elif action == "publish_rule":
        config = session.get(ClueProductRoutingConfig, before["product_id"])
        if before["product_scope"] == "byd" and (config is None or config.first_enabled_at is None):
            raise ProductRoutingError("PRODUCT_NOT_ENABLED", "本品首次开启前继承精诚共享基座，请先按已确认名单开启，之后可发布独立规则")
        rules = payload.get("rules")
        if not rules:
            raise ProductRoutingError("INVALID_RULE", "请至少选择一个要修改的规则字段")
        after.update(_patched_rule(before, rules))
    elif action == "enable":
        if not str(payload.get("authorization_note") or "").strip():
            raise ProductRoutingError("AUTHORIZATION_REQUIRED", "正式开启前须填写业务负责人确认名单并授权开启的说明")
        if not has_published_product_store_list(session, before["product_id"]) or not before["store_ids"]:
            raise ProductRoutingError("PUBLISHED_LIST_REQUIRED", "请先发布该商品的有效适用门店名单")
        if not payload.get("preview", True):
            expected = (payload.get("expected_list_versions") or {}).get(before["product_id"])
            if not isinstance(expected, str) or not expected:
                raise ProductRoutingError("PREVIEW_REQUIRED", "请先预览并确认该商品已发布的有效名单，再授权开启")
            if expected != before["list_version"]:
                raise ProductRoutingError("LIST_VERSION_CHANGED", "名单已在预览后换版，商品保持原开关状态，请重新预览确认")
        after["routing_enabled"] = True
    elif action == "disable":
        after["routing_enabled"] = False
    else:
        raise ProductRoutingError("INVALID_ACTION", "不支持的商品操作")
    after["proposed_change"] = after != before
    return after


def _apply_change(session: Session, actor: Any, product_id: str, payload: Mapping[str, Any], after: Mapping[str, Any]) -> ClueProductRoutingConfig:
    # The caller already holds this product row lock and has rechecked grants.
    config = session.get(ClueProductRoutingConfig, product_id)
    assert config is not None
    action = payload["action"]
    if action == "publish_list":
        store_ids = after["store_ids"]
        if sorted(load_product_store_ids(session, product_id)) != store_ids or not has_published_product_store_list(session, product_id):
            current_max = session.scalar(select(func.max(ClueProductStoreListVersion.version_no)).where(ClueProductStoreListVersion.product_id == product_id))
            version = ClueProductStoreListVersion(list_version_id=_new_id("product-list"), product_id=product_id,
                version_no=int(current_max or 0) + 1, content_sha256=_digest(store_ids), published_by=_actor_key(actor))
            session.add(version)
            session.flush()
            session.add_all([ClueProductStoreListMember(list_version_id=version.list_version_id, store_id=store_id) for store_id in store_ids])
            session.flush()
            config.active_list_version_id = version.list_version_id
    elif action == "publish_rule" or (action == "enable" and (not config.rule_version_id or
            (after["product_scope"] == "byd" and config.first_enabled_at is None))):
        old_version = session.get(ClueAllocationRuleVersion, config.rule_version_id) if config.rule_version_id else None
        inherit_as_new = old_version is None or (action == "enable" and after["product_scope"] == "byd" and config.first_enabled_at is None)
        if inherit_as_new or _rule_settings(_shared_snapshot(session, old_version)) != _rule_settings(after):
            base_rule = _ensure_shared_base_rule(session, actor)
            base_version = _shared_base_version(session)
            if base_version is None:
                base_version = _publish_version(session, base_rule, actor, _shared_snapshot(session, None), product_scope="jingcheng")
            rule = session.get(ClueAllocationRule, config.rule_id) if config.rule_id else None
            if rule is None:
                rule = ClueAllocationRule(rule_id=_new_id("product-rule"), rule_name=f"商品 {product_id}",
                    scope_type="product", scope_key=f"product:{product_id}", created_by=_actor_key(actor))
                session.add(rule)
                session.flush()
                config.rule_id = rule.rule_id
            inherited_base_id = base_version.rule_version_id if inherit_as_new else (old_version.snapshot or {}).get("base_rule_version_id")
            effective_settings = after
            if inherit_as_new:
                effective_settings = _shared_snapshot(session, base_version)
                if action == "publish_rule":
                    effective_settings.update(_patched_rule(effective_settings, payload.get("rules") or {}))
            version = _publish_version(session, rule, actor, effective_settings, product_scope=after["product_scope"],
                                       base_version_id=inherited_base_id)
            config.rule_version_id = version.rule_version_id
    if action in {"enable", "disable"}:
        config.routing_enabled = action == "enable"
        if action == "enable" and config.first_enabled_at is None:
            config.first_enabled_at = utcnow()
    config.updated_by = _actor_key(actor)
    config.updated_at = utcnow()
    session.flush()
    return config


def _patched_rule(before: Mapping[str, Any], rules: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(rules, Mapping) or set(rules) - RULE_PATCH_KEYS or not rules:
        raise ProductRoutingError("INVALID_RULE", "规则字段不合法")
    sla = rules.get("first_follow_up_sla_hours", before["first_follow_up_sla_hours"])
    if isinstance(sla, bool) or not isinstance(sla, int) or not 1 <= sla <= 168:
        raise ProductRoutingError("INVALID_RULE", "首触期限须为 1 至 168 的整数小时")
    nested = rules.get("follow_up_policy") or {}
    if not isinstance(nested, Mapping):
        raise ProductRoutingError("INVALID_RULE", "保护期规则须为对象")
    flat = {key: value for key, value in rules.items() if key in DEFAULT_FOLLOW_UP_POLICY}
    if set(flat) & set(nested):
        raise ProductRoutingError("INVALID_RULE", "同一保护期字段不可重复提交")
    try:
        policy = normalize_follow_up_policy({**before["follow_up_policy"], **nested, **flat})
    except (ValueError, TypeError):
        raise ProductRoutingError("INVALID_RULE", "保护小时须为1至8760的整数，到期动作仅支持next或close") from None
    return {"first_follow_up_sla_hours": sla, "follow_up_policy": policy}


def _shared_base_version(session: Session) -> ClueAllocationRuleVersion | None:
    return session.scalar(select(ClueAllocationRuleVersion).join(ClueAllocationRule,
        ClueAllocationRule.rule_id == ClueAllocationRuleVersion.rule_id).where(
        ClueAllocationRule.scope_key == SHARED_BASE_SCOPE_KEY, ClueAllocationRuleVersion.status == "published").limit(1))


def _shared_snapshot(session: Session, version: ClueAllocationRuleVersion | None) -> dict[str, Any]:
    return {"rule_version_id": version.rule_version_id if version else None,
            "first_follow_up_sla_hours": version.first_follow_up_sla_hours if version else 24,
            "follow_up_policy": normalize_follow_up_policy((version.snapshot or {}).get("follow_up_policy") if version else None),
            "can_manage": True}


def _ensure_shared_base_rule(session: Session, actor: Any) -> ClueAllocationRule:
    rule = session.scalar(select(ClueAllocationRule).where(ClueAllocationRule.scope_key == SHARED_BASE_SCOPE_KEY).with_for_update())
    if rule is None:
        try:
            with session.begin_nested():
                rule = ClueAllocationRule(rule_id=_new_id("product-base"), rule_name="精诚养车共享流转基座",
                    scope_type="product_base", scope_key=SHARED_BASE_SCOPE_KEY, created_by=_actor_key(actor))
                session.add(rule)
                session.flush()
        except IntegrityError:
            rule = session.scalar(select(ClueAllocationRule).where(ClueAllocationRule.scope_key == SHARED_BASE_SCOPE_KEY).with_for_update())
    assert rule is not None
    return rule


def _lock_rule_publications(session: Session) -> None:
    # Acquire the shared lock before any product row, including when no base
    # row exists yet. This avoids lock inversion for overlapping batches that
    # initialize the shared base while holding different product rows.
    if session.get_bind().dialect.name == "postgresql":
        session.execute(select(func.pg_advisory_xact_lock(SHARED_BASE_LOCK_KEY)))


def _publish_version(
    session: Session, rule: ClueAllocationRule, actor: Any, settings: Mapping[str, Any], *,
    product_scope: str, base_version_id: str | None = None,
) -> ClueAllocationRuleVersion:
    snapshot = {"schema_version": 2, "product_scope": product_scope,
                "follow_up_policy": deepcopy(settings["follow_up_policy"])}
    if base_version_id:
        snapshot["base_rule_version_id"] = base_version_id
    base = session.get(ClueAllocationRuleVersion, base_version_id) if base_version_id else None
    version = create_rule_version(session, rule.rule_id, auto_expiry_enabled=True,
        first_follow_up_sla_hours=settings["first_follow_up_sla_hours"], protection_days=7,
        conversion_weight=Decimal("0.7"), follow_24h_weight=Decimal("0.3"),
        lookback_days=base.lookback_days if base else 30, min_samples=base.min_samples if base else 20,
        strategy_configs=[
            {"strategy_type": "sales_store_priority", "enabled": True, "execution_order": 1, "params": {"max_distance_km": 10}},
            {"strategy_type": "nearby_city_optimization", "enabled": True, "execution_order": 2, "params": {"max_distance_km": 10, "selection_mode": "score"}},
            {"strategy_type": "city_fallback", "enabled": True, "execution_order": 3, "params": {}},
        ], created_by=_actor_key(actor), snapshot=snapshot)
    return publish_rule_version(session, version.rule_version_id, published_by=_actor_key(actor))


def _locked_config(session: Session, product_id: str) -> ClueProductRoutingConfig:
    config = session.scalar(select(ClueProductRoutingConfig).where(ClueProductRoutingConfig.product_id == product_id).with_for_update().execution_options(populate_existing=True))
    if config is None:
        try:
            with session.begin_nested():
                session.add(ClueProductRoutingConfig(product_id=product_id, routing_enabled=False))
                session.flush()
        except IntegrityError:
            pass
        config = session.scalar(select(ClueProductRoutingConfig).where(ClueProductRoutingConfig.product_id == product_id).with_for_update().execution_options(populate_existing=True))
    assert config is not None
    return config


def _locked_operation(session: Session, actor: Any, key: str, digest: str) -> ClueProductRoutingOperation:
    key = key.strip()
    if not key or len(key) > 128:
        raise ProductRoutingError("INVALID_IDEMPOTENCY_KEY", "幂等标识长度须为 1 至 128", http_status=422)
    identity = (_actor_key(actor), key)
    operation = session.get(ClueProductRoutingOperation, identity, with_for_update=True)
    if operation is None:
        try:
            with session.begin_nested():
                session.add(ClueProductRoutingOperation(actor_key=identity[0], idempotency_key=key, request_sha256=digest))
                session.flush()
        except IntegrityError:
            pass
        operation = session.get(ClueProductRoutingOperation, identity, with_for_update=True, populate_existing=True)
    assert operation is not None
    if operation.request_sha256 != digest:
        raise ProductRoutingError("IDEMPOTENCY_CONFLICT", "同一幂等标识不可用于不同操作", http_status=409)
    return operation


def _can_manage_grants(session: Session, actor: Any) -> bool:
    if getattr(actor, "auth_type", "") == "env_admin":
        return bool(getattr(actor, "can_manage_global_settings", False))
    if getattr(actor, "auth_type", "") != "user" or not getattr(actor, "user_id", None):
        return False
    user = session.get(User, actor.user_id, populate_existing=True)
    return bool(user and user.status == "active" and user.is_initialized and user.role in {"admin", "highest_admin"} and user.store_scope_mode == "all")


def _can_manage_shared_rule(session: Session, actor: Any) -> bool:
    if _can_manage_grants(session, actor):
        return True
    user_id = getattr(actor, "user_id", None)
    if not user_id or getattr(actor, "auth_type", "") != "user":
        return False
    return bool(session.scalar(select(exists().where(
        ClueSharedRuleMaintainer.user_id == user_id,
        User.user_id == ClueSharedRuleMaintainer.user_id,
        User.status == "active", User.is_initialized.is_(True),
    ))))


def _require_human_actor(actor: Any) -> None:
    if getattr(actor, "auth_type", "") not in {"user", "env_admin"}:
        raise ProductRoutingError("HUMAN_SESSION_REQUIRED", "商品管理须使用本人交互登录会话", http_status=403)


def _require_grant_manager(session: Session, actor: Any) -> None:
    _require_human_actor(actor)
    if not _can_manage_grants(session, actor):
        raise ProductRoutingError("GRANT_MANAGEMENT_FORBIDDEN", "仅全部门店范围管理员可以管理商品授权与共享基座维护人", http_status=403)


def _require_shared_rule_maintainer(session: Session, actor: Any) -> None:
    _require_human_actor(actor)
    if not _can_manage_shared_rule(session, actor):
        raise ProductRoutingError("SHARED_RULE_FORBIDDEN", "仅获授权的精诚共享规则维护人可以维护共享基座", http_status=403)


def _actor_key(actor: Any) -> str:
    return f"user:{actor.user_id}" if getattr(actor, "user_id", None) else f"env:{actor.username}"


def _rule_settings(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {"first_follow_up_sla_hours": snapshot["first_follow_up_sla_hours"], "follow_up_policy": snapshot["follow_up_policy"]}


def _normalized_ids(values: Sequence[str]) -> list[str]:
    if isinstance(values, (str, bytes)) or any(not isinstance(value, str) or not value.strip() for value in values):
        raise ProductRoutingError("INVALID_IDENTIFIERS", "编码须为非空字符串", http_status=422)
    return sorted({value.strip() for value in values})


def _digest(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _audit(
    session: Session, actor: Any, event: str, product_id: str | None,
    before: dict[str, Any], after: dict[str, Any], *, request_id: str | None = None,
    detail: dict[str, Any] | None = None, error: str | None = None,
) -> None:
    session.add(ClueAllocationAuditLog(audit_log_id=_new_id("product-audit"), event_type=event,
        actor=getattr(actor, "username", None), actor_user_id=getattr(actor, "user_id", None),
        actor_username_snapshot=getattr(actor, "username", None), actor_role_snapshot=getattr(actor, "role", None),
        actor_scope_snapshot={"store_scope_mode": getattr(actor, "store_scope_mode", None)},
        request_id=request_id, result_status="failed" if error else "success", reason_code=error,
        privileged_confirmation=event == "product_routing_enable" and error is None and bool((detail or {}).get("authorization_note")),
        before_snapshot=deepcopy(before), after_snapshot=deepcopy(after),
        detail_json={"product_id": product_id, **(detail or {})}))
