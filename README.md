# K-gov-agent

K-gov-agent는 중앙행정기관, 지방자치단체, 공공기관 등 공공부문 기관의 내부망에서 쓰도록 설계하는 업무 에이전트입니다. 직원은 ChatGPT Work와 유사한 흐름으로 업무를 맡기고, 진행 중 방향을 바꾸고, 결과물을 검토·수정할 수 있습니다. 기관별 독립 배포를 기본으로 하며, 공통 코드에 기관별 인증·모델·저장소·업무시스템을 연결할 수 있도록 설계합니다. [제품 방향](docs/PRODUCT_DIRECTION.md)

전체 범위는 [구현 계획](docs/IMPLEMENTATION_PLAN.md), 현재 구현과 제한은 [현재 상태](docs/STATUS.md), 인증·데이터 경계는 [설계 문서](docs/ARCHITECTURE.md)를 참고하세요.

PoC 가입 방식은 **Google 로그인 → 승인 대기 → 관리자 승인 후 사용**입니다. 사용자·부서 사전 지정은 하지 않습니다. [인증·승인 설정](docs/AUTH.md)을 기준으로 합니다. Cloudflare Access에서 Google로 로그인하고, 앱에서 관리자가 사용을 승인하는 구성으로 배포했습니다. 사용자도 실제 로그인 후 업무 화면 진입을 확인했습니다.

## Work 첫 버전

[Work 기능·사용법·제한](docs/WORK.md)에 구현 범위를 정리했습니다. 프로젝트와 자료를 연결해 실제 모델에 업무를 맡기고, 진행 중 추가 요청·중지를 하며, 오른쪽에서 생성 문서를 검토·수정·다운로드할 수 있습니다.

## 현재 가능한 기능

- Cloudflare Google 신원 기반 계정 자동 등록, 승인 대기·승인·거절·승인 취소
- 로컬 합성 계정 로그인·로그아웃, 일반 사용자·관리자 역할 분리
- 본인 대화 생성·목록·메시지 저장·삭제, 다른 직원의 대화 접근 차단
- 본인 파일 등록·목록·다운로드·삭제. 부서 공유는 제거
- 관리자 계정 활성/비활성 전환, 세션 폐기, 감사 이벤트 조회
- Work 형태의 대화 UI, 프로젝트·지침·자료, 실제 AI 스트리밍·작업 중지·질문 후 재개
- Markdown 결과물 생성·미리보기·버전·다운로드와 대화 재접속 복원

**현재 PoC는 LLM 응답, 작업 실행, Markdown 결과물을 지원합니다. 기관 인증 연동, 내부 문서 검색, 오피스 파일 생성, 내부망 배포 검증은 후속 범위입니다. 합성·공개 샘플로 검증하세요.** 로컬 계정 환경과 Cloudflare Access로 보호하는 원격 시연 환경을 지원합니다. 이 단계의 화면은 FastAPI가 제공하는 HTML/CSS/JavaScript이며, 업무 화면 확장 시 Next.js 도입을 검토합니다.

원격 시연 환경에서는 Cloudflare Access의 Google 로그인 후 앱에서 사용 승인을 관리합니다. [배포 안내](docs/DEPLOYMENT.md)

## 실행

Python 3.11 이상이 필요합니다. 저장소 루트에서 실행합니다. 화면·권한 검증에는 외부 모델 키가 필요하지 않습니다. 실제 AI 작업은 MODEL_API_KEY, MODEL_BASE_URL, MODEL_NAME을 설정해야 합니다.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
PYTHONPATH=services/api .venv/bin/python -m lh_agent.seed
PYTHONPATH=services/api .venv/bin/uvicorn lh_agent.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

seed 명령은 입력을 숨긴 상태로 공통 테스트 비밀번호를 두 번 요청합니다. 앞뒤 공백 없는 12~256자를 사용하세요. 비밀번호를 명령 인자나 저장소에 기록하지 않습니다. 기존 계정이 있으면 덮어쓰지 않습니다.

브라우저에서 [로컬 앱](http://127.0.0.1:8000)을 엽니다. origin 검증 때문에 `localhost` 대신 이 주소를 사용하세요. [API 명세](http://127.0.0.1:8000/docs)도 제공하며, 변경 요청은 같은 origin에서 호출해야 합니다.

| 계정 | 가상 부서 | 역할 |
| --- | --- | --- |
| alice | 테스트 기획부 | 직원 |
| bob | 테스트 기획부 | 직원 |
| carol | 테스트 운영부 | 직원 |
| admin | 테스트 운영부 | 관리자 |

각기 다른 브라우저 프로필 또는 일반/시크릿 창으로 로그인해 격리를 확인할 수 있습니다. 같은 브라우저 프로필의 탭들은 세션 쿠키를 공유합니다.

DB는 기본적으로 `data/lh_agent.db`에 생성되며 Git에서 제외됩니다. SQLite WAL 모드, 로컬 서버 한 프로세스를 전제로 합니다. `data`에는 파일 원문과 대화·생성 문서가 들어가므로 개발 OS 계정의 접근 권한으로 보호해야 합니다. 저장 암호화·백업·운영용 마이그레이션은 아직 제공하지 않습니다.

## 검증

```sh
.venv/bin/python -m pytest -q
node --check apps/web/app.js
```

테스트는 임시 DB와 합성 데이터만 사용합니다. 승인과 계정별 접근 통제, 세션 만료·로그아웃·계정 정지, CSRF·Host 검증, 파일 용량 제한, 동시 사용자 쓰기를 검증합니다.

## 설정

| 환경변수 | 기본값 | 의미 |
| --- | --- | --- |
| `APP_ENV` | `development` | 로컬은 `development` / `test`. `production`은 Cloudflare 인증·HTTPS 설정 필수 |
| `PUBLIC_ORIGIN` | `http://127.0.0.1:8000` | 브라우저가 사용하는 loopback origin과 정확히 일치해야 함 |
| `MODEL_API_KEY` | 빈 값 | 서버 전용 모델 키. 없으면 작업 실행 차단 |
| `MODEL_BASE_URL` | `https://api.deepinfra.com/v1/openai` | OpenAI 호환 API 주소 |
| `MODEL_NAME` | `deepseek-ai/DeepSeek-V4.1-Flash-1017` | 모델 ID |
| `DATABASE_URL` | `sqlite:///./data/lh_agent.db` | 현재 SQLite만 지원. 커스텀 경로의 부모 디렉터리는 미리 생성 |

`.env` 자동 로드는 하지 않습니다. 로컬 개발 설정은 실행 셸에서 주입합니다. 계정 생성과 API 서버는 같은 `DATABASE_URL`을 사용해야 합니다. 시연 환경의 런타임 설정과 로컬 운영 도구 자격증명 관리 방법은 [배포 문서](docs/DEPLOYMENT.md)를 참고하세요.
