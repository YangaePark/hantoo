# Hantoo 자동매매 대시보드

한국투자증권 Open API를 이용해 장중 변동성이 큰 국내 주식, 미국 NASDAQ 주식, 국내 1배 ETF를 자동 선별하고, 단타 전략을 모의 실행하거나 실전 현금 주문으로 실행하는 Python 웹 앱입니다. 별도 웹 프레임워크 없이 Python 표준 라이브러리만 사용합니다.

수익은 보장되지 않습니다. 반드시 `모의 실행`으로 충분히 확인한 뒤 소액으로만 실전 테스트하세요. 이 앱은 App Secret과 Access Token을 로컬에 저장하므로 공개 인터넷에 그대로 노출하면 안 됩니다.

## 현재 동작

- 웹에서 한국투자증권 `App Key`, `App Secret`, `Access Token`을 저장합니다.
- Access Token이 없거나 만료가 임박하면 앱이 한국투자 토큰 API로 자동 재발급하고 로컬 파일에 다시 저장합니다.
- 기본 종목은 수동 입력하지 않습니다. 장중 한국투자 순위 API로 거래대금 상위, 등락률 상위, 거래량 급증, 체결강도 상위 후보를 모읍니다.
- ETF, ETN, SPAC, 거래정지/투자경고 성격의 종목은 제외하고, 갭 상승과 당일 변동성이 큰 개별주를 우선 추적합니다.
- 최대 12개 종목을 15초 간격으로 조회하고, 앱 내부에서 5분봉을 만들어 단타 전략을 평가합니다.
- 자동선별 후보는 5분마다 갱신하고, 한번 선별된 종목은 최소 30분 유지해 관찰용 5분봉 데이터가 쌓일 시간을 줍니다.
- 기본 최대 동시보유는 3종목입니다. 신규 매수 1건의 예산은 자동매매 시드를 최대 동시보유 수로 나눈 슬롯 금액을 기준으로 제한합니다.
- `모의 실행`은 주문과 손익을 리포트에만 기록합니다.
- `실전 주문`은 웹에서 확인을 받은 뒤 한국투자 현금 주문 API로 실제 주문을 보냅니다. 레버리지나 미수 주문은 사용하지 않습니다.
- 웹의 `국내`/`해외`/`국내ETF` 탭은 키, 계좌, 전략 설정, 실행 상태, 리포트를 서로 분리해 각각 시작/중지할 수 있습니다.
- 해외 슬롯은 별도 한국투자 키와 해외계좌를 저장하고, NASDAQ 랭킹 API로 거래대금, 거래량, 상승률, 거래량 급증, 체결강도 후보를 합쳐 자동 선별합니다. 프리장 자동선별은 해외 탭에서 별도로 켤 수 있습니다.
- 국내ETF 슬롯은 국내 현금 주문 API를 그대로 쓰되, KODEX/TIGER 등 거래대금이 큰 1배 ETF만 추적하고 레버리지, 인버스, ETN, 저유동성 후보는 제외합니다.

## 트레이드 알고리즘

국내, 해외, 국내ETF는 완전히 별도 트레이더로 실행됩니다. 키, 계좌, 자동매매 설정, 리포트 폴더, 보유 포지션, 주문 로그가 서로 분리되므로 한 슬롯을 중지해도 다른 슬롯은 계속 돌 수 있습니다.

### 시장별 전략 한눈에 보기

| 구분 | 국내 | 해외 (NASDAQ) | 국내ETF |
| --- | --- | --- | --- |
| 대상 | 변동성 큰 국내 개별주 | NASDAQ 개별주 (ETF/ETN 제외) | 국내 1배 ETF (KODEX/TIGER 중심) |
| 자동선별 소스 | 거래대금/거래량급증/등락률/체결강도 | 거래대금/거래량/상승률/거래량급증/체결강도 | 국내 순위 API + ETF 유니버스 |
| 기본 관찰 시간 | 10분 | 본장 20분, 프리장 30분 | 5분 |
| 진입 시간 제한 | 전략 설정 기준 | 장세션(본장/프리장) 기준 | 09:05~14:30 |
| 핵심 진입 필터 | 갭상승 + 거래량 + ATR + VWAP + 관찰구간 고가 돌파 | 갭상승 + 거래량 + ATR + VWAP + 관찰구간 고가 돌파 | VWAP + 단기 모멘텀 + 거래량 + 지수 ETF 프록시 확인 |
| 위험관리 | 손절/익절/추적손절/강제청산 | 본장/프리장 각각 별도 손절/익절/추적손절 | 촘촘한 손절/익절 + 부분익절 + 일일 손익 차단 + 연속 손절 차단 |
| 일일 제한 | 일일 진입 횟수 제한 | 일일 진입 횟수 제한 (프리장은 더 보수적) | 일일 목표/손실/연속손절/쿨다운 동시 적용 |

### 시장별 전략 요약

- 국내 단타 전략
  - 장 초반 변동성 확대 구간에서 강한 종목을 찾고, 5분봉 기준으로 VWAP 상단 유지와 관찰구간 고가 돌파를 확인해 진입합니다.
  - 손절/익절/추적손절을 함께 사용해 급락 시 빠르게 방어하고, 추세가 이어질 때만 수익을 늘리는 구조입니다.

- 해외 NASDAQ 전략
  - NASDAQ 랭킹 기반으로 유동성 높은 종목을 우선 선별하고, 본장과 프리장을 분리해 리스크를 다르게 관리합니다.
  - 프리장은 스프레드와 유동성 리스크가 커서 거래대금/거래량/VWAP 조건을 본장보다 더 엄격하게 적용합니다.

- 국내ETF 단타 전략
  - 레버리지/인버스/ETN을 제외한 1배 ETF 중심으로 운용하며, 초단기 모멘텀과 VWAP을 함께 봅니다.
  - 부분익절(분할 매도), 일일 목표/손실 한도, 연속 손절 쿨다운을 함께 적용해 과매매를 억제합니다.
  - 코스피200/코스닥150 프록시 ETF의 VWAP 상태를 확인해 시장 역풍 구간 진입을 줄이도록 설계되었습니다.

공통 흐름은 아래와 같습니다.

1. 한국투자 순위 API로 후보 종목을 모읍니다.
2. ETF, ETN, SPAC, 레버리지/인버스/펀드 성격 종목을 제외합니다.
3. 후보 종목 현재가를 주기적으로 조회해 내부 5분봉을 만듭니다.
4. 선별된 종목은 최소 30분 유지해 관찰봉이 쌓이게 합니다.
5. 조건을 만족한 종목을 매수합니다. 이미 보유 중인 종목은 추가 매수하지 않습니다.
6. 보유 종목은 자동선별 목록에서 빠져도 계속 현재가를 조회해 매도 조건을 추적합니다.
7. 손절, 익절, 추적손절, 강제청산 조건이 발생하면 종목별로 개별 매도합니다.

### 자동선별

국내 자동선별은 `거래대금 상위`, `거래량 급증`, `등락률 상위`, `체결강도 상위` 순위 API를 합쳐 후보를 만듭니다. 6자리 국내 종목 코드만 사용하고, ETF/ETN/SPAC 성격 종목은 제외합니다. 이후 전일 대비 상승률, 당일 고저 변동폭, 거래량 급증, 거래대금 기준을 통과한 종목을 점수화해 최대 12개까지 추적합니다.

해외 자동선별은 미국 NASDAQ으로 한정합니다. `거래대금`, `거래량`, `상승률`, `거래량 급증`, `체결강도` 순위 API를 합쳐 후보를 만들고, ETF/ETN/FUND/TRUST/INDEX/레버리지/인버스 성격 종목은 제외합니다. 해외는 현재가가 `5달러` 미만이면 제외하고, 본장은 거래대금 `2천만 달러`, 프리장은 `200만 달러`를 기본 유동성 기준으로 봅니다.

국내ETF 자동선별은 국내 순위 API와 기본 ETF 유니버스를 합쳐 KODEX 200, TIGER 200, 코스닥150, 반도체, 2차전지, 은행, 자동차, 바이오 ETF를 우선 추적합니다. 레버리지, 인버스, ETN은 제외하고, 현재가 응답 기준 거래대금 `10억원` 이상 후보만 실시간 평가 대상으로 삼습니다.

### 매수 조건

매수는 “전일 종가 대비 강하게 출발했지만, 과열은 아닌 종목이 거래량을 동반해 관찰구간 고가와 VWAP를 돌파하는 상황”을 노립니다.

국내 기본값은 `config/volatile_stock_scalp.json` 기준입니다.

- 장 초반 관찰: `10분`
- 상승률 조건: 전일 대비 `+0.8% ~ +12%`
- 거래량 조건: 최근 `3개` 5분봉 평균 대비 `1.3배` 이상
- 변동성 조건: 5분봉 ATR `0.25% ~ 8%`
- 진입 확인: VWAP 위, 관찰구간 고가 돌파, VWAP 이격 `7%` 이하, 최근 모멘텀 유지
- 하루 최대 진입: `8회`

해외 본장 기본값은 `config/overseas_stock_scalp.json` 기준입니다.

- 장 초반 관찰: `20분`
- 상승률 조건: 전일 대비 `+1% ~ +8%`
- 거래량 조건: 설정상 최근 `4개` 5분봉 평균 대비 `1.6배` 이상, 실시간 직진입 프로필은 본장에서 최대 `1.3배`까지 완화
- 변동성 조건: 5분봉 ATR `0.4% ~ 6%`
- 진입 확인: VWAP 부근 이상, 관찰구간 고가 돌파 우대, VWAP 이격 `4%` 이하, 최근 모멘텀 유지
- 하루 최대 진입: `6회`

해외 프리장은 해외 탭에서 `프리장 자동선별 포함`을 켠 경우에만 동작합니다. 프리장은 유동성과 스프레드 위험이 커서 본장보다 더 엄격합니다.

- 프리장 시간: 미국 동부 시각 `04:00 ~ 09:30`
- 관찰 시간: `30분`
- 상승률 조건: 전일 대비 `+1.5% ~ +12%`, 실시간 직진입에서는 `+8%` 초과 과열 종목 제외
- 거래량 조건: 최근 `5개` 5분봉 평균 대비 `2.2배` 이상
- 진입 확인: VWAP보다 `0.3%` 이상 위, 관찰구간 고가 돌파 필수, VWAP 이격 `3.5%` 이하
- 손절/익절/추적손절: `-1.5%`, `+3.0%`, 고점 대비 `-2.0%`
- 하루 최대 진입: `3회`

국내ETF 슬롯 기본값은 `config/domestic_etf_scalp.json` 기준입니다.

- 진입 가능 시간: `09:05 ~ 14:30`, 강제청산 기준 `15:15`
- 추적 대상: 거래대금 큰 1배 ETF, 레버리지/인버스/ETN 제외
- 진입 확인: ETF가 VWAP 부근 이상, 최근 5분봉 상승, 체결량 증가, 과도한 VWAP 이격 제외
- 부분익절: `+0.15%`에서 절반 익절 시도
- 전량익절: `+0.30%`
- 손절: `-0.20%`
- 하루 목표 도달: `+0.40%`면 신규 진입 중단
- 하루 손실한도: `-0.70%`면 신규 진입 중단
- 3연속 손절: `30분` 신규 진입 정지
- 5연속 손절: 당일 신규 진입 중단

### 포지션 크기

웹 설정의 `최대 동시보유` 기본값은 `3`입니다. 신규 매수 1건의 예산은 아래 값을 모두 넘지 않도록 계산합니다.

- 사용 가능한 현금
- 자동매매 시드 / 최대 동시보유
- 손절폭 기준 리스크 한도
- 전략 파일의 최대 포지션 비중

예를 들어 시드가 `1,500,000원`, 최대 동시보유가 `3`이면 한 종목의 기본 슬롯은 약 `500,000원`입니다. 이미 1종목을 보유 중이어도 남은 슬롯이 있으면 다른 후보 종목을 추가 매수할 수 있습니다.

### 매도 조건

매도는 보유 종목별로 따로 추적합니다. 한 종목이 손절되어도 다른 보유 종목은 계속 보유할 수 있습니다.

- 국내 손절: 진입가 대비 `-1.0%`
- 국내 익절: 진입가 대비 `+2.5%`
- 국내 추적손절: 고점 대비 `-1.8%`
- 국내 강제청산: `15:15`
- 해외 본장 손절: 진입가 대비 `-1.2%`
- 해외 본장 익절: 진입가 대비 `+2.5%`
- 해외 본장 추적손절: 고점 대비 `-2.0%`
- 해외 본장 강제청산: 미국장 전략 시각 `15:50`
- 해외 프리장 손절: 진입가 대비 `-1.5%`
- 해외 프리장 익절: 진입가 대비 `+3.0%`
- 해외 프리장 추적손절: 고점 대비 `-2.0%`
- 익일로 넘어간 미청산 포지션: 다음 거래 가능 세션에서 강제청산

전략값을 바꾸려면 국내는 `config/volatile_stock_scalp.json`, 해외는 `config/overseas_stock_scalp.json`을 수정하면 됩니다. 웹에서 바꾸는 계좌, 시드, 자동시작, 프리장 포함, 최대 동시보유 값은 `${SEMIBOT_STATE_ROOT}/config/live*.local.json`에 따로 저장됩니다.

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

1. `국내`, `해외`, `국내ETF` 탭 중 실행할 시장을 선택합니다.
2. `한국투자 API` 영역에 해당 시장용 App Key, App Secret, Access Token을 입력하고 저장합니다.
3. `자동매매` 영역에서 먼저 `모의 실행` 모드를 선택합니다.
4. 계좌번호 앞 8자리, 상품코드 `01`, 자동매매에 사용할 시드와 `최대 동시보유` 수를 저장합니다. 기본 최대 동시보유는 `3`입니다.
5. 해외 탭은 NASDAQ 자동선별만 사용합니다. 주문 거래소는 `NASD`, 시세 거래소는 `NAS`, 통화는 `USD`로 고정됩니다. 프리장을 포함하려면 `프리장 자동선별 포함`을 켭니다.
6. 계좌 현금을 전부 시드로 쓰려면 `통장 잔고 최대로 사용`을 켭니다. 이 옵션은 자동매매 시작 시 잔고를 다시 조회해 예수금과 출금가능금액 중 큰 값을 시드로 사용합니다.
7. NAS 재부팅이나 컨테이너 재시작 후에도 자동으로 감시를 시작하려면 `서버 시작 시 자동매매 자동 시작`을 켭니다.
8. `잔고 새로고침`을 눌러 현재 실계좌 예수금, 출금가능금액, 총평가금, 손익을 확인합니다.
9. `자동매매 시작`을 누릅니다.
10. 상단 리포트에서 국내는 `live_trading`, 해외는 `live_trading_overseas`, 국내ETF는 `live_trading_domestic_etf`를 선택해 현재 상태, 거래 내역, 횟수, 수익률, 자산 그래프를 확인합니다.
11. 상태줄의 `동시보유: 현재/최대종목`, `5분봉`, `봉준비`, `매수대기 사유`를 확인합니다. 주문이 없을 때는 `decision_log.jsonl`에서 종목별 탈락 사유와 주문 실패 사유를 볼 수 있습니다. 현재가가 `0`으로 들어오면 KIS 응답의 `rt_cd`, `msg_cd`, `msg1`, `output_keys`도 함께 남습니다.
12. 모의 실행 결과가 충분히 쌓인 뒤에만 `실전 주문` 모드로 전환합니다.

## 저장 위치

기본 로컬 실행은 저장소 폴더 아래에 운영 데이터를 저장합니다. Docker나 Synology 배포에서는 `SEMIBOT_STATE_ROOT` 환경변수로 저장 위치를 분리합니다.

- `${SEMIBOT_STATE_ROOT}/config/kis.local.json`: 한국투자 키와 Access Token
- `${SEMIBOT_STATE_ROOT}/config/kis.overseas.local.json`: 해외 슬롯용 한국투자 키와 Access Token
- `${SEMIBOT_STATE_ROOT}/config/kis.domestic_etf.local.json`: 국내ETF 슬롯용 한국투자 키와 Access Token
- `${SEMIBOT_STATE_ROOT}/config/live.local.json`: 자동매매 설정
- `${SEMIBOT_STATE_ROOT}/config/live.overseas.local.json`: 해외 자동매매 설정
- `${SEMIBOT_STATE_ROOT}/config/live.domestic_etf.local.json`: 국내ETF 자동매매 설정
- `${SEMIBOT_STATE_ROOT}/reports/live_trading/metrics.json`: 실전/모의 리포트 지표
- `${SEMIBOT_STATE_ROOT}/reports/live_trading/trades.csv`: 주문 및 거래 기록
- `${SEMIBOT_STATE_ROOT}/reports/live_trading/equity_curve.csv`: 자산 곡선
- `${SEMIBOT_STATE_ROOT}/reports/live_trading/decision_log.jsonl`: 자동선별, 진입 거절, 주문 제출/실패, 통신 오류 의사결정 로그
- `${SEMIBOT_STATE_ROOT}/reports/live_trading_overseas/`: 해외 슬롯 리포트. 파일 구성은 `metrics.json`, `trades.csv`, `equity_curve.csv`, `decision_log.jsonl`로 국내와 같습니다.
- `${SEMIBOT_STATE_ROOT}/reports/live_trading_domestic_etf/`: 국내ETF 슬롯 리포트. 파일 구성은 국내와 같습니다.

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

SSH로 업데이트한다면 재시작 스크립트를 받아 실행하면 됩니다.

```bash
sudo mkdir -p /volume1/docker/hantoo
cd /volume1/docker/hantoo
sudo curl -fsSL -o restart.sh https://raw.githubusercontent.com/YangaePark/hantoo/main/deploy/synology/restart.sh
sudo chmod +x restart.sh
sudo ./restart.sh
```

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

NASDAQ 자동선별 스캐너 백테스트:

```bash
python3 scripts/generate_sample_overseas_stock_scanner_data.py --out data/sample_nasdaq_scanner.csv

python3 -m semibot_backtester.stock_scanner_cli \
  --csv data/sample_nasdaq_scanner.csv \
  --config config/overseas_stock_scalp.json \
  --currency USD \
  --out reports/sample_nasdaq_scanner
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
