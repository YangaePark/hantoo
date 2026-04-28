#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic multi-symbol 5-minute data for scanner tests.")
    parser.add_argument("--out", default="data/sample_stock_scanner.csv")
    args = parser.parse_args()

    symbols = ["FAST1", "FAST2", "CALM1", "WARN1", "FAST3"]
    base_prices = {"FAST1": 12000.0, "FAST2": 18000.0, "CALM1": 30000.0, "WARN1": 8000.0, "FAST3": 22000.0}
    rows = []
    start = datetime(2026, 1, 5, 9, 0)
    for day in range(10):
        session_start = start + timedelta(days=day)
        if session_start.weekday() >= 5:
            continue
        for symbol in symbols:
            previous = base_prices[symbol]
            gap = 0.045 if symbol.startswith("FAST") else 0.01
            if symbol == "FAST2" and day % 3 == 0:
                gap = 0.075
            if symbol == "WARN1":
                gap = 0.05
            price = previous * (1.0 + gap)
            for idx in range(78):
                ts = session_start + timedelta(minutes=5 * idx)
                is_fast = symbol.startswith("FAST")
                opening_push = 45 if is_fast and 4 <= idx <= 7 else 0
                trend = 24 if is_fast and idx > 6 else 4
                pullback = -35 if is_fast and idx % 13 == 0 else 0
                price = max(1000.0, price + opening_push + trend + pullback)
                volume = (180000 if is_fast else 40000) + idx * (4500 if is_fast else 600)
                if 4 <= idx <= 9 and is_fast:
                    volume *= 3
                if idx in {14, 22, 34, 48} and is_fast:
                    volume *= 4
                rows.append(
                    {
                        "symbol": symbol,
                        "datetime": ts.strftime("%Y-%m-%d %H:%M"),
                        "open": round(price * 0.998, 2),
                        "high": round(price * 1.008, 2),
                        "low": round(price * 0.994, 2),
                        "close": round(price, 2),
                        "volume": int(volume),
                        "spread_pct": 0.0015 if is_fast else 0.003,
                        "warning": 1 if symbol == "WARN1" else 0,
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
