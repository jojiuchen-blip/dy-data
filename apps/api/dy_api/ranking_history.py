"""Corroborate an old API nickname using two independent stable identity pairs.

This is ranking evidence only. Never manufacture a POI on a collected record
or use a present-day account binding on its own to infer a past sale.
"""
from collections import defaultdict
from dataclasses import dataclass

from apps.api.dy_api.ranking_identity import OrderAttributionResult


@dataclass(frozen=True)
class Alias:
    store: str
    douyin: str
    old: str
    current: str
    source_keys: tuple[str, str]
    witnessed_names: frozenset[str]


def _payload(row):
    return row.raw_payload if isinstance(row.raw_payload, dict) else {}


def _text(value):
    return str(value).strip() if value is not None else ""


def _unbounded(row):
    return all(_payload(row).get(k) in (None, "", 0, "0") for k in ("bind_start_time", "bind_end_time"))


def _export_type(row):
    p = _payload(row)
    return next((p[k] for k in ("账号类型", "账户类型", "account_type") if p.get(k)), None)


def historical_aliases(accounts, bindings, pois):
    """Return only unambiguous, independently corroborated old store names."""
    poi_stores = defaultdict(set)
    for poi, store in pois:
        poi_stores[poi].add(store)
    owners = defaultdict(set)
    names = defaultdict(set)
    groups = defaultdict(list)
    dimensions = defaultdict(list)
    for account in accounts:
        dimensions[account.account_id].append(account)
        if account.nickname:
            names[account.nickname].add(account.account_id)
    for row in bindings:
        owners[row.douyin_id].add(row.account_id)
        groups[row.account_id, row.douyin_id].append(row)
        for name in (row.douyin_nickname, row.account_name):
            if name:
                names[name].add(row.account_id)

    result = defaultdict(set)
    for (store, douyin), rows in groups.items():
        if not store or not douyin or owners[douyin] != {store}:
            continue
        dims = dimensions[store]
        if len(dims) != 1:
            continue
        dim = dims[0]
        # This dimension is keyed by merchant account; the binding below is
        # keyed by BOTH merchant and Douyin handle. Other handles can change
        # the dimension's display name or status without changing this pair.
        if dim.store_id != store or dim.valid_from or dim.valid_to:
            continue
        poi_ids = {r.poi_id for r in rows if r.poi_id}
        if len(poi_ids) != 1 or poi_stores[next(iter(poi_ids))] != {store}:
            continue
        if any(not _unbounded(r) or (r.binding_status not in {"active", "审核中", "认证成功"}
                and not (_export_type(r) == "个人号" and r.binding_status == "已解绑" and r.poi_id))
                for r in rows):
            continue
        new = [r for r in rows if r.poi_id and r.binding_status == "认证成功"
               and _export_type(r) == "子机构门店号"]
        if len(new) != 1 or not new[0].douyin_nickname or names[new[0].douyin_nickname] != {store}:
            continue
        witnessed_names = frozenset(r.douyin_nickname for r in rows
            if r.douyin_nickname and names[r.douyin_nickname] == {store})
        for r in rows:
            old = r.douyin_nickname
            if not old or names[old] != {store} or r.poi_id or r.binding_status != "active":
                continue
            p = _payload(r)
            content = p.get("integration_content")
            user = content.get("user_info") if isinstance(content, dict) else None
            if not isinstance(user, dict):
                continue
            if (_text(p.get("account_id")) != store or _text(p.get("scene_id")) != store or
                    _text(p.get("status")) != "1" or _text(p.get("account_type")) != "20" or
                    _text(user.get("aweme_id")) != douyin):
                continue
            result[old].add(Alias(store, douyin, old, new[0].douyin_nickname,
                (r.binding_key, new[0].binding_key), witnessed_names))
    return {name: next(iter(values)) for name, values in result.items() if len(values) == 1}


def confirmed_order_aliases(aliases, identities):
    """Names locate a source row; the verified account/handle pair proves the store.

    No sale under the new nickname is required. Block reuse of the old name
    across order owners and contradictory identities observed for the owner.
    """
    by_owner = defaultdict(set)
    name_owners = defaultdict(set)
    for account, name, uid in identities:
        if account:
            by_owner[account].add((name, uid))
            name_owners[name].add(account)
    confirmed = {}
    for account, observed in by_owner.items():
        names = {name for name, _ in observed}
        for old in names:
            alias = aliases.get(old)
            if (alias and name_owners[old] == {account} and names <= alias.witnessed_names and
                    all(not uid or uid == alias.douyin for _, uid in observed)):
                confirmed[account, old] = alias
    return confirmed


def load_confirmed_aliases(session, accounts, bindings, pois, limit, cutoff):
    """Bound memory and restrict the extra order read to candidate owner IDs."""
    from sqlalchemy import func, select
    from apps.api.dy_api.models import RawDouyinOrder as Order

    aliases = historical_aliases(accounts, bindings, pois)
    if not aliases:
        return {}
    at = func.coalesce(Order.sale_time, Order.pay_time)
    relevant = select(Order.owner_account_id).where(
        Order.owner_account_name.in_(tuple(aliases)), Order.owner_account_id.is_not(None), at <= cutoff)
    identities = session.execute(select(Order.owner_account_id, Order.owner_account_name,
        Order.owner_douyin_uid).where(Order.owner_account_id.in_(relevant), at <= cutoff)
        .distinct().limit(limit + 1)).all()
    if len(identities) > limit:
        raise ValueError("历史账户身份组合超过核查上限")
    return confirmed_order_aliases(aliases, identities)


def restore_missing_poi(result, confirmed, order):
    """Never replace a resolved order, explicit conflict, or invalid binding."""
    if result.store_id or result.reason != "missing_poi_mapping":
        return result
    alias = confirmed.get((order.owner_account_id, order.owner_account_name))
    if not alias or order.owner_douyin_uid or result.source_identifiers != (
        f"raw_aweme_binding:{alias.source_keys[0]}:name",
    ):
        return result
    return OrderAttributionResult(alias.store, "resolved_historical_store_account",
        result.source_identifiers + (f"raw_aweme_binding:{alias.source_keys[1]}:historical_pair",), True)
