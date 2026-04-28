#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic OHLCV data for a smoke test.")
    parser.add_argument("--out", default="data/sample_396500.csv")
    args = parser.parse_args()

    rows = []
    start = date(2025, 1, 2)
    price = 10_000.0
    for idx in range(140):
        if idx < 45:
            price += 25
        elif idx < 95:
            price += 95
        elif idx < 115:
            price -= 55
        else:
            price += 35

        rows.append(
            {
                "date": (start + timedelta(days=idx)).isoformat(),
                "open": round(price * 0.996, 2),
                "high": round(price * 1.018, 2),
                "low": round(price * 0.982, 2),
                "close": round(price, 2),
                "volume": 1_000_000 + idx * 12_000,
            }
        )

    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=["date", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {len(rows)} rows to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
