# TIGER Semiconductor Backtester

TIGER Fn반도체TOP10 ETF(`396500`) 자동매매 전략을 실전 주문 전에 검증하기 위한
작은 Python 백테스터입니다. 외부 패키지 없이 표준 라이브러리만 사용합니다.

## 전략 요약

- 전날 종가 기준으로 신호를 계산하고, 다음 거래일 시가에 체결합니다.
- 매수 조건:
  - 종가가 120일 이동평균보다 충분히 위에 있음
  - 20일 이동평균 > 60일 이동평균 > 120일 이동평균
  - 120일 이동평균이 10거래일 전보다 상승 중
  - RSI(14)가 35~84 사이일 때만 진입
  - ATR(14)이 종가의 9% 이하인 구간
  - 20일선 대비 18% 이상 벌어진 추격매수 금지
  - 추세 폭이 왕복 수수료, 슬리피지, 최소 기대폭보다 커야 함
- 자금 관리:
  - 1회 손실 위험을 계좌의 약 2.4%로 제한
  - 1차 매수 상한 55%
  - 추세 유지 및 +4% 이상 수익 시 1회 추가매수 25%
  - 최대 주식 비중 90%, 현금 10% 유지
- 매도 조건:
  - 진입 평균가 대비 -8% 손절
  - 120일선 이탈 시 전량 매도
  - 60일선 이탈, 120일선 이탈, ATR 추적손절, 15% 추적손절 중 먼저 발생한 조건 적용
  - +12% 수익 시 절반 익절
  - 월 손실 -5% 도달 시 다음 달까지 신규 진입 중단
  - 청산 후 3거래일 신규 진입 금지

## 데이터 준비

백테스터는 아래 형식의 CSV를 받습니다.

```csv
date,open,high,low,close,volume
2025-01-02,12000,12300,11900,12200,1500000
```

한국투자증권 Open API 앱키가 있으면 일봉 데이터를 받을 수 있습니다.

```bash
export KIS_APP_KEY="..."
export KIS_APP_SECRET="..."
python3 scripts/fetch_kis_daily.py --symbol 396500 --start 20210101 --end 20260428 --out data/396500.csv
```

## 실행

데이터 연결 전에는 샘플 데이터로 실행 흐름을 확인할 수 있습니다.

```bash
python3 scripts/generate_sample_data.py --out data/sample_396500.csv
```

```bash
python3 -m semibot_backtester.cli \
  --csv data/396500.csv \
  --config config/tiger_semiconductor.json \
  --out reports/tiger_396500
```

## 단타 전략

단타는 일봉이 아니라 1분, 3분, 5분봉 데이터가 필요합니다. 현재 기본값은 5분봉 기준입니다.

- 장 초반 20분 고가를 돌파할 때만 진입
- 가격이 VWAP 위에 있고, 6봉 이동평균이 18봉 이동평균보다 위일 때만 진입
- 거래량이 최근 평균의 85% 이상은 붙어야 진입
- 왕복 수수료와 슬리피지를 넘는 최소 돌파폭이 있어야 진입
- 손절 -0.6%, 익절 +1.5%, 추적손절 -0.7%
- 1회 진입은 계좌의 최대 100%까지 사용하는 하이리스크 설정
- 하루 최대 4번 진입, 하루 -1.8% 손실이면 당일 매매 중단
- 15:15 이후에는 당일 포지션 강제 청산

단타 백테스터 CSV 형식:

```csv
datetime,open,high,low,close,volume
2026-01-05 09:00,30000,30100,29900,30050,100000
```

샘플 5분봉 데이터로 실행:

```bash
python3 scripts/generate_sample_intraday_data.py --out data/sample_396500_intraday.csv

python3 -m semibot_backtester.intraday_cli \
  --csv data/sample_396500_intraday.csv \
  --config config/tiger_semiconductor_scalp.json \
  --out reports/sample_396500_intraday
```

## 변동성 개별주 스캐너

ETF 단일종목보다 더 공격적인 단타를 하려면 여러 개별주 5분봉을 넣고, 그날 강한 종목만 골라 거래하는 방식이 더 적합합니다.

필터:

- 장 초반 관찰 20분 이후만 진입
- 당일 누적 거래대금 상위 5개 종목만 후보
- 시가 갭 +2%~+8%
- 현재 5분봉 거래량이 직전 평균의 2배 이상
- 5분봉 ATR이 0.6%~5%
- 스프레드 0.2% 이하, 스프레드 데이터가 없으면 기본값에서는 통과
- 투자주의/경고 등 제외 플래그가 있으면 제외
- VI로 추정되는 5분봉 급변 이후 2봉 동안 진입 금지
- VWAP 위, 장 초반 고가 돌파, 수수료/슬리피지를 넘는 돌파폭 필요
- 손절 -1.0%, 익절 +2.5%, 추적손절 -1.2%
- 하루 손실 -3.5%면 중단, 당일 청산

CSV 형식:

```csv
symbol,datetime,open,high,low,close,volume,spread_pct,warning
005930,2026-01-05 09:00,70000,70500,69800,70400,1200000,0.001,0
```

`spread_pct`, `warning`은 선택 컬럼입니다. 실전 자동매매에서는 한국투자증권 호가/종목상태 API로 채우는 것을 권장합니다.

샘플 다종목 데이터 실행:

```bash
python3 scripts/generate_sample_stock_scanner_data.py --out data/sample_stock_scanner.csv

python3 -m semibot_backtester.stock_scanner_cli \
  --csv data/sample_stock_scanner.csv \
  --config config/volatile_stock_scalp.json \
  --out reports/sample_stock_scanner
```

## 웹 대시보드

백테스트 결과는 브라우저에서 확인할 수 있습니다. 별도 패키지 없이 Python 표준 라이브러리만 사용합니다.

```bash
python3 -m semibot_web.server
```

브라우저에서 열기:

```text
http://127.0.0.1:8000
```

웹에서 볼 수 있는 것:

- 현재 선택 리포트의 평가금, 현금, 보유 종목
- 최종 평가금, 수익률, 최대낙폭, 거래횟수, 승률, 거래비용
- 자산 곡선 그래프
- 매도 거래 손익 분포 그래프
- 트레이드 상세 내역
- 한국투자증권 App Key / App Secret / Access Token 입력 및 로컬 저장
- 자동매매 모드, 계좌 설정과 시작/중지

한국투자증권 키는 `config/kis.local.json`에 저장됩니다. 이 파일은 `.gitignore`에 포함되어 Git에 올라가지 않습니다. 웹 API는 키 조회 시 App Key만 마스킹해서 보여주고, App Secret은 다시 반환하지 않습니다.

## 실전 자동매매

웹 대시보드의 자동매매 영역에서 아래 순서로 실행합니다.

1. 한국투자 API 영역에 App Key, App Secret, 발급받은 Access Token을 저장합니다.
2. 자동매매 영역에서 모드는 먼저 `모의 실행`으로 둡니다.
3. 계좌번호 앞 8자리, 상품코드(`01`)를 입력합니다.
4. 설정 저장 후 자동매매 시작을 누릅니다.
5. 리포트 선택에서 `live_trading`을 선택하면 실시간 주문 기록과 손익 기록을 확인할 수 있습니다.

자동매매는 변동성 개별주 스캐너 전략(`config/volatile_stock_scalp.json`)을 사용합니다. 한국투자 순위 API로 시장 후보를 자동선별하고 현재가 API로 5분봉을 만든 뒤, 조건이 맞으면 매수/매도 신호를 냅니다. `모의 실행`은 주문을 기록만 하고 실제 주문을 보내지 않습니다. `실전 주문` 모드는 웹에서 다시 확인을 받은 뒤 한국투자 주문 API로 실제 현금 주문을 보냅니다.

기본값은 고정 감시종목이 아니라 시장 자동선별입니다. 한국투자 순위 API에서 거래대금 상위, 거래량 증가 상위, 등락률 상위, 체결강도 상위 후보를 모으고, 현재가 조회로 아래 조건을 다시 확인해 상위 종목만 추적합니다.

- 당일 누적 거래대금 10억원 이상
- 전일 대비 +2%~+8% 갭 상승
- 당일 고저 변동폭이 충분히 클 것
- 평균 거래량 대비 거래량이 급증했을 것
- 투자위험/경고, 거래정지, ETF/ETN 등 제외 조건을 순위 API에 요청

실전 기록은 아래 위치에 저장됩니다.

- `reports/live_trading/metrics.json`
- `reports/live_trading/trades.csv`
- `reports/live_trading/equity_curve.csv`

실전 주문 전에는 반드시 장중에 `모의 실행`으로 주문 타이밍, 자동선별 로그가 의도대로 쌓이는지 확인하세요. 이 앱은 로컬 개인 사용을 전제로 하며, App Secret과 Access Token을 저장하므로 공개망에 그대로 노출하지 않는 것을 강하게 권장합니다.

포트를 바꾸고 싶으면 Python에서 직접 실행할 수 있습니다.

```bash
python3 - <<'PY'
from semibot_web.server import run
run(host="0.0.0.0", port=8080)
PY
```

## 배포

### Synology Container Manager

시놀로지에서는 GitHub 저장소를 NAS에 클론한 뒤 Container Manager 프로젝트로 배포하는 방식을 권장합니다. Docker의 원격 GitHub build context는 private 저장소 인증을 못 받는 경우가 있어, NAS에 `git clone` 해두는 방식이 더 안정적입니다.

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
5. Project name은 `hantoo`, Path는 `/volume1/docker/hantoo`로 둡니다.
6. Source는 `Create docker-compose.yml`을 선택하고 아래 내용을 붙여넣습니다.

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

배포 후 접속 주소:

```text
http://<NAS-IP>:8000
```

키와 자동매매 리포트는 `/volume1/docker/hantoo/state` 아래에 저장됩니다. GitHub에서 최신 코드를 다시 빌드해도 이 폴더는 유지됩니다.

자세한 시놀로지 배포 안내는 `deploy/synology/README.md`에 있습니다.

### 일반 서버

가장 단순한 배포 방식은 서버 한 대에서 이 저장소를 실행하고, 내부망 또는 본인 PC에서만 접근하는 것입니다.

```bash
git clone <repo-url>
cd hantoo
python3 scripts/generate_sample_stock_scanner_data.py --out data/sample_stock_scanner.csv
python3 -m semibot_backtester.stock_scanner_cli \
  --csv data/sample_stock_scanner.csv \
  --config config/volatile_stock_scalp.json \
  --out reports/sample_stock_scanner
python3 -m semibot_web.server
```

운영 환경에서는 아래처럼 systemd 서비스로 띄울 수 있습니다.

```ini
[Unit]
Description=Semibot Web Dashboard
After=network.target

[Service]
WorkingDirectory=/opt/hantoo
ExecStart=/usr/bin/python3 -m semibot_web.server
Restart=always
User=semibot

[Install]
WantedBy=multi-user.target
```

외부 인터넷에 공개할 경우에는 반드시 Nginx 같은 리버스 프록시 뒤에 두고 HTTPS, 방화벽, 접근제어를 설정하세요. App Secret이 입력되는 화면이 있으므로 공개망에 그대로 노출하지 않는 것을 권장합니다.

결과물:

- `reports/tiger_396500/metrics.json`
- `reports/tiger_396500/trades.csv`
- `reports/tiger_396500/equity_curve.csv`

성과 지표에는 명시적 거래비용과 왕복 비용률도 포함됩니다. ETF 운용보수는 실제 가격에 반영되므로, 과거 ETF 가격으로 백테스트할 때 별도 차감하지 않습니다.

## 판정 기준

실전 투입 전에 최소 20거래일 이상 최신 데이터로 다시 돌리고 아래 기준을 통과시키는 것을 권장합니다.

- 전략 수익률이 단순 보유 수익률보다 나쁘지 않을 것
- 최대낙폭이 계좌 허용 손실 이내일 것
- 매도 거래 승률보다 평균손익비가 더 중요함
- 거래 횟수가 과도하지 않을 것

수익은 보장되지 않습니다. 이 백테스터의 목적은 좋은 전략을 찾는 것보다, 나쁜 규칙을 실전에 넣기 전에 걸러내는 것입니다.
