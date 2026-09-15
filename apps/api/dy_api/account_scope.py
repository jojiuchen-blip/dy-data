"""Organization bindings resolve against current store ownership on every request."""
from sqlalchemy import select
from apps.api.dy_api.models import DimStore, DimStoreOrgAssignment

ORG_FIELDS = ('group_name', 'service_center_name', 'district_name', 'area_name')
ORG_LEVELS = ('group', 'service_center', 'district', 'area')
ORG_SCOPE_FIELDS = {
    'group': ('group_name',),
    'service_center': ('service_center_name',),
    'district': ('service_center_name', 'district_name'),
    'area': ('service_center_name', 'district_name', 'area_name'),
}
ORG_FIELD_LABELS = dict(zip(ORG_FIELDS, ('集团', '服务中心', '大区', '区域')))


def normalize_org_scope(scope: dict) -> dict:
    level = scope.get('level')
    if level not in ORG_LEVELS:
        raise ValueError('请选择有效的组织层级')
    fields = ORG_SCOPE_FIELDS[level]
    result = {'level': level}
    for field in fields:
        value = scope.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'请填写{ORG_FIELD_LABELS[field]}')
        result[field] = value.strip()
    return result


def organization_store_ids(session, scope: dict) -> tuple[str, ...]:
    try:
        normalized = normalize_org_scope(scope)
    except (ValueError, TypeError, AttributeError):
        return ()  # Invalid persisted bindings never grant access.
    statement = select(DimStore.store_id).join(
        DimStoreOrgAssignment, DimStoreOrgAssignment.service_store_code == DimStore.service_store_code
    ).where(DimStoreOrgAssignment.is_active.is_(True), DimStore.is_active.is_(True))
    for field, value in normalized.items():
        if field != 'level':
            statement = statement.where(getattr(DimStoreOrgAssignment, field) == value)
    return tuple(session.scalars(statement.order_by(DimStore.store_id)).all())


def account_store_catalog(session, actor) -> list[dict]:
    statement = select(DimStore, DimStoreOrgAssignment).outerjoin(
        DimStoreOrgAssignment, (DimStoreOrgAssignment.service_store_code == DimStore.service_store_code)
        & DimStoreOrgAssignment.is_active.is_(True)
    ).where(DimStore.is_active.is_(True)).order_by(DimStore.store_name, DimStore.store_id)
    if not actor.has_global_data_access:
        statement = statement.where(DimStore.store_id.in_(actor.store_ids))
    return [dict(store_id=store.store_id, store_name=store.store_name or '',
                 **{field: getattr(org, field, None) or '' for field in ORG_FIELDS})
            for store, org in session.execute(statement).all()]
