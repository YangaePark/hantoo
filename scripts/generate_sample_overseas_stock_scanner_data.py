#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic NASDAQ 5-minute data for overseas scanner tests.")
    parser.add_argument("--out", default="data/sample_nasdaq_scanner.csv")
    args = parser.parse_args()

    symbols = ["AAPL", "NVDA", "TSLA", "MSFT", "QQQ"]
    base_prices = {"AAPL": 168.0, "NVDA": 830.0, "TSLA": 244.0, "MSFT": 410.0, "QQQ": 430.0}
    rows = []
    start = datetime(2026, 1, 5, 9, 30)
    for day in range(10):
        session_start = start + timedelta(days=day)
        if session_start.weekday() >= 5:
            continue
        for symbol in symbols:
            previous = base_prices[symbol]
            strong = symbol in {"AAPL", "NVDA", "TSLA"}
            gap = 0.035 if strong else 0.008
            if symbol == "TSLA" and day % 3 == 0:
                gap = 0.065
            price = previous * (1.0 + gap)
            for idx in range(78):
                ts = session_start + timedelta(minutes=5 * idx)
                opening_push = 4.0 if strong and 4 <= idx <= 8 else 0.0
                trend = 0.7 if strong and idx > 8 else 0.04
                pullback = -2.2 if strong and idx % 19 == 0 else 0.0
                price = max(5.0, price + opening_push + trend + pullback)
                volume = (700_000 if strong else 180_000) + idx * (22_000 if strong else 3_500)
                if 4 <= idx <= 10 and strong:
                    volume *= 3
                if idx in {15, 24, 36, 51} and strong:
                    volume *= 4
                rows.append(
                    {
                        "symbol": symbol,
                        "datetime": ts.strftime("%Y-%m-%d %H:%M"),
                        "open": round(price * 0.998, 2),
                        "high": round(price * 1.003, 2),
                        "low": round(price * 0.997, 2),
                        "close": round(price, 2),
                        "volume": int(volume),
                        "spread_pct": 0.0012 if strong else 0.0025,
                        "warning": 0,
                    }
                )
            base_prices[symbol] = price

    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        fieldnames = ["symbol", "datetime", "open", "high", "low", "close", "volume", "spread_pct", "warning"]
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
