"""Permission-checked internal monthly trial reads and Chinese exports."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from dy_api.auth import AuthContext, get_current_user
from dy_api.routes._data import generated_at, get_data_store, request_id, with_utf8_bom
from dy_api.routes._publications import attach_publication, publication_read
from dy_api.routes.dashboard import (
    FINANCE_DIRECTION_PAGE_KEYS, _billing_session, _finance_scope_store_ids,
    _normalize_billing_direction, _raise_reporting_error, _reporting_success,
    _require_billing_store, _require_finance_admin, _require_finance_store_scope, _validate_month,
)
from apps.api.dy_api.dashboard_publications.fee_trial import read, read_stores
from apps.api.dy_api.download_localization import localized_csv
from apps.api.dy_api.fee_trial_schemas import FeeTrialData, FeeTrialStoresData


router = APIRouter()
STATUS_LABELS = {"CALCULATED": "已算费用（试算）", "PENDING": "待核验", "EXCLUDED": "已明确排除"}


def _read_trial(request, store, current_user, *, month, fee_direction, store_id, product_type,
                q, record_status, publication_id, page=1, page_size=50, export=False, view="detail"):
    session = _billing_session(store, request)
    _validate_month(month, "month", request)
    direction = _normalize_billing_direction(fee_direction, request)
    _require_finance_admin(current_user, request, page_key=FINANCE_DIRECTION_PAGE_KEYS[direction])
    if store_id is not None:
        _require_billing_store(session, store_id, request)
        _require_finance_store_scope(current_user, store_id, request)
    if record_status is not None and record_status not in STATUS_LABELS:
        _raise_reporting_error(request, 422, "VALIDATION_FAILED", "试算记录状态不合法")
    with publication_read(session, "settlement", publication_id) as publication:
        reader = read_stores if view == "stores" else read
        data = reader(session, publication.id, month=month, fee_direction=direction,
            store_id=store_id, product_type=product_type, q=q, record_status=record_status,
            scope_store_ids=_finance_scope_store_ids(current_user), page=page, page_size=page_size, export=export)
    schema = FeeTrialStoresData if view == "stores" else FeeTrialData
    return schema.model_validate(data).model_dump(), publication


@router.get("/admin/finance/trial")
def monthly_fee_trial(
    request: Request,
    month: str = Query(), fee_direction: str = Query(alias="feeDirection"),
    store_id: str | None = Query(default=None, alias="storeId"),
    product_type: str = Query(default="all", alias="productType", max_length=128),
    q: str | None = Query(default=None, max_length=255),
    record_status: str | None = Query(default=None, alias="recordStatus"),
    publication_id: str | None = Query(default=None, max_length=64),
    page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=100, alias="pageSize"),
    current_user: AuthContext = Depends(get_current_user), store=Depends(get_data_store),
):
    data, publication = _read_trial(request, store, current_user, month=month, fee_direction=fee_direction,
        store_id=store_id, product_type=product_type, q=q, record_status=record_status,
        publication_id=publication_id, page=page, page_size=page_size)
    return attach_publication(_reporting_success(request, data), publication)


@router.get("/admin/finance/trial/export")
def export_monthly_fee_trial(
    request: Request,
    month: str = Query(), fee_direction: str = Query(alias="feeDirection"),
    store_id: str | None = Query(default=None, alias="storeId"),
    product_type: str = Query(default="all", alias="productType", max_length=128),
    q: str | None = Query(default=None, max_length=255),
    record_status: str | None = Query(default=None, alias="recordStatus"),
    publication_id: str = Query(max_length=64),
    current_user: AuthContext = Depends(get_current_user), store=Depends(get_data_store),
):
    data, publication = _read_trial(request, store, current_user, month=month, fee_direction=fee_direction,
        store_id=store_id, product_type=product_type, q=q, record_status=record_status,
        publication_id=publication_id, export=True)
    if data["total"] > 100000:
        _raise_reporting_error(request, 413, "EXPORT_LIMIT_EXCEEDED", "试算明细超过 100000 行，请缩小筛选范围")
    coverage = data["coverage"]
    export_rows = [{**item, "month": month, "fee_direction": data["fee_direction"],
        "trial_status": "试算／待核验", "record_status_label": STATUS_LABELS[item["record_status"]],
        "publication_version": publication.id,
        "coverage_note": coverage["note"], "fee_amount_note": "金额待核" if item["record_status"] == "PENDING" else ""}
        for item in data["list"]]
    fields = {"month": "账期", "trial_status": "数据状态", "publication_version": "试算版本",
        "fee_direction": "费用方向", "coupon_id": "券ID", "order_id": "订单ID", "store_id": "门店ID",
        "store_name": "门店名称", "product_type": "商品类型", "sku_id": "SKU ID",
        "record_status_label": "核对状态", "base_amount_cent": "计费基数", "fee_rate": "费率",
        "fee_amount_cent": "试算费用", "fee_amount_note": "金额说明", "rule_version": "费率规则版本",
        "reason": "待核或排除原因", "coverage_note": "覆盖范围说明"}
    content = localized_csv(list(fields), export_rows, header_labels=fields)
    title = "推广服务费" if data["fee_direction"] == "PROMOTION" else "管理服务费"
    filename = quote(f"{title}内部试算_{month}_{publication.id[:12]}.csv")
    return Response(content=with_utf8_bom(content), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
        "X-Export-Result": "SUCCESS" if export_rows else "EMPTY", "X-Publication-ID": publication.id,
        "X-Request-ID": request_id(request), "X-Export-Generated-At": generated_at().isoformat(),
    })


@router.get("/admin/finance/trial/stores")
def monthly_fee_trial_stores(
    request: Request,
    month: str = Query(), fee_direction: str = Query(alias="feeDirection"),
    store_id: str | None = Query(default=None, alias="storeId"),
    product_type: str = Query(default="all", alias="productType", max_length=128),
    q: str | None = Query(default=None, max_length=255),
    record_status: str | None = Query(default=None, alias="recordStatus"),
    publication_id: str | None = Query(default=None, max_length=64),
    page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=100, alias="pageSize"),
    current_user: AuthContext = Depends(get_current_user), store=Depends(get_data_store),
):
    data, publication = _read_trial(request, store, current_user, month=month, fee_direction=fee_direction,
        store_id=store_id, product_type=product_type, q=q, record_status=record_status,
        publication_id=publication_id, page=page, page_size=page_size, view="stores")
    return attach_publication(_reporting_success(request, data), publication)


@router.get("/admin/finance/trial/stores/export")
def export_monthly_fee_trial_stores(
    request: Request,
    month: str = Query(), fee_direction: str = Query(alias="feeDirection"),
    store_id: str | None = Query(default=None, alias="storeId"),
    product_type: str = Query(default="all", alias="productType", max_length=128),
    q: str | None = Query(default=None, max_length=255),
    record_status: str | None = Query(default=None, alias="recordStatus"),
    publication_id: str = Query(max_length=64),
    current_user: AuthContext = Depends(get_current_user), store=Depends(get_data_store),
):
    data, publication = _read_trial(request, store, current_user, month=month, fee_direction=fee_direction,
        store_id=store_id, product_type=product_type, q=q, record_status=record_status,
        publication_id=publication_id, export=True, view="stores")
    if data["total"] > 100000:
        _raise_reporting_error(request, 413, "EXPORT_LIMIT_EXCEEDED", "试算汇总超过 100000 家门店，请缩小筛选范围")
    records = [{**item, "summary_level": "门店"} for item in data["list"]]
    records.append({**data["summary"], "summary_level": "总计", "store_id": None, "store_name": "全部筛选范围"})
    export_rows = [{**item, "month": month, "fee_direction": data["fee_direction"],
        "trial_status": "试算／待核验", "publication_version": publication.id,
        "coverage_status": "完整" if item["coverage_complete"] else "待核验",
        "coverage_note": data["coverage"]["note"]} for item in records]
    fields = {"month": "账期", "trial_status": "数据状态", "publication_version": "试算版本",
        "fee_direction": "费用方向", "summary_level": "汇总层级", "store_id": "门店ID", "store_name": "门店名称",
        "calculated_fee_cent": "已算费用", "calculated_coupon_count": "已算券数",
        "pending_coupon_count": "待核券数", "excluded_coupon_count": "已排除券数",
        "candidate_coupon_count": "候选券数", "coverage_status": "覆盖状态", "coverage_note": "覆盖范围说明"}
    content = localized_csv(list(fields), export_rows, header_labels=fields)
    title = "推广服务费" if data["fee_direction"] == "PROMOTION" else "管理服务费"
    filename = quote(f"{title}门店试算汇总_{month}_{publication.id[:12]}.csv")
    return Response(content=with_utf8_bom(content), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
        "X-Export-Result": "SUCCESS", "X-Export-Data-Rows": str(data["total"]), "X-Publication-ID": publication.id,
        "X-Request-ID": request_id(request), "X-Export-Generated-At": generated_at().isoformat(),
    })
