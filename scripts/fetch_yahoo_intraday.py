#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


DEFAULT_SYMBOLS = "AAPL,NVDA,MSFT,AMZN,META,GOOGL,AVGO,AMD,TSLA,NFLX,COST,ADBE,INTC,CSCO,PEP"
NY_TZ = ZoneInfo("America/New_York")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download intraday OHLCV from Yahoo Chart API.")
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS, help="Comma-separated ticker list")
    parser.add_argument("--interval", default="5m", help="Yahoo interval, e.g. 1m, 5m, 15m")
    parser.add_argument("--days", type=int, default=45, help="Calendar days to request")
    parser.add_argument("--out", default="data/nasdaq_yahoo_5m.csv", help="Output CSV path")
    parser.add_argument("--timeout", type=int, default=30, help="Per-request timeout seconds")
    parser.add_argument("--retries", type=int, default=2, help="Retries per symbol after the first attempt")
    parser.add_argument("--pause-sec", type=float, default=0.25, help="Pause between symbols")
    args = parser.parse_args()

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    rows = []
    failures = []
    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    for idx, symbol in enumerate(symbols, start=1):
        print(f"fetching {symbol} ({idx}/{len(symbols)})...", flush=True)
        try:
            fetched = fetch_symbol(symbol, start, end, args.interval, args.timeout, args.retries)
        except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
            failures.append((symbol, str(exc)))
            print(f"{symbol}: failed ({exc})", flush=True)
            continue
        print(f"{symbol}: {len(fetched)} rows", flush=True)
        rows.extend(fetched)
        if args.pause_sec > 0:
            time.sleep(args.pause_sec)

    rows.sort(key=lambda row: (row["datetime"], row["symbol"]))
    write_csv(Path(args.out), rows)
    print(f"wrote {len(rows)} rows to {args.out}")
    if failures:
        failed_symbols = ", ".join(symbol for symbol, _ in failures)
        print(f"failed symbols: {failed_symbols}")
    return 0


def fetch_symbol(
    symbol: str,
    start: datetime,
    end: datetime,
    interval: str,
    timeout: int = 30,
    retries: int = 2,
) -> list[dict[str, object]]:
    params = {
        "period1": int(start.timestamp()),
        "period2": int(end.timestamp()),
        "interval": interval,
        "includePrePost": "false",
        "events": "history",
    }
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{urlencode(params)}"
    request = Request(url, headers={"user-agent": "Mozilla/5.0"})
    attempts = max(1, retries + 1)
    for attempt in range(1, attempts + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            break
        except (HTTPError, URLError, TimeoutError):
            if attempt >= attempts:
                raise
            time.sleep(min(2.0 * attempt, 5.0))

    chart = data.get("chart", {})
    error = chart.get("error")
    if error:
        raise RuntimeError(error.get("description") or str(error))
    result = (chart.get("result") or [{}])[0]
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    rows = []
    for idx, timestamp in enumerate(timestamps):
        values = [opens, highs, lows, closes, volumes]
        if any(idx >= len(value) for value in values):
            continue
        open_price = opens[idx]
        high = highs[idx]
        low = lows[idx]
        close = closes[idx]
        volume = volumes[idx]
        if None in {open_price, high, low, close, volume}:
            continue
        dt = datetime.fromtimestamp(int(timestamp), timezone.utc).astimezone(NY_TZ).replace(tzinfo=None)
        if not _regular_session(dt):
            continue
        rows.append(
            {
                "symbol": symbol,
                "datetime": dt.strftime("%Y-%m-%d %H:%M"),
                "open": round(float(open_price), 4),
                "high": round(float(high), 4),
                "low": round(float(low), 4),
                "close": round(float(close), 4),
                "volume": int(volume),
                "spread_pct": 0.0015,
                "warning": 0,
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        fieldnames = ["symbol", "datetime", "open", "high", "low", "close", "volume", "spread_pct", "warning"]
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _regular_session(dt: datetime) -> bool:
    minutes = dt.hour * 60 + dt.minute
    return (9 * 60 + 30) <= minutes <= (15 * 60 + 55)


if __name__ == "__main__":
    raise SystemExit(main())
