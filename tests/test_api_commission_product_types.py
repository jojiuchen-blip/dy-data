"""Real administrator routes keep formal participant types on every edit path."""

import pytest
from sqlalchemy import func, select

from apps.api.dy_api.models import JobRun
from test_api_fee_admin import client, _login, _seed_sku, _upload_product_import
from test_commission_product_classification import _rule


@pytest.mark.parametrize("mode", ["single", "bulk", "import"])
@pytest.mark.parametrize("official", [False, True])
@pytest.mark.parametrize("requested_type", ["外观清洁", "售后官方"])
def test_commission_rule_types_survive_manual_edit_and_import(client, db_session, mode, official, requested_type):
    row = _seed_sku(db_session, "exact-participant", "Synthetic participant")
    row.product_scope = "与精诚旧scope无关"
    row.product_type = "268保养"
    fee_rule = _rule(db_session, row.sku_id, product_type="售后官方" if official else "268保养")
    db_session.commit()
    _login(client)
    if mode == "single":
        response = client.put(f"/api/v1/admin/sku-products/{row.sku_id}", json={
            "expectedManualModifiedAt": None, "productType": requested_type})
    elif mode == "bulk":
        response = client.put("/api/v1/admin/sku-products/bulk", json={
            "skuIds": [row.sku_id], "productType": requested_type})
    else:
        uploaded = _upload_product_import(client, [(row.sku_id, "ignored", requested_type)])
        assert uploaded.status_code == 200
        assert uploaded.json()["data"]["normalizedTypeCount"] == int(requested_type != ("售后官方" if official else "精诚养车"))
        batch_id = uploaded.json()["data"]["batch"]["batchId"]
        response = client.post(f"/api/v1/admin/sku-product-imports/{batch_id}/commit")
    assert response.status_code == 200, response.text
    db_session.refresh(row)
    db_session.refresh(fee_rule)
    assert row.product_type == ("售后官方" if official else "精诚养车")
    assert row.product_scope == "与精诚旧scope无关"
    assert fee_rule.product_type_snapshot == ("售后官方" if official else "268保养")
    assert db_session.scalar(select(func.count()).select_from(JobRun)) == 0
