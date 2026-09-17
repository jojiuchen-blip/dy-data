"""Organization bindings resolve against current store ownership on every request."""
from datetime import datetime, timezone
from sqlalchemy import inspect, select
from apps.api.dy_api.models import DimStore, DimStoreOrgAssignment
from apps.api.dy_api.ranking_schema_v1 import org_history

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


def _current_organization_source(session):
    """Use one complete effective roster; never revive removed historical stores."""
    if inspect(session.connection()).has_table(org_history.name):
        version = session.scalar(select(org_history.c.mapping_version).where(
            org_history.c.effective_from <= datetime.now(timezone.utc)
        ).order_by(org_history.c.effective_from.desc(),
                   org_history.c.mapping_version.desc()).limit(1))
        if version is not None:
            source = select(org_history).where(
                org_history.c.mapping_version == version).subquery()
            return source, source.c.store_id == DimStore.store_id
    # Compatibility for installations which have not published a formal roster.
    source = select(DimStoreOrgAssignment).where(
        DimStoreOrgAssignment.is_active.is_(True)).subquery()
    return source, source.c.service_store_code == DimStore.service_store_code


def organization_store_ids(session, scope: dict) -> tuple[str, ...]:
    try:
        normalized = normalize_org_scope(scope)
    except (ValueError, TypeError, AttributeError):
        return ()  # Invalid persisted bindings never grant access.
    source, join_condition = _current_organization_source(session)
    statement = select(DimStore.store_id).join(source, join_condition).where(
        DimStore.is_active.is_(True))
    for field, value in normalized.items():
        if field != 'level':
            statement = statement.where(source.c[field] == value)
    return tuple(session.scalars(statement.order_by(DimStore.store_id)).all())


def account_store_catalog(session, actor) -> list[dict]:
    source, join_condition = _current_organization_source(session)
    statement = select(DimStore, *(source.c[field] for field in ORG_FIELDS)).outerjoin(
        source, join_condition
    ).where(DimStore.is_active.is_(True)).order_by(DimStore.store_name, DimStore.store_id)
    if not actor.has_global_data_access:
        statement = statement.where(DimStore.store_id.in_(actor.store_ids))
    return [dict(store_id=row[0].store_id, store_name=row[0].store_name or '',
                 **dict(zip(ORG_FIELDS, (value or '' for value in row[1:]))))
            for row in session.execute(statement).all()]
