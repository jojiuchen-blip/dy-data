from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.dy_api.models import (
    DataQualityIssue,
    DimSkuProductRule,
    JobRun,
    SkuProductSyncHistory,
    SyncSetting,
)
from apps.worker.product_sync import (
    NormalizedProductSyncAdapter,
    execute_product_sync,
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
