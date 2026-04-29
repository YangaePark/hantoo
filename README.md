# Hantoo 자동매매 대시보드

한국투자증권 Open API를 이용해 장중 변동성이 큰 국내 주식을 자동 선별하고, 단타 전략을 모의 실행하거나 실전 현금 주문으로 실행하는 Python 웹 앱입니다. 별도 웹 프레임워크 없이 Python 표준 라이브러리만 사용합니다.

수익은 보장되지 않습니다. 반드시 `모의 실행`으로 충분히 확인한 뒤 소액으로만 실전 테스트하세요. 이 앱은 App Secret과 Access Token을 로컬에 저장하므로 공개 인터넷에 그대로 노출하면 안 됩니다.

## 현재 동작

- 웹에서 한국투자증권 `App Key`, `App Secret`, `Access Token`을 저장합니다.
- Access Token이 없거나 만료가 임박하면 앱이 한국투자 토큰 API로 자동 재발급하고 로컬 파일에 다시 저장합니다.
- 기본 종목은 수동 입력하지 않습니다. 장중 한국투자 순위 API로 거래대금 상위, 등락률 상위, 거래량 급증, 체결강도 상위 후보를 모읍니다.
- ETF, ETN, SPAC, 거래정지/투자경고 성격의 종목은 제외하고, 갭 상승과 당일 변동성이 큰 개별주를 우선 추적합니다.
- 최대 20개 종목을 10초 간격으로 조회하고, 앱 내부에서 5분봉을 만들어 단타 전략을 평가합니다.
- `모의 실행`은 주문과 손익을 리포트에만 기록합니다.
- `실전 주문`은 웹에서 확인을 받은 뒤 한국투자 현금 주문 API로 실제 주문을 보냅니다. 레버리지나 미수 주문은 사용하지 않습니다.

## 자동선별 기준

실전 자동매매는 `config/volatile_stock_scalp.json` 전략을 사용합니다. 주요 기본값은 아래와 같습니다.

- 시드: `1,000,000원`
- 장 초반 관찰: `20분`
- 종목 선별: 거래대금, 거래량 급증, 등락률, 체결강도 순위 API 조합
- 갭 조건: 전일 대비 `+2% ~ +8%`
- 최소 거래대금: 약 `10억원` 이상
- 변동성 조건: 5분봉 ATR `0.6% ~ 5%`
- 거래량 조건: 최근 평균 대비 `2배` 이상
- 진입: VWAP 위, 장 초반 고가 돌파, 수수료/슬리피지를 넘는 기대폭 필요
- 손절: `-1.0%`
- 익절: `+2.5%`
- 추적손절: `-1.2%`
- 하루 손실 제한: `-3.5%`
- 하루 최대 거래: `6회`
- 강제 청산: `15:15`
- 비용 가정: 수수료 `1.5bps`, 슬리피지 `8bps`, 매도세 `0bps`

전략값을 바꾸려면 `config/volatile_stock_scalp.json`을 수정하면 됩니다.

## 로컬 실행

```bash
python3 -m semibot_web.server
```

브라우저에서 접속합니다.

```text
http://127.0.0.1:8000
```

같은 내부망의 다른 기기에서 접속하려면 서버를 `0.0.0.0`으로 실행합니다.

```bash
python3 - <<'PY'
from semibot_web.server import run
run(host="0.0.0.0", port=8000)
PY
```

## 웹 사용 순서

1. `한국투자 API` 영역에 App Key, App Secret, Access Token을 입력하고 저장합니다.
2. `자동매매` 영역에서 먼저 `모의 실행` 모드를 선택합니다.
3. 계좌번호 앞 8자리, 상품코드 `01`, 자동매매에 사용할 시드를 저장합니다.
4. 계좌 현금을 전부 시드로 쓰려면 `통장 잔고 최대로 사용`을 켭니다. 이 옵션은 자동매매 시작 시 잔고를 다시 조회해 예수금과 출금가능금액 중 큰 값을 시드로 사용합니다.
5. NAS 재부팅이나 컨테이너 재시작 후에도 자동으로 감시를 시작하려면 `서버 시작 시 자동매매 자동 시작`을 켭니다.
6. `잔고 새로고침`을 눌러 현재 실계좌 예수금, 출금가능금액, 총평가금, 손익을 확인합니다.
7. `자동매매 시작`을 누릅니다.
8. 상단 리포트에서 `live_trading`을 선택해 현재 상태, 거래 내역, 횟수, 수익률, 자산 그래프를 확인합니다.
9. 모의 실행 결과가 충분히 쌓인 뒤에만 `실전 주문` 모드로 전환합니다.

## 저장 위치

기본 로컬 실행은 저장소 폴더 아래에 운영 데이터를 저장합니다. Docker나 Synology 배포에서는 `SEMIBOT_STATE_ROOT` 환경변수로 저장 위치를 분리합니다.

- `${SEMIBOT_STATE_ROOT}/config/kis.local.json`: 한국투자 키와 Access Token
- `${SEMIBOT_STATE_ROOT}/config/live.local.json`: 자동매매 설정
- `${SEMIBOT_STATE_ROOT}/reports/live_trading/metrics.json`: 실전/모의 리포트 지표
- `${SEMIBOT_STATE_ROOT}/reports/live_trading/trades.csv`: 주문 및 거래 기록
- `${SEMIBOT_STATE_ROOT}/reports/live_trading/equity_curve.csv`: 자산 곡선

`*.local.json`, `reports/`, `data/`는 Git에 올리지 않도록 제외되어 있습니다.

## Synology 배포

Synology Container Manager에서는 공개 GitHub 저장소를 Docker build context로 바로 사용할 수 있습니다. NAS에 소스 코드를 직접 클론하지 않아도 됩니다.

1. DSM 패키지 센터에서 `Container Manager`를 설치합니다.
2. File Station 또는 SSH로 `/volume1/docker/hantoo/state` 폴더를 만듭니다.
3. SSH로 NAS에 접속해 Compose 파일을 받습니다.

```bash
mkdir -p /volume1/docker/hantoo/state
cd /volume1/docker/hantoo
curl -L -o docker-compose.yml https://raw.githubusercontent.com/YangaePark/hantoo/main/deploy/synology/docker-compose.yml
```

4. Container Manager > Project > Create를 엽니다.
5. Project name은 `hantoo`, Path는 `/volume1/docker/hantoo`로 둡니다.
6. Source는 `Existing docker-compose.yml` 또는 기존 Compose 파일 선택을 사용합니다.
7. Deploy를 누릅니다.

Compose 내용은 아래와 같습니다.

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

배포 후 접속 주소:

```text
http://<NAS-IP>:8000
```

운영 데이터는 `/volume1/docker/hantoo/state`에 남습니다. GitHub에서 최신 코드를 다시 빌드해도 키, 설정, 리포트는 유지됩니다.

자세한 Synology 안내는 `deploy/synology/README.md`에 있습니다.

## 업데이트

GitHub `main`에 새 커밋이 올라간 뒤 Synology Container Manager에서 `hantoo` 프로젝트를 중지하고 다시 Build/Deploy 하면 최신 코드가 반영됩니다.

로컬 Docker에서 확인하려면 아래처럼 실행할 수 있습니다. 단, Compose 파일의 볼륨 경로가 Synology 기준이므로 일반 PC에서는 필요에 맞게 경로를 바꾸세요.

```bash
docker compose -f deploy/synology/docker-compose.yml up -d --build
```

## 백테스트 도구

현재 웹 앱의 중심은 실시간 자동선별과 모의/실전 자동매매입니다. 다만 전략 검증용 CLI도 함께 들어 있습니다.

샘플 다종목 5분봉 생성:

```bash
python3 scripts/generate_sample_stock_scanner_data.py --out data/sample_stock_scanner.csv
```

변동성 개별주 스캐너 백테스트:

```bash
python3 -m semibot_backtester.stock_scanner_cli \
  --csv data/sample_stock_scanner.csv \
  --config config/volatile_stock_scalp.json \
  --out reports/sample_stock_scanner
```

ETF 일봉 백테스트:

```bash
python3 scripts/generate_sample_data.py --out data/sample_396500.csv

python3 -m semibot_backtester.cli \
  --csv data/sample_396500.csv \
  --config config/tiger_semiconductor.json \
  --out reports/tiger_396500
```

ETF 5분봉 단타 백테스트:

```bash
python3 scripts/generate_sample_intraday_data.py --out data/sample_396500_intraday.csv

python3 -m semibot_backtester.intraday_cli \
  --csv data/sample_396500_intraday.csv \
  --config config/tiger_semiconductor_scalp.json \
  --out reports/sample_396500_intraday
```

## 테스트

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

## 보안과 운영 주의

- 실전 주문 모드는 실제 현금 주문을 보냅니다.
- 이 앱에는 로그인 기능이 없습니다. 공유기 포트포워딩으로 공개 인터넷에 직접 열지 마세요.
- NAS 밖에서 접속하려면 Tailscale, VPN, 방화벽, 리버스 프록시 인증을 사용하세요.
- Access Token은 자동 갱신되지만 한국투자 Open API 정책이나 계정 상태에 따라 재로그인이 필요할 수 있습니다.
- 백테스트와 모의 실행 결과가 좋아도 실전 수익을 보장하지 않습니다.
