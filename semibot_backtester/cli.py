from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import Backtester, load_bars_csv
from .report import format_metrics, write_result
from .strategy import StrategyConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest TIGER semiconductor ETF strategy.")
    parser.add_argument("--csv", required=True, help="OHLCV CSV path")
    parser.add_argument("--config", default="config/tiger_semiconductor.json", help="Strategy JSON config path")
    parser.add_argument("--out", default=None, help="Output directory for metrics/trades/equity curve")
    args = parser.parse_args()

    config_data = json.loads(Path(args.config).read_text(encoding="utf-8"))
    config = StrategyConfig.from_dict(config_data)
    bars = load_bars_csv(args.csv)
    result = Backtester(config).run(bars)

    if args.out:
        write_result(result, args.out)

    print(format_metrics(result.metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
