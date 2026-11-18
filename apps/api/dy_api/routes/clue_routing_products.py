"""Human-session product management, sharing service authorization with the CLI."""
from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from apps.api.dy_api.clue_product_routing import (
    ProductRoutingError, batch_product_changes, get_product_grants, get_shared_rule,
    get_shared_rule_grants, list_products, publish_shared_rule, replace_product_grants,
    replace_shared_rule_grants,
)
from apps.api.dy_api.clue_product_routing_schemas import (
    ProductRoutingBatchRequest, ProductRoutingGrantsRequest, SharedRoutingRuleRequest,
)
from dy_api.auth import AuthContext, get_current_user
from dy_api.routes._data import generated_at, get_session_dependency


router = APIRouter(prefix="/clue-routing")


def _human_user(current_user: AuthContext = Depends(get_current_user)) -> AuthContext:
    if current_user.auth_type not in {"user", "env_admin"}:
        raise HTTPException(status_code=403, detail={"code": "HUMAN_SESSION_REQUIRED", "message": "商品管理须使用本人交互登录会话"})
    return current_user


def _session(session: Any = Depends(get_session_dependency)) -> Session:
    if session is None:
        raise HTTPException(status_code=503, detail={"code": "DATABASE_REQUIRED", "message": "商品管理数据库暂不可用"})
    return session


def _response(request: Request, data: dict[str, Any]) -> dict[str, Any]:
    return {"data": data, "meta": {"request_id": _request_id(request), "generated_at": generated_at()}}


def _request_id(request: Request) -> str:
    if not getattr(request.state, "product_routing_request_id", None):
        request.state.product_routing_request_id = uuid4().hex
    return request.state.product_routing_request_id


def _http_error(exc: ProductRoutingError) -> HTTPException:
    return HTTPException(status_code=exc.http_status, detail={"code": exc.code, "message": exc.message})


@router.get("/products", summary="查询本人可管理的商品及已发布流转配置")
def list_routing_products(
    request: Request, q: str = Query(default="", max_length=200),
    product_scope: Literal["all", "jingcheng", "byd"] = "all",
    page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200),
    actor: AuthContext = Depends(_human_user), session: Session = Depends(_session),
) -> dict[str, Any]:
    """Return one row per permitted product; GET never publishes or enables."""
    return _response(request, list_products(session, actor, q=q, product_scope=product_scope, page=page, page_size=page_size))


@router.post("/products/batch", summary="预览或逐商品发布名单、规则与手动启停")
def change_routing_products(
    request: Request, body: ProductRoutingBatchRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
    actor: AuthContext = Depends(_human_user), session: Session = Depends(_session),
) -> dict[str, Any]:
    """Use product savepoints so a failed item retains its prior publication."""
    try:
        data = batch_product_changes(session, actor, body.model_dump(exclude_none=True),
            request_id=_request_id(request), idempotency_key=idempotency_key)
        if not body.preview:
            session.commit()
        return _response(request, data)
    except ProductRoutingError as exc:
        session.rollback()
        raise _http_error(exc) from None


@router.get("/products/{product_id}/grants", summary="读取商品管理授权与可授权账号")
def read_routing_product_grants(
    request: Request, product_id: str,
    actor: AuthContext = Depends(_human_user), session: Session = Depends(_session),
) -> dict[str, Any]:
    """Grant delegation remains exclusive to all-store administrators."""
    try:
        return _response(request, get_product_grants(session, actor, product_id))
    except ProductRoutingError as exc:
        raise _http_error(exc) from None


@router.put("/products/{product_id}/grants", summary="替换指定商品的管理授权")
def update_routing_product_grants(
    request: Request, product_id: str, body: ProductRoutingGrantsRequest,
    actor: AuthContext = Depends(_human_user), session: Session = Depends(_session),
) -> dict[str, Any]:
    """Replace a grant set atomically and preserve the permission audit."""
    try:
        data = replace_product_grants(session, actor, product_id, body.user_ids, request_id=_request_id(request))
        session.commit()
        return _response(request, data)
    except ProductRoutingError as exc:
        session.rollback()
        raise _http_error(exc) from None


@router.get("/shared-rule", summary="读取明确标识的精诚养车共享流转基座")
def read_shared_routing_rule(
    request: Request, actor: AuthContext = Depends(_human_user), session: Session = Depends(_session),
) -> dict[str, Any]:
    """Return fixed initial defaults when the first base is not published yet."""
    try:
        return _response(request, get_shared_rule(session, actor))
    except ProductRoutingError as exc:
        raise _http_error(exc) from None


@router.get("/shared-rule/grants", summary="查询精诚共享规则维护人与可授权账号")
def read_shared_rule_maintainers(
    request: Request, actor: AuthContext = Depends(_human_user), session: Session = Depends(_session),
) -> dict[str, Any]:
    """Only global admins may inspect or delegate maintainer membership."""
    try:
        return _response(request, get_shared_rule_grants(session, actor))
    except ProductRoutingError as exc:
        raise _http_error(exc) from None


@router.put("/shared-rule/grants", summary="替换精诚共享规则维护人授权")
def update_shared_rule_maintainers(
    request: Request, body: ProductRoutingGrantsRequest,
    actor: AuthContext = Depends(_human_user), session: Session = Depends(_session),
) -> dict[str, Any]:
    """Grant shared-base maintenance without widening any product/store scope."""
    try:
        data = replace_shared_rule_grants(session, actor, body.user_ids, request_id=_request_id(request))
        session.commit()
        return _response(request, data)
    except ProductRoutingError as exc:
        session.rollback()
        raise _http_error(exc) from None


@router.put("/shared-rule", summary="预览或发布精诚养车共享基座的新版本")
def update_shared_routing_rule(
    request: Request, body: SharedRoutingRuleRequest,
    actor: AuthContext = Depends(_human_user), session: Session = Depends(_session),
) -> dict[str, Any]:
    """Existing product pointers and ingress bindings never change with the base."""
    try:
        data = publish_shared_rule(session, actor, body.rules.model_dump(exclude_none=True),
                                   preview=body.preview, request_id=_request_id(request))
        if not body.preview:
            session.commit()
        return _response(request, data)
    except ProductRoutingError as exc:
        session.rollback()
        raise _http_error(exc) from None
