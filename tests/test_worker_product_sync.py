from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dy_api.models import (
    DataQualityIssue,
    DimSkuProductRule,
    JobRun,
    RawDouyinOrder,
    SkuProductSyncHistory,
    SyncSetting,
)
from apps.worker.product_sync import (
    DouyinProductSyncAdapter,
    NormalizedProductSyncAdapter,
    extract_known_order_products,
    execute_product_sync,
    run_product_sync_job,
)
from apps.worker.repositories import queue_job_run


class FixturePages:
    def __init__(self, pages: list[dict]) -> None:
        self.pages = list(pages)
        self.calls: list[tuple[str, str | None]] = []

    def __call__(self, *, mode: str, cursor: str | None) -> dict:
        self.calls.append((mode, cursor))
        return self.pages.pop(0)


def _queue(session: Session, job_id: str = "product-sync-1", mode: str = "FULL") -> JobRun:
    job = queue_job_run(
        session,
        job_id,
        "product_sync",
        metadata_json={"mode": mode, "phase_counts": {}},
    )
    session.flush()
    return job


def _item(*, sku_id: str, sku_name: str, status: str = "ACTIVE") -> dict:
    return {
        "skuId": sku_id,
        "skuName": sku_name,
        "productId": f"product-{sku_id}",
        "productName": f"商品-{sku_id}",
        "spuId": f"spu-{sku_id}",
        "creatorAccountId": "creator-1",
        "creatorAccountName": "创建者",
        "ownerAccountId": "owner-1",
        "ownerAccountName": "归属账号",
        "productStatusRaw": status.lower(),
        "productStatus": status,
    }


def test_product_sync_success_writes_history_and_preserves_manual_fields(db_session: Session) -> None:
    existing = DimSkuProductRule(
        sku_id="sku-1",
        sku_name="旧名称",
        product_scope="手工范围",
        product_type="手工类型",
        is_service_product=True,
        manual_modified_by="admin",
    )
    db_session.add(existing)
    _queue(db_session)
    fixture = FixturePages(
        [
            {
                "items": [_item(sku_id="sku-1", sku_name="新名称")],
                "hasMore": True,
                "nextCursor": "opaque-cursor-1",
            },
            {
                "items": [_item(sku_id="sku-2", sku_name="第二个")],
                "hasMore": False,
                "nextCursor": None,
            },
        ]
    )

    result = execute_product_sync(
        db_session,
        job_id="product-sync-1",
        adapter=NormalizedProductSyncAdapter(fixture),
        observed_at=datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc),
    )

    db_session.flush()
    sku_1 = db_session.scalar(select(DimSkuProductRule).where(DimSkuProductRule.sku_id == "sku-1"))
    sku_2 = db_session.scalar(select(DimSkuProductRule).where(DimSkuProductRule.sku_id == "sku-2"))
    histories = list(db_session.scalars(select(SkuProductSyncHistory).order_by(SkuProductSyncHistory.sku_id)))
    job = db_session.get(JobRun, "product-sync-1")

    assert result.status == "SUCCESS"
    assert (result.observed_count, result.inserted_count, result.updated_count) == (2, 1, 1)
    assert sku_1 is not None and sku_2 is not None
    assert sku_1.sku_name == "新名称"
    assert sku_1.product_scope == "手工范围"
    assert sku_1.product_type == "手工类型"
    assert sku_1.is_service_product is True
    assert sku_1.manual_modified_by == "admin"
    assert sku_1.sync_run_id == "product-sync-1"
    assert sku_2.product_scope == ""
    assert sku_2.product_type == ""
    assert [row.sku_id for row in histories] == ["sku-1", "sku-2"]
    assert all(row.raw_payload and set(row.raw_payload) <= {
        "skuId", "skuName", "productId", "productName", "spuId",
        "creatorAccountId", "creatorAccountName", "ownerAccountId",
        "ownerAccountName", "productStatusRaw", "productStatus",
    } for row in histories)
    assert job is not None and job.status == "success"
    assert job.metadata_json["next_cursor_masked"] is None
    assert "opaque-cursor-1" not in str(job.metadata_json)
    assert fixture.calls == [("FULL", None), ("FULL", "opaque-cursor-1")]


def test_sync_maintains_exact_scope_conversion_without_inferring_membership(db_session: Session) -> None:
    from decimal import Decimal

    for sku_id, scope, product_type in (
        ("target", "精诚养车", "268保养"),
        ("other", "其他", "人工类型"),
        ("code", "jingcheng", "人工类型"),
        ("type-only", "", "精诚养车"),
    ):
        db_session.add(DimSkuProductRule(
            sku_id=sku_id, product_scope=scope, product_type=product_type,
            commission_rate=Decimal(".1234"), manual_modified_by="original-admin",
        ))
    db_session.flush()
    for index in range(2):
        job_id = f"classification-sync-{index}"
        _queue(db_session, job_id=job_id)
        result = execute_product_sync(
            db_session, job_id=job_id,
            adapter=NormalizedProductSyncAdapter(FixturePages([{
                "items": [_item(sku_id=sku_id, sku_name="精诚养车名称不参与分类")
                          for sku_id in ("target", "other", "code", "type-only", "new")],
                "hasMore": False, "nextCursor": None,
            }])),
        )
        assert result.status == "SUCCESS"
        db_session.flush()
    rows = {row.sku_id: row for row in db_session.scalars(select(DimSkuProductRule))}
    assert (rows["target"].product_scope, rows["target"].product_type) == ("精诚养车", "精诚养车")
    assert (rows["other"].product_scope, rows["other"].product_type) == ("其他", "人工类型")
    assert (rows["code"].product_scope, rows["code"].product_type) == ("jingcheng", "人工类型")
    assert (rows["type-only"].product_scope, rows["type-only"].product_type) == ("", "精诚养车")
    assert (rows["new"].product_scope, rows["new"].product_type) == ("", "")
    assert rows["target"].commission_rate == Decimal(".1234")
    assert rows["target"].manual_modified_by == "original-admin"


def test_empty_terminal_page_completes_without_creating_rows(db_session: Session) -> None:
    _queue(db_session)

    result = execute_product_sync(
        db_session,
        job_id="product-sync-1",
        adapter=NormalizedProductSyncAdapter(
            FixturePages([{"items": [], "hasMore": False, "nextCursor": None}])
        ),
    )

    assert result.status == "SUCCESS"
    assert result.observed_count == 0
    assert db_session.scalar(select(JobRun).where(JobRun.job_id == "product-sync-1")).status == "success"


def test_duplicate_page_stops_safely_and_does_not_update_current_snapshot(db_session: Session) -> None:
    _queue(db_session)
    page = {
        "items": [_item(sku_id="sku-1", sku_name="名称")],
        "hasMore": True,
        "nextCursor": "same-cursor",
    }
    fixture = FixturePages([page, page])

    result = execute_product_sync(
        db_session,
        job_id="product-sync-1",
        adapter=NormalizedProductSyncAdapter(fixture),
    )

    assert result.status == "PARTIAL"
    assert db_session.scalar(select(DimSkuProductRule).where(DimSkuProductRule.sku_id == "sku-1")) is None
    issue = db_session.scalar(select(DataQualityIssue).where(DataQualityIssue.source_run_id == "product-sync-1"))
    assert issue is not None and issue.issue_type == "product_sync_duplicate_page"
    job = db_session.get(JobRun, "product-sync-1")
    assert job is not None and job.metadata_json["error_code"] == "DUPLICATE_PAGE"
    assert "same-cursor" not in str(job.metadata_json)


def test_invalid_item_records_quality_issue_and_does_not_advance_success_timestamp(db_session: Session) -> None:
    db_session.add(
        DimSkuProductRule(
            sku_id="sku-existing",
            sku_name="保留",
            product_scope="人工",
            product_type="人工",
            last_synced_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
    )
    _queue(db_session)

    result = execute_product_sync(
        db_session,
        job_id="product-sync-1",
        adapter=NormalizedProductSyncAdapter(
            FixturePages(
                [
                    {
                        "items": [
                            _item(sku_id="sku-valid", sku_name="合法"),
                            {"skuId": "", "skuName": "非法"},
                        ],
                        "hasMore": False,
                        "nextCursor": None,
                    }
                ]
            )
        ),
    )

    assert result.status == "PARTIAL"
    assert db_session.scalar(select(DimSkuProductRule).where(DimSkuProductRule.sku_id == "sku-valid")) is None
    existing = db_session.scalar(
        select(DimSkuProductRule).where(DimSkuProductRule.sku_id == "sku-existing")
    )
    assert existing is not None
    assert existing.last_synced_at is not None
    assert existing.last_synced_at.replace(tzinfo=timezone.utc) == datetime(
        2026, 7, 1, tzinfo=timezone.utc
    )
    issue = db_session.scalar(select(DataQualityIssue).where(DataQualityIssue.source_run_id == "product-sync-1"))
    assert issue is not None and issue.issue_type == "product_sync_invalid_item"


def test_unknown_platform_status_is_not_expanded_to_active(db_session: Session) -> None:
    _queue(db_session)

    result = execute_product_sync(
        db_session,
        job_id="product-sync-1",
        adapter=NormalizedProductSyncAdapter(
            FixturePages(
                [
                    {
                        "items": [_item(sku_id="sku-1", sku_name="名称", status="NEW_ENUM")],
                        "hasMore": False,
                        "nextCursor": None,
                    }
                ]
            )
        ),
    )

    row = db_session.scalar(select(DimSkuProductRule).where(DimSkuProductRule.sku_id == "sku-1"))
    assert result.status == "SUCCESS"
    assert row is not None
    assert row.product_status_normalized == "UNKNOWN"
    assert row.is_active_product is False


def test_invalid_page_response_is_failed_and_recorded_as_data_quality_issue(
    db_session: Session,
) -> None:
    _queue(db_session)

    result = execute_product_sync(
        db_session,
        job_id="product-sync-1",
        adapter=NormalizedProductSyncAdapter(FixturePages([{"hasMore": False}])),
    )

    assert result.status == "FAILED"
    assert result.error_code == "INVALID_RESPONSE"
    issue = db_session.scalar(
        select(DataQualityIssue).where(DataQualityIssue.source_run_id == "product-sync-1")
    )
    assert issue is not None and issue.issue_type == "product_sync_invalid_response"
    assert db_session.scalar(select(DimSkuProductRule)) is None


def test_upstream_failure_is_retryable_and_sensitive_error_is_redacted(
    db_session: Session,
) -> None:
    _queue(db_session)

    def fail_page(*, mode: str, cursor: str | None) -> dict:
        _ = mode, cursor
        raise RuntimeError("token=upstream-sensitive")

    result = execute_product_sync(
        db_session,
        job_id="product-sync-1",
        adapter=NormalizedProductSyncAdapter(fail_page),
    )

    job = db_session.get(JobRun, "product-sync-1")
    assert result.status == "FAILED"
    assert result.error_code == "UPSTREAM_ERROR"
    assert job is not None
    assert job.metadata_json["retryable"] is True
    assert job.error_message == "[redacted sensitive error]"
    assert "upstream-sensitive" not in str(job.metadata_json)


def test_incremental_sync_resumes_internal_cursor_without_exposing_it_in_job_metadata(
    db_session: Session,
) -> None:
    db_session.add(
        SyncSetting(
            setting_key="product_sync.incremental_cursor",
            setting_value="opaque-resume-cursor",
        )
    )
    _queue(db_session, mode="INCREMENTAL")
    fixture = FixturePages(
        [
            {
                "items": [],
                "hasMore": False,
                "nextCursor": "opaque-new-checkpoint",
            }
        ]
    )

    result = execute_product_sync(
        db_session,
        job_id="product-sync-1",
        adapter=NormalizedProductSyncAdapter(fixture),
    )

    cursor = db_session.get(SyncSetting, "product_sync.incremental_cursor")
    job = db_session.get(JobRun, "product-sync-1")
    assert result.status == "SUCCESS"
    assert fixture.calls == [("INCREMENTAL", "opaque-resume-cursor")]
    assert cursor is not None and cursor.setting_value == "opaque-new-checkpoint"
    assert job is not None
    assert job.metadata_json["next_cursor_masked"].startswith("sha256:")
    assert "opaque-resume-cursor" not in str(job.metadata_json)
    assert "opaque-new-checkpoint" not in str(job.metadata_json)


class FakeDouyinProductClient:
    def __init__(self) -> None:
        self.list_calls: list[dict] = []
        self.id_calls: list[list[str]] = []

    def query_online_products(self, **params):
        self.list_calls.append(params)
        status = params["status"]
        if status == 1:
            return {
                "data": {
                    "products": [
                        {
                            "online_status": 1,
                            "product": {
                                "product_id": "product-visible",
                                "product_name": "Current product",
                                "spu_id": "spu-visible",
                                "creator_account_id": 1001,
                                "owner_account_id": 2001,
                                "account_name": "Owner account",
                                "update_time": 1785081600,
                            },
                            "sku": {
                                "sku_id": "sku-visible",
                                "sku_name": "Current SKU",
                            },
                            "skus": [],
                        }
                    ],
                    "has_more": False,
                    "next_cursor": "",
                }
            }
        return {"data": {"products": [], "has_more": False, "next_cursor": ""}}

    def query_online_products_by_id(self, product_ids):
        self.id_calls.append(list(product_ids))
        return {
            "data": {
                "product_onlines": [
                    {
                        "online_status": 3,
                        "product": {
                            "product_id": "product-hidden",
                            "product_name": "Hidden product",
                            "creator_account_id": 1002,
                            "owner_account_id": 2002,
                            "account_name": "Hidden owner",
                        },
                        "skus": [
                            {"sku_id": "sku-hidden", "sku_name": "Hidden SKU"},
                            {"sku_id": "sku-hidden-2", "sku_name": "Second SKU"},
                        ],
                    }
                ]
            }
        }


def test_real_adapter_maps_all_statuses_and_uses_id_fallback():
    client = FakeDouyinProductClient()
    adapter = DouyinProductSyncAdapter(
        client,
        known_products={
            "product-visible": {"sku-visible"},
            "product-hidden": {"sku-hidden"},
        },
    )
    cursor = None
    items = []
    while True:
        page = adapter.fetch_page(mode="FULL", cursor=cursor)
        items.extend(page.items)
        if not page.has_more:
            break
        cursor = page.next_cursor

    by_sku = {item.sku_id: item for item in items}
    assert [call["status"] for call in client.list_calls] == [1, 2, 3]
    assert client.id_calls == [["product-hidden"]]
    assert by_sku["sku-visible"].product_status_normalized == "ACTIVE"
    assert by_sku["sku-visible"].owner_account_id == "2001"
    assert by_sku["sku-visible"].owner_account_name == "Owner account"
    assert by_sku["sku-visible"].product_updated_at == datetime(
        2026, 7, 26, 16, 0, tzinfo=timezone.utc
    )
    assert by_sku["sku-hidden"].product_status_normalized == "BANNED"
    assert by_sku["sku-hidden-2"].product_status_normalized == "BANNED"
    assert "sku-missing" not in by_sku


class MissingSkuDouyinProductClient:
    def query_online_products(self, *, status, cursor, count, goods_query_type):
        _ = cursor, count, goods_query_type
        products = []
        if status == 1:
            products = [
                {
                    "online_status": 1,
                    "product": {
                        "product_id": "product-with-sku",
                        "product_name": "Product with SKU",
                        "creator_account_id": 1001,
                        "owner_account_id": 2001,
                        "account_name": "Owner account",
                    },
                    "sku": {"sku_id": "sku-valid", "sku_name": "Valid SKU"},
                },
                {
                    "online_status": 1,
                    "product": {
                        "product_id": "product-without-sku",
                        "product_name": "Product without SKU",
                    },
                    "skus": [],
                },
            ]
        return {"data": {"products": products, "has_more": False, "next_cursor": ""}}

    def query_online_products_by_id(self, product_ids):
        _ = product_ids
        return {"data": {"product_onlines": []}}


def test_real_adapter_skips_product_rows_without_sku_without_blocking_current_table(
    db_session: Session,
):
    _queue(db_session)
    adapter = DouyinProductSyncAdapter(MissingSkuDouyinProductClient())

    result = execute_product_sync(db_session, job_id="product-sync-1", adapter=adapter)

    current = list(db_session.scalars(select(DimSkuProductRule)))
    assert result.status == "SUCCESS"
    assert result.observed_count == 2
    assert result.skipped_count == 1
    assert result.failed_count == 0
    assert [row.sku_id for row in current] == ["sku-valid"]
    job = db_session.get(JobRun, "product-sync-1")
    assert job is not None
    assert job.metadata_json["skipped_count"] == 1


def test_runtime_initialization_failure_finishes_job_without_overwriting_current_snapshot(
    db_session: Session,
    monkeypatch,
):
    existing = DimSkuProductRule(
        sku_id="sku-trusted",
        sku_name="Trusted SKU",
        product_scope="Manual scope",
        product_type="Manual type",
        is_active_product=True,
        sync_status="SUCCESS",
    )
    db_session.add(existing)
    _queue(db_session)
    db_session.commit()

    def fail_client_initialization():
        raise RuntimeError("credential is unavailable")

    monkeypatch.setattr(
        "apps.worker.pipeline.build_douyin_client_from_env",
        fail_client_initialization,
    )
    factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
        future=True,
    )

    result = run_product_sync_job(job_id="product-sync-1", factory=factory)

    db_session.expire_all()
    job = db_session.get(JobRun, "product-sync-1")
    current = db_session.scalar(
        select(DimSkuProductRule).where(DimSkuProductRule.sku_id == "sku-trusted")
    )
    assert result.status == "FAILED"
    assert result.error_code == "INITIALIZATION_ERROR"
    assert job is not None and job.status == "failed"
    assert job.metadata_json["retryable"] is True
    assert job.error_message == "[redacted sensitive error]"
    assert current is not None
    assert current.sku_name == "Trusted SKU"
    assert current.product_scope == "Manual scope"


def test_extract_known_order_products_uses_products_array_and_deduplicates(db_session: Session):
    db_session.add_all(
        [
            RawDouyinOrder(
                order_id="order-1",
                sku_id="sku-1",
                raw_payload={
                    "products": [
                        {"product_id": "product-1", "sku_id": "sku-1"},
                        {"product_id": "product-1", "sku_id": "sku-2"},
                    ]
                },
            ),
            RawDouyinOrder(
                order_id="order-2",
                sku_id="sku-1",
                raw_payload={
                    "products": [
                        {"product_id": "product-1", "sku_id": "sku-1"},
                        {"product_id": "", "sku_id": "ignored"},
                    ]
                },
            ),
        ]
    )
    db_session.flush()

    assert extract_known_order_products(db_session) == {
        "product-1": {"sku-1", "sku-2"}
    }


def test_missing_product_exhausts_retries_and_preserves_last_good_platform_fields(db_session: Session):
    existing = DimSkuProductRule(
        sku_id="sku-missing",
        sku_name="Trusted SKU",
        product_id="product-missing",
        owner_account_id="owner-trusted",
        owner_account_name="Trusted owner",
        product_status_raw="1",
        product_status_normalized="ACTIVE",
        is_active_product=True,
        sync_status="SUCCESS",
        product_scope="Manual scope",
        product_type="Manual type",
    )
    db_session.add(existing)
    _queue(db_session)
    client = FakeDouyinProductClient()
    # This case represents an actually empty ID lookup, not a reply for an
    # unrelated product (which must now fail the adapter's identity fence).
    client.query_online_products_by_id = lambda product_ids: {"data": {"product_onlines": []}}
    adapter = DouyinProductSyncAdapter(
        client,
        known_products={"product-missing": {"sku-missing"}},
    )

    result = execute_product_sync(db_session, job_id="product-sync-1", adapter=adapter)

    db_session.flush()
    row = db_session.scalar(
        select(DimSkuProductRule).where(DimSkuProductRule.sku_id == "sku-missing")
    )
    assert result.status == "FAILED"
    assert result.error_code == "INCOMPLETE_RESPONSE"
    assert row is not None
    assert row.sku_name == "Trusted SKU"
    assert row.owner_account_id == "owner-trusted"
    assert row.product_status_normalized == "ACTIVE"
    assert row.is_active_product is True
    assert row.sync_status == "SUCCESS"
    assert row.sync_error is None
    assert row.product_scope == "Manual scope"
    assert row.product_type == "Manual type"


def _platform_product(product_id: str, sku_ids: list[str]) -> dict:
    return {
        "online_status": 1,
        "product": {
            "product_id": product_id,
            "product_name": product_id,
            "creator_account_id": "creator-1",
            "owner_account_id": "owner-1",
            "account_name": "Owner",
        },
        "skus": [{"sku_id": sku_id, "sku_name": sku_id} for sku_id in sku_ids],
    }


class SkuCoverageClient:
    def __init__(self, list_pages: dict, detail_rows: dict) -> None:
        self.list_pages = list_pages
        self.detail_rows = detail_rows
        self.list_calls: list[tuple[int, str | None]] = []
        self.id_calls: list[list[str]] = []
        self.sku_calls: list[tuple[str, list[str]]] = []

    def query_online_products(self, *, status, cursor, **kwargs):
        self.list_calls.append((status, cursor))
        return {
            "data": self.list_pages.get(
                (status, cursor), {"products": [], "has_more": False}
            )
        }

    def query_online_products_by_id(self, product_ids):
        self.id_calls.append(list(product_ids))
        return {
            "data": {
                "product_onlines": [
                    self.detail_rows[product_id]
                    for product_id in product_ids
                    if product_id in self.detail_rows
                ]
            }
        }


    def query_product_skus(self, product_id, sku_ids):
        self.sku_calls.append((product_id, list(sku_ids)))
        return {"data": {"error_code": 0, "skus": [
            {"sku_id": sku_id, "sku_name": sku_id, "status": 1}
            for sku_id in sku_ids
        ]}}


def test_same_product_missing_skus_uses_detail_once_without_duplicate_snapshot_conflict(
    db_session: Session,
) -> None:
    listed = _platform_product("product-1", ["sku-a"])
    detail = _platform_product("product-1", ["sku-a", "sku-b", "sku-c"])
    # List and detail observations can differ for an already observed SKU. The
    # gap query must add missing variants without replaying the earlier snapshot.
    detail["skus"][0]["sku_name"] = "Detail observation"
    client = SkuCoverageClient(
        {(1, None): {"products": [listed], "has_more": False}},
        {"product-1": detail},
    )
    _queue(db_session)
    result = execute_product_sync(
        db_session,
        job_id="product-sync-1",
        adapter=DouyinProductSyncAdapter(
            client, known_products={"product-1": {"sku-a", "sku-b", "sku-c"}}
        ),
    )
    assert result.status == "SUCCESS"
    assert client.id_calls == [["product-1"]]
    assert result.inserted_count == 3
    current = {
        row.sku_id: row for row in db_session.scalars(select(DimSkuProductRule))
    }
    assert set(current) == {"sku-a", "sku-b", "sku-c"}
    assert current["sku-a"].sku_name == "sku-a"
    assert current["sku-b"].owner_account_id == "owner-1"
    assert current["sku-c"].product_id == "product-1"
    assert client.sku_calls == []
    assert len(list(db_session.scalars(select(SkuProductSyncHistory)))) == 3


def test_sku_coverage_waits_for_every_list_page_and_status_before_fallback(
    db_session: Session,
) -> None:
    client = SkuCoverageClient(
        {
            (1, None): {
                "products": [_platform_product("product-1", ["sku-a"])],
                "has_more": True,
                "next_cursor": "second-list-page",
            },
            (1, "second-list-page"): {
                "products": [_platform_product("product-1", ["sku-b"])],
                "has_more": False,
            },
            (2, None): {
                "products": [_platform_product("product-1", ["sku-c"])],
                "has_more": False,
            },
        },
        {},
    )
    _queue(db_session)
    result = execute_product_sync(
        db_session,
        job_id="product-sync-1",
        adapter=DouyinProductSyncAdapter(
            client, known_products={"product-1": {"sku-a", "sku-b", "sku-c"}}
        ),
    )
    assert result.status == "SUCCESS"
    assert result.inserted_count == 3
    assert client.id_calls == []
    assert client.sku_calls == []
    assert client.list_calls == [
        (1, None), (1, "second-list-page"), (2, None), (3, None)
    ]


def test_unresolved_sku_gaps_are_batched_once_without_expanding_fallback(
    db_session: Session,
) -> None:
    product_ids = [f"product-{index:02}" for index in range(23)]
    listed = [
        _platform_product(product_id, [f"{product_id}-seen"])
        for product_id in product_ids
    ]
    client = SkuCoverageClient(
        {(1, None): {"products": listed, "has_more": False}},
        dict(zip(product_ids, listed)),
    )
    _queue(db_session)
    result = execute_product_sync(
        db_session,
        job_id="product-sync-1",
        adapter=DouyinProductSyncAdapter(
            client,
            known_products={
                product_id: {f"{product_id}-seen", f"{product_id}-missing"}
                for product_id in product_ids
            },
        ),
    )
    assert result.status == "SUCCESS"
    assert client.id_calls == [product_ids[:10], product_ids[10:20], product_ids[20:]]
    assert result.inserted_count == 46
    assert client.sku_calls == [(product_id, [f"{product_id}-missing"]) for product_id in product_ids]
    assert sum(row.sku_id.endswith("-missing") for row in db_session.scalars(select(DimSkuProductRule))) == 23


def test_missing_detail_does_not_mark_already_listed_sku_not_found(
    db_session: Session,
) -> None:
    client = SkuCoverageClient(
        {(1, None): {
            "products": [_platform_product("product-1", ["sku-a"])],
            "has_more": False,
        }},
        {},
    )
    _queue(db_session)
    result = execute_product_sync(
        db_session,
        job_id="product-sync-1",
        adapter=DouyinProductSyncAdapter(
            client, known_products={"product-1": {"sku-a", "sku-b"}}
        ),
    )
    assert result.status == "FAILED"
    assert result.error_code == "INCOMPLETE_RESPONSE"
    assert client.id_calls == [["product-1"]] * 3
    current = {
        row.sku_id: row for row in db_session.scalars(select(DimSkuProductRule))
    }
    assert current == {}


def test_twenty_three_product_partial_sku_reply_preserves_all_current_catalog(db_session: Session):
    product_ids = [f"product-{index:02}" for index in range(23)]
    listed = [_platform_product(product_id, [f"{product_id}-seen"]) for product_id in product_ids]
    client = SkuCoverageClient({(1, None): {"products": listed, "has_more": False}}, dict(zip(product_ids, listed)))
    def incomplete_reply(product_id, sku_ids):
        client.sku_calls.append((product_id, list(sku_ids)))
        return {"data": {"error_code": 0, "skus": []}}
    client.query_product_skus = incomplete_reply
    for product_id in product_ids:
        db_session.add(DimSkuProductRule(sku_id=f"{product_id}-seen", product_id=product_id,
            sku_name="Trusted before scan", owner_account_id="owner-1", sync_status="SUCCESS",
            is_active_product=True, product_status_normalized="ACTIVE"))
    _queue(db_session)
    result = execute_product_sync(db_session, job_id="product-sync-1", adapter=DouyinProductSyncAdapter(client,
        known_products={product_id: {f"{product_id}-seen", f"{product_id}-missing"} for product_id in product_ids}))
    assert result.status == "FAILED"
    current = list(db_session.scalars(select(DimSkuProductRule)))
    assert len(current) == 23
    assert all(row.sku_name == "Trusted before scan" and row.sync_status == "SUCCESS" and row.is_active_product for row in current)
    assert client.id_calls == [product_ids[:10]]
    assert client.sku_calls == [(product_ids[0], [f"{product_ids[0]}-missing"])] * 3
