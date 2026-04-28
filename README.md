# TIGER Semiconductor Backtester

TIGER Fn반도체TOP10 ETF(`396500`) 자동매매 전략을 실전 주문 전에 검증하기 위한
작은 Python 백테스터입니다. 외부 패키지 없이 표준 라이브러리만 사용합니다.

## 전략 요약

- 전날 종가 기준으로 신호를 계산하고, 다음 거래일 시가에 체결합니다.
- 매수 조건:
  - 종가 > 20일 이동평균
  - 20일 이동평균 > 60일 이동평균
  - RSI(14)가 45~70 사이
  - 거래량 >= 20일 평균 거래량
- 자금 관리:
  - 1차 매수 30%
  - 추세 유지 및 +3% 이상 수익 시 1회 추가매수 25%
  - 최대 주식 비중 70%, 현금 30% 유지
- 매도 조건:
  - 진입 평균가 대비 -4% 손절
  - 20일선 2거래일 연속 이탈 시 전량 매도
  - +7% 수익 시 절반 익절
  - 월 손실 -6% 도달 시 다음 달까지 신규 진입 중단

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

결과물:

- `reports/tiger_396500/metrics.json`
- `reports/tiger_396500/trades.csv`
- `reports/tiger_396500/equity_curve.csv`

## 판정 기준

실전 투입 전에 최소 20거래일 이상 최신 데이터로 다시 돌리고 아래 기준을 통과시키는 것을 권장합니다.

- 전략 수익률이 단순 보유 수익률보다 나쁘지 않을 것
- 최대낙폭이 계좌 허용 손실 이내일 것
- 매도 거래 승률보다 평균손익비가 더 중요함
- 거래 횟수가 과도하지 않을 것

수익은 보장되지 않습니다. 이 백테스터의 목적은 좋은 전략을 찾는 것보다, 나쁜 규칙을 실전에 넣기 전에 걸러내는 것입니다.
