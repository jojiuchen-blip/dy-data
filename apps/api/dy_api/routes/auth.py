from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select

from dy_api.auth import (
    AuthContext,
    AdminPasswordNotConfigured,
    clear_session_cookie,
    find_user_by_account_identifier,
    find_user_by_identifier,
    get_current_user,
    hash_password_pbkdf2,
    normalize_account_value,
    set_auth_cookie,
    set_session_cookie,
    user_store_ids,
    verify_user_credentials,
    verify_admin_credentials,
)
from dy_api.routes._data import generated_at, get_session_dependency
from dy_api.schemas import (
    AccountActivationIdentityRequest,
    AccountActivationStatusData,
    AccountInitializeRequest,
    AccountPasswordResetRequest,
    AccountPasswordUpdateRequest,
    AdminUser,
    LoginRequest,
    dump_model,
)
from apps.api.dy_api.models import (
    DimStore,
    DimStorePoiMapping,
    RawAwemeBinding,
    User,
    UserStoreScope,
)


router = APIRouter()
SUB_ACCOUNT_TYPES = {"子机构经营号", "子机构账号"}
SUCCESSFUL_BINDING_STATUS = "认证成功"
ACCOUNT_TYPE_KEYS = ("账号类型", "账户类型", "account_type")


def _session_response(auth: AuthContext) -> dict:
    data = AdminUser(
        user_id=auth.user_id,
        username=auth.username,
        display_name=auth.display_name,
        role=auth.role,
        status="active",
        is_initialized=True,
        store_ids=list(auth.store_ids),
        is_highest_admin=auth.is_highest_admin,
    )
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "session"},
    }


@router.post("/login")
def login(
    payload: LoginRequest,
    response: Response,
    session=Depends(get_session_dependency),
):
    user = verify_user_credentials(session, payload.username, payload.password)
    if user is not None:
        auth = AuthContext(
            user_id=user.user_id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            store_ids=user_store_ids(session, user.user_id),
            auth_type="user",
        )
        set_auth_cookie(response, auth)
        return _session_response(auth)

    try:
        valid = verify_admin_credentials(payload.username, payload.password)
    except AdminPasswordNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    set_session_cookie(response, payload.username)
    return _session_response(
        AuthContext(
            user_id=None,
            username=payload.username,
            display_name=payload.username,
            role="admin",
            store_ids=(),
            auth_type="env_admin",
        )
    )


@router.get("/me")
def me(current_user: AuthContext = Depends(get_current_user)):
    return _session_response(current_user)


@router.post("/logout")
def logout(response: Response, current_user: AuthContext = Depends(get_current_user)):
    clear_session_cookie(response)
    return _session_response(current_user)


@router.post("/change-password")
def change_password(
    payload: AccountPasswordUpdateRequest,
    current_user: AuthContext = Depends(get_current_user),
    session=Depends(get_session_dependency),
):
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not available",
        )
    if not current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Environment admin password cannot be changed here",
        )
    if payload.password != payload.password_confirm:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password confirmation does not match",
        )
    user = session.get(User, current_user.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    user.password_hash = hash_password_pbkdf2(payload.password)
    user.is_initialized = True
    user.updated_at = generated_at()
    session.commit()
    return _session_response(current_user)


@router.post("/initialize")
def initialize_account(
    payload: AccountInitializeRequest,
    response: Response,
    session=Depends(get_session_dependency),
):
    user = _activate_account(payload, session=session)
    auth = AuthContext(
        user_id=user.user_id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        store_ids=user_store_ids(session, user.user_id),
        auth_type="user",
    )
    set_auth_cookie(response, auth)
    return _session_response(auth)


@router.post("/activation-status")
def activation_status(
    payload: AccountActivationIdentityRequest,
    session=Depends(get_session_dependency),
):
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not available",
        )
    state = _account_activation_state(
        session,
        payload.external_account_id,
        payload.poi_id,
    )
    data = AccountActivationStatusData(status=state)
    return {
        "data": dump_model(data),
        "meta": {"generated_at": generated_at(), "source": "database"},
    }


@router.post("/reset-password")
def reset_password(
    payload: AccountPasswordResetRequest,
    response: Response,
    session=Depends(get_session_dependency),
):
    user = _reset_account_password(payload, session=session)
    auth = AuthContext(
        user_id=user.user_id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        store_ids=user_store_ids(session, user.user_id),
        auth_type="user",
    )
    set_auth_cookie(response, auth)
    return _session_response(auth)


def _activate_account(
    payload: AccountInitializeRequest,
    *,
    session,
) -> User:
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not available",
        )
    if payload.password != payload.password_confirm:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password confirmation does not match",
        )

    store = _verified_activation_store(
        session,
        payload.external_account_id,
        payload.poi_id,
    )
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account verification failed",
        )

    username = normalize_account_value(payload.username)
    external_account_id = normalize_account_value(store.store_id)
    target = find_user_by_account_identifier(session, store.store_id)
    existing_by_username = find_user_by_identifier(session, username)

    if existing_by_username is not None and existing_by_username is not target:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists",
        )
    if target is not None and (target.password_hash or target.is_initialized):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account already initialized",
        )

    now = generated_at()
    if target is None:
        target = User(
            user_id=uuid4().hex,
            username=username,
            external_account_id=external_account_id,
            display_name=store.store_name,
            role="store",
            status="active",
            is_initialized=True,
            password_hash=hash_password_pbkdf2(payload.password),
            created_at=now,
            updated_at=now,
        )
        session.add(target)
    else:
        target.username = username
        target.external_account_id = external_account_id
        target.display_name = store.store_name
        target.status = "active"
        target.is_initialized = True
        target.password_hash = hash_password_pbkdf2(payload.password)
        target.updated_at = now

    session.flush()
    _replace_store_scopes(session, target.user_id, [store.store_id])
    session.commit()
    return target


def _reset_account_password(
    payload: AccountPasswordResetRequest,
    *,
    session,
) -> User:
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not available",
        )
    if payload.password != payload.password_confirm:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password confirmation does not match",
        )

    store = _verified_activation_store(
        session,
        payload.external_account_id,
        payload.poi_id,
    )
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account verification failed",
        )

    target = find_user_by_account_identifier(session, store.store_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account is not activated",
        )
    if target.role != "store" or target.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account verification failed",
        )

    if not target.password_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account is not activated",
        )

    now = generated_at()
    target.is_initialized = True
    target.password_hash = hash_password_pbkdf2(payload.password)
    target.updated_at = now

    session.commit()
    return target


def _account_activation_state(
    session,
    external_account_id: str,
    poi_id: str,
) -> str:
    store = _verified_activation_store(session, external_account_id, poi_id)
    if store is None:
        return "invalid"
    target = find_user_by_account_identifier(session, store.store_id)
    if target is not None and target.password_hash:
        return "activated"
    return "ready"


def _verified_activation_store(
    session,
    external_account_id: str,
    poi_id: str,
) -> DimStore | None:
    normalized_account_id = normalize_account_value(external_account_id)
    normalized_poi_id = normalize_account_value(poi_id)
    bindings = session.execute(
        select(RawAwemeBinding).where(
            RawAwemeBinding.account_id == normalized_account_id,
            RawAwemeBinding.poi_id == normalized_poi_id,
            RawAwemeBinding.binding_status == SUCCESSFUL_BINDING_STATUS,
        )
    ).scalars().all()
    if not any(_is_sub_account_binding(binding) for binding in bindings):
        return None

    store = session.get(DimStore, normalized_account_id)
    if store is None or not store.is_active:
        return None
    mapping = session.execute(
        select(DimStorePoiMapping).where(
            DimStorePoiMapping.store_id == store.store_id,
            DimStorePoiMapping.poi_id == normalized_poi_id,
        )
    ).scalar_one_or_none()
    return store if mapping is not None else None


def _is_sub_account_binding(binding: RawAwemeBinding) -> bool:
    raw_payload = binding.raw_payload or {}
    account_type = next(
        (
            normalize_account_value(raw_payload.get(key))
            for key in ACCOUNT_TYPE_KEYS
            if normalize_account_value(raw_payload.get(key))
        ),
        "",
    )
    return not account_type or account_type in SUB_ACCOUNT_TYPES


def _replace_store_scopes(session, user_id: str, store_ids: list[str]) -> None:
    session.execute(delete(UserStoreScope).where(UserStoreScope.user_id == user_id))
    for store_id in sorted(set(store_ids)):
        session.add(UserStoreScope(user_id=user_id, store_id=store_id))
    session.flush()
