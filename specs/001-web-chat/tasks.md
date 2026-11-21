# 구현 작업 · 로그인과 관리자 승인이 있는 텍스트 챗봇

기준 문서 · [명세](spec.md) · [계획](plan.md) · [데이터 모델](data-model.md) · [인터페이스 계약](contracts/web.md) · [설계 근거](research.md) · [인수 절차](quickstart.md)

경로는 저장소 루트 기준이다. 데이터 필드 인용은 같은 폴더의 데이터 모델 표를 가리킨다. 체크는 구현과 해당 검증을 마친 뒤에 한다. `[P]`는 아래에 지정된 선행 작업이 끝나면 별도 파일에서 병행할 수 있다는 뜻이다.

## 1단계 · 설정

- [ ] T001 [P] `Cargo.toml`과 `Cargo.lock`에 계획의 JSON·HTTPS 스트림·JWT·비동기 SQLite 의존성과 필요한 Axum/Tokio 기능을 지정하고 Rust 1.93에서 잠금 파일 빌드를 확인한다.
- [ ] T002 [P] `.env.example`에 모델 주소·이름·서버 키와 DB 경로의 용도를 표시한다. 인증·모델 설정에는 예시 값만 사용한다.

## 2단계 · 공통 기반

- [ ] T003 [P] `src/config.rs`에 Access·초기 관리자·모델·DB 설정을 읽는 코드를 작성한다. 미설정 상태에서 업무 경로를 허용하지 않고 키나 토큰이 오류 출력에 포함되지 않게 한다.
- [ ] T004 [P] `src/store.rs`에 SQLite 풀과 버전별 마이그레이션 실행을 구성한다. 외래키 검사, WAL, 유한한 잠금 대기를 적용하고 임시 DB로도 구동 가능하게 한다.
- [ ] T005 `src/lib.rs`와 `src/main.rs`에서 테스트 가능한 라우터와 시작 절차를 조립한다. 기존 기본 Compose에서 루프백 헬스체크를 유지하고, 보호 응답의 no-store, 변경 요청의 Origin·JSON 검사, 공개 오류 형식을 공통 처리한다.

**완료 기준** 빈 DB로 서버를 시작할 수 있고 기존 내부 헬스체크가 200을 반환한다. 인증 정보가 없는 요청으로 업무 데이터를 읽을 수 없다.

## 3단계 · US1 Google 로그인과 승인 대기 (P1)

**목표와 독립 검증** 신규 직원의 로그인을 취소하면 등록 0건이다. 같은 직원으로 두 번 로그인하면 계정 한 건과 대기 상태가 유지된다. 로그아웃 후 보호 주소에 접근하면 Access 인증 절차가 시작된다. FR-008~010, FR-012.

- [ ] T006 [P] [US1] `src/auth.rs`에 설정된 issuer의 공개키 조회·기한 있는 캐시·kid 회전 처리와 RS256, aud, iss, exp, iat, 선택적 nbf, subject·이메일 검증을 구현한다. `tests/access_identity.rs`에서 유효·만료·서명 실패·다른 audience·키 갱신 결과를 확인한다.
- [ ] T007 [P] [US1] `migrations/0001_accounts.sql`에 신원 중복과 복수 초기 관리자를 방지하는 계정 스키마를 만든다. [data-model.md](data-model.md)의 `Account.id`, `Account.issuer`, `Account.subject`, `Account.email`, `Account.role`, `Account.status`, `Account.version`, `Account.created_at`, `Account.reviewed_at`, `Account.reviewed_by` 정의를 적용한다.
- [ ] T008 [P] [US1] `web/index.html`, `web/session.js`, `web/style.css`에 본인 상태 조회·새로고침, 대기·거절·정지 안내, 승인 사용자용 진입 영역을 구현한다. Access 로그아웃 링크와 세션 만료 시 재인증 이동을 연결한다.
- [ ] T009 [US1] `src/accounts.rs`에서 검증된 신원의 최초 등록과 지정 관리자 할당을 원자적으로 처리한다. `tests/account_registration.rs`에서 동시 첫 방문, 재로그인, 동일 이메일·다른 subject가 기존 승인이나 역할을 바꾸지 않는지 확인한다.
- [ ] T010 [US1] `src/lib.rs`에 보호된 GET /, 정적 자산, GET /api/me를 연결한다. 실패한 신원으로 DB 변경이 발생하지 않는지, 승인 전 허용된 화면만 보이는지 확인한다.

## 4단계 · US2 관리자 승인·거절·취소 (P1)

**목표와 독립 검증** 관리자와 직원 두 명으로 승인·거절·취소를 각각 확인한다. 일반 직원은 관리 목록·변경에 접근할 수 없고 승인 취소 뒤 같은 세션의 권한 검사도 실패해야 한다. 실제 채팅 조회·전송 차단은 US3 연결 후 같은 계정으로 재검증한다. FR-007, FR-010~011, SC-006~007.

- [ ] T011 [P] [US2] `migrations/0002_approval_decisions.sql`에 승인 변경 이력과 계정 참조를 정의한다. [data-model.md](data-model.md)의 `ApprovalDecision.id`, `ApprovalDecision.account_id`, `ApprovalDecision.actor_id`, `ApprovalDecision.action`, `ApprovalDecision.previous_status`, `ApprovalDecision.next_status`, `ApprovalDecision.decided_at` 정의를 적용한다.
- [ ] T012 [P] [US2] `web/admin.html`과 `web/admin.js`에서 이메일·상태를 표시하고 직원별 승인·거절·취소, 로그아웃을 연결한다. 버전 충돌 시 최신 목록을 다시 읽어 관리자가 결과를 확인하도록 한다.
- [ ] T013 [US2] `src/accounts.rs`에서 현재 관리자 권한·대상 직원·허용 전이·expected_version을 검사하고 상태 변경과 이력을 함께 커밋한다. 현재 승인·역할을 매 요청 조회하는 권한 검사를 제공한다.
- [ ] T014 [US2] `src/lib.rs`에서 GET /admin, GET /api/admin/accounts, POST /api/admin/accounts/{id}/decisions를 보호하고 `web/session.js`에서 승인된 관리자에게만 관리 링크를 표시한다.
- [ ] T015 [US2] `tests/admin_approval.rs`에서 승인·거절·취소와 재로그인 결과, 일반 직원의 목록 조회·변경 차단, 동시 변경 시 409 및 단일 이력 생성을 검증한다.

## 5단계 · US3 첫 질문과 실제 스트리밍 답변 (P1)

**목표와 독립 검증** 승인된 직원이 한글 질문 하나를 보내면 질문은 한 번만 보이고 실제 답변의 첫 글을 완료 전에 읽을 수 있다. 같은 요청의 재전송은 모델 호출을 추가하지 않는다. FR-001~003, FR-007, SC-004~005, SC-007.

- [ ] T016 [P] [US3] `migrations/0003_chat.sql`에 소유자 관계, 순번·요청 중복 제약, 활성 질문 인덱스를 구현한다. [data-model.md](data-model.md)의 `Conversation.id`, `Conversation.owner_id`, `Conversation.created_at`, `Turn.id`, `Turn.conversation_id`, `Turn.request_id`, `Turn.ordinal`, `Turn.user_text`, `Turn.assistant_text`, `Turn.state`, `Turn.revision`, `Turn.error_code`, `Turn.created_at`, `Turn.ended_at` 정의를 적용한다.
- [ ] T017 [P] [US3] `src/model.rs`에 순서 있는 메시지와 취소 신호를 받는 서버 측 DeepInfra 어댑터를 구현한다. UTF-8 조각을 스트림 프레임으로 조립하고 공개 답변과 완료 신호·사유를 해석한다. 키·원문·비공개 모델 출력은 브라우저와 로그에서 제외한다.
- [ ] T018 [P] [US3] `web/chat.js`에 한글 여러 줄 입력, 작성자와 순서 표시, 공백·중복 전송 방지, 페이지별 대화 ID와 전송별 요청 ID 재사용, revision 기반 누적 텍스트 표시를 구현한다. 응답은 일반 텍스트로 렌더링한다.
- [ ] T019 [US3] `src/store.rs`에서 소유자별 대화 생성·질문 접수·상태 조회를 구현한다. 동일 ID 재전송과 본문 충돌을 구분하고 승인 확인, 활성 질문 확인과 최초 접수를 원자적으로 처리한다.
- [ ] T020 [US3] `src/chat.rs`에서 새로 접수한 질문에 대해서만 모델 작업을 시작한다. 공개 본문을 짧은 배치로 저장한 뒤 revision과 상태를 알리고, 실제 본문과 정상 종료 확인 후 완료한다. 오류가 나면 활성 상태를 해제한다.
- [ ] T021 [US3] `src/chat.rs`, `src/lib.rs`에 대화 생성·질문 전송·스냅샷·events 경로를 연결한다. 최신 스냅샷부터 구독해 갱신을 놓치지 않게 하고, 새 본문 공개 전 승인·만료를 검사한다. 관리자 포함 타인 자원은 404로 처리한다.
- [ ] T022 [US3] `web/index.html`, `web/session.js`에 승인된 직원용 채팅 입력·대화 영역을 연결한다. SSE 단절 시 `web/chat.js`에서 현재 상태를 조회하고 활성 질문만 재구독한다. 권한 상실 시 구독을 닫고 본인 상태를 갱신한다.
- [ ] T023 [US3] `tests/chat_delivery.rs`에서 동시 재전송의 모델 호출 수, 빈 입력, 409 충돌, 구독 직전 도착한 본문, 관리자 및 다른 직원의 접근, 승인 취소 후 조회·전송·구독 차단을 확인한다.

## 6단계 · US4 앞선 대화를 이어가기 (P1)

**목표와 독립 검증** 첫 질문에서만 알려 준 행사 이름 ‘솔바람’이 두 번째 답변에 사용되고 두 질문과 답변이 순서대로 보인다. FR-004, SC-001.

- [ ] T024 [P] [US4] `src/store.rs`에서 승인된 소유자의 같은 대화에 속하는 완료된 질문·답변 쌍을 순번순으로 조회한다. 현재 질문 ID를 경계로 삼아 중복 포함을 방지한다.
- [ ] T025 [P] [US4] `src/model.rs`에서 완료 쌍과 현재 질문으로 모델 입력을 구성한다. 설정된 모델 한도에 맞춰 오래된 쌍부터 제외하고 현재 질문 자체가 한도를 넘는 경우 오류를 반환한다.
- [ ] T026 [US4] `src/chat.rs`의 모델 호출에 조회한 맥락을 연결하고 `tests/chat_context.rs`에서 두 차례 왕복, 중지·실패 쌍 제외, 다른 계정 및 다른 대화 격리를 확인한다.

## 7단계 · US5 답변 중지와 실패 후 계속하기 (P2)

**목표와 독립 검증** 긴 답변을 중지한 뒤 표시된 글이 유지되고 추가 델타가 붙지 않는다. 시작 전 실패와 일부 수신 후 실패가 모두 표시되고 연결 복구 뒤 같은 화면에서 새 질문을 보낼 수 있다. FR-005~006, SC-002~003.

- [ ] T027 [P] [US5] `src/store.rs`에 중지·실패·완료 중 최초 전이만 성공하는 조건부 저장을 구현한다. 종료 시각과 누적 본문을 보존하고 늦은 쓰기를 막는다. 재기동 시 잔여 활성 질문을 실패로 마감하는 복구 연산을 제공한다.
- [ ] T028 [P] [US5] `web/chat.js`에 중지 요청, 서버가 확정한 결과 표시와 다음 입력 활성화를 연결한다. 시작 전 실패·부분 수신 후 실패·사용자 중지를 구별하고 기존 메시지를 유지한다.
- [ ] T029 [US5] `src/chat.rs`, `src/model.rs`, `src/accounts.rs`에서 소유자 중지 및 승인 취소 시 실행 취소 신호를 전달한다. 모델 시간 초과, 비정상 EOF, 잘린 응답을 공개 가능한 실패 코드로 변환하고 마지막 완료와의 경합 결과를 그대로 반환한다.
- [ ] T030 [US5] `src/lib.rs`에 소유자 전용 POST /api/conversations/{id}/turns/{turn}/stop을 등록하고 `src/main.rs`에서 새 요청을 받기 전에 T027 복구를 실행한다. 종료된 질문의 중지 재요청은 저장된 결과를 반환한다.
- [ ] T031 [US5] `tests/chat_recovery.rs`에서 중지·완료 경합, 타인의 중지 시도, 승인 취소 중 공개 차단, 응답 전·도중 실패, 재기동 후 후속 전송을 검증한다. 장애 재현용 모델은 테스트에서만 사용한다.

## 8단계 · 패키징과 통합 인수

- [ ] T032 `infra/Dockerfile`, `.dockerignore`, `compose.yaml`, `compose.tunnel.yaml`에 자산·마이그레이션 빌드 입력과 UID 10001 전용 데이터 볼륨을 반영한다. 읽기 전용 루트와 루프백 헬스체크를 보존하고 모델 키는 web에, 전용 Tunnel 토큰은 cloudflared에만 전달한다.
- [ ] T033 `docs/DEPLOYMENT.md`의 배포 아카이브 명령에 필요한 소스·자산·마이그레이션만 추가한다. 잠금 빌드, 내부 헬스체크, 새 볼륨 초기화와 컨테이너 교체 후 계정·승인 상태 보존을 별도 ARM64 환경에서 확인한다.
- [ ] T034 `specs/001-web-chat/quickstart.md`에 따라 자동화 테스트와 별도 Google 전용 Access/Tunnel 환경의 실제 모델 브라우저 인수를 수행한다. SC-001~007별 결과와 미실행 항목을 같은 문서에 기록한다. 운영 호스트 전환은 별도 배포 작업이다.

## 의존 관계와 병렬 실행

설정(T001~002) → 기반(T003~005) → US1 → US2 → US3 → US4·US5 → 통합 인수. 기본 실행 순서는 작업 번호순이다. US4와 US5는 기능상 서로 독립적이지만 `src/store.rs`, `src/chat.rs`, `src/model.rs`를 함께 수정하므로 같은 파일 변경은 순차 통합한다.

| 단계 | 병행 가능한 작업 | 합류 지점 |
| --- | --- | --- |
| 설정·기반 | T001과 T002. 설정 후 T003과 T004 | T005에서 조립 |
| US1 | T006 서명 검증, T007 계정 스키마, T008 상태 화면 | T009에서 등록, T010에서 화면·서버 연결 |
| US2 | T011 승인 이력 스키마, T012 관리 화면 | T013 처리 후 T014 연결 |
| US3 | T016 대화 스키마, T017 모델 어댑터, T018 브라우저 | T019~022에서 전송과 구독 연결 |
| US4 | T024 이력 조회, T025 모델 입력 구성 | T026에서 실제 호출 연결 |
| US5 | T027 종료 상태 저장, T028 중지·오류 UI | T029~030에서 실행과 라우터 연결 |

## 인도 순서

US1은 첫 독립 검증 지점이다. US2까지 마치면 관리자가 실제 신청을 처리할 수 있다. **직원용 최소 채팅 시연은 US1~US4**로 잡는다. 직원이 로그인해 승인을 받고, 첫 답변에 이어 맥락 있는 후속 답변까지 받아야 한다. 첫 기능 전체의 완료 판정에는 US5와 통합 인수 결과도 필요하다.
