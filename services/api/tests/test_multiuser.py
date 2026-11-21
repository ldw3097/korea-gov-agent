import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from lh_agent.app import MAX_FILE_BYTES, Settings, create_app
from lh_agent.db import AuditEvent, Base, SessionToken, now
from lh_agent.seed import seed

ORIGIN = 'http://127.0.0.1:8000'
PASSWORD = 'synthetic-test-password-123'


@pytest.fixture
def app(tmp_path):
    app = create_app(Settings(database_url=f'sqlite:///{tmp_path}/test.db', environment='test'))
    Base.metadata.create_all(app.state.engine)
    with app.state.sessions() as db:
        seed(db, PASSWORD)
    yield app
    app.state.engine.dispose()


@pytest.fixture
def clients(app):
    result = {}
    for name in ('alice', 'bob', 'carol', 'admin'):
        client = TestClient(app, base_url=ORIGIN, headers={'Origin': ORIGIN})
        assert client.post('/api/auth/login', json={'username': name, 'password': PASSWORD}).status_code == 200
        result[name] = client
    yield result
    for client in result.values():
        client.close()


def thread(client, title='합성 업무 검토'):
    response = client.post('/api/threads', json={'title': title})
    assert response.status_code == 201
    return response.json()['id']


def upload(client, visibility='private'):
    response = client.post('/api/files', params={'name': '합성자료.txt', 'visibility': visibility}, content=b'synthetic only')
    assert response.status_code == 201
    return response.json()['id']


def test_anonymous_and_untrusted_headers(app):
    with TestClient(app, base_url=ORIGIN) as client:
        for path in ('/api/me', '/api/threads', '/api/files', '/api/admin/users'):
            assert client.get(path, headers={'X-User-Id': 'admin', 'X-Forwarded-User': 'admin'}).status_code == 401


def test_login_cookie_and_logout(app):
    with TestClient(app, base_url=ORIGIN, headers={'Origin': ORIGIN}) as client:
        assert client.post('/api/auth/login', json={'username': 'alice', 'password': 'wrong'}).status_code == 401
        response = client.post('/api/auth/login', json={'username': 'alice', 'password': PASSWORD})
        assert response.status_code == 200
        cookie = response.headers['set-cookie']
        assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie
        token = client.cookies.get('lh_session')
        with app.state.sessions() as db:
            assert db.get(SessionToken, hashlib.sha256(token.encode()).hexdigest())
            assert token not in str(db.scalars(select(SessionToken.token_hash)).all())
        assert client.post('/api/auth/logout').status_code == 204
        assert client.get('/api/me').status_code == 401


@pytest.mark.parametrize('other', ['bob', 'carol', 'admin'])
def test_thread_ownership_for_every_operation(clients, other):
    tid = thread(clients['alice'])
    owner, outsider = clients['alice'], clients[other]
    assert owner.post(f'/api/threads/{tid}/messages', json={'content': '비공개 합성 메시지'}).status_code == 201
    assert outsider.get('/api/threads').json() == []
    assert outsider.get(f'/api/threads/{tid}').status_code == 404
    assert outsider.post(f'/api/threads/{tid}/messages', json={'content': '침입'}).status_code == 404
    assert outsider.delete(f'/api/threads/{tid}').status_code == 404
    assert owner.get(f'/api/threads/{tid}').json()['messages'][0]['content'] == '비공개 합성 메시지'


@pytest.mark.parametrize('other', ['bob', 'carol', 'admin'])
def test_private_files_are_owner_only(clients, other):
    fid = upload(clients['alice'])
    assert clients[other].get('/api/files').json() == []
    assert clients[other].get(f'/api/files/{fid}/download').status_code == 404
    assert clients[other].delete(f'/api/files/{fid}').status_code == 404
    response = clients['alice'].get(f'/api/files/{fid}/download')
    assert response.content == b'synthetic only'
    assert response.headers['content-type'] == 'application/octet-stream'
    assert response.headers['content-disposition'].startswith('attachment;')


def test_department_sharing_removed_and_owner_delete(clients):
    assert clients['alice'].post('/api/files?name=x&visibility=department', content=b'x').status_code == 422
    fid = upload(clients['alice'])
    for name in ('bob', 'carol', 'admin'):
        assert clients[name].get('/api/files').json() == []
        assert clients[name].get(f'/api/files/{fid}/download').status_code == 404
    assert clients['alice'].delete(f'/api/files/{fid}').status_code == 204
    assert clients['bob'].get(f'/api/files/{fid}/download').status_code == 404


def test_identity_and_scope_cannot_be_forged(clients):
    client = clients['alice']
    assert client.post('/api/threads', json={'title': 'test', 'owner_id': 'bob'}).status_code == 422
    assert client.post('/api/threads', json={'title': '  '}).status_code == 422
    assert client.post('/api/files?name=x&visibility=all', content=b'x').status_code == 422
    response = client.post('/api/files?name=x&department_id=operations', content=b'x', headers={'X-User-Id': 'admin'})
    assert 'department_id' not in response.json()
    assert response.json()['owner_id'] == 'alice'


def test_csrf_host_and_body_limits(app, clients):
    client = clients['alice']
    assert client.post('/api/threads', json={'title': 'x'}, headers={'Origin': 'https://evil.example'}).status_code == 403
    with TestClient(app, base_url=ORIGIN) as anonymous:
        assert anonymous.post('/api/auth/login', json={'username': 'alice', 'password': PASSWORD}).status_code == 403
    assert client.get('/api/me', headers={'Host': 'evil.example'}).status_code == 400
    assert client.post('/api/files?name=x', content=b'x' * (MAX_FILE_BYTES + 1)).status_code == 413
    assert client.post('/api/files?name=x', content=b'').status_code == 422
    assert client.post('/api/files?name=../secret', content=b'x').status_code == 422
    assert client.post('/api/files?name=x', content=iter([b'x' * (MAX_FILE_BYTES + 4097)])).status_code == 413
    assert client.post('/api/threads', content=b'{}', headers={'Content-Length': 'invalid'}).status_code == 400


def test_admin_and_session_revocation(clients):
    assert clients['alice'].get('/api/admin/users').status_code == 403
    assert clients['alice'].get('/api/admin/audit').status_code == 403
    admin = clients['admin']
    assert len(admin.get('/api/admin/users').json()) == 4
    assert admin.get('/api/admin/departments').status_code == 404
    assert admin.patch('/api/admin/users/admin', json={'active': False}).status_code == 409
    assert admin.patch('/api/admin/users/alice', json={'active': False}).status_code == 200
    assert clients['alice'].get('/api/me').status_code == 401
    assert clients['alice'].post('/api/auth/login', json={'username': 'alice', 'password': PASSWORD}).status_code == 401
    assert admin.patch('/api/admin/users/alice', json={'active': True}).status_code == 200
    assert clients['alice'].get('/api/me').status_code == 401


def test_expired_session_and_rotation(app, clients):
    client = clients['alice']
    old_token = client.cookies.get('lh_session')
    assert client.post('/api/auth/login', json={'username': 'alice', 'password': PASSWORD}).status_code == 200
    with app.state.sessions() as db:
        assert db.get(SessionToken, hashlib.sha256(old_token.encode()).hexdigest()) is None
        session = db.get(SessionToken, hashlib.sha256(client.cookies.get('lh_session').encode()).hexdigest())
        session.expires_at = now() - 1
        db.commit()
    assert client.get('/api/me').status_code == 401


def test_login_rate_limit(app):
    with TestClient(app, base_url=ORIGIN, headers={'Origin': ORIGIN}) as client:
        for _ in range(10):
            assert client.post('/api/auth/login', json={'username': 'alice', 'password': 'incorrect'}).status_code == 401
        assert client.post('/api/auth/login', json={'username': 'alice', 'password': PASSWORD}).status_code == 429


def test_remote_client_and_validation_redaction(app):
    with TestClient(app, base_url=ORIGIN, client=('192.0.2.10', 12345)) as client:
        assert client.get('/').status_code == 403
    with TestClient(app, base_url=ORIGIN, headers={'Origin': ORIGIN}) as client:
        sensitive = 'synthetic-secret-' * 30
        response = client.post('/api/auth/login', json={'username': 'alice', 'password': sensitive})
        assert response.status_code == 422
        assert sensitive not in response.text


def test_database_survives_new_app_instance(app, clients):
    tid = thread(clients['alice'])
    fid = upload(clients['alice'])
    recreated = create_app(Settings(database_url=str(app.state.engine.url), environment='test'))
    with TestClient(recreated, base_url=ORIGIN, headers={'Origin': ORIGIN}) as client:
        client.cookies.update(clients['alice'].cookies)
        assert client.get(f'/api/threads/{tid}').status_code == 200
        assert client.get(f'/api/files/{fid}/download').content == b'synthetic only'


def test_persistence_order_deletion_and_audit(app, clients):
    client = clients['alice']
    tid = thread(client)
    for value in ('first', 'second', 'third'):
        assert client.post(f'/api/threads/{tid}/messages', json={'content': value}).status_code == 201
    with TestClient(app, base_url=ORIGIN, headers={'Origin': ORIGIN}) as reconnect:
        reconnect.cookies.update(client.cookies)
        assert [m['content'] for m in reconnect.get(f'/api/threads/{tid}').json()['messages']] == ['first', 'second', 'third']
    assert client.delete(f'/api/threads/{tid}').status_code == 204
    assert client.get(f'/api/threads/{tid}').status_code == 404
    with app.state.sessions() as db:
        from lh_agent.db import Message
        assert db.scalars(select(Message)).all() == []
        events = db.scalars(select(AuditEvent)).all()
        assert any(e.action == 'thread_deleted' for e in events)
        assert 'first' not in str([e.__dict__ for e in events])
    assert 'password_hash' not in str(clients['admin'].get('/api/admin/users').json())


def test_concurrent_user_writes(clients):
    def work(name):
        tid = thread(clients[name], name)
        assert clients[name].post(f'/api/threads/{tid}/messages', json={'content': name}).status_code == 201
        return tid
    with ThreadPoolExecutor(max_workers=3) as pool:
        ids = list(pool.map(work, ('alice', 'bob', 'carol')))
    for name, tid in zip(('alice', 'bob', 'carol'), ids):
        assert [t['id'] for t in clients[name].get('/api/threads').json()] == [tid]


def test_static_ui_security_headers_and_health(app):
    with TestClient(app, base_url=ORIGIN) as client:
        for path in ('/', '/app.js', '/style.css'):
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers['cache-control'] == 'no-store'
            assert "script-src 'self'" in response.headers['content-security-policy']
        assert client.get('/health').json()['agent_available'] is False


@pytest.mark.parametrize('settings', [Settings(environment='production'), Settings(origin='http://0.0.0.0:8000'), Settings(database_url='postgresql://localhost/lh')])
def test_unsupported_deployment_fails_closed(settings):
    with pytest.raises(ValueError):
        create_app(settings)
