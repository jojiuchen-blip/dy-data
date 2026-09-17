from datetime import datetime, timedelta, timezone

from test_api_access_control import client, _login
from test_account_bulk_import import workbook
from apps.api.dy_api.models import DimStore, DimStoreOrgAssignment
from apps.api.dy_api.ranking_schema_v1 import org_history
from apps.api.dy_api.account_scope import organization_store_ids


def publish(session, version, when, entries):
    org_history.create(session.connection(), checkfirst=True)
    session.execute(org_history.insert(), [dict(
        mapping_version=version, effective_from=when, source_hash=version,
        store_id=store, service_store_code='code-' + store, store_name=store,
        group_name='集团', service_center_name=center, district_name='大区', area_name='区域',
    ) for store, center in entries])
    session.commit()


def test_current_published_roster_drives_catalog_bulk_and_login(client, db_session):
    now = datetime.now(timezone.utc)
    publish(db_session, 'current', now-timedelta(days=1), [('store-1', '中心一'), ('store-2', '中心二')])
    _login(client, 'system-admin', 'test-password')
    catalog = client.get('/api/v1/admin/account-store-catalog').json()['data']['stores']
    assert any(row['service_center_name'] == '中心一' for row in catalog)
    content = workbook([['current-area', '区域人员', '区域账号', '', '中心一', '大区', '区域']])
    files = {'file': ('accounts.xlsx', content, 'application/octet-stream')}
    preview = client.post('/api/v1/admin/account-bulk-import/preview', files=files).json()['data']
    assert preview['errors'] == []
    assert preview['rows'][0]['store_count'] == 1
    assert client.post('/api/v1/admin/account-bulk-import/commit', files=files, data={'digest': preview['digest']}).status_code == 200
    _login(client, 'current-area', '123456')
    assert client.get('/api/v1/auth/me').json()['data']['store_ids'] == ['store-1']
    assert client.get('/api/v1/store-settlements', params={'storeId':'store-2', 'month':'2026-09','metricScope':'MONTH'}).status_code == 403
    publish(db_session, 'next', now-timedelta(hours=1), [('store-2', '中心一')])
    assert client.get('/api/v1/auth/me').json()['data']['store_ids'] == ['store-2']


def test_complete_effective_version_excludes_removed_future_and_inactive(client, db_session):
    now = datetime.now(timezone.utc)
    publish(db_session, 'old', now-timedelta(days=2), [('store-1', '中心一')])
    publish(db_session, 'current', now-timedelta(days=1), [('store-2', '中心一')])
    publish(db_session, 'future', now+timedelta(days=1), [('store-1', '中心一')])
    scope = {'level':'service_center', 'service_center_name':'中心一'}
    assert organization_store_ids(db_session, scope) == ('store-2',)
    db_session.get(DimStore, 'store-2').is_active = False
    db_session.commit()
    assert organization_store_ids(db_session, scope) == ()


def test_future_only_formal_roster_does_not_revive_legacy(client, db_session):
    db_session.get(DimStore, 'store-1').service_store_code = 'legacy'
    db_session.add(DimStoreOrgAssignment(service_store_code='legacy', is_active=True,
                                       service_center_name='旧中心'))
    publish(db_session, 'future', datetime.now(timezone.utc)+timedelta(days=1),
            [('store-2', '新中心')])
    assert organization_store_ids(db_session, {'level':'service_center', 'service_center_name':'旧中心'}) == ()
