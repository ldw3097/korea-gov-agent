import base64
import hashlib
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import select

from lh_agent.app import Settings, create_app
from lh_agent.db import GoogleAccount, OAuthAttempt, SessionToken, User, now
from lh_agent.security import hash_password

ORIGIN = 'http://127.0.0.1:8000'


@pytest.fixture
def google(tmp_path, monkeypatch):
    app = create_app(Settings(database_url=f'sqlite:///{tmp_path}/google.db', environment='test',
                              auth_mode='google', google_client_id='synthetic-client',
                              google_client_secret='synthetic-secret', admin_email='admin@example.org'))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(app.state.google.keys, 'get_signing_key_from_jwt', lambda token: SimpleNamespace(key=key.public_key()))
    clients = []
    with TestClient(app, base_url=ORIGIN, headers={'Origin': ORIGIN}) as lifecycle:
        def client():
            value = TestClient(app, base_url=ORIGIN, headers={'Origin': ORIGIN}, follow_redirects=False)
            clients.append(value)
            return value

        def login(browser, email='person@example.org', overrides=None, subject=None):
            start = browser.get('/api/auth/google/start')
            query = parse_qs(urlsplit(start.headers['location']).query)
            assert query['scope'] == ['openid email profile']
            assert query['code_challenge_method'] == ['S256']
            claims = {'sub': subject or email, 'email': email, 'email_verified': True,
                      'iss': 'https://accounts.google.com', 'aud': 'synthetic-client',
                      'iat': now(), 'exp': now() + 3600, 'nonce': query['nonce'][0]}
            claims.update(overrides or {})

            async def exchange(code, verifier):
                assert code == 'synthetic-code'
                assert base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode() == query['code_challenge'][0]
                return jwt.encode(claims, key, algorithm='RS256')

            monkeypatch.setattr(app.state.google, 'exchange', exchange)
            return browser.get('/api/auth/google/callback', params={'state': query['state'][0], 'code': 'synthetic-code'})
        yield app, client, login
    for browser in clients:
        browser.close()


def test_google_signup_pending_and_admin_approval(google):
    app, client, login = google
    pending, admin = client(), client()
    assert login(pending).status_code == 302
    me = pending.get('/api/me').json()
    assert me['approval_status'] == 'pending'
    assert 'department_id' not in me
    for path in ('/api/threads', '/api/files', '/api/admin/users'):
        assert pending.get(path).status_code == 403
    assert pending.post('/api/threads', json={'title': 'blocked'}).status_code == 403
    assert pending.post('/api/files?name=x', content=b'x').status_code == 403
    assert pending.patch(f"/api/admin/users/{me['id']}/approval", json={'status': 'approved'}).status_code == 403
    assert login(admin, 'admin@example.org').status_code == 302
    assert admin.get('/api/me').json()['role'] == 'admin'
    response = admin.patch(f"/api/admin/users/{me['id']}/approval", json={'status': 'approved'})
    assert response.status_code == 200
    assert pending.get('/api/me').json()['approval_status'] == 'approved'
    assert pending.post('/api/threads', json={'title': 'works'}).status_code == 201
    assert pending.post('/api/auth/login', json={'username': 'alice', 'password': 'anything'}).status_code == 403
    assert admin.get('/api/admin/departments').status_code == 404
    with app.state.sessions() as db:
        account = db.get(GoogleAccount, me['id'])
        assert account.reviewed_by == admin.get('/api/me').json()['id']


def test_rejection_revokes_all_sessions_and_relogin_does_not_approve(google):
    app, client, login = google
    first, second, admin = client(), client(), client()
    login(first); login(second); login(admin, 'admin@example.org')
    uid = first.get('/api/me').json()['id']
    assert admin.patch(f'/api/admin/users/{uid}/approval', json={'status': 'approved'}).status_code == 200
    assert second.get('/api/threads').status_code == 200
    assert admin.patch(f'/api/admin/users/{uid}/approval', json={'status': 'rejected'}).status_code == 200
    for browser in (first, second):
        assert browser.get('/api/me').status_code == 401
    login(first)
    assert first.get('/api/me').json()['approval_status'] == 'rejected'
    assert first.get('/api/threads').status_code == 403
    assert admin.patch('/api/admin/users/' + admin.get('/api/me').json()['id'] + '/approval', json={'status': 'rejected'}).status_code == 409


@pytest.mark.parametrize('overrides', [{'nonce': 'wrong'}, {'aud': 'wrong'}, {'iss': 'https://evil.example'},
                                       {'exp': 1}, {'email_verified': False}, {'email_verified': 'true'},
                                       {'azp': 'wrong'}, {'sub': ''}])
def test_invalid_google_token_cannot_create_session(google, overrides):
    app, client, login = google
    browser = client()
    assert login(browser, overrides=overrides).status_code == 400
    assert browser.get('/api/me').status_code == 401
    with app.state.sessions() as db:
        assert db.scalars(select(SessionToken)).all() == []


def test_state_browser_binding_expiry_and_one_use(google):
    app, client, _ = google
    first, other = client(), client()
    start = first.get('/api/auth/google/start')
    state = parse_qs(urlsplit(start.headers['location']).query)['state'][0]
    assert other.get('/api/auth/google/callback', params={'state': state, 'code': 'x'}).status_code == 400
    assert first.get('/api/auth/google/callback', params={'state': state, 'error': 'access_denied'}).status_code == 400
    assert first.get('/api/auth/google/callback', params={'state': state, 'code': 'x'}).status_code == 400
    start = first.get('/api/auth/google/start')
    state = parse_qs(urlsplit(start.headers['location']).query)['state'][0]
    with app.state.sessions() as db:
        for attempt in db.scalars(select(OAuthAttempt)):
            attempt.expires_at = now() - 1
        db.commit()
    assert first.get('/api/auth/google/callback', params={'state': state, 'code': 'x'}).status_code == 400


def test_google_accounts_keep_private_data_separate(google):
    _, client, login = google
    admin, alice, bob = client(), client(), client()
    login(admin, 'admin@example.org'); login(alice, 'alice@example.org'); login(bob, 'bob@example.org')
    for browser in (alice, bob):
        uid = browser.get('/api/me').json()['id']
        admin.patch(f'/api/admin/users/{uid}/approval', json={'status': 'approved'})
    tid = alice.post('/api/threads', json={'title': 'private'}).json()['id']
    fid = alice.post('/api/files?name=x', content=b'synthetic').json()['id']
    for browser in (bob, admin):
        assert browser.get(f'/api/threads/{tid}').status_code == 404
        assert browser.get(f'/api/files/{fid}/download').status_code == 404
    assert alice.post('/api/files?name=x&visibility=department', content=b'x').status_code == 422


def test_google_production_requires_credentials_and_secure_cookies(tmp_path):
    with pytest.raises(ValueError):
        create_app(Settings(environment='production', auth_mode='google', origin='https://poc.example.org'))
    app = create_app(Settings(database_url=f'sqlite:///{tmp_path}/secure.db', environment='production', auth_mode='google',
                              origin='https://poc.example.org', google_client_id='x', google_client_secret='y', admin_email='admin@example.org'))
    with TestClient(app, base_url='https://poc.example.org', follow_redirects=False) as browser:
        assert 'Secure' in browser.get('/api/auth/google/start').headers['set-cookie']
        assert browser.get('/api/threads').status_code == 401


def test_legacy_email_is_not_linked_and_claimed_role_is_ignored(google):
    app, client, login = google
    with app.state.sessions() as db:
        db.add(User(id='legacy', username='person@example.org', display_name='old', department_id='google-poc',
                    role='admin', password_hash=hash_password('synthetic-only-password')))
        db.commit()
    browser = client()
    assert login(browser, overrides={'role': 'admin', 'department_id': 'anything'}).status_code == 302
    me = browser.get('/api/me').json()
    assert me['id'] != 'legacy'
    assert me['role'] == 'employee'
    assert me['approval_status'] == 'pending'


def test_provider_failure_is_sanitized_and_state_consumed(google, monkeypatch):
    app, client, _ = google
    browser = client()
    state = parse_qs(urlsplit(browser.get('/api/auth/google/start').headers['location']).query)['state'][0]
    async def broken(*args):
        raise RuntimeError('sensitive synthetic provider payload')
    monkeypatch.setattr(app.state.google, 'exchange', broken)
    response = browser.get('/api/auth/google/callback', params={'state': state, 'code': 'synthetic-code'})
    assert response.status_code == 400
    assert 'sensitive' not in response.text
    with app.state.sessions() as db:
        assert db.scalars(select(OAuthAttempt)).all() == []
