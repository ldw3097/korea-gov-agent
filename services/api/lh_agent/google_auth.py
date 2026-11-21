"""Google code flow with browser-bound one-use state, nonce, and PKCE."""
import asyncio
import base64
import hashlib
import hmac
import secrets
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import jwt
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from .db import AuditEvent, GoogleAccount, OAuthAttempt, SessionToken, User, now
from .security import hash_password, token_hash


class GoogleOIDC:
    def __init__(self, settings):
        self.settings = settings
        self.keys = jwt.PyJWKClient('https://www.googleapis.com/oauth2/v3/certs', timeout=5)

    async def exchange(self, code, verifier):
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            result = await client.post('https://oauth2.googleapis.com/token', data={
                'client_id': self.settings.google_client_id, 'client_secret': self.settings.google_client_secret,
                'code': code, 'code_verifier': verifier, 'grant_type': 'authorization_code',
                'redirect_uri': self.settings.origin + '/api/auth/google/callback',
            })
            result.raise_for_status()
            return result.json()['id_token']

    def verify(self, token, nonce):
        key = self.keys.get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=['RS256'], audience=self.settings.google_client_id,
                            issuer=['https://accounts.google.com', 'accounts.google.com'],
                            options={'require': ['exp', 'iat', 'iss', 'aud', 'sub', 'email', 'email_verified', 'nonce']})
        if claims['email_verified'] is not True or not isinstance(claims['nonce'], str) or not hmac.compare_digest(claims['nonce'], nonce):
            raise ValueError('Identity not verified')
        if claims.get('azp', self.settings.google_client_id) != self.settings.google_client_id:
            raise ValueError('Wrong authorized party')
        if not isinstance(claims['sub'], str) or not 1 <= len(claims['sub']) <= 256:
            raise ValueError('Invalid subject')
        if not isinstance(claims['email'], str) or not 3 <= len(claims['email']) <= 100 or '@' not in claims['email']:
            raise ValueError('Invalid email')
        return claims


def register_google(app, settings, sessions):
    adapter = GoogleOIDC(settings)
    app.state.google = adapter
    secure = settings.environment == 'production'

    @app.get('/api/auth/google/start')
    def start():
        state, binding = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        with sessions() as db:
            db.execute(delete(OAuthAttempt).where(OAuthAttempt.expires_at <= now()))
            db.add(OAuthAttempt(state_hash=token_hash(state), browser_hash=token_hash(binding), nonce=nonce,
                                verifier=verifier, expires_at=now() + 600))
            db.commit()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        response = RedirectResponse('https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
            'client_id': settings.google_client_id, 'redirect_uri': settings.origin + '/api/auth/google/callback',
            'response_type': 'code', 'scope': 'openid email profile', 'state': state, 'nonce': nonce,
            'code_challenge': challenge, 'code_challenge_method': 'S256', 'prompt': 'select_account',
        }), status_code=302)
        response.set_cookie('lh_oauth', binding, max_age=600, httponly=True, secure=secure, samesite='lax', path='/api/auth/google')
        return response

    @app.get('/api/auth/google/callback')
    async def callback(request: Request):
        params = request.query_params
        state, code = params.get('state', ''), params.get('code', '')
        response = JSONResponse(status_code=400, content={'detail': 'Google 로그인을 완료하지 못했습니다. 다시 로그인해 주세요.'})
        response.delete_cookie('lh_oauth', path='/api/auth/google')
        if not 1 <= len(state) <= 128:
            return response
        with sessions() as db:
            attempt = db.execute(delete(OAuthAttempt).where(
                OAuthAttempt.state_hash == token_hash(state),
                OAuthAttempt.browser_hash == token_hash(request.cookies.get('lh_oauth', '')),
                OAuthAttempt.expires_at > now(),
            ).returning(OAuthAttempt.nonce, OAuthAttempt.verifier)).first()
            db.commit()  # Consume before calling Google. A callback can never be replayed.
        if not attempt or params.get('error') or not 1 <= len(code) <= 4096:
            return response
        try:
            token = await adapter.exchange(code, attempt.verifier)
            claims = await asyncio.to_thread(adapter.verify, token, attempt.nonce)
        except Exception:
            return response  # Never return token endpoint payloads, codes, or credentials.
        uid = token_hash('google:' + claims['sub'])
        with sessions() as db:
            account = db.get(GoogleAccount, uid)
            if not account:
                email = claims['email'].casefold()
                is_admin = email == settings.admin_email
                # Subject-based identity stays separate from legacy accounts with the same email.
                user = User(id=uid, username=uid, display_name=str(claims.get('name') or email)[:100],
                            department_id='google-poc', role='admin' if is_admin else 'employee',
                            password_hash=hash_password(secrets.token_urlsafe(32)))
                try:
                    db.add(user)
                    db.flush()
                    account = GoogleAccount(user_id=uid, subject=claims['sub'], email=email, approval_status='approved' if is_admin else 'pending')
                    db.add(account)
                    db.add(AuditEvent(id=str(uuid4()), actor_id=uid, action='google_registered', resource_id=uid))
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    account = db.get(GoogleAccount, uid)
            if not account:
                return response
            account.email = claims['email'].casefold()
            old_token = request.cookies.get('lh_session', '')
            db.execute(delete(SessionToken).where((SessionToken.token_hash == token_hash(old_token)) | (SessionToken.expires_at <= now())))
            session_token = secrets.token_urlsafe(32)
            db.add(SessionToken(token_hash=token_hash(session_token), user_id=uid, expires_at=now() + settings.session_seconds))
            db.add(AuditEvent(id=str(uuid4()), actor_id=uid, action='google_login', resource_id=uid))
            db.commit()
        response = RedirectResponse('/', status_code=302)
        response.delete_cookie('lh_oauth', path='/api/auth/google')
        response.set_cookie('lh_session', session_token, max_age=settings.session_seconds, httponly=True, secure=secure, samesite='lax', path='/')
        return response
