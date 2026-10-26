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
    SkuProductImportRow,
)
from dy_api.main import create_app  # noqa: E402
from dy_api.auth import hash_password_pbkdf2  # noqa: E402
from apps.api.dy_api.models import User, UserPagePermissionOverride  # noqa: E402
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


def _login_rule_operator(client: TestClient, session: Session, role: str = "admin") -> User:
    operator = User(
        user_id="rule-operator", username="rule-operator", display_name="Rule Operator",
        role=role, status="active", is_initialized=True, store_scope_mode="all",
        password_hash=hash_password_pbkdf2("isolated-password"),
    )
    session.add(operator)
    session.commit()
    response = client.post("/api/v1/auth/login", json={
        "username": operator.username, "password": "isolated-password",
    })
    assert response.status_code == 200
    session.merge(UserPagePermissionOverride(
        user_id=operator.user_id, page_key="D03", effect="allow",
    ))
    session.commit()
    return operator


@pytest.mark.parametrize("mode", ["single", "import"])
def test_authorized_admin_can_publish_fee_rules(client: TestClient, db_session: Session, mode: str) -> None:
    _seed_sku(db_session, "permission-sku", "权限测试")
    operator = _login_rule_operator(client, db_session)
    if mode == "single":
        path = "/api/v1/admin/sku-fee-rules"
        payload = {
            "skuId": "permission-sku", "promotionServiceFeeRate": "0.100000",
            "managementServiceFeeRate": "0.100000", "effectiveDate": "2026-08-01",
            "ruleStatus": "ACTIVE", "changeReason": "isolated permission test",
        }
    else:
        uploaded = _upload(client, _csv([("权限测试", "permission-sku", "0.1", "0.1")]))
        assert uploaded.status_code == 200
        batch_id = uploaded.json()["data"]["batch"]["batchId"]
        path = f"/api/v1/admin/sku-fee-rule-imports/{batch_id}/commit"
        payload = {"changeReason": "isolated permission test"}
    headers = {"Idempotency-Key": f"permission-test-{mode}-0001"}
    response = client.post(path, json=payload, headers=headers)
    assert response.status_code == 200, response.text
    retry = client.post(path, json=payload, headers=headers)
    assert retry.status_code == 200
    assert retry.json()["data"] == response.json()["data"]
    rules = list(db_session.scalars(select(SkuFeeRule)))
    assert len(rules) == 1
    assert rules[0].created_by == operator.username
    detail = client.get(f"/api/v1/admin/sku-fee-rules/{rules[0].rule_version}")
    assert detail.status_code == 200
    assert detail.json()["data"]["ruleVersion"] == rules[0].rule_version
    assert detail.json()["data"]["createdBy"] == operator.username
    assert detail.json()["data"]["promotionServiceFeeRate"] == "0.100000"
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 1
    assert operator.role == "admin"


@pytest.mark.parametrize("role", ["admin", "store"])
def test_rule_write_preserves_page_and_role_boundaries(client: TestClient, db_session: Session, role: str) -> None:
    operator = _login_rule_operator(client, db_session, role)
    if role == "admin":
        operator.store_scope_mode = "specified"
        db_session.merge(UserPagePermissionOverride(
            user_id=operator.user_id, page_key="D03", effect="deny",
        ))
        db_session.commit()
    for path in ["/api/v1/admin/sku-fee-rules", "/api/v1/admin/sku-fee-rule-imports/missing/commit"]:
        response = client.post(path, json={}, headers={"Idempotency-Key": "permission-denied-0001"})
        assert response.status_code == 403
    assert db_session.scalar(select(func.count()).select_from(SkuFeeRule)) == 0
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0


def test_scoped_admin_cannot_use_global_rebuild_or_scope(client: TestClient, db_session: Session) -> None:
    operator = _login_rule_operator(client, db_session)
    operator.store_scope_mode = "specified"
    db_session.commit()
    for path in ["/api/v1/admin/sku-fee-rules/rebuild", "/api/v1/admin/settlement-scope-rules"]:
        response = client.post(path, json={}, headers={"Idempotency-Key": "highest-only-test-0001"})
        assert response.status_code == 403
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0


@pytest.mark.parametrize("session_state", ["anonymous", "revoked", "inactive"])
def test_fee_publish_rejects_invalid_sessions(client: TestClient, db_session: Session, session_state: str) -> None:
    if session_state != "anonymous":
        operator = _login_rule_operator(client, db_session)
        if session_state == "revoked":
            operator.auth_version += 1
        else:
            operator.status = "inactive"
        db_session.commit()
    for path in ["/api/v1/admin/sku-fee-rules", "/api/v1/admin/sku-fee-rule-imports/missing/commit"]:
        response = client.post(path, json={}, headers={"Idempotency-Key": "invalid-session-test-0001"})
        assert response.status_code == 401
    assert db_session.scalar(select(func.count()).select_from(SkuFeeRule)) == 0
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0


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


def test_admin_type_filter_ignores_legacy_scope_and_updates_only_manual_type(client, db_session):
    first = _seed_sku(db_session, "type-a-1", "商品一")
    second = _seed_sku(db_session, "type-a-2", "商品二")
    third = _seed_sku(db_session, "type-b", "商品三")
    first.product_scope, first.product_type = "", "类型A"
    second.product_scope, second.product_type = "其他内部范围", "类型A"
    third.product_type = "类型B"
    db_session.commit()
    before = (first.product_id, first.owner_account_id, first.last_synced_at, first.commission_rate)
    _login(client)
    listing = client.get("/api/v1/admin/sku-products", params={
        "productType": "类型A", "productScope": "不存在的旧范围", "pageSize": 1,
    })
    assert listing.status_code == 200
    assert listing.json()["data"]["total"] == 2
    assert len(listing.json()["data"]["list"]) == 1
    assert listing.json()["data"]["statusCounts"] == {"unconfigured": 0, "partial": 0, "configured": 2}
    assert client.get("/api/v1/admin/sku-products").json()["data"]["total"] == 3
    assert client.get("/api/v1/admin/sku-products", params={"productType": "类型B"}).json()["data"]["total"] == 1
    updated = client.put(f"/api/v1/admin/sku-products/{first.sku_id}", json={
        "expectedManualModifiedAt": None, "productScope": "精诚养车", "productType": " 新类型 ",
    })
    assert updated.status_code == 200
    assert updated.json()["data"]["productType"] == "新类型"
    assert updated.json()["data"]["productScope"] == ""
    assert updated.json()["data"]["configurationStatus"] == "CONFIGURED"
    db_session.refresh(first)
    assert (first.product_id, first.owner_account_id, first.last_synced_at, first.commission_rate) == before
    assert first.manual_modified_by == "system-admin"
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0
    rejected = client.put(f"/api/v1/admin/sku-products/{first.sku_id}", json={
        "expectedManualModifiedAt": updated.json()["data"]["manualModifiedAt"], "productType": "类型B", "productName": "禁止覆盖",
    })
    assert rejected.status_code == 422


def test_configuration_status_only_uses_type_and_orders_latest_changes(client, db_session):
    rows = [
        ("empty", "", ""), ("scope-only", "精诚养车", ""),
        ("type-old", "", "类型A"), ("type-new", "其他", "类型B"),
        ("unknown", "其他", "unknown"), ("keep", "", "KEEP"),
    ]
    for index, (sku_id, scope, product_type) in enumerate(rows):
        row = _seed_sku(db_session, sku_id, sku_id)
        row.product_scope, row.product_type = scope, product_type
        row.manual_modified_at = datetime(2026, 10, 1, index, tzinfo=timezone.utc)
    db_session.commit()
    _login(client)
    response = client.get("/api/v1/admin/sku-products")
    data = response.json()["data"]
    assert data["statusCounts"] == {"unconfigured": 4, "partial": 0, "configured": 2}
    assert [item["skuId"] for item in data["list"]] == ["keep", "unknown", "scope-only", "empty", "type-new", "type-old"]
    assert all(item["configurationStatus"] == "UNCONFIGURED" for item in data["list"][:4])
    pending = client.get("/api/v1/admin/sku-products", params={"configurationStatus": "PENDING"})
    assert pending.json()["data"]["total"] == 4
    assert client.get("/api/v1/admin/sku-products", params={"configurationStatus": "PARTIAL"}).json()["data"]["total"] == 0


def test_single_type_update_rejects_stale_manual_version(client, db_session):
    row = _seed_sku(db_session, "concurrent", "并发商品")
    db_session.commit()
    _login(client)
    first = client.put(f"/api/v1/admin/sku-products/{row.sku_id}", json={
        "expectedManualModifiedAt": None, "productType": "首次类型",
    })
    assert first.status_code == 200
    stale = client.put(f"/api/v1/admin/sku-products/{row.sku_id}", json={
        "expectedManualModifiedAt": None, "productType": "过期覆盖",
    }, headers={"X-Request-ID": "stale-type-update"})
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "CONCURRENT_MODIFICATION"
    db_session.refresh(row)
    assert row.product_type == "首次类型" and row.product_scope == "原范围"


def test_service_only_update_preserves_type_and_scope_only_input_is_rejected(client, db_session):
    row = _seed_sku(db_session, "manual", "人工商品")
    db_session.commit()
    _login(client)
    response = client.put(f"/api/v1/admin/sku-products/{row.sku_id}", json={
        "expectedManualModifiedAt": None, "productScope": "新范围", "isServiceProduct": True,
    })
    assert response.status_code == 200
    assert response.json()["data"]["productScope"] == "原范围"
    assert response.json()["data"]["productType"] == "原类型"
    scope_only = client.put(f"/api/v1/admin/sku-products/{row.sku_id}", json={
        "expectedManualModifiedAt": response.json()["data"]["manualModifiedAt"], "productScope": "ignored",
    })
    assert scope_only.status_code == 422
    assert scope_only.json()["detail"]["code"] == "VALIDATION_FAILED"


@pytest.mark.parametrize("reserved", ["all", "unknown", "KEEP", "  keep  ", " "])
def test_type_update_rejects_reserved_or_empty_values(client, db_session, reserved):
    row = _seed_sku(db_session, "reserved", "保留值商品")
    db_session.commit()
    _login(client)
    response = client.put(f"/api/v1/admin/sku-products/{row.sku_id}", json={
        "expectedManualModifiedAt": None, "productType": reserved,
    })
    assert response.status_code == 422
    db_session.refresh(row)
    assert row.product_type == "原类型"


def test_bulk_type_update_is_atomic_across_scopes_and_keeps_scope(client, db_session):
    first = _seed_sku(db_session, "bulk-a", "批量一")
    second = _seed_sku(db_session, "bulk-b", "批量二")
    first.product_scope, second.product_scope = "", "其他"
    second.product_type = "第二类型"
    db_session.commit()
    _login(client)
    rejected = client.put("/api/v1/admin/sku-products/bulk", json={
        "skuIds": [first.sku_id, "missing"], "productType": "不能部分写入",
    })
    assert rejected.status_code == 404
    db_session.refresh(first)
    assert first.product_type == "原类型"
    service_only = client.put("/api/v1/admin/sku-products/bulk", json={
        "skuIds": [first.sku_id, second.sku_id], "isServiceProduct": True, "productScope": "ignored",
    })
    assert service_only.status_code == 200
    db_session.refresh(first)
    db_session.refresh(second)
    assert (first.product_type, second.product_type) == ("原类型", "第二类型")
    changed = client.put("/api/v1/admin/sku-products/bulk", json={
        "skuIds": [first.sku_id, second.sku_id], "productType": "统一类型", "productScope": "ignored",
    })
    assert changed.status_code == 200 and changed.json()["data"]["updatedCount"] == 2
    db_session.refresh(first)
    db_session.refresh(second)
    assert (first.product_scope, second.product_scope) == ("", "其他")
    assert first.product_type == second.product_type == "统一类型"
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0


@pytest.mark.parametrize("mode", ["single", "bulk", "import"])
def test_exact_jingcheng_scope_normalizes_type_consistently(client, db_session, mode):
    row = _seed_sku(db_session, "jingcheng", "与名称无关")
    row.product_scope = "精诚养车"
    db_session.commit()
    _login(client)
    if mode == "single":
        response = client.put(f"/api/v1/admin/sku-products/{row.sku_id}", json={
            "expectedManualModifiedAt": None, "productType": "旧分类",
        })
        assert response.json()["data"]["productType"] == "精诚养车"
    elif mode == "bulk":
        response = client.put("/api/v1/admin/sku-products/bulk", json={"skuIds": [row.sku_id], "productType": "旧分类"})
    else:
        uploaded = _upload_product_import(client, [(row.sku_id, "ignored", "旧分类")])
        assert uploaded.json()["data"]["normalizedTypeCount"] == 1
        assert "归一为精诚养车" in uploaded.json()["data"]["normalizationNotice"]
        batch_id = uploaded.json()["data"]["batch"]["batchId"]
        detail = client.get(f"/api/v1/admin/sku-product-imports/{batch_id}")
        assert detail.json()["data"]["rows"][0]["productType"] == "精诚养车"
        response = client.post(f"/api/v1/admin/sku-product-imports/{batch_id}/commit")
    assert response.status_code == 200
    db_session.refresh(row)
    assert row.product_type == row.product_scope == "精诚养车"
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0


@pytest.mark.parametrize("format", ["legacy-csv", "csv", "xlsx"])
def test_type_import_template_and_commit_preserve_internal_scope(client, db_session, format):
    first = _seed_sku(db_session, "import-a", "导入一")
    second = _seed_sku(db_session, "import-b", "导入二")
    first.product_scope, second.product_scope = "", "内部范围"
    db_session.commit()
    _login(client)
    template = client.get("/api/v1/admin/sku-product-imports/template")
    assert template.content.decode("utf-8-sig").splitlines()[0] == "skuId,productType"
    if format == "legacy-csv":
        uploaded = _upload_product_import(client, [(first.sku_id, "精诚养车", "类型A"), (second.sku_id, "", "类型B")])
    else:
        if format == "csv":
            content = "skuId,productType\nimport-a,类型A\nimport-b,类型B\n".encode("utf-8")
        else:
            workbook = Workbook()
            workbook.active.append(["skuId", "productType"])
            workbook.active.append([first.sku_id, "类型A"])
            workbook.active.append([second.sku_id, "类型B"])
            output = BytesIO()
            workbook.save(output)
            content = output.getvalue()
        uploaded = client.post("/api/v1/admin/sku-product-imports", files={"file": (f"types.{format}", content)})
    assert uploaded.status_code == 200
    batch = uploaded.json()["data"]["batch"]
    assert batch["batchStatus"] == "PENDING_COMMIT" and batch["validCount"] == 2
    url = f"/api/v1/admin/sku-product-imports/{batch['batchId']}/commit"
    assert client.post(url).json()["data"]["batch"]["successCount"] == 2
    assert client.post(url).status_code == 200
    db_session.refresh(first)
    db_session.refresh(second)
    assert (first.product_scope, first.product_type) == ("", "类型A")
    assert (second.product_scope, second.product_type) == ("内部范围", "类型B")
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0


@pytest.mark.parametrize("rows", [
    [("invalid", "ignored", "")], [("invalid", "ignored", "KEEP")],
    [("invalid", "ignored", "all")], [("invalid", "ignored", "unknown")],
    [("missing", "ignored", "类型")],
    [("invalid", "ignored", "类型A"), ("invalid", "ignored", "类型B")],
])
def test_type_import_prevalidation_rejects_invalid_type_or_identity(client, db_session, rows):
    row = _seed_sku(db_session, "invalid", "非法输入")
    db_session.commit()
    _login(client)
    uploaded = _upload_product_import(client, rows)
    batch = uploaded.json()["data"]["batch"]
    assert batch["batchStatus"] == "VALIDATION_FAILED" and batch["successCount"] == 0
    assert uploaded.json()["data"]["errorPreview"]
    assert client.post(f"/api/v1/admin/sku-product-imports/{batch['batchId']}/commit").status_code == 409
    db_session.refresh(row)
    assert row.product_type == "原类型"


def test_preexisting_legacy_pending_batch_never_changes_scope(client, db_session):
    first = _seed_sku(db_session, "legacy-change", "历史批次")
    second = _seed_sku(db_session, "legacy-keep", "历史仅改范围")
    target = _seed_sku(db_session, "legacy-jingcheng", "目标")
    target.product_scope = "精诚养车"
    db_session.add(SkuProductImportBatch(batch_id="legacy-batch", file_name="old.csv", file_sha256="a" * 64,
        batch_status=3, total_count=3, valid_count=3, uploaded_by="legacy"))
    for index, sku_id in enumerate((first.sku_id, second.sku_id, target.sku_id)):
        db_session.add(SkuProductImportRow(batch_id="legacy-batch", row_number=index + 2, sku_id=sku_id,
            product_scope="不能覆盖内部范围", keep_product_scope=False,
            product_type="历史待提交类型", keep_product_type=index == 1, validation_status=2))
    db_session.commit()
    _login(client)
    response = client.post("/api/v1/admin/sku-product-imports/legacy-batch/commit")
    assert response.status_code == 200
    for row in (first, second, target):
        db_session.refresh(row)
    assert (first.product_scope, first.product_type) == ("原范围", "历史待提交类型")
    assert (second.product_scope, second.product_type) == ("原范围", "原类型")
    assert (target.product_scope, target.product_type) == ("精诚养车", "精诚养车")


@pytest.mark.parametrize("mutation", ["delete", "invalid-row"])
def test_type_import_commit_revalidates_all_rows_atomically(client, db_session, mutation):
    first = _seed_sku(db_session, "atomic-a", "原子一")
    second = _seed_sku(db_session, "atomic-b", "原子二")
    db_session.commit()
    _login(client)
    uploaded = _upload_product_import(client, [(first.sku_id, "ignored", "类型A"), (second.sku_id, "ignored", "类型B")])
    batch_id = uploaded.json()["data"]["batch"]["batchId"]
    if mutation == "delete":
        db_session.delete(second)
    else:
        imported = db_session.scalar(select(SkuProductImportRow).where(SkuProductImportRow.batch_id == batch_id))
        imported.product_type = "unknown"
    db_session.commit()
    response = client.post(f"/api/v1/admin/sku-product-imports/{batch_id}/commit")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "IMPORT_DATA_CHANGED"
    db_session.refresh(first)
    assert first.product_type == "原类型"
    batch = db_session.scalar(select(SkuProductImportBatch).where(SkuProductImportBatch.batch_id == batch_id))
    assert batch.success_count == 0


@pytest.mark.parametrize("role", ["admin", "store"])
def test_classification_write_preserves_global_role_boundary(client, db_session, role):
    row = _seed_sku(db_session, "restricted", "权限商品")
    db_session.commit()
    operator = _login_rule_operator(client, db_session, role)
    operator.store_scope_mode = "specified"
    db_session.commit()
    assert client.put(f"/api/v1/admin/sku-products/{row.sku_id}", json={
        "expectedManualModifiedAt": None, "productType": "unauthorized",
    }).status_code == 403
    assert client.put("/api/v1/admin/sku-products/bulk", json={"skuIds": [row.sku_id], "productType": "unauthorized"}).status_code == 403
    assert _upload_product_import(client, [(row.sku_id, "ignored", "unauthorized")]).status_code == 403


def test_bulk_type_failure_rolls_back_previous_row_changes(client, db_session, monkeypatch):
    first = _seed_sku(db_session, "rollback-a", "回滚一")
    second = _seed_sku(db_session, "rollback-b", "回滚二")
    db_session.commit()
    _login(client)
    bind = db_session.get_bind()
    def isolated_session():
        with Session(bind, autoflush=False) as session:
            yield session
    client.app.dependency_overrides[get_session_dependency] = isolated_session
    original = fee_admin_routes._apply_sku_product_manual_update
    def fail_second(row, *args, **kwargs):
        original(row, *args, **kwargs)
        if row.sku_id == "rollback-b":
            raise RuntimeError("injected second-row failure")
    monkeypatch.setattr(fee_admin_routes, "_apply_sku_product_manual_update", fail_second)
    with pytest.raises(RuntimeError, match="injected"):
        client.put("/api/v1/admin/sku-products/bulk", json={"skuIds": [first.sku_id, second.sku_id], "productType": "new"})
    db_session.expire_all()
    assert [row.product_type for row in db_session.scalars(select(DimSkuProductRule).order_by(DimSkuProductRule.sku_id))] == ["原类型", "原类型"]


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
    rebuild_jobs = list(
        db_session.scalars(
            select(JobRun).where(JobRun.job_name == "settlement_rebuild")
        )
    )
    assert len(rebuild_jobs) == 1
    assert rebuild_jobs[0].status == "queued"
    assert rebuild_jobs[0].metadata_json["trigger"] == "admin_sku_fee_rule"
    assert rebuild_jobs[0].metadata_json["updated_rule_count"] == 1
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
) -> None:
    _login(client)
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
    rebuild_jobs = list(
        db_session.scalars(
            select(JobRun).where(JobRun.job_name == "settlement_rebuild")
        )
    )
    assert len(rebuild_jobs) == 1
    assert rebuild_jobs[0].status == "queued"
    assert rebuild_jobs[0].metadata_json["trigger"] == (
        "admin_settlement_scope_rule"
    )
    assert rebuild_jobs[0].metadata_json["updated_rule_count"] == 2

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
