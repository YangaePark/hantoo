# Synology 배포

이 배포 방식은 GitHub에서 코드를 한 번 클론한 뒤, Synology Container Manager가 로컬 폴더를 빌드하게 합니다. Docker의 원격 GitHub build context는 private 저장소 인증을 못 받는 경우가 있어 이 방식이 더 안정적입니다.

## DSM Container Manager

1. DSM 패키지 센터에서 `Container Manager`를 설치합니다.
2. File Station에서 `/volume1/docker/hantoo/state` 폴더를 만듭니다.
3. SSH로 NAS에 접속해 GitHub 저장소를 받습니다.

```bash
mkdir -p /volume1/docker/hantoo
cd /volume1/docker/hantoo
git clone https://github.com/YangaePark/hantoo.git app
```

private 저장소라 인증이 필요하면 GitHub Personal Access Token 또는 SSH deploy key를 사용합니다.

4. Container Manager > Project > Create를 엽니다.
5. Project name은 `hantoo`로 입력합니다.
6. Path는 `/volume1/docker/hantoo`를 선택합니다.
7. Source는 `Create docker-compose.yml`을 선택합니다.
8. 아래 내용을 붙여넣고 Deploy를 누릅니다.

```yaml
services:
  hantoo:
    container_name: hantoo-trader
    build:
      context: ./app
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      TZ: Asia/Seoul
      SEMIBOT_STATE_ROOT: /app/state
      PYTHONUNBUFFERED: "1"
    volumes:
      - /volume1/docker/hantoo/state:/app/state
```

접속 주소:

```text
http://<NAS-IP>:8000
```

## 저장 위치

운영 데이터는 NAS에 남습니다.

- `/volume1/docker/hantoo/state/config/kis.local.json`
- `/volume1/docker/hantoo/state/config/live.local.json`
- `/volume1/docker/hantoo/state/reports/live_trading/`

앱 코드는 GitHub에서 다시 빌드해도 위 파일들은 유지됩니다.

## 업데이트

GitHub `main`에 새 커밋을 올린 뒤 Container Manager에서 `hantoo` 프로젝트를 중지하고 다시 Build/Deploy 하면 최신 코드가 반영됩니다.

SSH로 업데이트할 때는 아래처럼 먼저 코드를 당겨옵니다.

```bash
cd /volume1/docker/hantoo/app
git pull
```

## 접근 권장

App Secret과 Access Token이 저장되는 앱입니다. 공유기 포트포워딩으로 공개 인터넷에 직접 열기보다 Tailscale이나 VPN으로 NAS에 접속한 뒤 `http://<NAS-IP>:8000`으로 여는 방식을 권장합니다.
