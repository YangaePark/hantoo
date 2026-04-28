from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from semibot_backtester.stock_scanner import StockBar, StockScannerBacktester, StockScannerConfig


class StockScannerBacktesterTest(unittest.TestCase):
    def test_scanner_runs(self) -> None:
        config = StockScannerConfig(
            observation_minutes=15,
            volume_sma=3,
            volume_factor=0.8,
            atr_period=3,
            min_atr_pct=0.001,
            top_value_rank=2,
            require_spread=True,
        )
        result = StockScannerBacktester(config).run(synthetic_bars())

        self.assertGreater(result.metrics["final_equity"], 0)
        self.assertEqual(result.metrics["symbols"], 3)
        self.assertTrue(result.equity_curve)
        self.assertIn("explicit_trade_cost", result.metrics)


def synthetic_bars() -> list[StockBar]:
    bars: list[StockBar] = []
    symbols = ["AAA", "BBB", "CCC"]
    start = datetime(2026, 1, 5, 9, 0)
    previous = {"AAA": 10000.0, "BBB": 20000.0, "CCC": 15000.0}
    for day in range(3):
        session_start = start + timedelta(days=day)
        for symbol in symbols:
            price = previous[symbol] * (1.04 if symbol != "CCC" else 1.01)
            for idx in range(30):
                ts = session_start + timedelta(minutes=5 * idx)
                price += 35 if symbol == "AAA" and idx > 4 else 8
                bars.append(
                    StockBar(
                        symbol=symbol,
                        timestamp=ts,
                        open=price * 0.998,
                        high=price * 1.006,
                        low=price * 0.994,
                        close=price,
                        volume=200000 + idx * 4000 if symbol == "AAA" else 50000 + idx * 500,
                        spread_pct=0.001,
                    )
                )
            previous[symbol] = price
    return bars


if __name__ == "__main__":
    unittest.main()
