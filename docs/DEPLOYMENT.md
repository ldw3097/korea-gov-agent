# K-gov-agent 시연 배포

현재 PoC 시연 환경은 OCI ARM64 서버에서 실행한다. 사용자는 Cloudflare Access의 Google 로그인과 앱 관리자 승인을 거쳐 접속한다. Protect with Access와 Google-only Allow 정책을 유지한다. 시연 주소와 SSH 대상은 운영 설정에서 확인한다. 기관별 내부망 배포 목표는 [제품 방향](PRODUCT_DIRECTION.md)을 참고한다.

## 비밀 설정

시연 서버에서는 `~/lh-agent-poc/.env` (0600)를 설정 원본으로 사용한다. `PUBLIC_ORIGIN`, Access issuer·audience, 초기 관리자 이메일, 모델 키, Tunnel 토큰과 검증한 cloudflared 이미지 digest를 설정한다. Compose가 웹 서비스에는 모델 키를, cloudflared에는 Tunnel 토큰을 주입한다.

로컬 운영 도구는 `.private/operator.json` (0600)을 읽는다. 기존 시연 환경 설정은 이 파일에 통합돼 있다. 새 작업 복사본에 설정할 때는 `.private/`를 0700으로 만들고 아래 자리표시자를 교체한다. `create-google` 작업이 필요한 경우에만 Google 웹 OAuth 자격증명을 넣는다.

```json
{
  "ssh_target": "poc-ssh-alias",
  "access_hostname": "poc.example.com",
  "cloudflare_api_token": "",
  "google_oauth": {
    "web": {
      "client_id": "",
      "client_secret": ""
    }
  }
}
```

Access 관리자 토큰과 Google OAuth 자격증명은 로컬 운영 도구에서 사용한다. Google 로그인은 Cloudflare의 IdP에서 처리한다. 서버의 `.env`, 로컬 운영 설정, Access 스냅샷, 대화·파일·DB 백업은 Git과 배포 소스 번들에서 제외한다.

## 상태 확인과 업데이트

업데이트 전 DB 백업과 스키마 호환성을 확인한다. 웹 앱은 SQLite 볼륨과 API 프로세스 하나를 사용한다. 실행기 두 슬롯은 이 프로세스에 내장돼 있다. [실행과 복구 동작](WORK.md)

아래 `poc-ssh-alias`는 `.private/operator.json`의 `ssh_target`으로 바꾼다.

```sh
ssh poc-ssh-alias 'cd "$HOME/lh-agent-poc" && sudo docker compose -p lh-agent-poc --profile tunnel ps'
.venv/bin/python scripts/upload.py
ssh poc-ssh-alias 'cd "$HOME/lh-agent-poc" && sudo docker compose -p lh-agent-poc up --build -d web'
```

정상 상태는 `web` healthy, `cloudflared` running이다. 컨테이너 내부 loopback의 `/health`는 200을 반환한다. 외부 익명 요청은 Access 로그인으로 이동한다.

## 복구 기록

기존 시연 환경의 구체적인 이미지·백업 경로와 전환 기록은 로컬 `.private/deployment-history/`에 보관한다. 개인용 서비스의 보존 자료와 복구 기록은 승인된 복구에만 사용한다. 개인 대화·기억은 시연 DB로 이관하지 않았다.
