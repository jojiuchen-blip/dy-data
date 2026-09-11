"""Resolve an order owner to one store from auditable account evidence."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo


BEIJING = ZoneInfo("Asia/Shanghai")
_SUCCESS_CODES = {"2", "105"}
_SUCCESS_TEXT = {"active", "bound", "认证成功", "绑定成功", "已绑定"}
_UNBOUND_CODES = {"5"}
_UNBOUND_TEXT = {"unbound", "已解绑", "解绑"}


@dataclass(frozen=True)
class OrderAttributionResult:
    """A store resolution with safe, non-nickname audit evidence."""

    store_id: str | None
    reason: str
    source_identifiers: tuple[str, ...]
    historical_period_unverified: bool


@dataclass(frozen=True)
class _Candidate:
    store_id: str | None
    source_identifier: str
    method: str
    valid: bool
    historical_period_unverified: bool
    failure: str | None = None
    ambiguous_latest: bool = False


class OrderAttributionIndex:
    """Preprocessed account and binding evidence reusable across many orders."""

    def __init__(
        self,
        *,
        accounts: Iterable[Any],
        bindings: Iterable[Any],
        poi_to_store: Mapping[object, object] | Iterable[Any],
    ) -> None:
        self._poi_stores = _collect_poi_stores(poi_to_store)
        latest_accounts, ambiguous_accounts = _latest_rows(
            accounts, _account_identity, _account_material_signature
        )
        latest_bindings, ambiguous_bindings = _latest_binding_rows(bindings)

        self._accounts_by_id: defaultdict[str, list[tuple[Any, bool]]] = defaultdict(list)
        self._accounts_by_name: defaultdict[str, list[tuple[Any, bool]]] = defaultdict(list)
        for row in latest_accounts:
            indexed = (row, _account_identity(row) in ambiguous_accounts)
            account_id = _identifier(getattr(row, "account_id", None))
            if account_id is not None:
                self._accounts_by_id[account_id].append(indexed)
            nickname = getattr(row, "nickname", None)
            if isinstance(nickname, str) and nickname.strip() != "":
                self._accounts_by_name[nickname].append(indexed)

        self._bindings_by_account_id: defaultdict[
            str, list[tuple[Any, bool]]
        ] = defaultdict(list)
        self._bindings_by_douyin_uid: defaultdict[
            str, list[tuple[Any, bool]]
        ] = defaultdict(list)
        self._bindings_by_name: defaultdict[str, list[tuple[Any, bool]]] = defaultdict(list)
        for row in latest_bindings:
            indexed = (row, id(row) in ambiguous_bindings)
            for account_id in _binding_account_ids(row):
                self._bindings_by_account_id[account_id].append(indexed)
            for douyin_uid in _binding_douyin_ids(row):
                self._bindings_by_douyin_uid[douyin_uid].append(indexed)
            names = {
                name
                for name in (
                    getattr(row, "douyin_nickname", None),
                    getattr(row, "account_name", None),
                )
                if isinstance(name, str) and name.strip() != ""
            }
            for name in names:
                self._bindings_by_name[name].append(indexed)

    def resolve(
        self,
        *,
        occurred_at: datetime,
        owner_account_id: object | None = None,
        owner_douyin_uid: object | None = None,
        owner_account_name: object | None = None,
    ) -> OrderAttributionResult:
        """Resolve one order using the already prepared dimension indexes."""

        at = _as_aware_utc(occurred_at)
        account_id = _identifier(owner_account_id)
        douyin_uid = _identifier(owner_douyin_uid)
        owner_name = owner_account_name if isinstance(owner_account_name, str) else None

        explicit: list[_Candidate] = []
        if account_id is not None:
            explicit.extend(
                _account_candidate(
                    row, at, method="owner_account_id", ambiguous=ambiguous
                )
                for row, ambiguous in self._accounts_by_id.get(account_id, ())
            )
            explicit.extend(
                _binding_candidate(
                    row,
                    at,
                    self._poi_stores,
                    method="owner_account_id",
                    ambiguous=ambiguous,
                )
                for row, ambiguous in self._bindings_by_account_id.get(account_id, ())
            )
        if douyin_uid is not None:
            explicit.extend(
                _binding_candidate(
                    row,
                    at,
                    self._poi_stores,
                    method="owner_douyin_uid",
                    ambiguous=ambiguous,
                )
                for row, ambiguous in self._bindings_by_douyin_uid.get(douyin_uid, ())
            )
        if explicit:
            return _resolve_candidates(explicit, by_name=False)

        if owner_name is None or owner_name.strip() == "":
            return _unresolved("missing_account_binding")

        by_name = [
            _account_candidate(row, at, method="owner_name", ambiguous=ambiguous)
            for row, ambiguous in self._accounts_by_name.get(owner_name, ())
        ]
        by_name.extend(
            _binding_candidate(
                row,
                at,
                self._poi_stores,
                method="owner_name",
                ambiguous=ambiguous,
            )
            for row, ambiguous in self._bindings_by_name.get(owner_name, ())
        )
        return _resolve_candidates(by_name, by_name=True) if by_name else _unresolved(
            "missing_account_binding"
        )


def resolve_order_attribution(
    *,
    occurred_at: datetime,
    owner_account_id: object | None,
    owner_douyin_uid: object | None,
    owner_account_name: object | None,
    accounts: Iterable[Any],
    bindings: Iterable[Any],
    poi_to_store: Mapping[object, object] | Iterable[Any],
) -> OrderAttributionResult:
    """Resolve one order owner without guessing across stores or identity fields.

    ``accounts`` and ``bindings`` accept ORM instances or attribute-compatible
    objects. ``poi_to_store`` accepts either a mapping or an iterable of objects
    exposing ``poi_id`` and ``store_id`` (two-item tuples are also accepted).
    """

    return OrderAttributionIndex(
        accounts=accounts,
        bindings=bindings,
        poi_to_store=poi_to_store,
    ).resolve(
        occurred_at=occurred_at,
        owner_account_id=owner_account_id,
        owner_douyin_uid=owner_douyin_uid,
        owner_account_name=owner_account_name,
    )


def _resolve_candidates(candidates: list[_Candidate], *, by_name: bool) -> OrderAttributionResult:
    sources = tuple(sorted({candidate.source_identifier for candidate in candidates}))
    if any(candidate.ambiguous_latest for candidate in candidates):
        return OrderAttributionResult(None, "ambiguous_latest_binding", sources, False)
    if any(candidate.failure == "conflicting_poi_mapping" for candidate in candidates):
        return OrderAttributionResult(None, "conflicting_poi_mapping", sources, False)

    pointed_stores = {candidate.store_id for candidate in candidates if candidate.store_id}
    if len(pointed_stores) > 1:
        reason = "conflicting_name_binding" if by_name else "conflicting_account_binding"
        return OrderAttributionResult(None, reason, sources, False)

    valid = [candidate for candidate in candidates if candidate.valid and candidate.store_id]
    stores = {candidate.store_id for candidate in valid}
    if not valid:
        failures = {candidate.failure for candidate in candidates}
        reason = "missing_poi_mapping" if failures == {"missing_poi_mapping"} else "invalid_account_binding"
        return OrderAttributionResult(None, reason, sources, False)

    methods = {candidate.method for candidate in valid}
    if by_name:
        reason = "resolved_owner_name"
    elif methods == {"owner_account_id"}:
        reason = "resolved_owner_account_id"
    elif methods == {"owner_douyin_uid"}:
        reason = "resolved_owner_douyin_uid"
    else:
        reason = "resolved_explicit_ids"
    historical_unverified = all(
        candidate.historical_period_unverified for candidate in valid
    )
    return OrderAttributionResult(next(iter(stores)), reason, sources, historical_unverified)


def _unresolved(reason: str) -> OrderAttributionResult:
    return OrderAttributionResult(None, reason, (), False)


def _account_candidate(
    row: Any, at: datetime, *, method: str, ambiguous: bool
) -> _Candidate:
    account_id = _identifier(getattr(row, "account_id", None)) or "unknown"
    source = f"dim_aweme_account:{account_id}:{'name' if method == 'owner_name' else method}"
    store_id = _identifier(getattr(row, "store_id", None))
    status = _status_kind(getattr(row, "binding_status", None), missing_is_success=True)
    start, start_valid = _as_date_boundary(getattr(row, "valid_from", None))
    end, end_valid = _as_date_boundary(getattr(row, "valid_to", None))
    local_day = at.astimezone(BEIJING).date()
    complete = start is not None and end is not None

    valid = start_valid and end_valid and store_id is not None
    if status == "success":
        valid = valid and (start is None or start <= local_day) and (end is None or local_day <= end)
    elif status == "unbound":
        valid = valid and complete and start <= local_day <= end
    else:
        valid = False
    return _Candidate(
        store_id,
        source,
        method,
        valid,
        valid and not complete,
        None if valid else "invalid_account_binding",
        ambiguous,
    )


def _binding_candidate(
    row: Any,
    at: datetime,
    poi_stores: Mapping[str, set[str]],
    *,
    method: str,
    ambiguous: bool,
) -> _Candidate:
    key = _identifier(getattr(row, "binding_key", None)) or "unknown"
    source = f"raw_aweme_binding:{key}:{'name' if method == 'owner_name' else method}"
    stores = poi_stores.get(_identifier(getattr(row, "poi_id", None)) or "", set())
    if len(stores) > 1:
        return _Candidate(None, source, method, False, False, "conflicting_poi_mapping", ambiguous)
    store_id = next(iter(stores)) if stores else None
    payload = getattr(row, "raw_payload", None)
    payload = payload if isinstance(payload, Mapping) else {}
    start_provided, start, start_valid = _epoch_boundary(payload.get("bind_start_time"))
    end_provided, end, end_valid = _epoch_boundary(payload.get("bind_end_time"))
    complete = start_provided and end_provided and start_valid and end_valid
    status = _status_kind(getattr(row, "binding_status", None), missing_is_success=False)

    valid = store_id is not None and start_valid and end_valid
    if start is not None and end is not None and start > end:
        valid = False
    if status == "success":
        valid = valid and (start is None or start <= at) and (end is None or at <= end)
    elif status == "unbound":
        valid = valid and complete and start <= at <= end
    else:
        valid = False

    failure = None if valid else ("missing_poi_mapping" if store_id is None else "invalid_account_binding")
    return _Candidate(
        store_id,
        source,
        method,
        valid,
        valid and not complete,
        failure,
        ambiguous,
    )


def _collect_poi_stores(
    value: Mapping[object, object] | Iterable[Any],
) -> dict[str, set[str]]:
    result: defaultdict[str, set[str]] = defaultdict(set)
    rows = value.items() if isinstance(value, Mapping) else value
    for row in rows:
        if isinstance(row, tuple) and len(row) == 2:
            poi_id, store_value = row
        else:
            poi_id = getattr(row, "poi_id", None)
            store_value = getattr(row, "store_id", None)
        poi = _identifier(poi_id)
        if poi is None:
            continue
        if isinstance(store_value, (set, tuple, list, frozenset)):
            stores = store_value
        else:
            stores = (store_value,)
        for store_value_item in stores:
            store = _identifier(store_value_item)
            if store is not None:
                result[poi].add(store)
    return dict(result)


def _latest_rows(
    rows: Iterable[Any], identity_key: Any, material_signature: Any
) -> tuple[list[Any], set[tuple[Any, ...]]]:
    grouped: defaultdict[tuple[Any, ...], list[Any]] = defaultdict(list)
    for row in rows:
        grouped[identity_key(row)].append(row)
    selected: list[Any] = []
    ambiguous: set[tuple[Any, ...]] = set()
    for identity, versions in grouped.items():
        latest = max((_updated_at(row) for row in versions), default=datetime.min.replace(tzinfo=timezone.utc))
        winners = [row for row in versions if _updated_at(row) == latest]
        if len({material_signature(row) for row in winners}) > 1:
            ambiguous.add(identity)
        selected.extend(winners)
    return selected, ambiguous


def _latest_binding_rows(rows: Iterable[Any]) -> tuple[list[Any], set[int]]:
    """Collapse safely linked binding versions before any lookup index is built."""

    materialized = list(rows)
    parents = list(range(len(materialized)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    owners: dict[tuple[str | None, str, str], int] = {}
    for index, row in enumerate(materialized):
        identity = _binding_identity(row)
        poi_id = identity[-1]
        identifiers = identity[:-1]
        tokens = [
            (poi_id, field, value)
            for field, value in zip(
                ("account_id", "craftsman_uid", "settlement_id", "douyin_id"),
                identifiers,
            )
            if value is not None
        ]
        if not tokens:
            key = _identifier(getattr(row, "binding_key", None)) or f"row:{index}"
            tokens = [(poi_id, "binding_key", key)]
        for token in tokens:
            previous = owners.setdefault(token, index)
            union(index, previous)

    components: defaultdict[int, list[Any]] = defaultdict(list)
    for index, row in enumerate(materialized):
        components[find(index)].append(row)

    selected: list[Any] = []
    ambiguous_rows: set[int] = set()
    for component in components.values():
        identities = [_binding_identity(row) for row in component]
        conflicts = any(
            len({identity[field] for identity in identities if identity[field] is not None}) > 1
            for field in range(4)
        )
        if conflicts:
            exact_groups: defaultdict[tuple[Any, ...], list[Any]] = defaultdict(list)
            for row in component:
                exact_groups[_binding_identity(row)].append(row)
            groups = exact_groups.values()
        else:
            groups = (component,)
        for versions in groups:
            latest = max(_updated_at(row) for row in versions)
            winners = [row for row in versions if _updated_at(row) == latest]
            if len({_binding_material_signature(row) for row in winners}) > 1:
                ambiguous_rows.update(id(row) for row in winners)
            selected.extend(winners)
    return selected, ambiguous_rows


def _account_identity(row: Any) -> tuple[Any, ...]:
    return (_identifier(getattr(row, "account_id", None)), _identifier(getattr(row, "store_id", None)))


def _account_material_signature(row: Any) -> tuple[Any, ...]:
    return (
        _status_value(getattr(row, "binding_status", None)),
        _boundary_signature(getattr(row, "valid_from", None)),
        _boundary_signature(getattr(row, "valid_to", None)),
        getattr(row, "nickname", None),
    )


def _binding_identity(row: Any) -> tuple[Any, ...]:
    payload = getattr(row, "raw_payload", None)
    payload = payload if isinstance(payload, Mapping) else {}
    return (
        _identifier(getattr(row, "account_id", None)),
        _identifier(payload.get("craftsman_uid")),
        _identifier(payload.get("account_id_for_settlement")),
        _identifier(getattr(row, "douyin_id", None)),
        _identifier(getattr(row, "poi_id", None)),
    )


def _binding_material_signature(row: Any) -> tuple[Any, ...]:
    payload = getattr(row, "raw_payload", None)
    payload = payload if isinstance(payload, Mapping) else {}
    return (
        _status_value(getattr(row, "binding_status", None)),
        _boundary_signature(payload.get("bind_start_time")),
        _boundary_signature(payload.get("bind_end_time")),
        getattr(row, "douyin_nickname", None),
        getattr(row, "account_name", None),
    )


def _binding_account_ids(row: Any) -> set[str]:
    payload = getattr(row, "raw_payload", None)
    payload = payload if isinstance(payload, Mapping) else {}
    return {
        value
        for value in (
            _identifier(getattr(row, "account_id", None)),
            _identifier(payload.get("account_id_for_settlement")),
        )
        if value is not None
    }


def _binding_douyin_ids(row: Any) -> set[str]:
    payload = getattr(row, "raw_payload", None)
    payload = payload if isinstance(payload, Mapping) else {}
    return {
        value
        for value in (
            _identifier(getattr(row, "douyin_id", None)),
            _identifier(payload.get("craftsman_uid")),
        )
        if value is not None
    }


def _identifier(value: object | None) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value)
    return text if text != "" else None


def _status_value(value: object | None) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    return str(value).strip().lower()


def _status_kind(value: object | None, *, missing_is_success: bool) -> str:
    normalized = _status_value(value)
    if normalized is None:
        return "success" if missing_is_success else "invalid"
    if normalized in _SUCCESS_CODES or normalized in _SUCCESS_TEXT:
        return "success"
    if normalized in _UNBOUND_CODES or normalized in _UNBOUND_TEXT:
        return "unbound"
    return "invalid"


def _epoch_boundary(value: object | None) -> tuple[bool, datetime | None, bool]:
    if isinstance(value, bool):
        return True, None, False
    if value is None or value == 0 or value == "0":
        return False, None, True
    if isinstance(value, int):
        raw = value
    elif isinstance(value, str) and value.isdigit():
        raw = int(value)
    else:
        return True, None, False
    if raw <= 0:
        return True, None, False
    seconds = raw / 1000 if raw >= 100_000_000_000 else raw
    try:
        return True, datetime.fromtimestamp(seconds, tz=timezone.utc), True
    except (OverflowError, OSError, ValueError):
        return True, None, False


def _as_date_boundary(value: object | None) -> tuple[date | None, bool]:
    if value is None:
        return None, True
    if isinstance(value, datetime):
        return value.astimezone(BEIJING).date() if value.tzinfo else value.date(), True
    if isinstance(value, date):
        return value, True
    return None, False


def _as_aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("occurred_at must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _updated_at(row: Any) -> datetime:
    value = getattr(row, "updated_at", None)
    if not isinstance(value, datetime):
        return datetime.min.replace(tzinfo=timezone.utc)
    return _as_aware_utc(value)


def _boundary_signature(value: object | None) -> tuple[str, str]:
    return type(value).__name__, repr(value)
