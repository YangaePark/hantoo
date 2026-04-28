#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic 5-minute ETF data for intraday smoke tests.")
    parser.add_argument("--out", default="data/sample_396500_intraday.csv")
    args = parser.parse_args()

    rows = []
    start_day = datetime(2026, 1, 5, 9, 0)
    price = 30_000.0
    for day in range(30):
        session_start = start_day + timedelta(days=day)
        if session_start.weekday() >= 5:
            continue
        day_bias = 1 if day % 3 != 0 else -1
        for bar_idx in range(78):
            ts = session_start + timedelta(minutes=5 * bar_idx)
            opening_push = 35 * day_bias if 4 <= bar_idx <= 8 else 0
            trend = 14 * day_bias if bar_idx > 8 else 3 * day_bias
            wobble = ((bar_idx % 7) - 3) * 8
            price = max(1000.0, price + opening_push + trend + wobble)
            rows.append(
                {
                    "datetime": ts.strftime("%Y-%m-%d %H:%M"),
                    "open": round(price * 0.999, 2),
                    "high": round(price * 1.003, 2),
                    "low": round(price * 0.997, 2),
                    "close": round(price, 2),
                    "volume": 80_000 + bar_idx * 1_500 + abs(opening_push) * 120,
                }
            )

    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=["datetime", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {len(rows)} rows to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
