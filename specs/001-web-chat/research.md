# 설계 결정과 근거

## 1. Google 신원과 앱 사용 권한

**결정** 시연에서는 기존 Cloudflare Access의 Google IdP와 Protect with Access를 유지한다. Rust 앱은 설정된 팀의 공개키로 앱 토큰을 검증한 뒤 계정을 만든다. 계정의 승인 여부는 요청 시 기관 DB에서 읽는다. 대기·채팅 화면의 로그아웃은 앱 호스트의 `/cdn-cgi/access/logout`으로 브라우저를 이동시킨다.

**근거** Access의 서명은 로그인한 신원을 제공한다. 관리자 승인과 대화 소유권은 앱 데이터이며, 관리자의 승인 취소를 현재 로그인에도 반영해야 한다. 로그아웃 검증에서는 보호된 주소에 다시 접근해 Access 인증 절차가 재개되는지 확인한다. Google 계정의 비밀번호 재입력 여부는 IdP 세션에 따라 달라진다. [Access 토큰 검증](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/) · [Access 로그아웃](https://developers.cloudflare.com/cloudflare-one/access-controls/access-settings/session-management/#log-out-as-a-user)

**검토한 대안** 앱에서 직접 Google OAuth를 처리하면 기존 인증 경계가 바뀐다. 승인 상태를 로그인 시점에만 캐싱하면 취소 직후의 차단 기준을 만족하지 못한다. 기관별 신원 제공자는 검증된 발급자·사용자 식별자·이메일을 반환하는 동일한 경계에 연결한다.

## 2. 단일 서버와 SQLite

**결정** 승인 이력, 대화, 질문과 답변 상태를 기관별 SQLite에 저장한다. 연결마다 외래키 검사를 활성화하고 WAL, 제한된 잠금 대기, 짧은 쓰기 트랜잭션을 사용한다. 모델 호출과 공개키 조회는 트랜잭션 밖에서 수행한다.

**근거** 단일 앱 인스턴스에서 계정 최초 등록, 승인 전이, 중복 전송 방지를 원자적으로 처리할 수 있다. DB와 WAL 파일은 같은 호스트의 쓰기 가능한 볼륨에 둔다. 요청 단위 비동기 DB 접근으로 현재 서버의 이벤트 루프가 막히는 것을 피한다. [SQLite 트랜잭션](https://sqlite.org/lang_transaction.html) · [WAL](https://sqlite.org/wal.html) · [외래키](https://sqlite.org/foreignkeys.html) · [Docker 볼륨](https://docs.docker.com/engine/storage/volumes/)

**검토한 대안** 메모리만 사용하면 프로세스 교체 시 승인 취소 기록이 사라진다. 별도 DB 서버는 복수 앱 인스턴스가 필요한 단계에서 검토한다.

## 3. 실제 응답과 중지

**결정** 서버에서 구성된 모델에 대화 맥락을 보내고 공개 답변 텍스트 조각만 반영한다. 브라우저는 질문을 한 번 제출한 뒤 동일 출처의 GET 이벤트 스트림을 구독한다. 스트림 개설 전 도착한 글도 현재 스냅샷에 포함한다.

**근거** DeepInfra의 호환 API는 스트리밍 델타와 종료 신호를 제공한다. 제공자별 파싱은 모델 어댑터 안에 둔다. 서버에서 확정한 종료 상태를 기준으로 표시해야 중지와 마지막 글 도착이 겹쳐도 화면과 저장된 답변이 일치한다. [DeepInfra 스트리밍 예시](https://deepinfra.com/openai/gpt-oss-120b/api) · [브라우저 이벤트 스트림](https://html.spec.whatwg.org/multipage/server-sent-events.html)

**검토한 대안** 브라우저에서 모델을 직접 호출하면 기관 자격증명과 대화 소유권 검사를 서버 경계 안에 유지하기 어렵다. 탭에서 읽기를 중단하는 동작만으로는 원격 연산 종료를 확인할 수 없다. 모델 연결을 취소하고 늦게 도착한 글은 적용하지 않는다.

## 4. 첫 화면의 범위

**결정** 같은 Rust 서비스에서 로컬 HTML·CSS·JavaScript를 제공한다. 관리자는 신청자 목록과 상태 변경 화면을, 직원은 승인 상태에 따라 대기 화면이나 한 대화 화면을 사용한다. 긴 연결이 끊겨도 열린 페이지에서 현재 답변 상태를 다시 조회할 수 있다.

**근거** 이번 명세에는 대화 목록, 파일, 결과물 패널이 없다. 정적 자산을 빌드에 포함하면 외부 CDN 없이 실행할 수 있다. 별도 프런트엔드 서비스와 영속 작업 큐는 이번 구현 범위를 넘는다. [기능 명세](spec.md) · [제품 방향](../../docs/PRODUCT_DIRECTION.md)
