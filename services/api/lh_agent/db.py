from datetime import datetime, timezone
from time import time_ns

from sqlalchemy import Boolean, ForeignKey, LargeBinary, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def now() -> int:
    return int(datetime.now(timezone.utc).timestamp())


class Base(DeclarativeBase):
    pass


class Department(Base):
    __tablename__ = 'departments'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    department_id: Mapped[str] = mapped_column(ForeignKey('departments.id'))
    role: Mapped[str] = mapped_column(String(20), default='employee')
    password_hash: Mapped[str] = mapped_column(String(256))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class SessionToken(Base):
    __tablename__ = 'sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    expires_at: Mapped[int]


class GoogleAccount(Base):
    __tablename__ = 'google_accounts'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    subject: Mapped[str] = mapped_column(String(256), unique=True)
    email: Mapped[str] = mapped_column(String(100))
    approval_status: Mapped[str] = mapped_column(String(20), default='pending')
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    reviewed_at: Mapped[int | None] = mapped_column(nullable=True)


class AccessAccount(Base):
    __tablename__ = 'access_accounts'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    issuer: Mapped[str] = mapped_column(String(256))
    subject: Mapped[str] = mapped_column(String(256))
    email: Mapped[str] = mapped_column(String(100))
    approval_status: Mapped[str] = mapped_column(String(20), default='pending')
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    reviewed_at: Mapped[int | None] = mapped_column(nullable=True)


class OAuthAttempt(Base):
    __tablename__ = 'oauth_attempts'
    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    browser_hash: Mapped[str] = mapped_column(String(64))
    nonce: Mapped[str] = mapped_column(String(128))
    verifier: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[int]


class LoginAttempt(Base):
    __tablename__ = 'login_attempts'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(default=0)
    window_start: Mapped[int]


class Thread(Base):
    __tablename__ = 'threads'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    title: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[int] = mapped_column(default=now)


class Message(Base):
    __tablename__ = 'messages'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey('threads.id', ondelete='CASCADE'), index=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(default=time_ns)


class File(Base):
    __tablename__ = 'files'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    department_id: Mapped[str] = mapped_column(ForeignKey('departments.id'), index=True)
    visibility: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    size: Mapped[int]
    content: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[int] = mapped_column(default=now)


class AuditEvent(Base):
    __tablename__ = 'audit_events'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[int] = mapped_column(default=now)


class Project(Base):
    __tablename__ = 'projects'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(String(100))
    instructions: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[int] = mapped_column(default=now)


class ThreadProject(Base):
    __tablename__ = 'thread_projects'
    thread_id: Mapped[str] = mapped_column(ForeignKey('threads.id', ondelete='CASCADE'), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), index=True)


class ProjectFile(Base):
    __tablename__ = 'project_files'
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), primary_key=True)
    file_id: Mapped[str] = mapped_column(ForeignKey('files.id', ondelete='CASCADE'), primary_key=True)


class Run(Base):
    __tablename__ = 'work_runs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey('threads.id', ondelete='CASCADE'), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    mode: Mapped[str] = mapped_column(String(10))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default='queued', index=True)
    partial: Mapped[str] = mapped_column(Text, default='')
    error: Mapped[str | None] = mapped_column(String(64), nullable=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[int] = mapped_column(default=time_ns)
    updated_at: Mapped[int] = mapped_column(default=now)


class RunAttachment(Base):
    __tablename__ = 'run_attachments'
    run_id: Mapped[str] = mapped_column(ForeignKey('work_runs.id', ondelete='CASCADE'), primary_key=True)
    file_id: Mapped[str] = mapped_column(ForeignKey('files.id', ondelete='CASCADE'), primary_key=True)


class RunEvent(Base):
    __tablename__ = 'work_run_events'
    sequence: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey('work_runs.id', ondelete='CASCADE'), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[int] = mapped_column(default=now)


class AssistantMessage(Base):
    __tablename__ = 'assistant_messages'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey('threads.id', ondelete='CASCADE'), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey('work_runs.id', ondelete='CASCADE'), index=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(default=time_ns)


class Artifact(Base):
    __tablename__ = 'artifacts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey('threads.id', ondelete='CASCADE'), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey('work_runs.id', ondelete='CASCADE'), index=True)
    filename: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(120))
    version: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(default=now)


def database(url: str):
    kwargs = {'connect_args': {'check_same_thread': False, 'timeout': 15}} if url.startswith('sqlite:') else {}
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == 'sqlite':
        @event.listens_for(engine, 'connect')
        def configure(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA journal_mode=WAL')
    return engine, sessionmaker(engine, expire_on_commit=False)
