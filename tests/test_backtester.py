from __future__ import annotations

import unittest
from datetime import date, timedelta

from semibot_backtester import Backtester, StrategyConfig
from semibot_backtester.models import Bar


class BacktesterTest(unittest.TestCase):
    def test_backtester_runs_and_returns_metrics(self) -> None:
        bars = synthetic_bars()
        config = StrategyConfig(
            initial_capital=1_000_000,
            fast_sma=5,
            slow_sma=10,
            volume_sma=5,
            rsi_period=5,
            rsi_min=40,
            rsi_max=90,
            take_profit_pct=0.04,
        )

        result = Backtester(config).run(bars)

        self.assertGreater(result.metrics["final_equity"], 0)
        self.assertIn("max_drawdown_pct", result.metrics)
        self.assertIn("explicit_trade_cost", result.metrics)
        self.assertIn("round_trip_cost_pct", result.metrics)
        self.assertTrue(result.equity_curve)
        self.assertEqual(len(result.equity_curve), len(bars))


def synthetic_bars() -> list[Bar]:
    start = date(2025, 1, 2)
    bars: list[Bar] = []
    price = 10_000.0
    for idx in range(180):
        if idx < 60:
            price += 30
        elif idx < 130:
            price += 90
        else:
            price -= 45
        open_price = price * 0.995
        high = price * 1.015
        low = price * 0.985
        close = price
        bars.append(
            Bar(
                date=start + timedelta(days=idx),
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=1_000_000 + idx * 10_000,
            )
        )
    return bars


if __name__ == "__main__":
    unittest.main()
