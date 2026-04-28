from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from .models import BacktestResult


def write_result(result: BacktestResult, output_dir: str | Path) -> None:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)

    (path / "metrics.json").write_text(
        json.dumps(result.metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with (path / "trades.csv").open("w", newline="", encoding="utf-8") as csv_file:
        fieldnames = [
            "date",
            "action",
            "symbol",
            "shares",
            "price",
            "gross",
            "cost",
            "realized_pnl",
            "cash_after",
            "position_after",
            "reason",
        ]
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for trade in result.trades:
            row = asdict(trade)
            row["date"] = trade.date.isoformat()
            writer.writerow(row)

    with (path / "equity_curve.csv").open("w", newline="", encoding="utf-8") as csv_file:
        fieldnames = ["date", "cash", "shares", "close", "equity", "drawdown", "paused"]
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(result.equity_curve)


def format_metrics(metrics: dict[str, object]) -> str:
    lines = [
        f"symbol: {metrics['symbol']}",
        f"period: {metrics['start_date']} ~ {metrics['end_date']}",
        f"final equity: {metrics['final_equity']:,} KRW",
        f"total return: {metrics['total_return_pct']}%",
        f"CAGR: {metrics['cagr_pct']}%",
        f"max drawdown: {metrics['max_drawdown_pct']}%",
        f"buy & hold: {metrics['buy_and_hold_return_pct']}%",
        f"sharpe approx: {metrics['sharpe_approx']}",
        f"trades: {metrics['trades']}",
        f"sell win rate: {metrics['sell_win_rate_pct']}%",
        f"realized pnl: {metrics['realized_pnl']:,} KRW",
        f"exposure: {metrics['exposure_pct']}%",
    ]
    return "\n".join(lines)
