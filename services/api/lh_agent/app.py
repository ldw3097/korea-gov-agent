import os
import secrets
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote, urlsplit
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from .access import AccessVerifier
from .db import AccessAccount, AuditEvent, Base, Department, File, GoogleAccount, LoginAttempt, Message, SessionToken, Thread, User, database, now
from .google_auth import register_google
from .security import hash_password, token_hash, verify_password
from .work import ACTIVE, register_work
from .db import Project, ThreadProject, Run, RunAttachment

COOKIE = 'lh_session'
MAX_FILE_BYTES = 2 * 1024 * 1024
WEB_ROOT = Path(__file__).resolve().parents[3] / 'apps' / 'web'


@dataclass(frozen=True)
class Settings:
    database_url: str = 'sqlite:///./data/lh_agent.db'
    origin: str = 'http://127.0.0.1:8000'
    environment: str = 'development'
    session_seconds: int = 8 * 60 * 60
    auth_mode: str = 'local'
    cf_issuer: str = ''
    cf_audience: str = ''
    admin_email: str = ''
    google_client_id: str = ''
    google_client_secret: str = ''
    model_api_key: str = ''
    model_base_url: str = 'https://api.deepinfra.com/v1/openai'
    model_name: str = 'deepseek-ai/DeepSeek-V4.1-Flash-1017'

    def validate(self):
        url = urlsplit(self.origin)
        if url.path or url.query or url.fragment or url.username or url.password or not url.hostname:
            raise ValueError('유효한 origin을 설정하세요.')
        if self.environment == 'production':
            issuer = urlsplit(self.cf_issuer)
            if self.auth_mode not in ('cloudflare', 'google') or url.scheme != 'https' or url.hostname in ('localhost', '127.0.0.1', '::1'):
                raise ValueError('배포 모드는 외부 로그인과 HTTPS origin이 필요합니다.')
            if self.auth_mode == 'cloudflare' and (issuer.scheme != 'https' or not issuer.hostname or not issuer.hostname.endswith('.cloudflareaccess.com') or issuer.path or issuer.query or issuer.fragment or issuer.username or issuer.port):
                raise ValueError('Cloudflare Access issuer를 확인하세요.')
            if self.auth_mode == 'cloudflare' and (not self.cf_audience or '@' not in self.admin_email):
                raise ValueError('Access audience와 초기 관리자 이메일이 필요합니다.')
        elif self.environment in ('development', 'test'):
            if self.auth_mode not in ('local', 'google') or url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost', '::1'):
                raise ValueError('로컬 PoC는 http loopback origin을 사용하세요.')
        else:
            raise ValueError('지원하지 않는 실행 환경입니다.')
        if self.auth_mode == 'google' and (not self.google_client_id or not self.google_client_secret or '@' not in self.admin_email):
            raise ValueError('Google OAuth client ID·secret과 초기 관리자 이메일이 필요합니다.')
        if not self.database_url.startswith('sqlite:'):
            raise ValueError('이 단계에서는 로컬 SQLite만 검증됐습니다. 운영 DB는 후속 단계입니다.')
        if not 60 <= self.session_seconds <= 86400:
            raise ValueError('session_seconds는 60~86400이어야 합니다.')
        model_url = urlsplit(self.model_base_url)
        if model_url.scheme not in ('https', 'http') or not model_url.hostname or model_url.username or model_url.password or model_url.query or model_url.fragment:
            raise ValueError('모델 API 주소를 확인하세요.')


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Login(Input):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class ThreadInput(Input):
    title: str = Field(min_length=1, max_length=100)
    project_id: str | None = Field(default=None, max_length=36)


class MessageInput(Input):
    content: str = Field(min_length=1, max_length=10000)


class ActiveInput(Input):
    active: bool


class ApprovalInput(Input):
    status: Literal['approved', 'rejected']


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings(
        database_url=os.getenv('DATABASE_URL', Settings.database_url),
        origin=os.getenv('PUBLIC_ORIGIN', Settings.origin),
        environment=os.getenv('APP_ENV', 'development'),
        auth_mode=os.getenv('AUTH_MODE', 'local'),
        cf_issuer=os.getenv('CF_ACCESS_ISSUER', '').rstrip('/'),
        cf_audience=os.getenv('CF_ACCESS_AUD', ''),
        admin_email=os.getenv('ADMIN_EMAIL', '').strip().casefold(),
        google_client_id=os.getenv('GOOGLE_CLIENT_ID', ''),
        google_client_secret=os.getenv('GOOGLE_CLIENT_SECRET', ''),
        model_api_key=os.getenv('MODEL_API_KEY', ''),
        model_base_url=os.getenv('MODEL_BASE_URL', 'https://api.deepinfra.com/v1/openai'),
        model_name=os.getenv('MODEL_NAME', 'deepseek-ai/DeepSeek-V4.1-Flash-1017'),
    )
    settings.validate()
    if settings.database_url == Settings.database_url:
        Path('data').mkdir(mode=0o700, exist_ok=True)
    engine, sessions = database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        Base.metadata.create_all(engine)
        if settings.auth_mode in ('cloudflare', 'google'):
            with sessions() as db:
                group = 'google-poc' if settings.auth_mode == 'google' else 'poc'
                if not db.get(Department, group):
                    db.add(Department(id=group, name='PoC'))
                    db.commit()
        await app.state.work.start()
        try:
            yield
        finally:
            await app.state.work.stop()
            engine.dispose()

    app = FastAPI(title='K-gov-agent', lifespan=lifespan)
    app.state.sessions = sessions
    app.state.engine = engine
    if settings.auth_mode == 'google':
        register_google(app, settings, sessions)
    verifier = AccessVerifier(settings.cf_issuer, settings.cf_audience) if settings.auth_mode == 'cloudflare' else None
    # Unknown usernames still perform the same expensive password derivation.
    dummy_password = hash_password(secrets.token_urlsafe(32))

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        # Pydantic validation errors can include the submitted password or file name.
        return JSONResponse(status_code=422, content={'detail': '요청 형식을 확인해 주세요.'})

    @app.middleware('http')
    async def boundary(request: Request, call_next):
        # Intentionally no CORS, proxy-header identity, or browser-provided user IDs.
        allowed_hosts = {urlsplit(settings.origin).netloc}
        try:
            length = int(request.headers.get('content-length', '0'))
        except ValueError:
            length = -1
        local_clients = {'127.0.0.1', '::1'} | ({'testclient'} if settings.environment == 'test' else set())
        # Container liveness is the sole unauthenticated deployment endpoint.
        health_probe = (settings.environment == 'production' and request.url.path == '/health'
                        and request.method == 'GET' and request.client and request.client.host in ('127.0.0.1', '::1'))
        access_denied = False
        if verifier and not health_probe:
            try:
                request.state.access_claims = await asyncio.to_thread(verifier.verify, request.headers.get('cf-access-jwt-assertion', ''))
            except Exception:
                access_denied = True
        if settings.environment != 'production' and (not request.client or request.client.host not in local_clients):
            response = Response(status_code=403)
        elif access_denied:
            response = JSONResponse(status_code=401, content={'detail': 'Cloudflare 로그인이 필요합니다.'})
        elif not health_probe and request.headers.get('host') not in allowed_hosts:
            response = Response(status_code=400)
        elif request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('origin') != settings.origin:
            response = Response(status_code=403)
        elif length < 0:
            response = Response(status_code=400)
        elif length > MAX_FILE_BYTES + 4096:
            response = Response(status_code=413)
        else:
            # Bound chunked requests as well as Content-Length requests before JSON parsing.
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > MAX_FILE_BYTES + 4096:
                    break
                body.extend(chunk)
            else:
                # Starlette's cached request replays this bounded body to downstream handlers.
                request._body = bytes(body)
                response = await call_next(request)
                body = None
            if body is not None:
                response = Response(status_code=413)
        response.headers.update({
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        })
        return response

    def get_db():
        with sessions() as db:
            yield db

    DB = Annotated[Session, Depends(get_db)]

    def authenticated_user(request: Request, db: DB):
        if settings.auth_mode == 'cloudflare':
            claims = request.state.access_claims
            uid = token_hash(settings.cf_issuer + ':' + claims['sub'])
            user = db.get(User, uid)
            account = db.get(AccessAccount, uid)
            if account is None:
                is_admin = claims['email'] == settings.admin_email
                try:
                    if user is None:
                        user = User(id=uid, username=uid, display_name='PoC 관리자' if is_admin else claims['email'],
                                    department_id='poc', role='admin' if is_admin else 'employee',
                                    password_hash=hash_password(secrets.token_urlsafe(32)))
                        db.add(user)
                        db.flush()
                    # Existing Access users retain identity and data; no email-based linking.
                    account = AccessAccount(user_id=uid, issuer=settings.cf_issuer, subject=claims['sub'], email=claims['email'],
                                            approval_status='approved' if is_admin and user.active else 'pending')
                    db.add(account)
                    audit(db, uid, 'access_user_registered', uid)
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    user = db.get(User, uid)
                    account = db.get(AccessAccount, uid)
            if not user or not account:
                raise HTTPException(403, '계정 접근이 제한됐습니다.')
            if account.email != claims['email']:
                account.email = claims['email']
                db.commit()
            return user
        token = request.cookies.get(COOKIE, '')
        session = db.get(SessionToken, token_hash(token)) if token else None
        user = db.get(User, session.user_id) if session and session.expires_at > now() else None
        if not user or (not user.active and settings.auth_mode != 'google'):
            raise HTTPException(401, '로그인이 필요합니다.')
        if settings.auth_mode == 'google' and not db.get(GoogleAccount, user.id):
            raise HTTPException(401, 'Google 로그인이 필요합니다.')
        return user

    Identity = Annotated[User, Depends(authenticated_user)]

    def current_user(actor: Identity, db: DB):
        if settings.auth_mode in ('google', 'cloudflare'):
            account = db.get(AccessAccount if settings.auth_mode == 'cloudflare' else GoogleAccount, actor.id)
            if not actor.active or account.approval_status != 'approved':
                raise HTTPException(403, '관리자 사용 승인이 필요합니다.')
        return actor

    Actor = Annotated[User, Depends(current_user)]
    register_work(app, sessions, settings, Actor, DB)

    def admin(actor: Actor):
        if actor.role != 'admin':
            raise HTTPException(403, '관리자 권한이 필요합니다.')
        return actor

    Admin = Annotated[User, Depends(admin)]

    def audit(db, actor_id, action, resource_id=None):
        db.add(AuditEvent(id=str(uuid4()), actor_id=actor_id, action=action, resource_id=resource_id))

    def user_view(user, db=None):
        result = {k: getattr(user, k) for k in ('id', 'username', 'display_name', 'role', 'active')}
        account = db.get(AccessAccount if settings.auth_mode == 'cloudflare' else GoogleAccount, user.id) if db is not None else None
        if account:
            result['username'] = account.email
        result['approval_status'] = ('suspended' if not user.active else account.approval_status if account else 'approved')
        return result

    def owned_thread(db, actor, tid):
        thread = db.scalar(select(Thread).where(Thread.id == tid, Thread.owner_id == actor.id))
        if thread is None:
            raise HTTPException(404, '대화를 찾을 수 없습니다.')
        return thread

    def file_scope(actor):
        return File.owner_id == actor.id

    def file_view(row):
        return {k: getattr(row, k) for k in ('id', 'owner_id', 'name', 'size', 'created_at')}

    @app.get('/health')
    def health():
        return {'status': 'ok', 'mode': settings.environment, 'agent_available': app.state.work.provider.ready}

    @app.post('/api/auth/login')
    def login(body: Login, request: Request, response: Response, db: DB):
        if settings.auth_mode != 'local':
            raise HTTPException(403, '설정된 외부 로그인 방식을 사용하세요.')
        # Per-account and per-client rolling windows persisted across process restarts.
        timestamp = now()
        keys = [token_hash('account:' + body.username), token_hash('client:' + (request.client.host if request.client else 'unknown'))]
        buckets = []
        for key in keys:
            bucket = db.get(LoginAttempt, key)
            if bucket and timestamp - bucket.window_start < 900 and bucket.failures >= 10:
                raise HTTPException(429, '로그인 시도가 많습니다. 15분 후 다시 시도해 주세요.')
            if not bucket:
                bucket = LoginAttempt(key=key, failures=0, window_start=timestamp)
                db.add(bucket)
            elif timestamp - bucket.window_start >= 900:
                bucket.failures, bucket.window_start = 0, timestamp
            buckets.append(bucket)
        user = db.scalar(select(User).where(User.username == body.username))
        valid = verify_password(body.password, user.password_hash if user else dummy_password)
        if not user or not valid or not user.active:
            for bucket in buckets:
                bucket.failures += 1
            audit(db, None, 'login_failed')
            db.commit()
            raise HTTPException(401, '계정 또는 비밀번호를 확인해 주세요.')
        existing = request.cookies.get(COOKIE)
        if existing:
            db.execute(delete(SessionToken).where(SessionToken.token_hash == token_hash(existing)))
        db.execute(delete(SessionToken).where(SessionToken.expires_at <= timestamp))
        token = secrets.token_urlsafe(32)
        db.add(SessionToken(token_hash=token_hash(token), user_id=user.id, expires_at=timestamp + settings.session_seconds))
        audit(db, user.id, 'login')
        db.commit()
        response.set_cookie(COOKIE, token, httponly=True, samesite='strict', max_age=settings.session_seconds, path='/')
        return user_view(user)

    @app.post('/api/auth/logout', status_code=204)
    def logout(request: Request, response: Response, db: DB):
        db.execute(delete(SessionToken).where(SessionToken.token_hash == token_hash(request.cookies.get(COOKIE, ''))))
        db.commit()
        response.delete_cookie(COOKIE, path='/')

    @app.get('/api/config')
    def config():
        return {'auth_mode': settings.auth_mode, 'logout_url': '/cdn-cgi/access/logout' if verifier else None,
                'agent_available': app.state.work.provider.ready, 'model_name': settings.model_name if app.state.work.provider.ready else None,
                'attachment_formats': ['txt', 'md', 'csv', 'tsv', 'json']}

    @app.get('/api/me')
    def me(actor: Identity, db: DB):
        return user_view(actor, db)

    @app.get('/api/threads')
    def threads(actor: Actor, db: DB):
        rows = db.scalars(select(Thread).where(Thread.owner_id == actor.id).order_by(Thread.created_at.desc(), Thread.id).limit(200))
        return [{'id': t.id, 'title': t.title, 'created_at': t.created_at,
                 'project_id': (relation.project_id if (relation := db.get(ThreadProject, t.id)) else None)} for t in rows]

    @app.post('/api/threads', status_code=201)
    def create_thread(body: ThreadInput, actor: Actor, db: DB):
        if body.project_id and not db.scalar(select(Project.id).where(Project.id == body.project_id, Project.owner_id == actor.id)):
            raise HTTPException(404, '프로젝트를 찾을 수 없습니다.')
        thread = Thread(id=str(uuid4()), owner_id=actor.id, title=body.title)
        db.add(thread)
        db.flush()
        if body.project_id:
            db.add(ThreadProject(thread_id=thread.id, project_id=body.project_id))
        audit(db, actor.id, 'thread_created', thread.id)
        db.commit()
        return {'id': thread.id, 'title': thread.title, 'created_at': thread.created_at}

    @app.get('/api/threads/{tid}')
    def get_thread(tid: str, actor: Actor, db: DB):
        thread = owned_thread(db, actor, tid)
        messages = db.scalars(select(Message).where(Message.thread_id == thread.id).order_by(Message.created_at, Message.id).limit(500))
        return {'id': thread.id, 'title': thread.title, 'messages': [{'id': m.id, 'role': 'user', 'content': m.content} for m in messages]}

    @app.post('/api/threads/{tid}/messages', status_code=201)
    def add_message(tid: str, body: MessageInput, actor: Actor, db: DB):
        owned_thread(db, actor, tid)
        message = Message(id=str(uuid4()), thread_id=tid, content=body.content)
        db.add(message)
        audit(db, actor.id, 'message_created', message.id)
        db.commit()
        return {'id': message.id, 'role': 'user', 'content': message.content, 'agent_status': 'not_connected'}

    @app.delete('/api/threads/{tid}', status_code=204)
    def remove_thread(tid: str, actor: Actor, db: DB):
        owned_thread(db, actor, tid)
        if db.scalar(select(Run.id).where(Run.thread_id == tid, Run.status.in_(ACTIVE))):
            raise HTTPException(409, '진행 중인 작업을 중지한 뒤 대화를 삭제해 주세요.')
        db.execute(delete(Thread).where(Thread.id == tid, Thread.owner_id == actor.id))
        audit(db, actor.id, 'thread_deleted', tid)
        db.commit()

    @app.get('/api/files')
    def files(actor: Actor, db: DB):
        # Do not fetch file bodies for list requests.
        columns = [getattr(File, k) for k in ('id', 'owner_id', 'name', 'size', 'created_at')]
        return [dict(row) for row in db.execute(select(*columns).where(file_scope(actor)).order_by(File.created_at.desc(), File.id).limit(200)).mappings()]

    @app.post('/api/files', status_code=201)
    async def upload(request: Request, actor: Actor, db: DB, name: Annotated[str, Query(min_length=1, max_length=200)], visibility: Literal['private'] = 'private'):
        if any(ord(c) < 32 or ord(c) == 127 for c in name) or '/' in name or '\\' in name or not name.strip():
            raise HTTPException(422, '유효하지 않은 파일명입니다.')
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > MAX_FILE_BYTES:
                raise HTTPException(413, '파일은 2 MiB 이하만 등록할 수 있습니다.')
            content.extend(chunk)
        if not content:
            raise HTTPException(422, '빈 파일은 등록할 수 없습니다.')
        row = File(id=str(uuid4()), owner_id=actor.id, department_id=actor.department_id, visibility=visibility, name=name, size=len(content), content=bytes(content))
        db.add(row)
        audit(db, actor.id, 'file_uploaded', row.id)
        db.commit()
        return file_view(row)

    @app.get('/api/files/{fid}/download')
    def download(fid: str, actor: Actor, db: DB):
        row = db.scalar(select(File).where(File.id == fid, file_scope(actor)))
        if row is None:
            raise HTTPException(404, '파일을 찾을 수 없습니다.')
        audit(db, actor.id, 'file_downloaded', fid)
        db.commit()
        return Response(content=row.content, media_type='application/octet-stream', headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(row.name, safe='')})

    @app.delete('/api/files/{fid}', status_code=204)
    def remove_file(fid: str, actor: Actor, db: DB):
        row = db.scalar(select(File).where(File.id == fid, File.owner_id == actor.id))
        if row is None:
            raise HTTPException(404, '파일을 찾을 수 없습니다.')
        if db.scalar(select(Run.id).join(RunAttachment).where(RunAttachment.file_id == fid, Run.status.in_(ACTIVE))):
            raise HTTPException(409, '이 파일을 사용하는 작업을 먼저 중지해 주세요.')
        db.delete(row)
        audit(db, actor.id, 'file_deleted', fid)
        db.commit()

    @app.get('/api/admin/users')
    def users(actor: Admin, db: DB):
        query = select(User)
        if settings.auth_mode in ('google', 'cloudflare'):
            membership = AccessAccount if settings.auth_mode == 'cloudflare' else GoogleAccount
            query = query.join(membership, membership.user_id == User.id)
        return [user_view(u, db) for u in db.scalars(query.order_by(User.username))]

    @app.patch('/api/admin/users/{uid}/approval')
    def approval(uid: str, body: ApprovalInput, actor: Admin, db: DB):
        if uid == actor.id:
            raise HTTPException(409, '본인 승인 상태는 변경할 수 없습니다.')
        account = db.get(AccessAccount if settings.auth_mode == 'cloudflare' else GoogleAccount, uid)
        if account is None:
            raise HTTPException(404, '가입 계정을 찾을 수 없습니다.')
        account.approval_status, account.reviewed_by, account.reviewed_at = body.status, actor.id, now()
        user = db.get(User, uid)
        if body.status == 'approved':
            user.active = True
        else:
            db.execute(delete(SessionToken).where(SessionToken.user_id == uid))
        audit(db, actor.id, 'user_' + body.status, uid)
        db.commit()
        return user_view(user, db)

    @app.patch('/api/admin/users/{uid}')
    def set_active(uid: str, body: ActiveInput, actor: Admin, db: DB):
        if uid == actor.id:
            raise HTTPException(409, '본인 계정은 여기서 비활성화할 수 없습니다.')
        user = db.get(User, uid)
        if not user:
            raise HTTPException(404, '사용자를 찾을 수 없습니다.')
        user.active = body.active
        if not body.active:
            db.execute(delete(SessionToken).where(SessionToken.user_id == uid))
        audit(db, actor.id, 'user_activated' if body.active else 'user_deactivated', uid)
        db.commit()
        return user_view(user, db)

    @app.get('/api/admin/audit')
    def audit_events(actor: Admin, db: DB):
        return [{k: getattr(row, k) for k in ('id', 'actor_id', 'action', 'resource_id', 'created_at')} for row in db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id).limit(200))]

    @app.get('/', include_in_schema=False)
    def index():
        return FileResponse(WEB_ROOT / 'index.html')

    @app.get('/app.js', include_in_schema=False)
    def javascript():
        return FileResponse(WEB_ROOT / 'app.js', media_type='text/javascript')

    @app.get('/style.css', include_in_schema=False)
    def stylesheet():
        return FileResponse(WEB_ROOT / 'style.css', media_type='text/css')

    return app
