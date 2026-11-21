# PoC 로그인과 사용 승인

Google 로그인 → Cloudflare Access → 앱에서 서명된 신원 검증 → 계정 자동 등록·승인 대기 → 관리자 승인 → 업무 사용.

기존 Cloudflare 설정을 재사용하기 위한 기준입니다. Rust 시작점에는 앱의 JWT 검증·계정 등록·승인 처리가 아직 구현돼 있지 않습니다.

## Cloudflare Access 설정

- 시연 호스트에 연결된 기존 self-hosted Access 앱과 audience를 유지합니다.
- 로그인 제공자는 기존 전용 Google IdP 한 개로 제한합니다. Google 로그인 방법을 조건으로 하는 Allow 정책을 사용합니다.
- Tunnel에 `Protect with Access`를 적용하고 팀 이름과 허용 audience가 해당 Access 앱과 일치하는지 확인합니다. Bypass 정책은 추가하지 않습니다.
- Google OAuth 리디렉션에는 Access 팀 도메인의 `/cdn-cgi/access/callback`을 사용합니다. Google 인증과 세션 처리는 Cloudflare Access에서 담당합니다.
- Cloudflare 관리 토큰과 Google OAuth 비밀값은 앱과 Tunnel의 런타임 환경에 포함하지 않습니다.

[Google IdP 설정](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/google/)

## Rust 앱 구현 기준

- `Cf-Access-Jwt-Assertion`의 RS256 서명을 설정된 Access 팀 공개키로 검증합니다. `CF_ACCESS_ISSUER`와 `CF_ACCESS_AUD`를 기준으로 issuer와 audience를 확인하고, 만료·발행 시각·subject·이메일을 검증합니다. `nbf`가 있으면 적용합니다. 계정 식별에는 검증된 issuer와 subject를 사용합니다.
- 신규 계정은 기본 `pending`입니다. `ADMIN_EMAIL`에 해당하는 최초 관리자만 `approved`로 초기 등록합니다. 미승인 사용자는 본인 승인 상태 확인과 로그아웃만 가능합니다. 거절·승인 취소·정지는 유효한 Access 세션이 있어도 매 요청에서 적용합니다.
- 계정별 대화·파일·결과물의 소유권을 서버에서 검사합니다. 관리자 승인 권한으로 다른 계정의 업무 데이터 열람 권한을 얻을 수 없습니다. 사전 사용자 지정·부서 배정·부서 공유는 구현하지 않습니다.
- 인증 검사의 예외는 컨테이너 루프백의 헬스체크로 제한합니다.

[Cloudflare JWT 검증](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/)
