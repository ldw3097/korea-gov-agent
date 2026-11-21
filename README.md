# K-gov-agent

공공부문 기관의 내부망에서 업무를 맡기고, 실행 중에 개입하고, 결과물을 검토하는 업무 공간을 목표로 합니다. 이 브랜치는 Rust로 새로 시작하는 개발 기반입니다. [제품 방향](docs/PRODUCT_DIRECTION.md)

## 로컬 실행

Rust 1.93 이상이 필요합니다. 기본 주소는 `127.0.0.1:3000`입니다.

```sh
cargo run --locked
```

다른 터미널에서 서버 상태를 확인합니다.

```sh
curl --fail -i http://127.0.0.1:3000/health
```

Axum 서버는 루프백에서 헬스체크를 제공합니다. 화면, 업무 API, 앱의 JWT 검증과 관리자 승인은 구현 예정입니다.

## Spec Kit

프로젝트의 Codex 스킬은 `.agents/skills/`에, 템플릿과 스크립트는 `.specify/`에 있습니다. Codex에서 `$speckit-constitution`과 `$speckit-specify`를 사용할 수 있습니다.

새 작업 사본에서 CLI가 필요하면 Python 3.11 이상으로 프로젝트 전용 환경을 만듭니다.

```sh
python3 -m venv .venv-speckit
.venv-speckit/bin/python -m pip install 'specify-cli==1.4.3'
.venv-speckit/bin/specify version
```

## 배포 설정

OCI ARM64에서 사용하는 Docker 빌드와 Cloudflare Tunnel 설정을 보관합니다. 앱 인증 구현과 검증을 마친 뒤 시연 전환 절차를 따릅니다. [배포 절차](docs/DEPLOYMENT.md) · [인증 기준](docs/AUTH.md)
