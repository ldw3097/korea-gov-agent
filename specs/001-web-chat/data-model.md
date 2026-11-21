# 데이터 모델

기관 배포 한 곳에 DB 하나를 둔다. UTC 시각과 외부에 노출 가능한 불투명 ID를 사용한다. 이메일은 표시와 최초 관리자 매칭에 사용하고, 계정 소유권은 검증된 발급자와 subject 쌍으로 식별한다.

| 엔터티 | 주요 필드 | 관계와 제약 |
| --- | --- | --- |
| Account | id, issuer, subject, email, role, status, version, created_at, reviewed_at, reviewed_by | (issuer, subject) 유일. 역할은 employee/admin. status는 pending/approved/rejected/suspended. reviewed_by는 처리한 관리자 |
| ApprovalDecision | id, account_id, actor_id, action, previous_status, next_status, decided_at | 승인·거절·취소의 이력. 대상 상태 변경과 같은 트랜잭션에 기록 |
| Conversation | id, owner_id, created_at | 단일 소유 계정과 연결. 읽기·전송·구독·중지에 같은 소유권 적용 |
| Turn | id, conversation_id, request_id, ordinal, user_text, assistant_text, state, revision, error_code, created_at, ended_at | 질문과 해당 답변의 한 쌍. (conversation_id, request_id) 및 (conversation_id, ordinal) 각각 유일. 활성 상태에 한해 conversation_id 유일 |

## 계정 등록과 승인

1. 검증된 신원으로 계정을 조회한다. 신규 직원은 pending으로 생성한다. 동일 신원의 동시 요청은 유일 제약으로 같은 계정을 얻는다. 재로그인 시 기존 역할·승인 상태를 유지한다.
2. 설정된 관리자 이메일에 대응하는 검증된 신원이 처음 등록될 때 한 트랜잭션에서 최초 관리자 자리를 확보하고 approved/admin으로 생성한다. 관리자 한 명에 대한 유일 제약을 두며 같은 이메일의 다른 subject는 직원으로 취급한다.
3. 승인된 관리자는 대기 직원을 승인(pending → approved)하거나 거절(pending → rejected)한다. 승인 취소(approved → rejected)는 이력의 action으로 거절과 구분한다. suspended는 차단 상태로 인식한다. 이번 관리 화면은 직원 승인·거절·취소만 제공한다.
4. 변경자의 관리자 권한, 대상의 현재 상태와 version을 쓰기 트랜잭션 안에서 검사한다. 경쟁하는 변경 중 하나만 성공한다. 클라이언트는 충돌 시 새 목록을 읽는다.

## 대화와 실행

- 전송 시 승인·소유권을 검사하고 유효한 텍스트, 순번, 요청 ID와 queued 상태를 함께 저장한다. 같은 ID·같은 본문은 기존 질문을 반환한다. 다른 본문에 같은 ID를 쓰거나 이전 답변 생성 중 새 질문을 보내면 충돌이다.
- 실행은 queued → streaming → completed로 진행한다. queued 또는 streaming에서 stopped나 failed로 종료할 수도 있다. 첫 공개 텍스트를 기록하며 streaming으로 바꾼다. 모델의 정상 종료와 실제 본문을 모두 확인한 뒤 completed로 기록한다.
- 텍스트 추가 시 활성 상태를 조건으로 걸고 revision을 올린다. 중지·실패는 누적 본문을 유지하며 종료 시각을 기록한다. 최초 종료 전이만 성공한다. 종료 후 도착한 모델 조각은 폐기한다.
- 후속 요청은 서버에 저장된 같은 대화의 완료된 질문·답변을 순서대로 사용한다. 중지·실패한 쌍은 화면에 남기되 모델 맥락에서는 제외한다. 모델 한도에 맞춰 가장 오래된 완료 쌍부터 제외하고, 현재 질문 자체가 한도를 넘으면 사용자에게 오류를 돌려준다.
- 단일 인스턴스 재기동 시 새 요청을 받기 전에 남아 있는 활성 질문을 failed로 전환한다. 서버가 이미 수락한 질문을 자동으로 모델에 재전송하지 않는다. 새 페이지에서는 새 대화를 시작하며 대화 목록이나 기록 복원 화면은 이번 범위 밖이다.
- 본문·인증 토큰·모델 키는 운영 로그에 쓰지 않는다. 영속 DB의 보관·삭제 주기는 기관의 운영 정책을 따른다.
