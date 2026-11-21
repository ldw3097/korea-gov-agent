"""Create synthetic local accounts. Never imports personal-agent data."""
import getpass
import os
from pathlib import Path

from sqlalchemy import select

from .app import Settings
from .db import Base, Department, User, database
from .security import hash_password


def seed(db, password: str):
    if len(password) < 12 or len(password) > 256 or password != password.strip():
        raise ValueError('비밀번호는 앞뒤 공백 없이 12~256자로 설정하세요.')
    if db.scalar(select(User.id).limit(1)):
        raise ValueError('이미 계정이 있습니다. seed는 빈 DB에서만 실행할 수 있습니다.')
    db.add_all([Department(id='planning', name='테스트 기획부'), Department(id='operations', name='테스트 운영부')])
    db.flush()
    for username, name, department, role in [
        ('alice', '테스트 직원 A', 'planning', 'employee'),
        ('bob', '테스트 직원 B', 'planning', 'employee'),
        ('carol', '테스트 직원 C', 'operations', 'employee'),
        ('admin', '테스트 관리자', 'operations', 'admin'),
    ]:
        db.add(User(id=username, username=username, display_name=name, department_id=department, role=role, password_hash=hash_password(password)))
    db.commit()


def main():
    settings = Settings(database_url=os.getenv('DATABASE_URL', Settings.database_url), environment=os.getenv('APP_ENV', 'development'))
    settings.validate()
    if settings.environment != 'development':
        raise ValueError('seed는 development 환경에서만 실행하세요.')
    password = getpass.getpass('테스트 계정 공통 비밀번호 (12자 이상): ')
    if password != getpass.getpass('비밀번호 확인: '):
        raise ValueError('비밀번호가 일치하지 않습니다.')
    Path('data').mkdir(mode=0o700, exist_ok=True)
    engine, sessions = database(settings.database_url)
    try:
        Base.metadata.create_all(engine)
        with sessions() as db:
            seed(db, password)
    finally:
        engine.dispose()
    print('합성 계정 alice / bob / carol / admin 생성 완료. 실제 업무자료는 등록하지 마세요.')


if __name__ == '__main__':
    main()
