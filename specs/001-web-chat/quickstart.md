# 구현 후 검증 절차

현재 가능한 검증은 헬스체크다. 아래의 인증·관리·모델 시나리오는 기능 구현 후 실행할 인수 절차다. 기준은 [기능 명세](spec.md)와 [화면·HTTP 계약](contracts/web.md)이다.

## 준비

- Rust 1.93 이상과 Docker Compose를 준비한다. 실제 브라우저 검증에는 시연과 분리한 테스트 호스트·Tunnel·Access 앱, Google 전용 IdP, 지정 관리자와 별도 직원 A·B 계정을 사용한다. Protect with Access와 Google 전용 Allow 정책을 확인한다.
- 테스트 환경의 권한 0600인 환경 파일에 공개 주소, Access issuer·audience, 관리자 이메일, 검증한 Tunnel 이미지·전용 토큰을 설정한다. 구현 시 추가할 모델 설정은 `MODEL_BASE_URL`, `MODEL_NAME`, `MODEL_API_KEY`다. 모델 정보와 키는 web에, Tunnel 토큰은 cloudflared에만 전달한다. 기존 운영 환경 파일 전체를 복사하지 않는다. [배포 절차](../../docs/DEPLOYMENT.md)
- 데이터 볼륨은 이 테스트 프로젝트 전용으로 준비한다. 앱 UID 10001이 DB와 부속 파일을 쓸 수 있어야 한다. 테스트 더블과 테스트용 서명키는 자동화 테스트에서만 사용한다.

## 빌드와 기동

저장소 루트에서 실행한다. 첫 명령은 구현 시 추가할 통합 테스트까지 실행한다. Compose 명령은 준비한 검증 환경의 설정을 사용한다.

```sh
cargo test --locked
docker compose -p chat-acceptance -f compose.yaml -f compose.tunnel.yaml --profile tunnel config --quiet
docker compose -p chat-acceptance -f compose.yaml -f compose.tunnel.yaml --profile tunnel up --build -d --wait
docker compose -p chat-acceptance exec -T web curl --fail -i http://127.0.0.1:3000/health
```

기대 결과는 테스트 통과, web 컨테이너 healthy, 내부 헬스체크 HTTP 200이다. 외부에서는 인증 전 Access 로그인으로 이동해야 한다. 원본 앱의 업무 경로는 유효한 서명 없이 접근할 때 데이터를 반환하면 안 된다.

## 브라우저 인수

| 절차 | 기대 결과 | 기준 |
| --- | --- | --- |
| 별도 브라우저 프로필로 관리자·직원 A·B를 구분한다. A는 Google 로그인을 취소한 뒤 다시 접속해 정상 로그인한다. 로그아웃 후 한 번 더 로그인한다 | 취소 후 계정 생성 0건. 정상 로그인 두 번 후 관리자 목록에 A 한 건. 승인 전에는 본인 상태·로그아웃만 보인다 | SC-004~005 |
| 관리자가 A를 승인하고 A가 대기 화면을 새로고침한다. “행사 이름은 솔바람이야”와 “그 이름으로 환영 인사를 써 줘”를 차례로 보낸다 | 실제 답변 두 개. 두 번째 답변에 ‘솔바람’이 포함되고 각 질문의 작성자와 순서가 보인다 | SC-001, SC-005 |
| A가 긴 답변을 요청하고 일부 글이 보일 때 중지한 뒤 다른 질문을 보낸다 | 받은 글과 중지 상태가 남고 다음 질문에는 별도의 실제 답변이 도착한다 | SC-002 |
| A가 관리 화면·관리 요청에 접근하고, 관리자가 A의 대화 ID로 본문을 요청한다 | 직원의 관리 목록 조회·변경은 403, 타인 대화 읽기는 404. 상태와 내용이 노출되지 않는다 | SC-004, SC-007 |
| 관리자가 B의 대기 신청을 거절하고 A의 사용 승인을 취소한다. A의 기존 탭에서 조회·전송을 시도하고 두 직원 모두 재로그인한다 | B는 거절 상태를 확인한다. A의 다음 조회·전송이 차단된다. 재로그인 후에도 모두 채팅에 접근할 수 없다 | SC-004, SC-006 |
| 대기·채팅 화면 각각에서 로그아웃하고 기존 주소를 다시 연다 | Access 인증 절차가 재개되고 이전 화면에 보호된 내용을 표시하지 않는다 | FR-012, SC-005 |

## 실패와 재시작

- 자동화 테스트에서 모델이 응답 시작 전 실패하는 경우와 일부 한글 텍스트 후 연결이 종료되는 경우를 각각 재현한다. 둘 다 failed가 되고 두 번째 경우 받은 글이 유지되어야 한다. 모델 연결을 복구하고 같은 페이지에서 새 질문을 보낸다. 실제 모델 성공 경로는 위 브라우저 인수에서 별도로 확인한다(SC-003).
- 같은 요청 ID를 동시에 두 번 보내 질문 한 쌍과 모델 호출 한 번만 생기는지 확인한다. 빈 입력, 중지와 완료의 경합, 만료된 인증, 최초 관리자 이메일과 같은 다른 신원, 승인 변경의 버전 충돌, 다른 사용자의 중지·구독 요청도 검증한다.
- 테스트 환경에서 긴 답변 생성 중 아래 명령으로 web을 교체한다. 계정·승인 상태와 기존 본문은 남고 중단된 실행은 failed가 되어야 한다. 새 질문이 영구히 대기하지 않는지 확인한다. 검증이 끝나면 테스트 컨테이너를 내린다.

```sh
docker compose -p chat-acceptance -f compose.yaml -f compose.tunnel.yaml --profile tunnel up -d --force-recreate --no-deps --wait web
docker compose -p chat-acceptance -f compose.yaml -f compose.tunnel.yaml --profile tunnel down
```
