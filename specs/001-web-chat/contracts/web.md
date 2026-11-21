# 화면·HTTP·모델 계약

구현할 경로와 응답을 정의한다. 현재 서버에서 사용할 수 있는 경로는 컨테이너 루프백의 `GET /health`다.

## 신원과 접근

- 시연 호스트의 익명 방문은 Cloudflare Access가 Google 로그인으로 안내한다. 앱은 매 보호 요청의 `Cf-Access-Jwt-Assertion`을 확인한다. RS256만 허용하고 고정 issuer의 `/cdn-cgi/access/certs`에서 가져온 키를 kid로 선택한다. 키는 만료되는 캐시에 두고 알 수 없는 kid에는 제한된 새로고침을 적용한다.
- 서명·issuer·audience·exp·iat·선택적 nbf 및 유효한 subject·이메일을 검사한다. 검증 실패 시 신원·계정을 생성하지 않는다. 서비스가 키를 확인할 수 없는 경우에도 업무 데이터에 접근시키지 않는다. 요청 헤더의 평문 이메일이나 사용자가 보낸 역할은 신원 자료로 쓰지 않는다.
- 본인 상태 조회와 로그아웃은 모든 인증 사용자에게 허용한다. 채팅은 approved, 관리 기능은 approved/admin이 필요하다. 모든 대화 관련 경로는 소유자 조건도 검사한다. 보호 응답은 `Cache-Control: no-store`. 상태 변경 요청은 구성된 공개 주소와 Origin이 일치해야 하며 JSON만 받는다.
- 인증 실패는 앱에서 401, 승인·역할 부족은 403, 타인 소유 또는 존재하지 않는 자원은 404다. 로그인 세션 만료 시 화면에서 최상위 페이지로 인증을 다시 시작한다. 인증 예외는 기존 루프백 헬스체크 한 곳이다.

## 화면과 데이터 요청

| 요청 | 정상 응답과 화면 동작 |
| --- | --- |
| GET / | 인증된 페이지 진입점. 본인 상태에 따라 대기·거절 안내 또는 채팅 화면 표시. 승인된 관리자에게 관리 화면 링크 제공 |
| GET /api/me | 200, id·email·role·status. 검증된 신규 신원은 등록 후 응답. 대기 화면의 새로고침은 최신 상태를 읽음 |
| GET /admin 및 GET /api/admin/accounts | 관리자 전용 화면 및 목록. 목록은 id·email·status·version을 제공 |
| POST /api/admin/accounts/{id}/decisions | 입력 action(approve/reject/revoke), expected_version. 200으로 갱신된 직원 상태 반환. 상태·버전 충돌은 409 |
| GET /cdn-cgi/access/logout | 브라우저가 직접 이동하는 Access 경로. 대기·채팅·관리 화면에서 동일하게 제공 |
| POST /api/conversations | 빈 JSON 객체로 시작. 201 및 conversation_id. 한 페이지는 받은 ID를 후속 질문에 재사용 |
| POST /api/conversations/{id}/turns | 입력 request_id와 text. 새 질문은 202, 같은 요청 재전송은 200. 두 응답 모두 turn_id·state·revision 제공. 공백 입력은 422, ID 재사용 충돌 또는 다른 활성 질문은 409 |
| GET /api/conversations/{id}/turns/{turn} | 200, 해당 질문의 상태 스냅샷. 구독 연결이 끊겼을 때 실제 상태 확인에 사용 |
| GET /api/conversations/{id}/turns/{turn}/events | text/event-stream. 인증·승인·소유권 검사 후 현재 스냅샷부터 전송. 종단 상태 전달 후 연결 종료 |
| POST /api/conversations/{id}/turns/{turn}/stop | 빈 JSON 객체. 서버가 확정한 현재 스냅샷을 200으로 반환. 이미 종료된 경우 그 상태를 반환 |

요청 ID는 브라우저가 전송 동작마다 한 번 생성하고, 접수 여부가 불명확하면 같은 ID로 재시도한다. 응답 본문에는 공개 가능한 오류 코드와 사용자용 메시지만 포함한다.

## 진행·중지·오류

이벤트 이름은 `turn`, 데이터는 JSON 스냅샷이다. 각 스냅샷은 turn_id, revision, state, 누적된 assistant_text, 선택적 error_code를 담는다. 작은 텍스트 배치를 DB에 반영한 뒤 최신 상태를 구독자에게 알린다. 이벤트와 재조회가 뒤섞여도 화면은 더 높은 revision만 적용한다.

예를 들어 “반갑습니다”까지 생성한 직후 사용자가 중지하면 서버는 그때까지 확정한 본문과 stopped를 반환한다. 마지막 글이 먼저 완료됐다면 completed를 반환한다. 브라우저는 그 결과를 표시하고 다음 질문을 허용한다. 구독 단절만으로 질문을 실패로 표시하지 않는다. 현재 상태를 다시 읽어 활성 상태이면 재구독한다.

구독 시작과 새 본문 공개 전에 소유자의 승인과 인증 만료 시각을 확인한다. 승인 취소·세션 만료 시 데이터 전송을 닫고 재접근 시 권한을 재검사한다. 승인 취소된 계정의 활성 실행에는 취소 신호를 보내고 종료를 기록한다. 이미 브라우저에 전달된 본문은 회수할 수 없다.

## 모델 경계

서버 설정의 endpoint·model·자격증명을 사용하는 어댑터가 순서 있는 메시지와 취소 신호를 받는다. 시연에서는 DeepInfra의 채팅 스트림에서 공개 텍스트만 받아 전달한다. 키는 서버에만 주입한다. 정상 종료는 제공자의 완료 신호와 종료 사유를 함께 해석한다. 길이 한도 등으로 잘린 응답, 비정상 EOF, 시작 전·도중 오류, 시간 초과는 각각 원인을 구분해 failed와 수신된 부분을 보존한다. 인증 실패·모델 장애 때 예시 답변을 생성하지 않는다.
