# Synology 배포

공개 GitHub 저장소를 Docker build context로 바로 사용합니다. NAS에 소스 코드를 따로 클론하지 않아도 Container Manager가 GitHub에서 코드를 받아 이미지를 빌드합니다.

## DSM Container Manager

1. DSM 패키지 센터에서 `Container Manager`를 설치합니다.
2. File Station에서 `/volume1/docker/hantoo/state` 폴더를 만듭니다.
3. SSH로 NAS에 접속해 Compose 파일을 바로 받습니다.

```bash
mkdir -p /volume1/docker/hantoo/state
cd /volume1/docker/hantoo
curl -L -o docker-compose.yml https://raw.githubusercontent.com/YangaePark/hantoo/main/deploy/synology/docker-compose.yml
```

4. Container Manager > Project > Create를 엽니다.
5. Project name은 `hantoo`로 입력합니다.
6. Path는 `/volume1/docker/hantoo`를 선택합니다.
7. Source는 `Existing docker-compose.yml` 또는 기존 Compose 파일 선택을 사용합니다.
8. Deploy를 누릅니다.

UI에서 직접 붙여넣고 싶으면 Source를 `Create docker-compose.yml`로 선택하고 아래 내용을 넣어도 됩니다.

```yaml
services:
  hantoo:
    container_name: hantoo-trader
    build:
      context: https://github.com/YangaePark/hantoo.git#main
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
- `/volume1/docker/hantoo/state/config/kis.overseas.local.json`
- `/volume1/docker/hantoo/state/config/live.local.json`
- `/volume1/docker/hantoo/state/config/live.overseas.local.json`
- `/volume1/docker/hantoo/state/reports/live_trading/`
- `/volume1/docker/hantoo/state/reports/live_trading_overseas/`

앱 코드는 GitHub에서 매번 새로 받아 빌드해도 위 파일들은 유지됩니다.

## 업데이트

GitHub `main`에 새 커밋이 올라간 뒤 아래 스크립트를 실행하면 최신 코드로 다시 빌드하고 컨테이너를 재시작합니다.

```bash
sudo mkdir -p /volume1/docker/hantoo
cd /volume1/docker/hantoo
sudo curl -fsSL -o restart.sh https://raw.githubusercontent.com/YangaePark/hantoo/main/deploy/synology/restart.sh
sudo chmod +x restart.sh
sudo ./restart.sh
```

프로젝트 경로가 다르면 경로를 인자로 넘길 수 있습니다.

```bash
sudo ./restart.sh /volume2/docker/hantoo
```

Container Manager UI를 쓴다면 `hantoo` 프로젝트를 중지한 뒤 다시 Build/Deploy 해도 최신 코드가 반영됩니다.

## 접근 권장

App Secret과 Access Token이 저장되는 앱입니다. 공유기 포트포워딩으로 공개 인터넷에 직접 열기보다 Tailscale이나 VPN으로 NAS에 접속한 뒤 `http://<NAS-IP>:8000`으로 여는 방식을 권장합니다.
