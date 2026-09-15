from test_api_access_control import client, _login
from apps.api.dy_api.models import DimStore, DimStoreOrgAssignment, User, UserPagePermissionOverride
import pytest
from io import BytesIO
from openpyxl import load_workbook, Workbook


def test_area_scope_is_dynamic_and_path_specific(client, db_session):
    for index, center in [(1, '中心一'), (2, '中心二')]:
        db_session.get(DimStore, f'store-{index}').service_store_code = f'code-{index}'
        db_session.add(DimStoreOrgAssignment(service_store_code=f'code-{index}', group_name='集团', service_center_name=center, district_name='大区', area_name='同名区域', is_active=True))
    db_session.commit()
    _login(client, 'system-admin', 'test-password')
    response = client.post('/api/v1/admin/accounts', json={
        'username': 'area-admin', 'display_name': '区域管理员', 'role': 'admin',
        'store_scope_mode': 'specified', 'org_scope': {'level': 'area', 'group_name': '集团', 'service_center_name': '中心一', 'district_name': '大区', 'area_name': '同名区域'},
        'password': 'secret', 'password_confirm': 'secret',
    })
    assert response.status_code == 200, response.text
    assert [s['store_id'] for s in response.json()['data']['stores']] == ['store-1']
    _login(client, 'area-admin')
    assert client.get('/api/v1/auth/me').json()['data']['store_ids'] == ['store-1']
    assert client.get('/api/v1/admin/accounts').status_code == 403
    assert client.get('/api/v1/admin/account-store-catalog').status_code == 403
    params = {'storeId': 'store-2', 'month': '2026-09', 'metricScope': 'MONTH'}
    assert client.get('/api/v1/store-settlements', params=params).status_code == 403
    assert [s['storeId'] for s in client.get('/api/v1/meta/filters').json()['data']['stores']] == ['store-1']
    db_session.get(DimStoreOrgAssignment, 'code-1').service_center_name = '中心二'
    db_session.commit()
    assert client.get('/api/v1/auth/me').json()['data']['store_ids'] == []
    from dy_api.cli_auth import _auth_context_for_user
    user = db_session.query(User).filter_by(username='area-admin').one()
    assert _auth_context_for_user(db_session, user).store_ids == ()
    params['storeId'] = 'store-1'
    assert client.get('/api/v1/store-settlements', params=params).status_code == 403


def test_catalog_and_import_preview(client):
    _login(client, 'system-admin', 'test-password')
    catalog = client.get('/api/v1/admin/account-store-catalog')
    assert catalog.status_code == 200
    preview = client.post('/api/v1/admin/account-store-import/preview', files={'file': ('stores.csv', '门店ID,门店名称\nstore-1,Store One\nstore-1,Store One\nmissing,未知\n'.encode('utf-8-sig'), 'text/csv')})
    assert preview.status_code == 200, preview.text
    data = preview.json()['data']
    assert data['store_ids'] == ['store-1']
    assert data['duplicate_count'] == 1
    assert data['errors'][0]['row'] == 4


@pytest.mark.parametrize('level,fields', [('group', ('group_name',)), ('service_center', ('service_center_name',)), ('district', ('service_center_name', 'district_name')), ('area', ('service_center_name', 'district_name', 'area_name'))])
def test_all_organization_levels_and_invalid_paths(client, db_session, level, fields):
    from apps.api.dy_api.account_scope import ORG_FIELDS, organization_store_ids
    path = dict(zip(ORG_FIELDS, ['集团一', '中心一', '大区一', '区域一']))
    db_session.get(DimStore, 'store-1').service_store_code = '001'
    db_session.add(DimStoreOrgAssignment(service_store_code='001', is_active=True, **path))
    db_session.commit()
    scope = {'level': level, **{field: path[field] for field in fields}}
    assert organization_store_ids(db_session, scope) == ('store-1',)
    assert organization_store_ids(db_session, {'level': level}) == ()


def test_service_hierarchy_is_independent_of_group(client, db_session):
    from apps.api.dy_api.account_scope import organization_store_ids, normalize_org_scope
    for index, group in [(1, '集团甲'), (2, '集团乙')]:
        db_session.get(DimStore, f'store-{index}').service_store_code = f'independent-{index}'
        db_session.add(DimStoreOrgAssignment(service_store_code=f'independent-{index}', group_name=group, service_center_name='共同中心', district_name='共同大区', area_name='共同区域', is_active=True))
    db_session.commit()
    scope = {'level': 'area', 'service_center_name': '共同中心', 'district_name': '共同大区', 'area_name': '共同区域'}
    assert organization_store_ids(db_session, scope) == ('store-1', 'store-2')
    assert organization_store_ids(db_session, {'level': 'group', 'group_name': '集团甲'}) == ('store-1',)
    assert normalize_org_scope({**scope, 'group_name': '历史多填集团'}) == scope
    from dy_api.routes.admin import _account_row
    user = db_session.get(User, 'store-user')
    user.org_scope = {**scope, 'group_name': '历史多填集团'}
    db_session.commit()
    assert _account_row(db_session, user).org_scope == scope


def test_ranking_and_export_ignore_scope_and_a03_deny_but_require_login(client, db_session, monkeypatch):
    from dy_api.routes import dashboard
    db_session.add(UserPagePermissionOverride(user_id='store-user', page_key='A03', effect='deny', updated_by='test'))
    db_session.commit()
    seen = []
    monkeypatch.setattr(dashboard, 'ensure_business_snapshot', lambda *a, **kw: 'snapshot')
    def report(*args, **kwargs):
        seen.append(kwargs['scope_store_ids'])
        return {'rows': [{'name': 'Other Store'}]}
    monkeypatch.setattr(dashboard, 'read_snapshot_report', report)
    def export(*args, **kwargs):
        seen.append(kwargs['scope_store_ids'])
        return b'workbook'
    monkeypatch.setattr(dashboard, 'build_ranking_workbook', export)
    params = {'periodStart': '2026-09-01', 'periodEnd': '2026-09-10'}
    path = '/api/v1/dashboard/douyin-ranking'
    assert client.get(path, params=params).status_code == 401
    _login(client, 'store-user')
    assert client.get(path, params=params).status_code == 200
    assert client.get(path + '/export', params=params).status_code == 200
    assert seen == [None, None]
    assert client.get('/api/v1/admin/account-store-catalog').status_code == 403
    db_session.get(User, 'store-user').status = 'disabled'
    db_session.commit()
    assert client.get(path, params=params).status_code == 401


def test_template_round_trip_text_ids_and_bad_uploads(client):
    from apps.api.dy_api.account_store_import import store_template, preview_store_import
    catalog = [{'store_id': '000123', 'store_name': '测试门店'}]
    book = load_workbook(BytesIO(store_template(catalog)))
    book['门店名单'].append(['000123', '测试门店'])  # Template formatting retains text cell values.
    # Write explicitly to first data row, because formatting has allocated blank rows.
    book['门店名单']['A2'] = '000123'
    book['门店名单']['B2'] = '测试门店'
    out = BytesIO(); book.save(out)
    assert preview_store_import(out.getvalue(), 'test.xlsx', catalog)['store_ids'] == ['000123']
    book['门店名单']['A2'] = 123
    out = BytesIO(); book.save(out)
    assert preview_store_import(out.getvalue(), 'test.xlsx', catalog)['errors'][0]['row'] == 2
    _login(client, 'system-admin', 'test-password')
    response = client.post('/api/v1/admin/account-store-import/preview', files={'file': ('bad.csv', b'a' * 150000, 'text/csv')})
    assert response.status_code == 422
    assert client.post('/api/v1/admin/account-store-import/preview', files={'file': ('bad.xlsx', b'not excel', 'application/octet-stream')}).status_code == 422
