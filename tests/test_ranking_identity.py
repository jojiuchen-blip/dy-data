from datetime import date, datetime, timezone
from time import perf_counter
from types import SimpleNamespace

import pytest

from apps.api.dy_api import ranking_identity
from apps.api.dy_api.ranking_identity import resolve_order_attribution


SALE_AT = datetime(2026, 9, 11, 4, 0, tzinfo=timezone.utc)


def account(
    account_id: str,
    store_id: str | None,
    *,
    nickname: str | None = None,
    status: object = None,
    valid_from: date | None = None,
    valid_to: date | None = None,
    updated_at: datetime | None = None,
):
    return SimpleNamespace(
        account_id=account_id,
        store_id=store_id,
        nickname=nickname,
        binding_status=status,
        valid_from=valid_from,
        valid_to=valid_to,
        updated_at=updated_at,
    )


def binding(
    key: str,
    poi_id: str,
    *,
    account_id: str | None = None,
    douyin_id: str | None = None,
    nickname: str | None = None,
    account_name: str | None = None,
    status: object = "2",
    payload: dict | None = None,
    updated_at: datetime | None = None,
):
    return SimpleNamespace(
        binding_key=key,
        poi_id=poi_id,
        account_id=account_id,
        douyin_id=douyin_id,
        douyin_nickname=nickname,
        account_name=account_name,
        binding_status=status,
        raw_payload=payload or {},
        updated_at=updated_at,
    )


def resolve(*, accounts=(), bindings=(), pois=None, **identity):
    return resolve_order_attribution(
        occurred_at=identity.pop("occurred_at", SALE_AT),
        owner_account_id=identity.pop("owner_account_id", None),
        owner_douyin_uid=identity.pop("owner_douyin_uid", None),
        owner_account_name=identity.pop("owner_account_name", None),
        accounts=accounts,
        bindings=bindings,
        poi_to_store=pois or {"poi-a": "store-a", "poi-b": "store-b"},
    )


@pytest.mark.parametrize("status", [2, "2", 105, "105", "active", "bound", "认证成功", "绑定成功", "已绑定"])
def test_official_and_legacy_success_statuses_resolve_binding(status):
    result = resolve(
        owner_account_id="settlement-a",
        bindings=[binding("b-a", "poi-a", status=status, payload={"account_id_for_settlement": "settlement-a"})],
    )

    assert result.store_id == "store-a"
    assert result.reason == "resolved_owner_account_id"
    assert result.historical_period_unverified is True


@pytest.mark.parametrize("status", [1, "1", 106, "106", "待确认", "停用", "inactive"])
def test_pending_and_disabled_statuses_are_not_success(status):
    result = resolve(
        owner_account_id="account-a",
        bindings=[binding("b-a", "poi-a", account_id="account-a", status=status)],
    )

    assert result.store_id is None
    assert result.reason == "invalid_account_binding"


def test_owner_account_and_douyin_uid_use_their_own_known_identifiers():
    row = binding(
        "b-a",
        "poi-a",
        account_id="binding-account",
        douyin_id="douyin-number",
        payload={
            "craftsman_uid": "craftsman-uid",
            "account_id_for_settlement": "settlement-account",
        },
    )

    by_settlement = resolve(owner_account_id="settlement-account", bindings=[row])
    by_uid = resolve(owner_douyin_uid="craftsman-uid", bindings=[row])

    assert (by_settlement.store_id, by_settlement.reason) == ("store-a", "resolved_owner_account_id")
    assert (by_uid.store_id, by_uid.reason) == ("store-a", "resolved_owner_douyin_uid")
    assert all("craftsman-uid" not in source for source in by_settlement.source_identifiers)


def test_exact_name_fallback_rejects_cross_store_duplicates_and_blank_or_fuzzy_names():
    rows = [
        account("a", "store-a", nickname="同名职人", status="2"),
        binding("b", "poi-b", nickname="同名职人", status="105"),
    ]

    conflict = resolve(owner_account_name="同名职人", accounts=rows[:1], bindings=rows[1:])
    fuzzy = resolve(owner_account_name=" 同名职人 ", accounts=rows[:1])
    blank = resolve(owner_account_name="   ", accounts=[account("blank", "store-a", nickname="   ")])

    assert (conflict.store_id, conflict.reason) == (None, "conflicting_name_binding")
    assert (fuzzy.store_id, fuzzy.reason) == (None, "missing_account_binding")
    assert (blank.store_id, blank.reason) == (None, "missing_account_binding")


def test_known_invalid_id_cannot_fall_back_to_a_valid_matching_name():
    result = resolve(
        owner_account_id="known-invalid",
        owner_account_name="好看的昵称",
        accounts=[
            account("known-invalid", "store-a", nickname="旧昵称", status="5"),
            account("other", "store-b", nickname="好看的昵称", status="2"),
        ],
    )

    assert result.store_id is None
    assert result.reason == "invalid_account_binding"


def test_direct_account_and_binding_different_stores_are_a_conflict():
    result = resolve(
        owner_account_id="account-a",
        accounts=[account("account-a", "store-a", status="2")],
        bindings=[binding("b-b", "poi-b", account_id="account-a", status="2")],
    )

    assert result.store_id is None
    assert result.reason == "conflicting_account_binding"


def test_invalid_direct_id_still_exposes_a_different_store_binding_conflict():
    result = resolve(
        owner_account_id="account-a",
        accounts=[account("account-a", "store-a", status="5")],
        bindings=[binding("b-b", "poi-b", account_id="account-a", status="2")],
    )

    assert result.store_id is None
    assert result.reason == "conflicting_account_binding"


def test_binding_seconds_and_milliseconds_boundaries_are_inclusive():
    instant_seconds = int(SALE_AT.timestamp())
    seconds = resolve(
        owner_account_id="seconds",
        bindings=[binding("seconds", "poi-a", account_id="seconds", payload={
            "bind_start_time": instant_seconds,
            "bind_end_time": instant_seconds,
        })],
    )
    milliseconds = resolve(
        owner_account_id="milliseconds",
        bindings=[binding("milliseconds", "poi-a", account_id="milliseconds", payload={
            "bind_start_time": instant_seconds * 1000,
            "bind_end_time": instant_seconds * 1000,
        })],
    )

    assert seconds.store_id == milliseconds.store_id == "store-a"
    assert seconds.historical_period_unverified is milliseconds.historical_period_unverified is False


def test_open_current_interval_is_usable_but_marked_historically_unverified():
    result = resolve(
        owner_account_id="account-a",
        bindings=[binding("b-a", "poi-a", account_id="account-a", payload={
            "bind_start_time": int(SALE_AT.timestamp()) - 1,
        })],
    )

    assert result.store_id == "store-a"
    assert result.historical_period_unverified is True


@pytest.mark.parametrize(
    "payload",
    [
        {"bind_start_time": "not-a-time"},
        {"bind_start_time": False},
        {"bind_start_time": 1.5},
        {"bind_end_time": -1},
        {"bind_start_time": int(SALE_AT.timestamp()) + 1},
        {"bind_end_time": int(SALE_AT.timestamp()) - 1},
    ],
)
def test_illegal_or_out_of_period_binding_time_is_invalid(payload):
    result = resolve(
        owner_account_id="account-a",
        bindings=[binding("b-a", "poi-a", account_id="account-a", payload=payload)],
    )

    assert result.store_id is None
    assert result.reason == "invalid_account_binding"


def test_zero_binding_times_are_missing_boundaries_not_epoch_boundaries():
    result = resolve(
        owner_account_id="account-a",
        bindings=[binding("b-a", "poi-a", account_id="account-a", payload={
            "bind_start_time": 0,
            "bind_end_time": "0",
        })],
    )

    assert result.store_id == "store-a"
    assert result.historical_period_unverified is True


def test_unbound_status_is_historical_only_with_a_complete_covering_interval():
    instant = int(SALE_AT.timestamp())
    covered = binding("covered", "poi-a", account_id="covered", status=5, payload={
        "bind_start_time": instant - 60,
        "bind_end_time": instant + 60,
    })
    incomplete = binding("incomplete", "poi-a", account_id="incomplete", status=5, payload={
        "bind_start_time": instant - 60,
    })

    assert resolve(owner_account_id="covered", bindings=[covered]).store_id == "store-a"
    assert resolve(owner_account_id="covered", bindings=[covered]).historical_period_unverified is False
    assert resolve(owner_account_id="incomplete", bindings=[incomplete]).reason == "invalid_account_binding"


def test_disabled_status_cannot_be_revived_by_a_complete_historical_interval():
    instant = int(SALE_AT.timestamp())
    result = resolve(
        owner_account_id="disabled",
        bindings=[binding("disabled", "poi-a", account_id="disabled", status=106, payload={
            "bind_start_time": instant - 60,
            "bind_end_time": instant + 60,
        })],
    )

    assert result.store_id is None
    assert result.reason == "invalid_account_binding"


def test_dim_account_validity_uses_beijing_transaction_date():
    # 16:30 UTC is already the following calendar date in Beijing.
    occurred_at = datetime(2026, 9, 10, 16, 30, tzinfo=timezone.utc)
    valid = account("valid", "store-a", valid_from=date(2026, 9, 11), valid_to=date(2026, 9, 11))
    expired = account("expired", "store-a", nickname="same", valid_to=date(2026, 9, 10))

    resolved = resolve(owner_account_id="valid", accounts=[valid], occurred_at=occurred_at)
    rejected = resolve(
        owner_account_id="expired",
        owner_account_name="same",
        accounts=[expired, account("other", "store-b", nickname="same", status="2")],
        occurred_at=occurred_at,
    )

    assert resolved.store_id == "store-a"
    assert resolved.historical_period_unverified is False
    assert rejected.reason == "invalid_account_binding"


def test_latest_binding_row_wins_but_an_equal_time_status_conflict_is_not_guessed():
    old = datetime(2026, 9, 1, tzinfo=timezone.utc)
    new = datetime(2026, 9, 2, tzinfo=timezone.utc)
    identity = dict(account_id="account-a", douyin_id="dy-a")
    latest_success = [
        binding("old", "poi-a", status=1, updated_at=old, **identity),
        binding("new", "poi-a", status=2, updated_at=new, **identity),
    ]
    tie = [
        binding("tie-active", "poi-a", status=2, updated_at=new, **identity),
        binding("tie-disabled", "poi-a", status=106, updated_at=new, **identity),
    ]

    assert resolve(owner_account_id="account-a", bindings=latest_success).store_id == "store-a"
    assert resolve(owner_account_id="account-a", bindings=tie).reason == "ambiguous_latest_binding"


def test_equal_time_name_conflict_for_one_identity_is_not_guessed():
    updated_at = datetime(2026, 9, 2, tzinfo=timezone.utc)
    rows = [
        binding("name-a", "poi-a", account_id="account-a", nickname="名字甲", updated_at=updated_at),
        binding("name-b", "poi-a", account_id="account-a", nickname="名字乙", updated_at=updated_at),
    ]

    result = resolve(owner_account_name="名字甲", bindings=rows)

    assert result.store_id is None
    assert result.reason == "ambiguous_latest_binding"


def test_latest_binding_survives_optional_identifier_enrichment_before_name_indexing():
    old = datetime(2026, 9, 1, tzinfo=timezone.utc)
    new = datetime(2026, 9, 2, tzinfo=timezone.utc)
    rows = [
        binding(
            "old-active",
            "poi-a",
            account_id="account-a",
            douyin_id="douyin-a",
            nickname="旧昵称",
            status=2,
            updated_at=old,
        ),
        binding(
            "new-disabled",
            "poi-a",
            account_id="account-a",
            douyin_id="douyin-a",
            nickname="新昵称",
            status=106,
            payload={
                "craftsman_uid": "craftsman-a",
                "account_id_for_settlement": "settlement-a",
            },
            updated_at=new,
        ),
    ]

    stale_name = resolve(owner_account_name="旧昵称", bindings=rows)
    current_name = resolve(owner_account_name="新昵称", bindings=rows)

    assert (stale_name.store_id, stale_name.reason) == (None, "missing_account_binding")
    assert (current_name.store_id, current_name.reason) == (None, "invalid_account_binding")


def test_conflicting_explicit_identifiers_are_not_merged_as_one_latest_identity():
    old = datetime(2026, 9, 1, tzinfo=timezone.utc)
    new = datetime(2026, 9, 2, tzinfo=timezone.utc)
    rows = [
        binding(
            "douyin-old",
            "poi-a",
            account_id="shared-account",
            douyin_id="douyin-old",
            status=2,
            updated_at=old,
        ),
        binding(
            "douyin-new",
            "poi-a",
            account_id="shared-account",
            douyin_id="douyin-new",
            status=106,
            updated_at=new,
        ),
    ]

    result = resolve(owner_douyin_uid="douyin-old", bindings=rows)

    assert result.store_id == "store-a"
    assert result.reason == "resolved_owner_douyin_uid"


def test_identity_key_keeps_different_pois_and_conflicting_poi_maps_visible():
    cross_store = [
        binding("a", "poi-a", account_id="account-a"),
        binding("b", "poi-b", account_id="account-a"),
    ]
    duplicate_poi_map = [
        SimpleNamespace(poi_id="poi-a", store_id="store-a"),
        SimpleNamespace(poi_id="poi-a", store_id="store-b"),
    ]

    assert resolve(owner_account_id="account-a", bindings=cross_store).reason == "conflicting_account_binding"
    assert resolve(
        owner_account_id="account-a",
        bindings=[binding("a", "poi-a", account_id="account-a")],
        pois=duplicate_poi_map,
    ).reason == "conflicting_poi_mapping"


def test_audit_sources_identify_rows_without_echoing_nicknames():
    secret_nickname = "昵称不得进入审计证据"
    result = resolve(
        owner_account_name=secret_nickname,
        bindings=[binding("safe-key", "poi-a", nickname=secret_nickname)],
    )

    assert result.store_id == "store-a"
    assert result.source_identifiers == ("raw_aweme_binding:safe-key:name",)
    assert secret_nickname not in repr(result)


class CountingIterable:
    def __init__(self, rows):
        self.rows = rows
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        return iter(self.rows)


def test_reusable_index_consumes_dimension_inputs_once_for_multiple_orders():
    assert hasattr(ranking_identity, "OrderAttributionIndex")
    accounts = CountingIterable([account("account-a", "store-a", status=2)])
    bindings = CountingIterable(
        [binding("binding-b", "poi-b", account_id="account-b", status=105)]
    )
    pois = CountingIterable(
        [
            SimpleNamespace(poi_id="poi-a", store_id="store-a"),
            SimpleNamespace(poi_id="poi-b", store_id="store-b"),
        ]
    )

    index = ranking_identity.OrderAttributionIndex(
        accounts=accounts,
        bindings=bindings,
        poi_to_store=pois,
    )
    first = index.resolve(occurred_at=SALE_AT, owner_account_id="account-a")
    second = index.resolve(occurred_at=SALE_AT, owner_account_id="account-b")

    assert (first.store_id, second.store_id) == ("store-a", "store-b")
    assert (accounts.iterations, bindings.iterations, pois.iterations) == (1, 1, 1)


def test_reusable_index_handles_thousands_of_orders_without_rescanning_13000_dimensions():
    assert hasattr(ranking_identity, "OrderAttributionIndex")
    accounts = [
        account(f"account-{index}", f"store-{index}", status=2)
        for index in range(13_000)
    ]

    started = perf_counter()
    index = ranking_identity.OrderAttributionIndex(
        accounts=accounts,
        bindings=[],
        poi_to_store={},
    )
    results = [
        index.resolve(
            occurred_at=SALE_AT,
            owner_account_id=f"account-{order_index % 13_000}",
        )
        for order_index in range(5_000)
    ]
    elapsed = perf_counter() - started

    assert all(result.store_id is not None for result in results)
    assert elapsed < 5.0
