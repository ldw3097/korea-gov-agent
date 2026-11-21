from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from lh_agent.app import Settings, create_app
from lh_agent.db import now

ORIGIN = 'https://lh-poc.example.org'
ISSUER = 'https://test-team.cloudflareaccess.com'


@pytest.fixture
def deployed(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(jwt.PyJWKClient, 'get_signing_key_from_jwt', lambda self, token: SimpleNamespace(key=key.public_key()))
    settings = Settings(database_url=f'sqlite:///{tmp_path}/deploy.db', environment='production', origin=ORIGIN,
                        auth_mode='cloudflare', cf_issuer=ISSUER, cf_audience='lh-poc-audience',
                        admin_email='admin@example.org')
    app = create_app(settings)

    def token(**overrides):
        claims = {'sub': 'admin-subject', 'email': 'admin@example.org', 'iss': ISSUER,
                  'aud': 'lh-poc-audience', 'iat': now(), 'exp': now() + 3600}
        claims.update(overrides)
        return jwt.encode(claims, key, algorithm='RS256', headers={'kid': 'synthetic'})

    with TestClient(app, base_url=ORIGIN, headers={'Origin': ORIGIN}) as client:
        yield client, token


def test_deployment_rejects_no_assertion_and_forged_identity(deployed):
    client, _ = deployed
    for path in ('/', '/api/me', '/api/files', '/app.js', '/health'):
        assert client.get(path, headers={'Cf-Access-Authenticated-User-Email': 'admin@example.org'}).status_code == 401


@pytest.mark.parametrize('overrides', [{'aud': 'wrong'}, {'iss': 'https://wrong.cloudflareaccess.com'},
                                       {'exp': 1}, {'email': 'invalid-email'}, {'sub': ''}])
def test_deployment_rejects_bad_claims(deployed, overrides):
    client, token = deployed
    assert client.get('/api/me', headers={'Cf-Access-Jwt-Assertion': token(**overrides)}).status_code == 401


def test_deployment_rejects_bad_signature(deployed):
    client, token = deployed
    encoded = token()
    head, payload, signature = encoded.split('.')
    altered = head + '.' + payload + '.' + ('A' if signature[0] != 'A' else 'B') + signature[1:]
    assert client.get('/api/me', headers={'Cf-Access-Jwt-Assertion': altered}).status_code == 401


def test_access_identity_provisioning_roles_and_isolation(deployed):
    client, token = deployed
    admin_headers = {'Cf-Access-Jwt-Assertion': token()}
    employee_headers = {'Cf-Access-Jwt-Assertion': token(sub='employee-subject', email='employee@example.org')}
    admin = client.get('/api/me', headers=admin_headers).json()
    assert admin['role'] == 'admin'
    assert client.get('/api/me', headers=admin_headers).json()['id'] == admin['id']
    tid = client.post('/api/threads', json={'title': 'SSO synthetic'}, headers=admin_headers).json()['id']
    employee = client.get('/api/me', headers=employee_headers).json()
    assert employee['role'] == 'employee'
    assert employee['id'] != admin['id']
    assert employee['approval_status'] == 'pending'
    assert client.get('/api/threads', headers=employee_headers).status_code == 403
    assert client.patch('/api/admin/users/' + employee['id'] + '/approval', json={'status':'approved'}, headers=admin_headers).status_code == 200
    assert client.get(f'/api/threads/{tid}', headers=employee_headers).status_code == 404
    assert client.get('/api/admin/users', headers=employee_headers).status_code == 403
    assert client.post('/api/auth/login', json={'username': 'alice', 'password': 'anything'}, headers=admin_headers).status_code == 403
    assert client.get('/api/config', headers=admin_headers).json()['auth_mode'] == 'cloudflare'
    assert client.patch('/api/admin/users/' + employee['id'], json={'active': False}, headers=admin_headers).status_code == 200
    assert client.get('/api/me', headers=employee_headers).json()['approval_status'] == 'suspended'
    assert client.get('/api/threads', headers=employee_headers).status_code == 403


def test_access_signup_is_pending_without_email_preassignment(deployed):
    client, token = deployed
    headers = {'Cf-Access-Jwt-Assertion': token(sub='new-subject', email='new-google-user@example.net', role='admin')}
    me = client.get('/api/me', headers=headers).json()
    assert me['role'] == 'employee'
    assert me['approval_status'] == 'pending'
    assert 'department_id' not in me
    for path in ('/api/threads', '/api/files', '/api/admin/users', '/api/admin/audit'):
        assert client.get(path, headers=headers).status_code == 403
    assert client.post('/api/threads', json={'title': 'blocked'}, headers=headers).status_code == 403
    assert client.post('/api/files?name=x', content=b'x', headers=headers).status_code == 403
    assert client.patch('/api/admin/users/' + me['id'] + '/approval', json={'status':'approved'}, headers=headers).status_code == 403


def test_access_approval_revocation_and_subject_identity(deployed):
    client, token = deployed
    admin_headers = {'Cf-Access-Jwt-Assertion': token()}
    person_headers = {'Cf-Access-Jwt-Assertion': token(sub='person', email='person@example.net')}
    other_headers = {'Cf-Access-Jwt-Assertion': token(sub='other-person', email='person@example.net')}
    client.get('/api/me', headers=admin_headers)
    uid = client.get('/api/me', headers=person_headers).json()['id']
    other = client.get('/api/me', headers=other_headers).json()
    assert other['id'] != uid and other['approval_status'] == 'pending'
    assert client.patch(f'/api/admin/users/{uid}/approval', json={'status':'approved'}, headers=admin_headers).status_code == 200
    assert client.post('/api/threads', json={'title':'approved'}, headers=person_headers).status_code == 201
    assert client.patch(f'/api/admin/users/{uid}/approval', json={'status':'rejected'}, headers=admin_headers).status_code == 200
    assert client.get('/api/me', headers=person_headers).json()['approval_status'] == 'rejected'
    assert client.get('/api/threads', headers=person_headers).status_code == 403
    # Reusing a still-valid Access JWT cannot undo an app-level rejection.
    assert client.get('/api/me', headers=person_headers).json()['approval_status'] == 'rejected'
    assert client.get('/api/threads', headers=other_headers).status_code == 403


def test_deployment_csrf_and_host_still_enforced(deployed):
    client, token = deployed
    headers = {'Cf-Access-Jwt-Assertion': token(), 'Origin': 'https://evil.example.org'}
    assert client.post('/api/threads', json={'title': 'x'}, headers=headers).status_code == 403
    assert client.get('/api/me', headers={'Cf-Access-Jwt-Assertion': token(), 'Host': 'evil.example.org'}).status_code == 400


def test_local_health_probe_only(tmp_path):
    app = create_app(Settings(database_url=f'sqlite:///{tmp_path}/health.db', environment='production', origin=ORIGIN,
                             auth_mode='cloudflare', cf_issuer=ISSUER, cf_audience='x', admin_email='admin@example.org'))
    with TestClient(app, base_url='http://localhost:3000', client=('127.0.0.1', 1234)) as client:
        assert client.get('/health').status_code == 200
        assert client.get('/api/me').status_code == 401
