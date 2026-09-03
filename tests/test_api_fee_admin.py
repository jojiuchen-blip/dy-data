from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from apps.api.dy_api.models import (  # noqa: E402
    DimSkuProductRule,
    JobRun,
    SettlementScopeRule,
    SkuFeeRule,
    SkuFeeRuleImportBatch,
    SkuFeeRuleImportRow,
    SkuProductImportBatch,
)
from dy_api.main import create_app  # noqa: E402
from dy_api.routes import fee_admin as fee_admin_routes  # noqa: E402
from dy_api.routes._data import get_session_dependency  # noqa: E402


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> TestClient:
    monkeypatch.setenv("DY_API_TEST_MODE", "true")
    monkeypatch.setenv("DY_SUPER_ADMIN_USERNAME", "system-admin")
    monkeypatch.setenv("DY_TEST_ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("DY_SESSION_COOKIE_SECURE", "false")
    app = create_app()

    def override_session():
        yield db_session

    app.dependency_overrides[get_session_dependency] = override_session
    return TestClient(app)


def _login(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "system-admin", "password": "test-password"},
    )
    assert response.status_code == 200


def _seed_sku(
    session: Session,
    sku_id: str,
    sku_name: str,
    *,
    owner_account_id: str = "owner-stable-1",
) -> DimSkuProductRule:
    row = DimSkuProductRule(
        sku_id=sku_id,
        sku_name=sku_name,
        product_id=f"product-{sku_id}",
        product_name=f"商品-{sku_name}",
        spu_id=f"spu-{sku_id}",
        product_scope="原范围",
        product_type="原类型",
        is_service_product=False,
        creator_account_id="creator-1",
        owner_account_id=owner_account_id,
        owner_account_name="稳定归属账号",
        product_status_normalized="ACTIVE",
        is_active_product=True,
        last_synced_at=datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc),
    )
    session.add(row)
    session.flush()
    return row


def _csv(rows: list[tuple[str, str, str, str]]) -> bytes:
    lines = ["skuName,skuId,promotionServiceFeeRate,managementServiceFeeRate"]
    lines.extend(",".join(row) for row in rows)
    return ("\ufeff" + "\n".join(lines) + "\n").encode("utf-8")


def _xlsx(rows: list[tuple[str, str, str, str]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(
        ["skuName", "skuId", "promotionServiceFeeRate", "managementServiceFeeRate"]
    )
    for row in rows:
        sheet.append(list(row))
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _upload(
    client: TestClient,
    content: bytes,
    *,
    filename: str = "fees.csv",
    effective_date: str = "2026-08-01",
):
    return client.post(
        "/api/v1/admin/sku-fee-rule-imports",
        files={"file": (filename, content)},
        data={"effectiveDate": effective_date},
        headers={"X-Request-ID": "req-import-test"},
    )


def _product_csv(rows: list[tuple[str, str, str]]) -> bytes:
    lines = ["skuId,productScope,productType"]
    lines.extend(",".join(row) for row in rows)
    return ("\ufeff" + "\n".join(lines) + "\n").encode("utf-8")


def _upload_product_import(
    client: TestClient,
    rows: list[tuple[str, str, str]],
):
    return client.post(
        "/api/v1/admin/sku-product-imports",
        files={"file": ("product-types.csv", _product_csv(rows))},
    )


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("empty.csv", _csv([])),
        ("empty.xlsx", _xlsx([])),
    ],
)
def test_empty_import_is_rejected_during_prevalidation(
    client: TestClient,
    filename: str,
    content: bytes,
) -> None:
    _login(client)

    response = _upload(client, content, filename=filename)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["batch"]["batchStatus"] == "VALIDATION_FAILED"
    assert data["batch"]["successCount"] == 0
    assert data["batch"]["failedCount"] == 1
    assert data["errorPreview"][0]["errors"][0]["field"] == "template"
    assert "至少包含一条数据行" in data["errorPreview"][0]["errors"][0]["message"]


def test_new_fee_admin_endpoints_require_login(client: TestClient) -> None:
    sku_response = client.get(
        "/api/v1/admin/sku-products",
        headers={"X-Request-ID": "req-auth-required"},
    )
    assert sku_response.status_code == 401
    assert sku_response.json()["detail"]["code"] == "AUTH_REQUIRED"
    assert sku_response.json()["detail"]["requestId"] == "req-auth-required"
    assert client.get("/api/v1/admin/sku-fee-rules").status_code == 401
    assert client.get("/api/v1/admin/sku-fee-rule-imports").status_code == 401
    assert client.get("/api/v1/admin/settlement-scope-rules").status_code == 401


def test_fee_admin_query_validation_uses_stable_error_contract(client: TestClient) -> None:
    _login(client)

    response = client.get(
        "/api/v1/admin/sku-products",
        params={"page": 0},
        headers={"X-Request-ID": "req-query-invalid"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_FAILED"
    assert response.json()["detail"]["requestId"] == "req-query-invalid"


def test_admin_can_filter_and_update_only_manual_sku_fields(
    client: TestClient,
    db_session: Session,
) -> None:
    row = _seed_sku(db_session, "sku-1", "保养 SKU")
    reference = _seed_sku(db_session, "sku-reference", "目标组合参考")
    reference.product_scope = "精诚养车"
    reference.product_type = "268 保养"
    db_session.commit()
    platform_before = (row.product_id, row.owner_account_id, row.last_synced_at)
    _login(client)

    listing = client.get(
        "/api/v1/admin/sku-products",
        params={
            "page": 1,
            "pageSize": 20,
            "q": "保养",
            "productStatus": "ACTIVE",
            "isActiveProduct": "true",
        },
        headers={"X-Request-ID": "req-sku-list"},
    )
    updated = client.put(
        "/api/v1/admin/sku-products/sku-1",
        json={
            "expectedManualModifiedAt": None,
            "productScope": "精诚养车",
            "productType": "268 保养",
            "isServiceProduct": True,
        },
        headers={"X-Request-ID": "req-sku-update"},
    )

    assert listing.status_code == 200
    assert listing.json()["data"]["total"] == 1
    assert listing.json()["data"]["list"][0]["skuId"] == "sku-1"
    assert listing.json()["meta"]["requestId"] == "req-sku-list"
    assert updated.status_code == 200
    assert updated.json()["data"]["productScope"] == "精诚养车"
    assert updated.json()["data"]["productType"] == "268 保养"
    assert updated.json()["data"]["isServiceProduct"] is True
    assert updated.json()["meta"]["requestId"] == "req-sku-update"
    db_session.refresh(row)
    assert (row.product_id, row.owner_account_id, row.last_synced_at) == platform_before
    assert row.manual_modified_by == "system-admin"
    assert row.manual_modified_at is not None

    rejected = client.put(
        "/api/v1/admin/sku-products/sku-1",
        json={
            "productScope": "范围",
            "productType": "类型",
            "isServiceProduct": False,
            "productName": "禁止覆盖",
        },
        headers={"X-Request-ID": "req-sku-reject"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "VALIDATION_FAILED"
    assert rejected.json()["detail"]["requestId"] == "req-sku-reject"


def test_sku_product_list_exposes_configuration_status_counts_and_pending_order(
    client: TestClient,
    db_session: Session,
) -> None:
    unconfigured = _seed_sku(db_session, "sku-unconfigured", "未配置商品")
    unconfigured.product_scope = ""
    unconfigured.product_type = ""
    partial = _seed_sku(db_session, "sku-partial", "部分配置商品")
    partial.product_scope = "已有范围"
    partial.product_type = ""
    configured = _seed_sku(db_session, "sku-configured", "已配置商品")
    db_session.commit()
    _login(client)

    response = client.get(
        "/api/v1/admin/sku-products",
        params={"configurationStatus": "PENDING"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pageSize"] == 50
    assert data["total"] == 2
    assert data["statusCounts"] == {
        "unconfigured": 1,
        "partial": 1,
        "configured": 1,
    }
    assert [item["skuId"] for item in data["list"]] == [
        "sku-unconfigured",
        "sku-partial",
    ]
    assert [item["configurationStatus"] for item in data["list"]] == [
        "UNCONFIGURED",
        "PARTIAL",
    ]


def test_sku_product_lists_order_each_status_by_latest_manual_change(
    client: TestClient,
    db_session: Session,
) -> None:
    base_time = datetime(2026, 8, 19, 1, 0, tzinfo=timezone.utc)
    pending_rows = [
        _seed_sku(db_session, "sku-u-a-old", "未配置旧记录"),
        _seed_sku(db_session, "sku-u-z-new", "未配置新记录"),
        _seed_sku(db_session, "sku-p-a-old", "部分配置旧记录"),
        _seed_sku(db_session, "sku-p-z-new", "部分配置新记录"),
    ]
    for row in pending_rows[:2]:
        row.product_scope = ""
        row.product_type = ""
    for row in pending_rows[2:]:
        row.product_scope = "已有范围"
        row.product_type = ""
    pending_rows[0].manual_modified_at = base_time
    pending_rows[1].manual_modified_at = base_time + timedelta(hours=1)
    pending_rows[2].manual_modified_at = base_time
    pending_rows[3].manual_modified_at = base_time + timedelta(hours=1)

    configured_old = _seed_sku(db_session, "sku-c-a-old", "已配置旧记录")
    configured_new = _seed_sku(db_session, "sku-c-z-new", "已配置新记录")
    configured_old.manual_modified_at = base_time
    configured_new.manual_modified_at = base_time + timedelta(hours=1)
    db_session.commit()
    _login(client)

    pending = client.get(
        "/api/v1/admin/sku-products",
        params={"configurationStatus": "PENDING"},
    )
    configured = client.get(
        "/api/v1/admin/sku-products",
        params={"configurationStatus": "CONFIGURED"},
    )

    assert pending.status_code == 200
    assert [item["skuId"] for item in pending.json()["data"]["list"]] == [
        "sku-u-z-new",
        "sku-u-a-old",
        "sku-p-z-new",
        "sku-p-a-old",
    ]
    assert configured.status_code == 200
    assert [item["skuId"] for item in configured.json()["data"]["list"]] == [
        "sku-c-z-new",
        "sku-c-a-old",
    ]


def test_single_sku_product_update_rejects_stale_manual_version(
    client: TestClient,
    db_session: Session,
) -> None:
    row = _seed_sku(db_session, "sku-concurrent", "并发更新商品")
    row.manual_modified_at = datetime(2026, 8, 19, 1, 0, tzinfo=timezone.utc)
    reference = _seed_sku(db_session, "sku-concurrent-reference", "并发更新组合参考")
    reference.product_scope = "首次更新范围"
    reference.product_type = row.product_type
    db_session.commit()
    _login(client)

    listing = client.get(
        "/api/v1/admin/sku-products",
        params={"q": row.sku_id},
    )
    expected_version = listing.json()["data"]["list"][0]["manualModifiedAt"]
    first = client.put(
        f"/api/v1/admin/sku-products/{row.sku_id}",
        json={
            "expectedManualModifiedAt": expected_version,
            "productScope": "首次更新范围",
        },
    )
    stale = client.put(
        f"/api/v1/admin/sku-products/{row.sku_id}",
        json={
            "expectedManualModifiedAt": expected_version,
            "productScope": "首次更新范围",
        },
        headers={"X-Request-ID": "req-stale-sku-update"},
    )

    assert first.status_code == 200
    assert stale.status_code == 409
    assert stale.json()["detail"] == {
        "code": "CONCURRENT_MODIFICATION",
        "message": "SKU 已被其他操作更新，请刷新后重试",
        "requestId": "req-stale-sku-update",
        "errors": [],
    }
    db_session.refresh(row)
    assert row.product_scope == "首次更新范围"


def test_single_sku_product_update_preserves_omitted_manual_field(
    client: TestClient,
    db_session: Session,
) -> None:
    row = _seed_sku(db_session, "sku-partial-update", "单字段更新商品")
    reference = _seed_sku(db_session, "sku-partial-reference", "单字段组合参考")
    reference.product_scope = "新范围"
    db_session.commit()
    _login(client)

    response = client.put(
        "/api/v1/admin/sku-products/sku-partial-update",
        json={"expectedManualModifiedAt": None, "productScope": "新范围"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["productScope"] == "新范围"
    assert response.json()["data"]["productType"] == "原类型"
    db_session.refresh(row)
    assert row.product_scope == "新范围"
    assert row.product_type == "原类型"


def test_single_sku_product_update_allows_an_explicit_custom_pair(
    client: TestClient,
    db_session: Session,
) -> None:
    row = _seed_sku(db_session, "sku-custom-pair", "自定义口径商品")
    db_session.commit()
    _login(client)

    response = client.put(
        f"/api/v1/admin/sku-products/{row.sku_id}",
        json={
            "expectedManualModifiedAt": None,
            "productScope": "全新产品范围",
            "productType": "全新商品类型",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["productScope"] == "全新产品范围"
    assert response.json()["data"]["productType"] == "全新商品类型"
    db_session.refresh(row)
    assert (row.product_scope, row.product_type) == ("全新产品范围", "全新商品类型")


@pytest.mark.parametrize("reserved", ["all", "unknown", "KEEP", "  keep  "])
def test_sku_product_update_rejects_reserved_dimension_values(
    client: TestClient,
    db_session: Session,
    reserved: str,
) -> None:
    row = _seed_sku(db_session, f"sku-reserved-{reserved.strip()}", "保留值商品")
    db_session.commit()
    _login(client)

    response = client.put(
        f"/api/v1/admin/sku-products/{row.sku_id}",
        json={"expectedManualModifiedAt": None, "productScope": reserved},
    )

    assert response.status_code == 422
    db_session.refresh(row)
    assert row.product_scope == "原范围"


def test_bulk_sku_product_update_is_atomic_and_preserves_omitted_fields(
    client: TestClient,
    db_session: Session,
) -> None:
    first = _seed_sku(db_session, "sku-bulk-1", "批量商品一")
    second = _seed_sku(db_session, "sku-bulk-2", "批量商品二")
    second.product_type = "第二原类型"
    first_reference = _seed_sku(db_session, "sku-bulk-reference-1", "批量组合参考一")
    first_reference.product_scope = "批量新范围"
    second_reference = _seed_sku(db_session, "sku-bulk-reference-2", "批量组合参考二")
    second_reference.product_scope = "批量新范围"
    second_reference.product_type = "第二原类型"
    db_session.commit()
    _login(client)

    rejected = client.put(
        "/api/v1/admin/sku-products/bulk",
        json={
            "skuIds": ["sku-bulk-1", "sku-missing"],
            "productScope": "不能部分写入",
        },
    )

    assert rejected.status_code == 404
    db_session.refresh(first)
    assert first.product_scope == "原范围"

    updated = client.put(
        "/api/v1/admin/sku-products/bulk",
        json={
            "skuIds": ["sku-bulk-1", "sku-bulk-2"],
            "productScope": "批量新范围",
        },
    )

    assert updated.status_code == 200
    assert updated.json()["data"]["updatedCount"] == 2
    db_session.refresh(first)
    db_session.refresh(second)
    assert (first.product_scope, first.product_type) == ("批量新范围", "原类型")
    assert (second.product_scope, second.product_type) == (
        "批量新范围",
        "第二原类型",
    )


def test_bulk_sku_product_update_rejects_incompatible_scope_type_combinations(
    client: TestClient,
    db_session: Session,
) -> None:
    target = _seed_sku(db_session, "sku-combination-target", "组合校验商品")
    valid_reference = _seed_sku(db_session, "sku-combination-reference", "组合参考商品")
    valid_reference.product_scope = "新范围"
    valid_reference.product_type = "新范围类型"
    db_session.commit()
    _login(client)

    response = client.put(
        "/api/v1/admin/sku-products/bulk",
        json={"skuIds": [target.sku_id], "productScope": "新范围"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "PRODUCT_DIMENSION_MISMATCH"
    db_session.refresh(target)
    assert (target.product_scope, target.product_type) == ("原范围", "原类型")


def test_sku_product_import_template_and_atomic_commit_support_keep(
    client: TestClient,
    db_session: Session,
) -> None:
    first = _seed_sku(db_session, "sku-import-1", "导入商品一")
    second = _seed_sku(db_session, "sku-import-2", "导入商品二")
    second.product_scope = "第二原范围"
    first_reference = _seed_sku(db_session, "sku-import-reference-1", "导入组合参考一")
    first_reference.product_scope = "新范围"
    second_reference = _seed_sku(db_session, "sku-import-reference-2", "导入组合参考二")
    second_reference.product_scope = "第二原范围"
    second_reference.product_type = "新类型"
    db_session.commit()
    _login(client)

    template = client.get("/api/v1/admin/sku-product-imports/template")
    assert template.status_code == 200
    assert template.content.decode("utf-8-sig").splitlines()[0] == (
        "skuId,productScope,productType"
    )

    uploaded = _upload_product_import(
        client,
        [
            ("sku-import-1", "新范围", "KEEP"),
            ("sku-import-2", "KEEP", "新类型"),
        ],
    )
    assert uploaded.status_code == 200
    batch = uploaded.json()["data"]["batch"]
    assert batch["batchStatus"] == "PENDING_COMMIT"
    assert batch["validCount"] == 2

    committed = client.post(
        f"/api/v1/admin/sku-product-imports/{batch['batchId']}/commit"
    )
    assert committed.status_code == 200
    assert committed.json()["data"]["batch"]["successCount"] == 2
    db_session.refresh(first)
    db_session.refresh(second)
    assert (first.product_scope, first.product_type) == ("新范围", "原类型")
    assert (second.product_scope, second.product_type) == ("第二原范围", "新类型")


def test_sku_product_import_allows_an_explicit_custom_pair(
    client: TestClient,
    db_session: Session,
) -> None:
    row = _seed_sku(db_session, "sku-import-custom-pair", "导入自定义口径商品")
    db_session.commit()
    _login(client)

    uploaded = _upload_product_import(
        client,
        [(row.sku_id, "导入新范围", "导入新类型")],
    )

    assert uploaded.status_code == 200
    batch = uploaded.json()["data"]["batch"]
    assert batch["batchStatus"] == "PENDING_COMMIT"
    committed = client.post(
        f"/api/v1/admin/sku-product-imports/{batch['batchId']}/commit"
    )
    assert committed.status_code == 200
    db_session.refresh(row)
    assert (row.product_scope, row.product_type) == ("导入新范围", "导入新类型")


@pytest.mark.parametrize(
    "rows",
    [
        [("sku-invalid-import", "", "新类型")],
        [("sku-invalid-import", "KEEP", "KEEP")],
        [
            ("sku-invalid-import", "新范围", "KEEP"),
            ("sku-invalid-import", "KEEP", "新类型"),
        ],
    ],
)
def test_sku_product_import_rejects_blank_keep_only_and_duplicate_rows(
    client: TestClient,
    db_session: Session,
    rows: list[tuple[str, str, str]],
) -> None:
    _seed_sku(db_session, "sku-invalid-import", "非法导入商品")
    db_session.commit()
    _login(client)

    response = _upload_product_import(client, rows)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["batch"]["batchStatus"] == "VALIDATION_FAILED"
    assert data["batch"]["successCount"] == 0
    assert data["errorPreview"]


def test_sku_product_import_commit_revalidates_all_rows_before_writing(
    client: TestClient,
    db_session: Session,
) -> None:
    first = _seed_sku(db_session, "sku-atomic-import-1", "原子商品一")
    second = _seed_sku(db_session, "sku-atomic-import-2", "原子商品二")
    db_session.commit()
    _login(client)
    uploaded = _upload_product_import(
        client,
        [
            ("sku-atomic-import-1", "新范围", "KEEP"),
            ("sku-atomic-import-2", "新范围", "KEEP"),
        ],
    )
    batch_id = uploaded.json()["data"]["batch"]["batchId"]
    db_session.delete(second)
    db_session.commit()

    committed = client.post(
        f"/api/v1/admin/sku-product-imports/{batch_id}/commit"
    )

    assert committed.status_code == 409
    db_session.refresh(first)
    assert first.product_scope == "原范围"
    batch = db_session.scalar(
        select(SkuProductImportBatch).where(SkuProductImportBatch.batch_id == batch_id)
    )
    assert batch is not None
    assert batch.success_count == 0


def test_sku_product_import_commit_revalidates_product_dimension_combinations(
    client: TestClient,
    db_session: Session,
) -> None:
    target = _seed_sku(db_session, "sku-import-dimension-target", "导入口径目标商品")
    reference = _seed_sku(db_session, "sku-import-dimension-reference", "导入口径参考商品")
    reference.product_scope = target.product_scope
    reference.product_type = "目标类型"
    db_session.commit()
    _login(client)
    uploaded = _upload_product_import(
        client,
        [(target.sku_id, "KEEP", "目标类型")],
    )
    assert uploaded.status_code == 200
    batch_id = uploaded.json()["data"]["batch"]["batchId"]
    db_session.delete(reference)
    db_session.commit()

    committed = client.post(
        f"/api/v1/admin/sku-product-imports/{batch_id}/commit"
    )

    assert committed.status_code == 409
    assert committed.json()["detail"]["code"] == "IMPORT_DATA_CHANGED"
    db_session.refresh(target)
    assert (target.product_scope, target.product_type) == ("原范围", "原类型")


def test_sku_product_import_rejects_incompatible_product_dimensions(
    client: TestClient,
    db_session: Session,
) -> None:
    target = _seed_sku(db_session, "sku-import-mismatch", "导入组合校验商品")
    reference = _seed_sku(db_session, "sku-import-mismatch-reference", "导入组合参考")
    reference.product_scope = "目标范围"
    reference.product_type = "目标类型"
    db_session.commit()
    _login(client)

    response = _upload_product_import(
        client,
        [(target.sku_id, "目标范围", "KEEP")],
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["batch"]["batchStatus"] == "VALIDATION_FAILED"
    assert data["errorPreview"][0]["errors"][0]["code"] == (
        "PRODUCT_DIMENSION_MISMATCH"
    )


def test_single_fee_rule_publish_is_immutable_idempotent_and_day_scoped(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_sku(db_session, "sku-1", "保养 SKU")
    _seed_sku(db_session, "sku-2", "第二个 SKU")
    db_session.commit()
    _login(client)
    headers = {
        "Idempotency-Key": "fee-rule-key-0001",
        "X-Request-ID": "req-fee-create",
    }
    payload = {
        "skuId": "sku-1",
        "promotionServiceFeeRate": "0.080000",
        "managementServiceFeeRate": "0.100000",
        "effectiveDate": "2026-08-15",
        "ruleStatus": "ACTIVE",
        "changeReason": "8 月 15 日起生效",
    }

    first = client.post("/api/v1/admin/sku-fee-rules", headers=headers, json=payload)
    retried = client.post("/api/v1/admin/sku-fee-rules", headers=headers, json=payload)

    assert first.status_code == 200
    assert retried.status_code == 200
    assert first.json()["data"] == retried.json()["data"]
    item = first.json()["data"]
    assert item["promotionServiceFeeRate"] == "0.080000"
    assert item["managementServiceFeeRate"] == "0.100000"
    assert item["effectiveDate"] == "2026-08-15"
    assert item["effectiveAt"].endswith("+08:00")
    assert item["ruleStatus"] == "ACTIVE"
    assert db_session.scalar(select(func.count()).select_from(SkuFeeRule)) == 1
    detail = client.get(f"/api/v1/admin/sku-fee-rules/{item['ruleVersion']}")
    assert detail.status_code == 200
    assert detail.json()["data"] == item

    reused = client.post(
        "/api/v1/admin/sku-fee-rules",
        headers=headers,
        json={**payload, "promotionServiceFeeRate": "0.090000"},
    )
    assert reused.status_code == 409
    assert reused.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"

    reused_for_other_sku = client.post(
        "/api/v1/admin/sku-fee-rules",
        headers=headers,
        json={**payload, "skuId": "sku-2"},
    )
    assert reused_for_other_sku.status_code == 409
    assert reused_for_other_sku.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"

    date_conflict = client.post(
        "/api/v1/admin/sku-fee-rules",
        headers={"Idempotency-Key": "fee-rule-key-0002"},
        json=payload,
    )
    assert date_conflict.status_code == 409
    assert date_conflict.json()["detail"]["code"] == "SKU_FEE_RULE_DATE_CONFLICT"

    second_date = client.post(
        "/api/v1/admin/sku-fee-rules",
        headers={"Idempotency-Key": "fee-rule-key-0003"},
        json={**payload, "effectiveDate": "2026-08-20", "changeReason": "日级调整"},
    )
    assert second_date.status_code == 200
    assert second_date.json()["data"]["previousRuleVersion"] == item["ruleVersion"]

    matched = client.get(
        "/api/v1/admin/sku-fee-rules",
        params={"skuId": "sku-1", "asOfDate": "2026-08-18"},
    )
    assert matched.status_code == 200
    matched_rows = matched.json()["data"]["list"]
    assert [row["isMatchedVersion"] for row in matched_rows] == [False, True]

    disabled = client.post(
        "/api/v1/admin/sku-fee-rules",
        headers={"Idempotency-Key": "fee-rule-key-disabled-0001"},
        json={
            **payload,
            "effectiveDate": "2026-08-25",
            "ruleStatus": "INACTIVE",
            "changeReason": "停止后续订单费用计算",
        },
    )
    assert disabled.status_code == 200
    after_disabled = client.get(
        "/api/v1/admin/sku-fee-rules",
        params={"skuId": "sku-1", "asOfDate": "2026-08-30"},
    )
    assert after_disabled.status_code == 200
    assert not any(
        row["isMatchedVersion"] for row in after_disabled.json()["data"]["list"]
    )

    before_formal_period = client.post(
        "/api/v1/admin/sku-fee-rules",
        headers={"Idempotency-Key": "fee-rule-key-0004"},
        json={**payload, "effectiveDate": "2026-07-31"},
    )
    assert before_formal_period.status_code == 422
    assert before_formal_period.json()["detail"]["code"] == "VALIDATION_FAILED"


def test_fee_rule_rebuild_trigger_is_durable_and_idempotent(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _login(client)
    calls: list[str] = []
    monkeypatch.setattr(
        fee_admin_routes,
        "run_sku_fee_rule_rebuild_job",
        lambda *, job_id: calls.append(job_id),
        raising=False,
    )
    headers = {"Idempotency-Key": "fee-rebuild-key-0001"}
    payload = {"updatedRuleCount": 10}

    first = client.post(
        "/api/v1/admin/sku-fee-rules/rebuild",
        headers=headers,
        json=payload,
    )
    retried = client.post(
        "/api/v1/admin/sku-fee-rules/rebuild",
        headers=headers,
        json=payload,
    )

    assert first.status_code == 200
    assert retried.status_code == 200
    assert first.json()["data"] == retried.json()["data"]
    rebuild = first.json()["data"]
    assert rebuild["rebuildStatus"] == "queued"
    assert calls == [rebuild["jobId"]]
    job = db_session.get(JobRun, rebuild["jobId"])
    assert job is not None
    assert job.job_name == "settlement_rebuild"
    assert job.status == "queued"
    assert job.metadata_json["trigger"] == "admin_sku_fee_rules"
    assert job.metadata_json["updated_rule_count"] == 10
    assert job.metadata_json["request_payload_sha256"]

    reused = client.post(
        "/api/v1/admin/sku-fee-rules/rebuild",
        headers=headers,
        json={"updatedRuleCount": 9},
    )
    assert reused.status_code == 409
    assert reused.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_settlement_scope_publish_is_channel_scoped_and_idempotent(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_sku(db_session, "sku-1", "保养 SKU", owner_account_id="owner-stable-1")
    db_session.commit()
    _login(client)
    headers = {"Idempotency-Key": "scope-rule-key-01"}
    payload = {
        "effectiveMonth": "2026-08",
        "ownerAccountId": "owner-stable-1",
        "allowedSaleChannels": ["LIVE", "SHORT_VIDEO", "LIVE"],
        "changeReason": "正式结算范围",
    }

    first = client.post(
        "/api/v1/admin/settlement-scope-rules", headers=headers, json=payload
    )
    retried = client.post(
        "/api/v1/admin/settlement-scope-rules", headers=headers, json=payload
    )

    assert first.status_code == 200
    assert retried.status_code == 200
    assert first.json()["data"] == retried.json()["data"]
    assert first.json()["data"]["allowedSaleChannels"] == ["LIVE", "SHORT_VIDEO"]
    assert len(first.json()["data"]["scopeRuleVersions"]) == 2
    assert db_session.scalar(select(func.count()).select_from(SettlementScopeRule)) == 2

    conflict = client.post(
        "/api/v1/admin/settlement-scope-rules",
        headers={"Idempotency-Key": "scope-rule-key-02"},
        json={**payload, "allowedSaleChannels": ["LIVE"]},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "SETTLEMENT_SCOPE_SLOT_CONFLICT"

    listing = client.get(
        "/api/v1/admin/settlement-scope-rules",
        params={"effectiveMonth": "2026-08", "ownerAccountId": "owner-stable-1"},
    )
    assert listing.status_code == 200
    assert {row["saleChannel"] for row in listing.json()["data"]["list"]} == {
        "LIVE",
        "SHORT_VIDEO",
    }


def test_import_prevalidation_returns_all_row_errors_and_writes_zero_rules(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_sku(db_session, "sku-1", "正确名称")
    db_session.commit()
    _login(client)

    response = _upload(
        client,
        _csv(
            [
                ("错误名称", "sku-1", "1.200000", ""),
                ("正确名称", "sku-1", "0.080000", "0.100000"),
                ("不存在", "sku-missing", "not-a-rate", "0.100000"),
            ]
        ),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["batch"]["batchStatus"] == "VALIDATION_FAILED"
    assert payload["batch"]["successCount"] == 0
    assert payload["batch"]["failedCount"] == 3
    first_errors = payload["errorPreview"][0]["errors"]
    assert {error["field"] for error in first_errors} == {
        "skuName",
        "promotionServiceFeeRate",
        "managementServiceFeeRate",
        "skuId",
    }
    assert db_session.scalar(select(func.count()).select_from(SkuFeeRule)) == 0
    assert response.json()["meta"]["requestId"] == "req-import-test"
    listing = client.get(
        "/api/v1/admin/sku-fee-rule-imports",
        params={"batchStatus": "VALIDATION_FAILED"},
    )
    assert listing.status_code == 200
    assert listing.json()["data"]["total"] == 1
    assert listing.json()["data"]["list"][0]["batchId"] == payload["batch"]["batchId"]


def test_import_records_wrong_template_as_a_failed_batch(client: TestClient) -> None:
    _login(client)

    response = _upload(client, b"wrong,headers\n1,2\n", filename="wrong.csv")

    assert response.status_code == 200
    assert response.json()["data"]["batch"]["batchStatus"] == "VALIDATION_FAILED"
    assert response.json()["data"]["batch"]["successCount"] == 0
    error = response.json()["data"]["errorPreview"][0]["errors"][0]
    assert error["field"] == "template"
    assert error["code"] == "IMPORT_TEMPLATE_INVALID"


def test_import_rejects_unsupported_file_type(client: TestClient) -> None:
    _login(client)

    response = _upload(
        client,
        b"skuName,skuId,promotionServiceFeeRate,managementServiceFeeRate\n",
        filename="wrong.txt",
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_FAILED"


@pytest.mark.parametrize(
    ("filename", "content_factory"),
    [("fees.csv", _csv), ("fees.xlsx", _xlsx)],
)
def test_valid_csv_and_xlsx_imports_commit_atomically_and_idempotently(
    client: TestClient,
    db_session: Session,
    filename: str,
    content_factory,
) -> None:
    _seed_sku(db_session, "sku-1", "名称一")
    _seed_sku(db_session, "sku-2", "名称二")
    db_session.commit()
    _login(client)
    uploaded = _upload(
        client,
        content_factory(
            [
                ("名称一", "sku-1", "0.080000", "0.100000"),
                ("名称二", "sku-2", "0.090000", "0.110000"),
            ]
        ),
        filename=filename,
    )

    assert uploaded.status_code == 200
    batch = uploaded.json()["data"]["batch"]
    assert batch["batchStatus"] == "PENDING_COMMIT"
    assert batch["validCount"] == 2
    batch_id = batch["batchId"]
    headers = {"Idempotency-Key": f"commit-{filename}-0001"}
    request = {"changeReason": "2026-08 正式费率发布"}

    committed = client.post(
        f"/api/v1/admin/sku-fee-rule-imports/{batch_id}/commit",
        headers=headers,
        json=request,
    )
    retried = client.post(
        f"/api/v1/admin/sku-fee-rule-imports/{batch_id}/commit",
        headers=headers,
        json=request,
    )

    assert committed.status_code == 200
    assert retried.status_code == 200
    assert committed.json()["data"] == retried.json()["data"]
    assert committed.json()["data"]["batch"]["batchStatus"] == "COMPLETED"
    assert len(committed.json()["data"]["createdRuleVersions"]) == 2
    rebuild = committed.json()["data"]["settlementRebuild"]
    assert rebuild["rebuildStatus"] == "queued"
    job = db_session.get(JobRun, rebuild["jobId"])
    assert job is not None
    assert job.job_name == "settlement_rebuild"
    assert db_session.scalar(select(func.count()).select_from(SkuFeeRule)) == 2
    assert db_session.scalar(
        select(func.count())
        .select_from(SkuFeeRuleImportRow)
        .where(SkuFeeRuleImportRow.validation_status == 4)
    ) == 2

    detail = client.get(f"/api/v1/admin/sku-fee-rule-imports/{batch_id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["rows"]["total"] == 2
    result_file = client.get(
        f"/api/v1/admin/sku-fee-rule-imports/{batch_id}/result-file"
    )
    assert result_file.status_code == 200
    assert result_file.content


def test_import_commit_conflict_keeps_batch_atomic_with_zero_new_rules(
    client: TestClient,
    db_session: Session,
) -> None:
    sku_1 = _seed_sku(db_session, "sku-1", "名称一")
    _seed_sku(db_session, "sku-2", "名称二")
    db_session.commit()
    _login(client)
    uploaded = _upload(
        client,
        _csv(
            [
                ("名称一", "sku-1", "0.080000", "0.100000"),
                ("名称二", "sku-2", "0.090000", "0.110000"),
            ]
        ),
    )
    batch_id = uploaded.json()["data"]["batch"]["batchId"]
    db_session.add(
        SkuFeeRule(
            rule_version="fee-existing-conflict",
            idempotency_key_hash="a" * 64,
            request_payload_sha256="b" * 64,
            sku_id="sku-1",
            sku_name_snapshot=sku_1.sku_name,
            product_scope_snapshot=sku_1.product_scope,
            product_type_snapshot=sku_1.product_type,
            promotion_service_fee_rate=Decimal("0.010000"),
            management_service_fee_rate=Decimal("0.010000"),
            effective_date=date(2026, 8, 1),
            effective_at=datetime(2026, 7, 31, 16, 0, tzinfo=timezone.utc),
            rule_status=1,
            created_by="race",
            change_reason="模拟提交期竞争",
            published_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    response = client.post(
        f"/api/v1/admin/sku-fee-rule-imports/{batch_id}/commit",
        headers={"Idempotency-Key": "commit-race-key-01"},
        json={"changeReason": "提交时冲突"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SKU_FEE_RULE_DATE_CONFLICT"
    assert db_session.scalar(select(func.count()).select_from(SkuFeeRule)) == 1
    batch = db_session.scalar(
        select(SkuFeeRuleImportBatch).where(SkuFeeRuleImportBatch.batch_id == batch_id)
    )
    assert batch is not None
    assert batch.success_count == 0
    assert db_session.scalar(
        select(func.count())
        .select_from(JobRun)
        .where(JobRun.job_name == "settlement_rebuild")
    ) == 0


def test_import_flush_failure_rolls_back_every_new_rule(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_sku(db_session, "sku-1", "名称一")
    _seed_sku(db_session, "sku-2", "名称二")
    db_session.commit()
    _login(client)
    uploaded = _upload(
        client,
        _csv(
            [
                ("名称一", "sku-1", "0.080000", "0.100000"),
                ("名称二", "sku-2", "0.090000", "0.110000"),
            ]
        ),
    )
    batch_id = uploaded.json()["data"]["batch"]["batchId"]
    monkeypatch.setattr(
        fee_admin_routes,
        "_new_rule_version",
        lambda prefix, effective_date: "forced-duplicate-version",
    )

    response = client.post(
        f"/api/v1/admin/sku-fee-rule-imports/{batch_id}/commit",
        headers={"Idempotency-Key": "commit-flush-key01"},
        json={"changeReason": "故障注入"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SKU_FEE_RULE_DATE_CONFLICT"
    assert db_session.scalar(select(func.count()).select_from(SkuFeeRule)) == 0
    batch = db_session.scalar(
        select(SkuFeeRuleImportBatch).where(SkuFeeRuleImportBatch.batch_id == batch_id)
    )
    assert batch is not None
    assert batch.batch_status == 6
    assert batch.success_count == 0


def test_import_accepts_exactly_five_thousand_valid_rows(
    client: TestClient,
    db_session: Session,
) -> None:
    db_session.add_all(
        [
            DimSkuProductRule(
                sku_id=f"sku-{index:04d}",
                sku_name=f"名称{index:04d}",
                product_scope="范围",
                product_type="类型",
            )
            for index in range(5000)
        ]
    )
    db_session.commit()
    _login(client)
    content = _csv(
        [
            (f"名称{index:04d}", f"sku-{index:04d}", "0.080000", "0.100000")
            for index in range(5000)
        ]
    )

    response = _upload(client, content, filename="five-thousand.csv")

    assert response.status_code == 200
    batch = response.json()["data"]["batch"]
    assert batch["batchStatus"] == "PENDING_COMMIT"
    assert batch["totalCount"] == 5000
    assert batch["validCount"] == 5000
    assert batch["failedCount"] == 0


def test_import_template_contains_only_four_business_columns(client: TestClient) -> None:
    _login(client)

    response = client.get("/api/v1/admin/sku-fee-rule-imports/template")

    assert response.status_code == 200
    text = response.content.decode("utf-8-sig")
    assert text.splitlines()[0] == (
        "skuName,skuId,promotionServiceFeeRate,managementServiceFeeRate"
    )
    assert "真实" not in text
