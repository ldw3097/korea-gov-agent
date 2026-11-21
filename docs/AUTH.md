# K-gov-agent PoC 로그인과 사용 승인

기준일: 2026-11-15 (Asia/Seoul). 사용자 확정 구성은 **Cloudflare Access의 Google 로그인 + 앱의 관리자 사용 승인**이다. 사전 사용자 등록·부서 배정은 없다. 이 문서가 이전 직접 Google OAuth·부서 기반 제안보다 우선한다.

## 운영 흐름

Google 로그인 → Cloudflare Access → 앱에서 서명된 신원 검증 → 계정 자동 등록·승인 대기 → 관리자 승인 → 업무 사용.

Cloudflare는 Google 신원을 확인하고 앱은 사용 권한을 결정한다. Google 인증만으로 업무 사용이 승인되지 않는다. 신규 계정은 pending이고, 서버 ADMIN_EMAIL에 해당하는 최초 관리자만 approved로 등록한다. 첫 가입자에게 관리자 권한을 주지 않는다. 부서나 사용자 이메일 목록을 미리 배정하지 않는다.

승인 전에는 본인의 상태 확인·로그아웃만 가능하다. 관리자가 approved로 바꾸면 업무 API를 사용할 수 있다. 거절·승인 취소는 rejected로 바꾸며 매 요청에서 검사한다. 아직 유효한 Access 토큰이나 재로그인으로 앱의 거절 상태를 되돌릴 수 없다. 정지된 계정도 업무 접근이 차단된다.

## Cloudflare 설정

- 대상 호스트는 로컬 운영 설정의 `access_hostname`에 기록한다.
- 전용 Google 제공자: LH PoC Google. 사용자 제공 OAuth 자격증명으로 생성했다.
- 대상 앱의 허용 IdP는 위 Google 하나다. Google 로그인 방법을 조건으로 하는 전용 Allow 정책을 연결했다.
- Bypass 정책은 없다. Tunnel의 Protect with Access를 유지했다. 기존 앱 ID와 audience를 유지했다.
- 이전 앱 세션을 revoke해 새 Google 로그인을 요구했다. 다른 앱 정책과 전역 로그인 제공자는 수정하지 않았다.
- Google OAuth redirect URI는 Access 팀 도메인의 `/cdn-cgi/access/callback`을 사용한다.

앱 세션 쿠키·Google code exchange는 Cloudflare가 처리한다. 직접 Google OAuth 구현은 대체 모드 코드로만 남아 있으며 운영에서는 사용하지 않는다. 앱의 직접 Google client ID·secret 환경설정은 제거했다.

## 앱의 신원과 승인 검사

Cf-Access-Jwt-Assertion의 RS256 서명·issuer·audience·exp/iat·subject·이메일 형식을 검증한다. 이메일 헤더나 브라우저가 보낸 ID·역할은 인증에 사용하지 않는다. JWT는 설정된 팀의 공개키로 검증한다. 컨테이너 loopback의 GET /health만 인증 검사에서 제외한다.

계정 ID는 issuer+subject의 해시이며, 이메일은 표시·초기 관리자 확인용이다. Access 계정은 access_accounts에 승인 상태·검토자·시각을 저장한다. 같은 issuer+subject의 기존 Access 계정은 기존 ID와 자료를 유지한다. 직접 Google/local 계정과 이메일만으로 자동 병합하지 않는다. Google email과 동일한 다른 subject는 별도 승인 대상이다.

계정별 대화·파일 소유권을 유지한다. 관리자는 승인을 관리하지만 다른 사용자의 업무 내용을 자동 열람하지 않는다. 부서 공유·부서 목록 API는 없다. 기존 부서 컬럼은 저장 구조 호환값으로만 남으며 조직 배정이나 접근 권한에 사용하지 않는다.

## 설정·비밀 관리

서버 ~/lh-agent-poc/.env에는 AUTH_MODE=cloudflare, PUBLIC_ORIGIN, CF_ACCESS_ISSUER, CF_ACCESS_AUD, ADMIN_EMAIL을 설정한다. Google 클라이언트 비밀값과 Cloudflare 관리 API 토큰은 앱 이미지·브라우저·업무 worker에 전달하지 않는다.

Cloudflare 관리 토큰과 Google OAuth 자격증명은 로컬 `.private/operator.json` (0600)에서 관리한다. `scripts/cloudflare_access.py`는 이 파일의 대상 호스트를 사용한다. Access 앱·정책·IdP 스냅샷과 식별자는 `.private/cloudflare/`에 보관한다. 운영 설정 파일과 스냅샷은 Git에서 제외한다. [설정 절차](DEPLOYMENT.md)

## 검증과 제한

- API로 Google-only Allow, Bypass 없음, 기존 audience 유지를 검증했다.
- 외부 Access 로그인 응답에 Google 로그인 링크와 Google OAuth 경로가 있음을 확인했다.
- 새 앱의 내부 health 200, 서명 없는 신원 401, 승인 테이블 생성을 확인했다.
- 전체 테스트 49개 통과: 서명·클레임 변조, 승인 전 차단, 관리자 승인·거절, 거절 후 유효 JWT 재사용, 동일 이메일의 다른 subject, 대화·파일 격리 등.
- 사용자가 실제 Google 로그인 후 업무 화면 진입을 확인했다. 다른 실계정의 승인 대기·승인 취소는 합성 토큰 시험으로 검증했으며 실제 참여자 파일럿에서 추가 확인한다.

공공부문 기관 내부망 배포에서는 각 기관의 인증 체계에 연결할 수 있도록 설계한다. 현재 시연 PoC는 Cloudflare Access의 Google 로그인을 사용한다.

참고: [Cloudflare Google 연동](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/google/), [JWT 검증](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/).
