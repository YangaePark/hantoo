from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path

from .stock_scanner import StockScannerBacktester, StockScannerConfig, load_stock_scanner_csv


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest a volatile-stock intraday scanner strategy.")
    parser.add_argument("--csv", required=True, help="Multi-symbol intraday OHLCV CSV path")
    parser.add_argument("--config", default="config/volatile_stock_scalp.json", help="Strategy JSON config path")
    parser.add_argument("--out", default=None, help="Output directory")
    parser.add_argument("--currency", default="KRW", help="Display currency label, e.g. KRW or USD")
    args = parser.parse_args()

    config = StockScannerConfig.from_dict(json.loads(Path(args.config).read_text(encoding="utf-8")))
    result = StockScannerBacktester(config).run(load_stock_scanner_csv(args.csv))

    if args.out:
        write_result(result, args.out)
    print(format_metrics(result.metrics, args.currency.upper()))
    return 0


def write_result(result, output_dir: str | Path) -> None:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    (path / "metrics.json").write_text(json.dumps(result.metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    with (path / "trades.csv").open("w", newline="", encoding="utf-8") as csv_file:
        fieldnames = ["timestamp", "action", "symbol", "shares", "price", "gross", "cost", "realized_pnl", "cash_after", "reason"]
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for trade in result.trades:
            row = asdict(trade)
            row["timestamp"] = trade.timestamp.isoformat(sep=" ")
            writer.writerow(row)

    with (path / "equity_curve.csv").open("w", newline="", encoding="utf-8") as csv_file:
        fieldnames = ["datetime", "cash", "symbol", "shares", "mark_price", "equity", "drawdown", "paused"]
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(result.equity_curve)


def format_metrics(metrics: dict[str, object], currency: str = "KRW") -> str:
    lines = [
        f"strategy: {metrics['strategy']}",
        f"symbols: {metrics['symbols']}",
        f"period: {metrics['start_datetime']} ~ {metrics['end_datetime']}",
        f"sessions: {metrics['sessions']}",
        f"final equity: {metrics['final_equity']:,} {currency}",
        f"total return: {metrics['total_return_pct']}%",
        f"max drawdown: {metrics['max_drawdown_pct']}%",
        f"sharpe approx: {metrics['sharpe_approx']}",
        f"trades: {metrics['trades']}",
        f"sell win rate: {metrics['sell_win_rate_pct']}%",
        f"realized pnl: {metrics['realized_pnl']:,} {currency}",
        f"explicit trade cost: {metrics['explicit_trade_cost']:,} {currency}",
        f"round trip cost: {metrics['round_trip_cost_pct']}%",
        f"exposure: {metrics['exposure_pct']}%",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
