# K-gov-agent 기반 설계

공공부문 기관별 독립 배포를 목표로 한다. 아래는 현재 PoC의 기반 구조다. [제품 방향](PRODUCT_DIRECTION.md) · [인증 기준](AUTH.md) · [업무 실행](WORK.md)

## 현재 구현

FastAPI 한 프로세스가 정적 웹과 API를 같은 origin에서 제공한다. SQLite WAL을 이용하며 기본 DB와 파일 원문은 `data/lh_agent.db`에 저장한다. 합성 자료를 이용한 로컬 권한 검증이 목적이다. ORM은 SQLAlchemy를 사용하지만 PostgreSQL 전환을 검증한 것으로 보지 않는다.

```text
브라우저 → Host / Origin / 본문 크기 검사 → API
                                         ↓
                     쿠키 토큰 해시 조회 → 유효기간·계정 활성 확인
                                         ↓
                         서버 사용자 → 승인·소유자·역할 검사
                                         ↓
                           SQLite (업무 데이터 + 감사 이벤트)
```

## 인증과 권한

로컬 모드에서 비밀번호는 개별 무작위 salt와 scrypt로 해시한다. 세션은 256비트 무작위 opaque token이며 DB에는 SHA-256 해시만 저장한다. HttpOnly·SameSite=Strict 쿠키로 전달하며 기본 만료는 8시간이다. 로컬 HTTP 쿠키에는 Secure가 없으며 외부 배포에서 이 인증 방식을 사용할 수 없다.

원격 시연 모드는 Cloudflare Access가 HTTPS와 Google 로그인을 관리한다. 앱은 `Cf-Access-Jwt-Assertion`의 서명(RS256), issuer, audience, 만료·발급 시각, subject, 이메일을 검증한다. 발급자 주소는 설정된 cloudflareaccess.com 팀 주소로 제한하고, JWKS를 가져올 수 없으면 검증에 실패한다. 로컬 비밀번호 로그인은 차단한다. 컨테이너 내부 loopback의 `/health` GET은 상태 확인용으로 사용한다.

Access 계정이 처음 접속하면 issuer+subject의 해시를 계정 ID로 사용한다. 초기 관리자는 설정된 이메일로 정하고 다른 신규 계정은 사용 승인 대기 상태로 등록한다. 업무 API는 계정의 활성·승인 상태를 검사한다. 부서 컬럼은 기존 저장 구조와의 호환에 사용한다.

모든 변경 요청은 정확한 Origin을 요구하며 CORS를 열지 않는다. Host도 설정 origin과 일치해야 한다. 임의 사용자 식별 헤더·역할 헤더는 인증에 사용하지 않는다. 요청당 본문 크기를 제한한다. 로그인 실패는 계정명·클라이언트 주소의 해시별로 15분에 10회까지 허용한다. 이는 로컬 단일 프로세스의 기본 방어이며 다중 프로세스에서의 원자적 제한, 계정 복구·비밀번호 변경·MFA는 후속 작업이다.

로컬 계정 모드에서는 로컬 이외 클라이언트 주소의 요청을 거부한다. 테스트 환경의 TestClient 주소만 별도로 허용한다. Access 모드는 컨테이너 네트워크에서 요청을 받되 유효한 서명 토큰을 요구한다. 입력 검증 오류 응답은 제출한 비밀번호 등 원문을 포함하지 않는 일반 오류로 반환한다.

계정 정지는 현재 세션들을 삭제한다. 계정을 다시 활성화해도 기존 세션은 복원되지 않는다. 이미 인증을 통과해 처리 중인 요청까지 취소하는 기능은 없다.

| 리소스·작업 | 접근 기준 |
| --- | --- |
| 대화·메시지, 프로젝트, 실행과 결과물 | 소유 계정만 |
| 파일 목록·다운로드·삭제 | 등록 계정만 |
| 계정 목록·승인·활성 상태 관리 및 감사 조회 | 관리자만 |

소유자는 서버가 인증된 신원으로 지정한다. 권한 없는 대화·파일은 404를 반환한다.

## 저장 구조

| 테이블 | 내용 |
| --- | --- |
| departments / users / access_accounts | 기존 부서 호환값, 계정 ID·역할·상태·비밀번호 해시, Access 신원과 승인 이력 |
| sessions / login_attempts | 해시된 세션과 만료, 로그인 실패 제한 |
| threads / messages / assistant_messages | 소유자별 대화, 사용자 입력과 에이전트 응답 |
| files | 소유자·이름·크기·파일 BLOB과 기존 호환 컬럼 |
| projects / project_files / thread_projects | 프로젝트와 자료·대화 연결 |
| work_runs / work_run_events / artifacts | 실행, 영속 진행 이벤트, 결과물 버전 |
| audit_events | 행위자 ID·행위·리소스 ID·시각. 원문과 토큰 제외 |

파일은 최대 2 MiB, 다운로드는 attachment / application/octet-stream으로 고정한다. 파일명으로 OS 경로를 생성하지 않고 브라우저에서 파일 원문을 실행하지 않는다. 현재 미리보기·압축 해제·문서 추출·악성코드 검사·공용 다운로드 링크는 없다. 삭제는 앱 DB에서의 논리적 레코드 삭제이며 SQLite/WAL/OS 저장 매체의 물리적 완전 삭제를 보장하지 않는다.

목록은 대화·파일 최대 200건, 대화 상세는 첫 메시지 500건, 감사 기록은 최근 200건으로 제한된다. PoC 데이터가 이를 넘기기 전에 페이지네이션을 도입해야 한다. 초기 스키마는 `create_all`로 생성하며 기존 스키마를 자동 업그레이드하지 않는다. 변경 시 마이그레이션을 추가해야 한다.

## API

| 경로 | 기능 |
| --- | --- |
| `POST /api/auth/login`, `POST /api/auth/logout` | 세션 발급·폐기 |
| `GET /api/me` | 현재 직원 정보 |
| `GET/POST /api/threads` | 본인 대화 목록·생성 |
| `GET/DELETE /api/threads/{id}` | 본인 대화 상세·삭제 |
| `POST /api/threads/{id}/messages` | 본인 대화에 사용자 메시지 저장 |
| `GET/POST /api/files` | 접근 가능한 파일 목록·등록 |
| `GET /api/files/{id}/download` | 소유권 검사 후 다운로드 |
| `DELETE /api/files/{id}` | 등록자만 파일 삭제 |
| `GET /api/admin/users`, `PATCH /api/admin/users/{id}/approval` | 계정 목록·사용 승인 관리 |
| `PATCH /api/admin/users/{id}` | 계정 활성/비활성, 정지 시 세션 폐기 |
| `GET /api/admin/audit` | 최근 감사 이벤트 |
| `GET /health` | 서비스 상태와 모델 사용 가능 여부 |

파일 등록은 `name` 쿼리와 raw binary body를 사용한다. `visibility`의 허용값은 `private`이다. 프로젝트·작업·결과물의 동작은 [업무 실행 문서](WORK.md)를 참고한다.

## 운영 전 필요한 작업

기관별 배포에 기관 인증과 내부 모델·저장소를 연결한다. 운영 DB·마이그레이션, 파일 보관 정책·백업 복원, 사용량 제한, 문서 처리 격리, 실제 동시 부하를 검증해야 한다. 감사 기록은 현재 앱 DB에 저장한다. 현재 실행기는 API 프로세스에 내장돼 있다. [업무 실행 구조](WORK.md)
