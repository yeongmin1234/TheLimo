# Delivery Dashboard Code Review

작성일: 2026-05-04

## 1. 전체 구조 해석

- FastAPI 앱은 `app/main.py`에서 생성되며, 기본 `APP_ROOT_PATH`는 `/delivery`입니다.
- 내부 앱 실행 포트는 `deploy/limo.service` 기준 `8000`입니다.
- 외부 노출은 nginx가 `8001` 포트에서 `/delivery/` 경로만 받아 `http://127.0.0.1:8000/`으로 프록시하는 구조를 목표로 합니다.
- 템플릿과 JavaScript는 `/delivery` 하위 경로에서 동작하도록 `root_path`와 `data-root-path`를 사용합니다.
- DB는 기존 SCM DB(`limotech_scm_v3`)를 조회하고, 배송예약용 `reservation_info` 테이블을 앱 시작 시 확인/생성합니다.

## 2. SCM 영향 가능성

- 현재 앱 코드 자체는 SCM 웹 포트인 `80`, SCM 본체 포트인 `8080`을 직접 사용하지 않습니다.
- `deploy/install_limo_service.sh`와 `deploy/install_nginx_proxy.sh`는 `80`, `8080`을 사용하려고 하면 중단되도록 보호 로직이 들어가 있습니다.
- `deploy/install_nginx_proxy.sh`는 기존 nginx가 비활성 상태면 자동 시작하지 않도록 되어 있어, SCM에 영향을 줄 가능성을 낮춥니다.
- 다만 `deploy/install_httpd_proxy.sh`는 httpd 설정 파일을 만들고 `systemctl reload httpd || systemctl restart httpd`를 실행합니다. 포트 보호는 있지만, SCM이 httpd/Apache에 의존하는 환경에서는 실행 자체가 위험할 수 있습니다.
- 실제 서버에서 적용한 "배송예약 전용 별도 nginx 인스턴스" 설정은 현재 Git 코드에 완전히 자동화되어 있지 않습니다. 서버 수동 설정과 Git 코드 사이에 차이가 있습니다.

## 3. `/delivery` 경로 처리 점검

- `app = FastAPI(lifespan=lifespan, root_path=APP_ROOT_PATH)`로 `/delivery` 기준 프록시 구성을 지원합니다.
- `base.html`의 CSS/JS 경로는 `{{ root_path }}/static/...` 형태라 `/delivery/static/...`으로 정상 생성됩니다.
- 내비게이션 링크도 `{{ root_path }}/progress`, `{{ root_path }}/completed`처럼 생성됩니다.
- JavaScript API 호출은 `appUrl(...)` 헬퍼를 통해 `/delivery/api/...`로 호출됩니다.
- nginx 설정의 `location /delivery/`와 `proxy_pass http://127.0.0.1:8000/;` 조합은 `/delivery/abc`를 내부 `/abc`로 전달하므로 trailing slash 처리도 적절합니다.
- 주의: FastAPI 앱을 `http://192.168.222.110:8000/`으로 직접 열면 화면은 뜰 수 있지만, 링크들이 `/delivery/...`로 생성됩니다. 운영 접속 주소는 `http://192.168.222.110:8001/delivery/`로 고정하는 것이 맞습니다.

## 4. nginx/포트 설정 위험 요소

- `deploy/install_nginx_proxy.sh`의 기본값은 `PUBLIC_PORT=8001`, `PUBLIC_PATH=/delivery`라 요구사항과 일치합니다.
- `80`, `8080` 보호 로직이 있어 기본적인 SCM 포트 충돌은 방지됩니다.
- 기존 nginx 설정을 수정하지 않고 `/etc/nginx/conf.d/thelimo-dashboard-8001.conf`를 새로 생성하는 방식입니다.
- 그러나 현재 서버에서는 기본 nginx 서비스가 `failed` 상태였고, 실제로는 별도 nginx 설정 파일(`/etc/nginx/delivery-dashboard-nginx.conf`)을 만들어 독립 인스턴스로 실행했습니다. 이 방식은 Git의 `install_nginx_proxy.sh`와 다릅니다.
- `install_nginx_proxy.sh`는 `systemctl reload nginx`를 사용하므로, 기본 nginx 서비스가 SCM과 연결된 환경에서는 실행 전 반드시 영향도를 확인해야 합니다.
- iptables에 `8001` 허용 규칙을 추가한 것은 SCM 포트와 충돌하지 않습니다. 다만 배송예약 대시보드가 네트워크에서 접근 가능해지므로 인증/접근 제한은 별도 검토가 필요합니다.

## 5. 발견된 문제점

1. `deploy/install_httpd_proxy.sh`는 운영 환경에서 실행 금지에 가깝습니다.
   - httpd를 설치하거나 reload/restart할 수 있어 SCM에 부담을 줄 수 있습니다.
   - 배송예약은 nginx `8001` 경로로 분리했으므로 httpd 프록시 스크립트는 삭제하거나 `DEPRECATED`로 명시하는 것이 안전합니다.

2. 서버 수동 설정이 Git에 완전히 반영되어 있지 않습니다.
   - 실제 서버는 별도 nginx 인스턴스 방식으로 `8001`을 열었습니다.
   - Git에는 그 전용 nginx master config와 systemd unit이 없습니다.
   - 서버 재부팅 후 별도 nginx 인스턴스가 자동 복구되지 않을 수 있습니다.

3. 인증/접근 제어가 없습니다.
   - `8001/delivery/`가 열리면 같은 네트워크에서 대시보드 접근이 가능합니다.
   - 운송장번호 저장, 예약일 저장 등 DB 쓰기 API도 노출됩니다.

4. DB 변경 API는 CSRF 보호가 없습니다.
   - 사내망 전용이라도 브라우저 기반 POST 요청을 막는 장치가 없습니다.
   - 최소한 사내 IP 제한, Basic Auth, 간단한 로그인 중 하나는 권장됩니다.

5. `APP_ROOT_PATH` 기본값이 `/delivery`로 고정되어 있습니다.
   - 운영 목표에는 맞지만 로컬 개발이나 직접 `8000` 접속에서는 링크가 어색해질 수 있습니다.
   - 로컬 개발 시에는 `APP_ROOT_PATH=` 또는 별도 `.env` 값으로 조정하는 방법을 문서화하면 좋습니다.

6. 캐시는 프로세스 메모리 기반입니다.
   - 단일 uvicorn 프로세스에서는 괜찮지만, 여러 worker를 쓰면 캐시 일관성이 깨질 수 있습니다.
   - 현재 서비스 파일은 단일 프로세스라 큰 문제는 아닙니다.

## 6. 권장 수정사항

- `deploy/install_httpd_proxy.sh`는 사용하지 않도록 파일 상단에 강한 경고를 추가하거나 제거하는 것을 권장합니다.
- 실제 서버에서 사용한 별도 nginx 인스턴스 구성을 Git에 문서화하거나 systemd unit으로 관리하는 것이 좋습니다.
- 배송예약 대시보드에 최소한의 접근 제한을 추가하는 것을 권장합니다.
  - 예: nginx Basic Auth, 사내 IP allowlist, 간단한 앱 로그인.
- 운영 접속 주소는 하나로 고정합니다.
  - 권장: `http://192.168.222.110:8001/delivery/`
  - 직접 `:8000` 접속은 내부 점검용으로만 사용합니다.
- 퇴근/재부팅 대비를 위해 `8001` nginx 인스턴스 자동 시작 방식을 정리해야 합니다.
- 앞으로 배포 작업 전에는 아래 3가지를 먼저 확인하는 절차를 유지하는 것이 안전합니다.
  - SCM 기본 주소 `http://192.168.222.110/` 정상 여부
  - 배송예약 내부 앱 `127.0.0.1:8000` 정상 여부
  - 배송예약 외부 주소 `192.168.222.110:8001/delivery/` 정상 여부

## 결론

현재 코드 방향은 SCM과 배송예약을 분리한다는 목표에 대체로 부합합니다. 특히 `80`, `8080` 보호와 `/delivery` 경로 처리는 핵심 요구사항을 만족합니다.

가장 큰 남은 리스크는 SCM 충돌보다 운영 관리 측면입니다. 실제 서버의 별도 nginx 인스턴스 구성이 Git에 완전히 들어와 있지 않고, 배송예약 대시보드가 인증 없이 열려 있다는 점을 다음 개선 대상으로 보는 것이 좋습니다.
