"""Read-only authorization must not initialize or update existing permissions."""
import pytest
from fastapi import HTTPException
from sqlalchemy import event, select, text
from starlette.requests import Request

from apps.api.dy_api.models import AccessPage, User
from dy_api.auth import create_session_token
from dy_api import pdca_readonly_access as access


def request(token):
    return Request({'type': 'http', 'method': 'GET', 'path': '/api/v1/admin/pdca-source-evidence',
                    'headers': [(b'cookie', ('dy_session=' + token).encode())]})


@pytest.fixture(autouse=True)
def auth_environment(monkeypatch):
    monkeypatch.setenv('DY_API_TEST_MODE', '1')
    monkeypatch.setenv('DY_SUPER_ADMIN_USERNAME', 'synthetic-admin')
    monkeypatch.setenv('DY_TEST_ADMIN_PASSWORD', 'synthetic-password')
    monkeypatch.setenv('DY_SESSION_COOKIE_NAME', 'dy_session')


def test_environment_admin_does_not_seed_permissions(db_session):
    statements = []
    listener = lambda conn, cursor, statement, parameters, context, many: statements.append(statement)
    event.listen(db_session.get_bind(), 'before_cursor_execute', listener)
    try:
        token = create_session_token('synthetic-admin', role='highest_admin')
        assert access.require_pdca_super_admin(request(token), db_session) == 'synthetic-admin'
        assert list(db_session.scalars(select(AccessPage))) == []
        assert not db_session.new and not db_session.dirty
        assert not any(s.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for s in statements)
    finally:
        event.remove(db_session.get_bind(), 'before_cursor_execute', listener)


@pytest.mark.parametrize('token', ['', 'invalid', 'tampered.token'])
def test_invalid_session_rejected(db_session, token):
    with pytest.raises(HTTPException) as caught:
        access.require_pdca_super_admin(request(token), db_session)
    assert caught.value.status_code == 401


@pytest.mark.parametrize('role,status,initialized,version,expected', [
    ('highest_admin', 'active', True, 1, 200),
    ('admin', 'active', True, 1, 403),
    ('store', 'active', True, 1, 403),
    ('highest_admin', 'disabled', True, 1, 401),
    ('highest_admin', 'active', False, 1, 401),
    ('highest_admin', 'active', True, 2, 401),
])
def test_database_identity_checks_current_role_and_version(db_session, role, status, initialized, version, expected):
    db_session.add(User(user_id='pdca-user', username='pdca-user', display_name='Test',
                        role=role, status=status, is_initialized=initialized, auth_version=version))
    db_session.commit()
    # A signed role claim must not override the current persisted role.
    token = create_session_token('pdca-user', user_id='pdca-user', role='highest_admin', auth_type='user', auth_version=1)
    if expected == 200:
        assert access.require_pdca_super_admin(request(token), db_session) == 'pdca-user'
    else:
        with pytest.raises(HTTPException) as caught:
            access.require_pdca_super_admin(request(token), db_session)
        assert caught.value.status_code == expected
    assert list(db_session.scalars(select(AccessPage))) == []


def test_readonly_session_rejects_sql_writes_and_restores_connection(db_session, monkeypatch):
    engine = db_session.get_bind()
    monkeypatch.setattr(access, 'get_engine', lambda: engine)
    iterator = access.get_pdca_readonly_session()
    session = next(iterator)
    assert session.scalar(text('SELECT 1')) == 1
    with pytest.raises(Exception):
        session.execute(text("CREATE TABLE forbidden_write (id INTEGER)"))
    iterator.close()
    with engine.connect() as connection:
        assert connection.scalar(text('PRAGMA query_only')) == 0
        assert connection.scalar(text("SELECT count(*) FROM sqlite_master WHERE name='forbidden_write'")) == 0
