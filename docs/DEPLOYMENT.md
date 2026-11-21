# OCI·Cloudflare 시연 배포

현재 시연은 OCI ARM64의 Docker Compose에서 실행됩니다. 이 Rust 브랜치는 기존 Cloudflare 구성을 보존한 개발 시작점입니다. [앱 인증 기준](AUTH.md)을 구현하고 검증한 뒤 시연 환경을 전환합니다.

## 로컬 컨테이너 확인

기본 Compose 파일은 `web`만 실행합니다. 컨테이너는 내부 네트워크의 포트 3000을 사용하고, 호스트 포트는 게시하지 않습니다.

```sh
docker compose -p lh-agent-rust up --build -d --wait
docker compose -p lh-agent-rust exec -T web curl --fail -i http://127.0.0.1:3000/health
docker compose -p lh-agent-rust down
```

## 기존 Cloudflare 구성 확인

1. Cloudflare Zero Trust 대시보드에서 기존 Tunnel에 연결된 시연 호스트와 라우트의 원본 주소를 확인합니다. Compose 네트워크에서 Rust 앱으로 연결할 때 원본 주소는 `http://web:3000`입니다.
2. 같은 호스트의 기존 Access 앱, audience, 전용 Google IdP 하나를 허용하는 정책, Tunnel의 `Protect with Access` 설정을 확인합니다. Bypass 정책은 추가하지 않습니다.
3. 시연 호스트를 전환하기 전에 별도 환경에서 인증·승인 흐름을 검증합니다. 기존 Tunnel 토큰으로 같은 Tunnel에 새 환경을 병렬 연결하면 시연 호스트의 요청이 그 환경에도 들어갈 수 있으므로 별도 검증용 Tunnel과 Access 앱을 사용합니다.

[Cloudflare Tunnel 라우팅](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/)

## 서버 설정과 배포

기존 작업 폴더의 `.private/operator.json`에서 SSH 별칭과 시연 호스트를 확인할 수 있습니다. Access 설정 스냅샷은 `.private/cloudflare/`에, 기존 배포·복구 기록은 `.private/deployment-history/`에 있습니다. 기존 시연 서버의 설정 원본은 `~/lh-agent-poc/.env`입니다. 기존 DB·백업·비밀값은 각 보관 위치에서 관리합니다.

Rust용 서버 작업 폴더는 `~/lh-agent-rust`를 사용하고, 승인된 배포 환경의 설정값을 그 폴더의 `.env`(0600)에 구성합니다. [변수 예시](../.env.example)

| 항목 | 용도 |
| --- | --- |
| `PUBLIC_ORIGIN` | Access 앱의 공개 HTTPS 주소 |
| `CF_ACCESS_ISSUER` | Cloudflare Access 팀의 HTTPS 주소 |
| `CF_ACCESS_AUD` | Access 앱 audience |
| `ADMIN_EMAIL` | 앱 초기 관리자 이메일 |
| `CLOUDFLARED_IMAGE` | 해당 서버에서 검증한 cloudflared 이미지와 digest |
| `TUNNEL_TOKEN` | 배포 대상 Tunnel의 커넥터 토큰. `cloudflared`에만 주입 |

커밋된 빌드 소스만 서버로 보냅니다. 아래 `poc-ssh-alias`는 실제 SSH 별칭으로 바꿉니다.

```sh
git archive --format=tar.gz HEAD .dockerignore Cargo.toml Cargo.lock compose.yaml compose.tunnel.yaml infra/Dockerfile src/ |
  ssh poc-ssh-alias 'umask 077; mkdir -p "$HOME/lh-agent-rust" && tar -xzf - -C "$HOME/lh-agent-rust"'
```

배포가 승인된 환경의 서버 작업 폴더에서 두 Compose 파일을 함께 사용합니다.

```sh
sudo docker compose -p lh-agent-rust -f compose.yaml -f compose.tunnel.yaml --profile tunnel config --quiet
sudo docker compose -p lh-agent-rust -f compose.yaml -f compose.tunnel.yaml --profile tunnel up --build -d --wait
sudo docker compose -p lh-agent-rust -f compose.yaml -f compose.tunnel.yaml --profile tunnel ps
```

시연 전환 전 ARM64 빌드와 컨테이너 내부 헬스체크, 외부 익명 요청의 Access 로그인 이동, Google 로그인 후 앱 승인 대기, 승인 후 접근, 승인 취소 후 차단을 확인합니다.
